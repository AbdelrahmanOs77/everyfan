"""Bounded evidence-based Analyst; failed or ungrounded generation uses verified facts."""

import asyncio
import json
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from shared.schemas import InsightBrief, Moment
from shared.schemas.contracts import FactValue

from .llm import BudgetUnavailable, complete_with_budget
from .telemetry import TracedTools, annotate
from .names import focus_player
from .verifier import DIGITS, NUMBER, brief_from_moment, number_supported, numeric_values, target_personas


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Literal["get_recent_events", "get_player_statistics", "compare_to_baseline"]
    arguments: dict[str, FactValue | None] = Field(default_factory=dict)


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_calls: list[ToolCall] = Field(min_length=1, max_length=2)


REPLY = TypeAdapter(InsightBrief | ToolRequest)


def _collect(data, output: dict[str, list]) -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (str, int, float, bool)):
                output.setdefault(key, []).append(value)
            else:
                _collect(value, output)
    elif isinstance(data, list):
        for value in data:
            _collect(value, output)


def _same(value, candidate) -> bool:
    if isinstance(value, bool) or isinstance(candidate, bool):
        return type(value) is type(candidate) and value == candidate
    if isinstance(value, (int, float)) and isinstance(candidate, (int, float)):
        return math.isfinite(value) and math.isfinite(candidate) and value == candidate
    return isinstance(value, str) and isinstance(candidate, str) and value == candidate


def _ground(reply: InsightBrief, moment: Moment, data: list) -> InsightBrief:
    if reply.match_id != moment.match_id or reply.moment_id != moment.moment_id:
        raise ValueError("Analyst returned a different moment")
    by_key = {}
    _collect(data, by_key)
    facts = dict(moment.verified_facts)
    dropped = False
    for key, value in reply.facts.items():
        if key in moment.verified_facts:
            dropped = dropped or not _same(value, moment.verified_facts[key])
        elif any(_same(value, candidate) for candidate in by_key.get(key, [])):
            facts[key] = value
        else:
            dropped = True
    claim = reply.claim
    allowed = numeric_values(facts)
    if any(not number_supported(m.group(), allowed) for m in NUMBER.finditer(claim.translate(DIGITS))):
        claim, dropped = moment.type.replace("_", " "), True
    return reply.model_copy(update={"facts": facts, "claim": claim,
                                    "confidence": "low" if dropped else reply.confidence,
                                    "evidence_event_ids": list(moment.evidence_event_ids),
                                    "focus_player_id": focus_player(moment),
                                    "target_personas": target_personas(moment)})


async def analyze(moment: Moment, tools, model=None, budget=None, *, timeout_s: float = 2.5) -> InsightBrief:
    fallback = brief_from_moment(moment).model_copy(update={"confidence": "low"})
    if model is None:
        annotate(outcome="fallback", reason_code="OFF")
        return fallback
    tools = TracedTools(tools)

    async def run():
        evidence, state = await asyncio.gather(tools.get_moment_evidence(moment.match_id, moment.moment_id),
                                               tools.get_match_state(moment.match_id, moment.game_clock_s))
        if evidence.get("moment", {}).get("moment_id") != moment.moment_id:
            raise ValueError("Mismatched prefetched evidence")
        data = [evidence, state]
        system = Path(__file__).with_name("prompts").joinpath("analyst_v1.md").read_text(encoding="utf-8")
        payload = {"task": "analyst", "brief": brief_from_moment(moment).model_dump(), "evidence": evidence, "state": state}
        text, _ = await complete_with_budget(model, system, json.dumps(payload, ensure_ascii=False), REPLY.json_schema(), budget=budget)
        reply = REPLY.validate_json(text)
        if isinstance(reply, ToolRequest):
            prepared = []
            # Validate all scopes before executing any extra call.
            for call in reply.tool_calls:
                arguments = dict(call.arguments)
                if arguments.get("match_id", moment.match_id) != moment.match_id:
                    raise ValueError("Cross-match tool request")
                at_s = arguments.get("at_s", moment.game_clock_s)
                if not isinstance(at_s, (int, float)) or isinstance(at_s, bool) or not math.isfinite(at_s) or not 0 <= at_s <= moment.game_clock_s:
                    raise ValueError("Future or invalid tool request")
                arguments.update(match_id=moment.match_id, at_s=at_s)
                prepared.append((call.name, arguments))
            results = await asyncio.gather(*(getattr(tools, name)(**arguments) for name, arguments in prepared))
            data.extend(results)
            payload["tool_results"] = [{"name": name, "arguments": arguments, "result": result}
                                       for (name, arguments), result in zip(prepared, results)]
            text, _ = await complete_with_budget(model, system + "\nNo more tools. Return the final InsightBrief now.",
                                                 json.dumps(payload, ensure_ascii=False), InsightBrief.model_json_schema(), budget=budget)
            reply = InsightBrief.model_validate_json(text)
        result = _ground(reply, moment, data)
        annotate(outcome="completed")
        return result

    try:
        return await asyncio.wait_for(run(), timeout_s)
    except TimeoutError:
        annotate(outcome="fallback", reason_code="TIMEOUT")
        return fallback
    except BudgetUnavailable:
        annotate(outcome="fallback", reason_code="BUDGET")
        return fallback
    except Exception as exc:
        annotate(outcome="fallback", reason_code="ANALYST_ERROR", error_type=type(exc).__name__)
        return fallback
