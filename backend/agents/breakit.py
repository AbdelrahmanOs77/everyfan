"""Adversarial demo only: return a rejected draft and a checked template, never publish the draft."""

from __future__ import annotations

import asyncio
from copy import deepcopy

from backend.analytics.evidence import MatchEvidence
from backend.api.library import MatchLibrary
from backend.api.settings import Settings

from .names import NameAllowlist
from .templates import LANGUAGES, PERSONAS, template_overlays
from .verifier import NUMBER, brief_from_moment, verify

_library: MatchLibrary | None = None


def make_adversarial_draft(overlay: dict) -> dict:
    draft = deepcopy(overlay)
    body = str(draft.get("body", ""))
    bad = NUMBER.sub("999999", body, count=1)
    if bad == body or len(bad) > 160:
        bad = "سرعة التسديدة 999999 كم/س." if draft.get("language") == "ar" else "Shot speed 999999 km/h."
    draft["body"] = bad
    return draft


async def run_break_it(match_id: str = "match_001", moment_id: str | None = None,
                       persona: str = "tactical", lang: str = "en") -> dict:
    if persona not in PERSONAS or lang not in LANGUAGES:
        raise ValueError("Break-it supports beginner/tactical/player and en/ar")
    global _library
    if _library is None:
        _library = MatchLibrary(Settings().data_dir, max_loaded=1)
    match = await _library.get(match_id)
    evidence = await asyncio.to_thread(MatchEvidence, match.metadata, match.events, match.frames)
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
    template = next((o for o in template_overlays(moment, names) if o.persona == persona and o.language == lang), None)
    if template is None:
        raise ValueError("Requested persona has no focus player for this moment")
    brief = brief_from_moment(moment)
    original = template.model_dump(mode="json")
    safe = verify(original, brief, moment, names, persona)
    if safe.status != "approved":
        raise RuntimeError(f"Unsafe template: {safe.reason_code}")
    draft = make_adversarial_draft(original)
    verdict = verify(draft, brief, moment, names, persona)
    if verdict.status != "rejected":
        raise RuntimeError("Adversarial demo draft was not rejected")
    return {"draft": draft, "verdict": verdict.model_dump(), "repaired_or_fallback_overlay": original}
