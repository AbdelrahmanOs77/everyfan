"""Adversarial demo only: return a rejected draft and a checked template, never publish the draft."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from copy import deepcopy

from backend.analytics.evidence import MatchEvidence
from backend.api.library import MatchLibrary
from backend.api.settings import Settings

from .names import NameAllowlist
from .templates import ALL_PERSONAS, LANGUAGES, template_for
from .verifier import NUMBER, brief_from_moment, verify

_library: MatchLibrary | None = None
_evidence: OrderedDict[str, MatchEvidence] = OrderedDict()
_lock = asyncio.Lock()


def make_adversarial_draft(overlay: dict) -> dict:
    draft = deepcopy(overlay)
    body = str(draft.get("body", ""))
    bad = NUMBER.sub("999999", body, count=1)
    if bad == body or len(bad) > 160:
        bad = "سرعة التسديدة 999999 كم/س." if draft.get("language") == "ar" else "Shot speed 999999 km/h."
    draft["body"] = bad
    draft["source"], draft["verification_status"] = "agent", "rejected"
    draft["model"], draft["prompt_version"] = "break-it", "adversarial_v1"
    return draft


async def _match_evidence(library: MatchLibrary, match_id: str):
    match = await library.get(match_id)
    async with _lock:
        if match_id not in _evidence:
            _evidence[match_id] = await asyncio.to_thread(MatchEvidence, match.metadata, match.events, match.frames)
            while len(_evidence) > 2:
                _evidence.popitem(last=False)
        _evidence.move_to_end(match_id)
        return match, _evidence[match_id]


async def run_break_it(match_id: str = "match_001", moment_id: str | None = None,
                       persona: str = "tactical", lang: str = "en", club_id: str | None = None,
                       library: MatchLibrary | None = None) -> dict:
    if persona not in ALL_PERSONAS or lang not in LANGUAGES:
        raise ValueError("Break-it supports beginner/tactical/player/club and en/ar")
    global _library
    if library is None:
        if _library is None:
            _library = MatchLibrary(Settings().data_dir, max_loaded=1)
        library = _library
    match, evidence = await _match_evidence(library, match_id)
    if moment_id is None:
        candidates = [m for m in evidence.moments if m.type == "goal" and m.player_id == "nil_10" and m.game_clock_s == 3783]
        if not candidates:
            candidates = [m for m in evidence.moments if m.importance >= 0.5]
        if not candidates:
            raise KeyError("No agent-worthy moments in match")
        moment = candidates[0]
    else:
        moment = evidence.moment_by_id.get(moment_id)
        if moment is None:
            raise KeyError(moment_id)
    names = NameAllowlist(match.metadata)
    if persona == "club":
        club_id = club_id or moment.team_id
        if club_id not in names.teams:
            raise ValueError("Favorite Club needs club_id of one of the two teams and a team moment")
    template = template_for(moment, names, persona, lang, club_id if persona == "club" else None)
    if template is None:
        raise ValueError("Requested persona does not apply to this moment (no focus player or no team)")
    brief = brief_from_moment(moment)
    original = template.model_dump(mode="json")
    safe = verify(original, brief, moment, names, persona)
    if safe.status != "approved":
        raise RuntimeError(f"Unsafe template: {safe.reason_code}")
    draft = make_adversarial_draft(original)
    verdict = verify(draft, brief, moment, names, persona)
    if verdict.status != "rejected":
        raise RuntimeError("Adversarial demo draft was not rejected")
    return {"match_id": match_id, "moment_id": moment.moment_id, "persona": persona, "language": lang,
            "club_id": club_id if persona == "club" else None, "show_at_s": moment.game_clock_s,
            "draft": draft, "verdict": verdict.model_dump(), "repaired_or_fallback_overlay": original,
            "published": "repaired_or_fallback_overlay"}
