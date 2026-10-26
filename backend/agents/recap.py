"""Recap agent: the end-of-match (or so-far) story per persona and language.

Built only from overlays that were already published, i.e. approved by the Verifier or a checked
template fallback. The deterministic recap needs no model. When a model is available the Recap agent
rewrites it as a short story, and the result goes through the same kind of checks as an overlay:
every number must come from the facts of the overlays it summarises, every capitalised name must be
in the match metadata, the tone must be respectful, and Favorite Club recaps must name the club.
Anything that fails falls back to the deterministic recap.

    recap = await build_recap(metadata, overlays, persona="tactical", language="ar")
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shared.schemas import MatchMetadata, Overlay

from .llm import complete_with_budget
from .names import NameAllowlist
from .templates import ALL_PERSONAS, LANGUAGES
from .verifier import DIGITS, NUMBER, _disrespectful, _mentions, _unknown_entity, number_supported, numeric_values

log = logging.getLogger(__name__)
PROMPT = Path(__file__).with_name("prompts") / "recap_v2.md"
MAX_KEY_MOMENTS = 8


class RecapText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=600)


class RecapMoment(BaseModel):
    minute: int
    moment_id: str
    overlay_id: str
    headline: str
    body: str
    facts: dict[str, int | float | str | bool] = Field(default_factory=dict)


class Recap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    match_id: str
    persona: str
    language: str
    dir: Literal["ltr", "rtl"]
    club_id: str | None = None
    until_s: int
    final: bool
    headline: str
    body: str
    key_moments: list[RecapMoment]
    facts: dict[str, int | float | str | bool]
    evidence_overlay_ids: list[str]
    source: Literal["agent", "template"]
    verification_status: Literal["approved", "fallback"]
    reason_code: str | None = None
    model: str | None = None
    prompt_version: str
    _lines: list[str] = []

    @property
    def body_lines(self) -> list[str]:
        return self._lines or [self.body]


def _clip(text: str, limit: int) -> str:
    """Shorten at a word boundary, so a number is never cut in half."""
    if len(text) <= limit:
        return text
    return text[:limit - 1].rsplit(" ", 1)[0] + "…"


def _join(lines: list[str], limit: int) -> str:
    """Whole lines only, so names and numbers are never cut."""
    out, size = [], 0
    for line in lines:
        if out and size + 1 + len(line) > limit:
            break
        out.append(line)
        size += len(line) + (1 if size else 0)
    return _clip(" ".join(out), limit)


def _select(overlays: list[dict], persona: str, language: str, club_id: str | None, until_s: float) -> list[Overlay]:
    chosen = []
    for raw in overlays:
        try:
            o = Overlay.model_validate(raw)
        except ValidationError:
            continue
        if (o.persona != persona or o.language != language or o.verification_status == "rejected"
                or o.show_at_s > until_s or (persona == "club" and o.fields.get("club_id") != club_id)):
            continue
        chosen.append(o)
    # One overlay per moment (the latest version wins), in match order.
    by_moment = {o.moment_id: o for o in sorted(chosen, key=lambda o: o.show_at_s)}
    return sorted(by_moment.values(), key=lambda o: (o.show_at_s, o.moment_id))


def _key(overlays: list[Overlay]) -> list[Overlay]:
    """Goals and red cards always; then the remaining highest-priority moments, kept in time order."""
    urgent = [o for o in overlays if o.priority == 1]
    rest = sorted((o for o in overlays if o.priority != 1), key=lambda o: (o.priority, o.show_at_s))
    keep = {o.overlay_id for o in (urgent + rest)[:max(MAX_KEY_MOMENTS, len(urgent))]}
    return [o for o in overlays if o.overlay_id in keep]


def _score(overlays: list[Overlay]) -> tuple[int, int] | None:
    for o in reversed(overlays):
        h, a = o.fields.get("home_score"), o.fields.get("away_score")
        if isinstance(h, int) and isinstance(a, int) and not isinstance(h, bool) and not isinstance(a, bool):
            return h, a
    return None


RUNTIME_FIELDS = {"generated_ms", "budget_ms", "attempts", "reason_codes"}


def _moment_facts(o: Overlay) -> dict:
    return {name: value for name, value in o.fields.items() if name not in RUNTIME_FIELDS}


def deterministic_recap(meta: MatchMetadata, overlays: list[dict], *, persona: str, language: str,
                        club_id: str | None = None, until_s: float = 5400) -> Recap:
    if persona not in ALL_PERSONAS or language not in LANGUAGES:
        raise ValueError("Recaps support beginner/tactical/player/club in en/ar")
    names = NameAllowlist(meta)
    if persona == "club" and club_id not in names.teams:
        raise ValueError("A Favorite Club recap needs club_id of one of the two teams")
    ar = language == "ar"
    selected = _select(overlays, persona, language, club_id, until_s)
    key = _key(selected)
    final = until_s >= meta.match_duration_s
    home, away = names.team(meta.home.team_id, language), names.team(meta.away.team_id, language)
    score = _score(selected)
    if ar:
        stage = "نهاية المباراة" if final else "حتى الآن"
        headline = f"{stage}: {home} {score[0]}-{score[1]} {away}" if score else f"{stage}: {home} و{away}"
    else:
        stage = "Full time" if final else "So far"
        headline = f"{stage}: {home} {score[0]}-{score[1]} {away}" if score else f"{stage}: {home} v {away}"
    lines = []
    for o in key:
        minute = f"{o.show_at_s // 60 + 1}'"
        title = o.headline.rstrip(".!")
        lines.append(f"{title}. {o.body}" if minute in title else f"{minute} {title}. {o.body}")
    if not lines:
        lines = ["لا توجد لقطات موثقة بعد." if ar else "No verified moments yet."]
    body = _join(lines, 1200)
    facts = {"home_score": score[0], "away_score": score[1]} if score else {}
    recap = Recap(match_id=meta.match_id, persona=persona, language=language, dir="rtl" if ar else "ltr",
                 club_id=club_id if persona == "club" else None, until_s=int(min(until_s, meta.match_duration_s)),
                 final=final, headline=headline, body=body,
                 key_moments=[RecapMoment(minute=o.show_at_s // 60 + 1, moment_id=o.moment_id, overlay_id=o.overlay_id,
                                          headline=o.headline, body=o.body, facts=_moment_facts(o)) for o in key],
                 facts=facts, evidence_overlay_ids=[o.overlay_id for o in key], source="template",
                 verification_status="fallback", prompt_version="recap_template_v1")
    recap._lines = lines
    return recap


def verify_recap(text: RecapText, base: Recap, names: NameAllowlist) -> str | None:
    """Reason code if the generated recap must be rejected, else None."""
    full = text.headline + "\n" + text.body
    allowed = numeric_values(base.facts) + [m.minute for m in base.key_moments]
    for moment in base.key_moments:  # every value of every summarised overlay, not one per key
        allowed += numeric_values(moment.facts)
    for match in NUMBER.finditer(full.translate(DIGITS)):
        if not number_supported(match.group(), allowed):
            return "NUMBER_NOT_IN_EVIDENCE"
    if _unknown_entity(full, names):
        return "UNKNOWN_ENTITY"
    if _disrespectful(full):
        return "TONE"
    if base.persona == "club":
        team = names.teams[base.club_id]
        if not _mentions(full, [team.name, team.short_name, team.name_ar]):
            return "TONE"
    return None


async def build_recap(meta: MatchMetadata, overlays: list[dict], *, persona: str, language: str,
                      club_id: str | None = None, until_s: float = 5400, model=None, budget=None,
                      timeout_s: float = 15.0) -> Recap:
    base = deterministic_recap(meta, overlays, persona=persona, language=language, club_id=club_id, until_s=until_s)
    if model is None or not base.key_moments:
        return base
    names = NameAllowlist(meta)
    payload = {"task": "recap", "persona": persona, "language": language, "final": base.final,
               "favorite_club_id": base.club_id,
               "names": {k: {"name": t.name, "name_ar": t.name_ar} for k, t in names.teams.items()},
               "score": {"home_score": base.facts.get("home_score"), "away_score": base.facts.get("away_score")},
               "moments": [m.model_dump() for m in base.key_moments], "facts": base.facts,
               "template": {"headline": _clip(base.headline, 80), "body": _join(base.body_lines, 600)}}
    try:
        raw, _ = await complete_with_budget(model, PROMPT.read_text(encoding="utf-8"),
                                            json.dumps(payload, ensure_ascii=False),
                                            RecapText.model_json_schema(), budget=budget, timeout_s=timeout_s)
        text = RecapText.model_validate_json(raw)
    except Exception as exc:  # budget, timeout, transport, malformed JSON: keep the checked recap
        log.info("recap agent unavailable (%s); using deterministic recap", type(exc).__name__)
        return base.model_copy(update={"reason_code": "MODEL_ERROR"})
    reason = verify_recap(text, base, names)
    if reason:
        return base.model_copy(update={"reason_code": reason})
    return base.model_copy(update={"headline": text.headline, "body": text.body, "source": "agent",
                                   "verification_status": "approved", "model": getattr(model, "name", None),
                                   "prompt_version": "recap_v2", "reason_code": None})
