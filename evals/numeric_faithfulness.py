"""Numeric faithfulness: does every number shown to a viewer come from verified facts?

A code evaluator (no model), used three ways:

* `numeric_faithfulness(text, facts)` for one piece of text;
* `NumericFaithfulnessEvaluator()(response=..., context=...)`: the callable shape that
  `azure.ai.evaluation.evaluate(evaluators={...})` accepts as a custom evaluator next to Foundry's
  groundedness / relevance / fluency / coherence evaluators;
* by `evals/run_agent_eval.py`, on raw writer drafts (before the Verifier) and on what is published.

Rules match the Verifier's: Arabic-Indic digits are normalised, integers must match exactly, decimals
may differ by 0.05, a percentage may render a 0-1 fraction, and the display minute of the moment
(`game_clock_s // 60 + 1`) is allowed.
"""

from __future__ import annotations

import json
import math

from backend.agents.verifier import DIGITS, DISPLAY_NUMBER, number_supported, numeric_values


def allowed_numbers(facts: dict, game_clock_s: int | None = None) -> list[float]:
    allowed = numeric_values(facts)
    if game_clock_s is not None:
        allowed.append(float(game_clock_s // 60 + 1))
    return allowed


def numeric_faithfulness(text: str, facts: dict, game_clock_s: int | None = None) -> dict:
    """{"score": 1.0 or 0.0, "numbers": n, "unsupported": [...]} for one text."""
    allowed = allowed_numbers(facts, game_clock_s)
    found = [m.group().strip() for m in DISPLAY_NUMBER.finditer(text.translate(DIGITS))]
    unsupported = [n for n in found if not number_supported(n, allowed)]
    return {"score": 0.0 if unsupported else 1.0, "numbers": len(found), "unsupported": unsupported}


class NumericFaithfulnessEvaluator:
    """Custom evaluator for azure-ai-evaluation: `context` is the verified facts (dict or JSON)."""

    id = "everyfan.numeric_faithfulness"

    def __call__(self, *, response: str, context, game_clock_s: int | None = None, **_) -> dict:
        facts = json.loads(context) if isinstance(context, str) else dict(context or {})
        result = numeric_faithfulness(response or "", facts, game_clock_s)
        return {"numeric_faithfulness": result["score"], "numbers_checked": result["numbers"],
                "unsupported_numbers": ", ".join(result["unsupported"])}


def rate(scores: list[float]) -> float | None:
    scores = [s for s in scores if s is not None and not math.isnan(s)]
    return round(100 * sum(scores) / len(scores), 1) if scores else None
