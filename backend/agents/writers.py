"""Concurrent persona drafts. These remain rejected/pending until the Verifier approves them."""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shared.schemas import InsightBrief, Moment, Overlay
from shared.schemas.contracts import FactValue

from .llm import BudgetUnavailable, complete_with_budget
from .names import NameAllowlist, focus_player, prompt_names
from .producer import AirPlanItem
from .templates import template_for


class WriterText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: str = Field(min_length=1, max_length=60)
    body: str = Field(min_length=1, max_length=160)
    fields: dict[str, FactValue] = Field(default_factory=dict)


@dataclass(frozen=True)
class WriterResult:
    item: AirPlanItem
    draft: Overlay | None
    error: str | None = None


async def write_one(brief: InsightBrief, moment: Moment, names: NameAllowlist, item: AirPlanItem,
                    model, budget, *, trace_id: str, timeout_s: float = 2.0,
                    repair_reason: str | None = None, previous_draft: dict | None = None) -> WriterResult:
    start = time.perf_counter()
    if model is None:
        return WriterResult(item, None, "OFF")
    try:
        if brief.match_id != moment.match_id or brief.moment_id != moment.moment_id:
            raise ValueError("Brief does not match moment")
        template = template_for(moment, names, item.persona, item.language, item.club_id)
        if template is None:
            raise ValueError("No checked template for this air slot")
        system = Path(__file__).with_name("prompts").joinpath(f"writer_{item.persona}_v1.md").read_text(encoding="utf-8")
        payload = {"task": "writer", "persona": item.persona, "language": item.language,
                   "brief": brief.model_dump(), "names": prompt_names(names, moment),
                   "template": {"headline": template.headline, "body": template.body, "fields": {}}}
        if item.club_id:
            rival = next(t for t in names.teams if t != item.club_id)
            payload.update(favorite_club_id=item.club_id, rival_club_id=rival,
                           moment_is_for_favorite_club=moment.team_id == item.club_id)
        if repair_reason:
            payload.update(repair_reason=repair_reason, previous_draft=previous_draft)
        text, _ = await complete_with_budget(model, system, json.dumps(payload, ensure_ascii=False),
                                             WriterText.model_json_schema(), budget=budget, timeout_s=timeout_s)
        content = WriterText.model_validate_json(text)
        fields = {**template.fields, **content.fields}
        fields.pop("attempts", None)
        fields.pop("reason_codes", None)
        # Runtime measurements and player focus are code-owned, even during repair.
        fields.pop("player_id", None)
        fields.pop("club_id", None)
        if item.persona == "player":
            fields["player_id"] = focus_player(moment)
        if item.club_id:
            fields["club_id"] = item.club_id
        fields.update(generated_ms=round((time.perf_counter() - start) * 1000), budget_ms=round(timeout_s * 1000))
        overlay = Overlay(overlay_id=template.overlay_id,
                          moment_id=moment.moment_id, match_id=moment.match_id, persona=item.persona,
                          language=item.language, dir="rtl" if item.language == "ar" else "ltr",
                          template_id=item.template_id, slot=item.slot, priority=item.priority, ttl_s=item.ttl_s,
                          headline=content.headline, body=content.body, fields=fields,
                          evidence_event_ids=brief.evidence_event_ids, show_at_s=moment.game_clock_s,
                          source="agent", verification_status="rejected", trace_id=trace_id,
                          model=getattr(model, "name", "unknown"), prompt_version=f"writer_{item.persona}_v1")
        return WriterResult(item, overlay)
    except BudgetUnavailable:
        return WriterResult(item, None, "BUDGET")
    except TimeoutError:
        return WriterResult(item, None, "TIMEOUT")
    except (ValidationError, ValueError, StopIteration):
        return WriterResult(item, None, "INVALID_DRAFT")
    except Exception:
        return WriterResult(item, None, "MODEL_ERROR")


async def write_overlays(brief: InsightBrief, moment: Moment, names: NameAllowlist, plan: list[AirPlanItem],
                         model, budget, *, trace_id: str | None = None, timeout_s: float = 2.0) -> list[WriterResult]:
    trace_id = trace_id or uuid.uuid4().hex
    return list(await asyncio.gather(*(write_one(brief, moment, names, item, model, budget,
                                                trace_id=trace_id, timeout_s=timeout_s) for item in plan)))
