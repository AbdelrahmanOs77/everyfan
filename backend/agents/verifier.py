"""Deterministic checks first; optional, budgeted semantic model check second."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from shared.schemas import InsightBrief, Moment, Overlay

from .llm import ModelClient, complete_with_budget
from .names import NameAllowlist, focus_player, prompt_names

PROMPTS = Path(__file__).with_name("prompts")
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬", "01234567890123456789.,")
NUMBER = re.compile(r"(?<![\w.])[+-]?\d+(?:[.,]\d+)*(?:[eE][+-]?\d+)?\s*[%٪]?")
EN_WORD = re.compile(r"\b[A-Z][A-Za-z]*(?:'[a-z]+)?\b")
# Capitalization alone cannot distinguish names from football prose. These are
# ordinary sentence words / metrics, never an alternate list of allowed entities.
EN_PROSE = frozenset("""a an the this that these those it its he his they their we our
goal red card big chance momentum shifts pressing changes play becomes unsettled
pass creates shot match rhythm player highlight scores speed distance covered top
sent off minute players remaining possession means share ball recently index versus
opponent now baseline pressure regained regains zone chaos per median gap seconds
was followed by after winning driving forward single move from in on at with and
of for is are has have had into to as down left boot ppda xg km m fc
passes allowed defensive action improves""".split())
AR_WORD = r"[\u0621-\u064a]+"
AR_NAME_STARTS = frozenset("""محمد أحمد احمد محمود حسن حسين علي عمر عمرو يوسف ياسر ياسين
مصطفى خالد كريم طارق رامي سامح سامي أحمد أدهم ادهم إبراهيم ابراهيم إسماعيل اسماعيل
عبد عبدالله زين ليونيل كريستيانو نيمار كيليان إيرلينغ ارلينغ هاري روبرت لوكا""".split())
AR_KNOWN_FOREIGN = frozenset("ميسي رونالدو برشلونة ليفربول مانشستر أرسنال ارسنال تشيلسي يوفنتوس".split())
AR_ENTITY = re.compile(rf"(?<!\w)(?:نادي|فريق)\s+{AR_WORD}(?:\s+{AR_WORD})?")


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["approved", "rejected"]
    reason_code: Literal["TOO_LONG", "SCHEMA", "NUMBER_NOT_IN_EVIDENCE", "UNKNOWN_ENTITY",
                         "BAD_EVIDENCE_ID", "TONE", "UNSUPPORTED_CAUSALITY"] | None = None
    detail: str = ""


def reject(reason: str, detail: str) -> Verdict:
    return Verdict(status="rejected", reason_code=reason, detail=detail)


def brief_from_moment(moment: Moment) -> InsightBrief:
    """A fact-only brief for offline validation; no generated claim is trusted."""
    return InsightBrief(moment_id=moment.moment_id, match_id=moment.match_id,
                        claim=moment.type.replace("_", " "), facts=moment.verified_facts,
                        evidence_event_ids=moment.evidence_event_ids, focus_player_id=focus_player(moment),
                        confidence="high", target_personas=["beginner", "tactical", "player"])


def numeric_values(facts: dict) -> list[float]:
    return [float(value) for value in facts.values()
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)]


def number_supported(raw: str, allowed: list[float]) -> bool:
    normalized = raw.translate(DIGITS).strip()
    percent = normalized.endswith(("%", "٪"))
    literal = normalized.rstrip("%٪").strip().replace(",", "")
    number = float(literal)
    if not math.isfinite(number):
        return False
    # Integers require exact evidence; decimal renderings allow 0.05 rounding.
    decimal = "." in literal or "e" in literal.lower()
    for fact in allowed:
        candidates = [fact]
        if percent and 0 <= fact <= 1:
            candidates.append(fact * 100)
        for candidate in candidates:
            if number == candidate or (decimal and abs(number - candidate) <= 0.050000001):
                return True
            if percent and not decimal and number == round(candidate):
                return True
    return False


def _unknown_entity(text: str, names: NameAllowlist) -> str | None:
    remainder = text
    for name in sorted(names.allowed, key=len, reverse=True):
        remainder = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", " ", remainder, flags=re.IGNORECASE)
    for word in EN_WORD.findall(remainder):
        if word.lower() not in EN_PROSE:
            return word
    # Arabic has no capitalization. Flag explicit club cues and likely personal
    # names; arbitrary unseen Arabic names still require the semantic checker.
    match = AR_ENTITY.search(remainder)
    if match:
        return match.group()
    words = re.findall(AR_WORD, remainder)
    for word in words:
        if word in AR_NAME_STARTS or word in AR_KNOWN_FOREIGN:
            return word
    return None


def _unexplained_jargon(text: str) -> str | None:
    for filename in ("jargon_en.txt", "jargon_ar.txt"):
        for term in (PROMPTS / filename).read_text(encoding="utf-8").splitlines():
            if not term or term.startswith("#"):
                continue
            for match in re.finditer(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.IGNORECASE):
                tail = text[match.end():]
                if not re.match(r"\s*(?:—|means\b|called\b|يعني\b|تعني\b|يسمى\b|تسمى\b|أي\b)", tail, re.IGNORECASE):
                    return term
    return None


def _unsupported_shot_speed(text: str, brief: InsightBrief, moment: Moment) -> bool:
    # A measured speed alone never establishes a qualitative speed category.
    classification = brief.facts.get("shot_speed_classification", moment.verified_facts.get("shot_speed_classification"))
    normalized = re.sub(r"[\u064b-\u065f\u0670]", "", text)
    for label, arabic in (("fast", "سريعة"), ("slow", "بطيئة")):
        english = re.search(rf"\b{label}(?:er|est)?[\s-]+(?:shot|strike)\b|\b(?:shot|strike)\s+(?:(?:is|was)\s+)?{label}\b",
                            normalized, re.IGNORECASE)
        arabic_claim = "تسديد" in normalized and re.search(rf"(?<!\w)(?:ال)?{arabic}(?!\w)", normalized)
        if (english or arabic_claim) and classification not in {label, arabic}:
            return True
    return False


def verify(draft: dict, brief: InsightBrief, moment: Moment, names: NameAllowlist, persona: str) -> Verdict:
    try:
        overlay = Overlay.model_validate(draft)
    except ValidationError as exc:
        reason = "TOO_LONG" if any(e["type"] == "string_too_long" for e in exc.errors()) else "SCHEMA"
        return reject(reason, "Draft does not satisfy Contract C.")
    if (overlay.match_id != moment.match_id or brief.match_id != moment.match_id
            or names.meta.match_id != moment.match_id or overlay.moment_id != moment.moment_id
            or brief.moment_id != moment.moment_id or overlay.persona != persona
            or overlay.show_at_s != moment.game_clock_s or overlay.language not in {"en", "ar"}
            or overlay.dir != ("rtl" if overlay.language == "ar" else "ltr")):
        return reject("SCHEMA", "Draft, brief, metadata, persona, direction or timing do not match the moment.")
    allowed = numeric_values(brief.facts) + numeric_values(moment.verified_facts) + [moment.game_clock_s // 60 + 1]
    text = overlay.headline + "\n" + overlay.body
    if _unsupported_shot_speed(text, brief, moment):
        return reject("UNSUPPORTED_CAUSALITY", "Shot speed classification requires a verified label.")
    for match in NUMBER.finditer(text.translate(DIGITS)):
        if not number_supported(match.group(), allowed):
            return reject("NUMBER_NOT_IN_EVIDENCE", f"Unsupported number: {match.group().strip()}")
    # Frontend-rendered field values need the same checks. IDs are checked
    # separately; runtime latency metadata is explicitly not a match statistic.
    for key, value in overlay.fields.items():
        if key == "attempts" and type(value) is int and 0 <= value <= 2:
            continue  # code-owned workflow count, never a football statistic
        if key in {"generated_ms", "budget_ms"} or isinstance(value, bool):
            continue
        if isinstance(value, (int, float, str)):
            key_facts = [brief.facts[key]] if key in brief.facts else []
            if key in moment.verified_facts:
                key_facts.append(moment.verified_facts[key])
            candidates = numeric_values(dict(enumerate(key_facts))) if key_facts else allowed
            raw_numbers = [str(value)] if isinstance(value, (int, float)) else [
                match.group() for match in NUMBER.finditer(value.translate(DIGITS))]
            if any(not number_supported(raw, candidates) for raw in raw_numbers):
                return reject("NUMBER_NOT_IN_EVIDENCE", f"Unsupported field: {key}")
    entity_text = text + "\n" + "\n".join(str(value) for key, value in overlay.fields.items()
                                           if isinstance(value, str) and not key.endswith("_id"))
    unknown = _unknown_entity(entity_text, names)
    if unknown:
        return reject("UNKNOWN_ENTITY", f"Name or capitalized entity outside metadata: {unknown}")
    real_ids = set(moment.evidence_event_ids)
    if not set(brief.evidence_event_ids) <= real_ids or not set(overlay.evidence_event_ids) <= set(brief.evidence_event_ids):
        return reject("BAD_EVIDENCE_ID", "Evidence IDs must resolve to the brief and moment.")
    if persona == "beginner":
        jargon = _unexplained_jargon(text)
        if jargon:
            return reject("TONE", f"Explain this term immediately: {jargon}")
    if persona == "player":
        pid = focus_player(moment)
        if (pid not in names.players or brief.focus_player_id != pid or overlay.fields.get("player_id") != pid):
            return reject("TONE", "Player overlay must identify the moment's focus player.")
        player = names.players[pid]
        aliases = [player.name, player.short_name, player.name_ar]
        if not any(alias and re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text, re.IGNORECASE) for alias in aliases):
            return reject("TONE", "Player overlay must mention the focus player.")
    return Verdict(status="approved", detail="Deterministic checks passed.")


async def verify_with_model(draft: dict, brief: InsightBrief, moment: Moment, names: NameAllowlist,
                            persona: str, *, model: ModelClient | None = None, budget=None,
                            timeout_s: float = 1.0) -> Verdict:
    verdict = verify(draft, brief, moment, names, persona)
    if verdict.status == "rejected" or model is None or getattr(model, "name", None) == "stub":
        return verdict
    try:
        payload = {"draft": draft, "brief": brief.model_dump(), "moment": moment.model_dump(),
                   "names": prompt_names(names, moment)}
        system = (PROMPTS / "verifier_v1.md").read_text(encoding="utf-8")
        text, _ = await complete_with_budget(model, system, json.dumps(payload, ensure_ascii=False),
                                             Verdict.model_json_schema(), budget=budget, timeout_s=timeout_s)
        semantic = Verdict.model_validate_json(text)
        if ((semantic.status == "approved" and semantic.reason_code is not None)
                or (semantic.status == "rejected" and semantic.reason_code not in {"UNSUPPORTED_CAUSALITY", "TONE"})):
            return reject("SCHEMA", "Malformed semantic verdict.")
        return semantic
    except Exception:
        return reject("SCHEMA", "Semantic check failed or exceeded its deadline; use fallback.")
