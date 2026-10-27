"""Offline Ask evaluation: raw/published numeric faithfulness, refusal/fact correctness, latency."""
import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from backend.agents.ask import AskRequest, answer_question
from backend.agents.config import AgentConfig
from backend.agents.feature_writer import numbers
from backend.agents.llm import StubModel
from backend.agents.mcp_server import EvidenceTools
from backend.agents.verifier import NUMBER, DIGITS, number_supported
from backend.api.library import MatchLibrary
from backend.api.settings import ROOT
from backend.services.budget import DailyTokenBudget


class DraftModel(StubModel):
    def __init__(self, corrupt):
        self.first, self.corrupt = None, corrupt

    async def complete(self, system, user, json_schema=None):
        raw, usage = await super().complete(system, user, json_schema)
        if json.loads(user).get("task") == "recap" and self.first is None:
            draft = json.loads(raw)
            if self.corrupt:
                draft["body"] += " 999999."
            raw = json.dumps(draft, ensure_ascii=False)
            self.first = draft
        return raw, usage


def faithful(answer, facts):
    return all(number_supported(m.group(), numbers(facts)) for m in NUMBER.finditer((answer["headline"] + " " + answer["body"]).translate(DIGITS)))


async def run(inject=.3):
    rows = [json.loads(s) for s in (ROOT / "evals/ask_eval.jsonl").read_text(encoding="utf-8").splitlines() if s]
    tools = EvidenceTools(MatchLibrary(ROOT / "data"))
    ev = await tools._evidence("match_001")
    started = time.perf_counter()
    await tools.get_player_profile("match_001", "nil_14", 1800)
    warmup_ms = round((time.perf_counter() - started) * 1000, 2)
    raw, published, refusal, correct, times = [], [], [], [], []
    for i, row in enumerate(rows):
        model = DraftModel((i % 10) < round(inject * 10))
        started = time.perf_counter()
        result = await answer_question(ev, AskRequest.model_validate(row["request"]), tools, model=model,
                                       budget=DailyTokenBudget(2_000_000), config=AgentConfig(mode="stub"))
        times.append((time.perf_counter() - started) * 1000)
        if model.first:
            raw.append(faithful(model.first, result["facts"]))
        published.append(faithful(result["answer"], result["facts"]))
        expected = row["expected"]
        refusal.append((result["verification_status"] == "refused") == expected["refused"])
        matches = result["intent"] == expected["intent"] and all(key in result["facts"] for key in expected.get("facts_required", []))
        if "score" in expected:
            matches = matches and result["facts"].get("score") == expected["score"]
        correct.append(matches)
    rate = lambda values: round(100 * sum(values) / len(values), 2) if values else None
    return {"mode": "stub", "questions": len(rows), "provider_warmup_ms": warmup_ms, "raw_drafts": len(raw), "raw_numeric_faithfulness_pct": rate(raw),
            "published_numeric_faithfulness_pct": rate(published), "refusal_correctness_pct": rate(refusal),
            "expected_facts_pct": rate(correct), "p50_ms": round(statistics.median(times), 2),
            "p95_ms": round(sorted(times)[int(.95 * len(times)) - 1], 2), "model_calls_are_offline": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["stub"], default="stub")
    parser.add_argument("--inject", type=float, default=.3)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not 0 <= args.inject <= 1:
        parser.error("--inject must be between 0 and 1")
    result = asyncio.run(run(args.inject))
    if args.out:
        args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return int(any(result[k] != 100 for k in ("published_numeric_faithfulness_pct", "refusal_correctness_pct", "expected_facts_pct")))


if __name__ == "__main__":
    raise SystemExit(main())
