"""Agent evaluation: numeric faithfulness before and after the Verifier, plus approval and latency.

    python -m evals.run_agent_eval --mode stub                       # offline, free, CI-safe
    python -m evals.run_agent_eval --mode stub --inject 0.3          # 30% of drafts get an invented number
    python -m evals.run_agent_eval --mode foundry --limit 30         # real Foundry agents (.env settings)
    python -m evals.run_agent_eval --mode foundry --foundry-evaluators   # + Foundry quality evaluators

For each eval moment (Owner B's evals/moments_eval.jsonl, balanced across moment types) and each air slot
the Producer plans (beginner, tactical, player, Favorite Club per club) x (en, ar), it runs the real
stages: Analyst -> writer -> Verifier -> one repair -> checked template fallback, and measures

  raw     numeric faithfulness of the writers' first drafts, BEFORE the Verifier
  final   numeric faithfulness of what would be published (must be 100%)
  approval, rejections by reason code, repairs, fallbacks, stage latency.

The gap between raw and final is the evidence that the Verifier works. `--inject` corrupts a share of
first drafts with an invented number (like Break it) to show the gap even when the model is perfect.
Results: evals/results/<timestamp>-<mode>.json and evals/results/latest.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

from shared.schemas import Moment

from backend.agents.analyst import analyze
from backend.agents.breakit import make_adversarial_draft
from backend.agents.config import AgentConfig
from backend.agents.llm import create_model
from backend.agents.mcp_server import EvidenceTools
from backend.agents.names import NameAllowlist
from backend.agents.producer import produce
from backend.agents.templates import template_for
from backend.agents.verifier import brief_from_moment, verify, verify_with_model
from backend.agents.writers import write_one
from backend.api.library import MatchLibrary
from backend.api.settings import Settings
from backend.services.budget import DailyTokenBudget

from .numeric_faithfulness import numeric_faithfulness, rate

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "moments_eval.jsonl"
RESULTS = ROOT / "evals" / "results"


def load_rows(limit: int | None, seed: int) -> list[dict]:
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not limit or limit >= len(rows):
        return rows
    by_type: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_type[row["type"]].append(row)
    rng = random.Random(seed)
    for group in by_type.values():
        rng.shuffle(group)
    picked: list[dict] = []
    while len(picked) < limit and any(by_type.values()):  # round-robin: every moment type is represented
        for kind in sorted(by_type):
            if by_type[kind] and len(picked) < limit:
                picked.append(by_type[kind].pop())
    return sorted(picked, key=lambda r: (r["match_id"], r["state"]["game_clock_s"]))


def to_moment(row: dict) -> Moment:
    return Moment(moment_id=row["moment_id"], match_id=row["match_id"], game_clock_s=row["state"]["game_clock_s"],
                  type=row["type"], importance=row["importance"], team_id=row["team_id"],
                  player_id=row["player_id"], evidence_event_ids=row["evidence_event_ids"],
                  verified_facts=row["facts"], rule_id=row["rule_id"])


def text_of(overlay: dict) -> str:
    return f"{overlay['headline']}\n{overlay['body']}"


async def eval_moment(row, *, library, tools, fast, strong, config, budget, inject, rng) -> list[dict]:
    moment = to_moment(row)
    match = await library.get(moment.match_id)
    names = NameAllowlist(match.metadata)
    plan = produce(moment, {}, tuple(names.teams))
    if not plan:
        return []
    analyst_model = fast if config.analyst_model_role == "fast" else strong
    verifier_model = fast if config.verifier_model_role == "fast" else strong
    t0 = time.perf_counter()
    brief = await analyze(moment, tools, analyst_model, budget, timeout_s=config.analyst_timeout_s)
    analyst_ms = (time.perf_counter() - t0) * 1000
    facts = {**moment.verified_facts, **brief.facts}

    async def slot(item) -> dict:
        record = {"match_id": moment.match_id, "moment_id": moment.moment_id, "type": moment.type,
                  "persona": item.persona, "language": item.language, "club_id": item.club_id,
                  "analyst_ms": round(analyst_ms), "brief_confidence": brief.confidence, "injected": False}
        t1 = time.perf_counter()
        result = await write_one(brief, moment, names, item, fast, budget, trace_id="eval",
                                 timeout_s=config.writer_timeout_s)
        record["writer_ms"] = round((time.perf_counter() - t1) * 1000)
        final, reasons = None, []
        if result.draft is None:
            reasons.append(result.error or "INVALID_DRAFT")
            record["raw"] = None
        else:
            draft = result.draft.model_dump()
            if inject and rng.random() < inject:
                draft, record["injected"] = make_adversarial_draft(draft), True
            raw = numeric_faithfulness(text_of(draft), facts, moment.game_clock_s)
            record["raw"], record["raw_unsupported"] = raw["score"], raw["unsupported"]
            for attempt in (1, 2):
                t2 = time.perf_counter()
                verdict = await verify_with_model(draft, brief, moment, names, item.persona, model=verifier_model,
                                                  budget=budget, timeout_s=config.verifier_timeout_s)
                record[f"verifier_ms_{attempt}"] = round((time.perf_counter() - t2) * 1000)
                if verdict.status == "approved":
                    final = draft
                    break
                reasons.append(verdict.reason_code)
                if attempt == 2 or verdict.reason_code == "SCHEMA":
                    break
                repaired = await write_one(brief, moment, names, item, fast, budget, trace_id="eval",
                                           timeout_s=config.writer_timeout_s, repair_reason=verdict.reason_code,
                                           previous_draft=draft)
                record["repaired"] = True
                if repaired.draft is None:
                    reasons.append(repaired.error or "INVALID_DRAFT")
                    break
                draft = repaired.draft.model_dump()
        record["outcome"] = "approved" if final is not None else "fallback"
        if final is None:
            template = template_for(moment, names, item.persona, item.language, item.club_id)
            final = template.model_dump()
            ok = verify(final, brief_from_moment(moment), moment, names, item.persona).status == "approved"
            record["fallback_checked"] = ok
        record["reasons"] = reasons
        record["final"] = numeric_faithfulness(text_of(final), facts, moment.game_clock_s)["score"]
        record["headline"], record["body"] = final["headline"], final["body"]
        return record

    return list(await asyncio.gather(*(slot(item) for item in plan)))


def summarise(records: list[dict], meta: dict) -> dict:
    raw = [r["raw"] for r in records if r.get("raw") is not None]
    by_reason = Counter(reason for r in records for reason in r["reasons"])
    groups = defaultdict(list)
    for r in records:
        groups[(r["persona"], r["language"])].append(r)

    def pct(xs):
        return round(100 * sum(xs) / len(xs), 1) if xs else None

    def p(values, q):
        values = sorted(v for v in values if v is not None)
        return round(values[min(len(values) - 1, int(q * len(values)))]) if values else None

    return {
        **meta,
        "moments": len({(r["match_id"], r["moment_id"]) for r in records}),
        "overlays": len(records),
        "raw_numeric_faithfulness_pct": rate(raw),
        "final_numeric_faithfulness_pct": rate([r["final"] for r in records]),
        "approved_pct": pct([r["outcome"] == "approved" for r in records]),
        "fallback_pct": pct([r["outcome"] == "fallback" for r in records]),
        "repairs": sum(bool(r.get("repaired")) for r in records),
        "injected": sum(r["injected"] for r in records),
        "injected_caught_pct": pct([r["final"] == 1.0 for r in records if r["injected"]]),
        "rejections_by_reason": dict(by_reason.most_common()),
        "latency_ms": {stage: {"p50": p([r.get(key) for r in records], .5), "p95": p([r.get(key) for r in records], .95)}
                       for stage, key in (("analyst", "analyst_ms"), ("writer", "writer_ms"),
                                          ("verifier", "verifier_ms_1"))},
        "by_persona_language": {f"{k[0]}/{k[1]}": {"n": len(v), "raw_pct": rate([r["raw"] for r in v if r.get("raw") is not None]),
                                                   "final_pct": rate([r["final"] for r in v]),
                                                   "approved_pct": pct([r["outcome"] == "approved" for r in v])}
                                for k, v in sorted(groups.items())},
    }


def markdown(summary: dict) -> str:
    lines = [f"# Agent evaluation — {summary['mode']} ({summary['finished_at']})", "",
             f"{summary['moments']} moments, {summary['overlays']} overlays (personas × languages × clubs).", "",
             "| Metric | Value |", "| --- | --- |",
             f"| Raw writer numeric faithfulness (before Verifier) | {summary['raw_numeric_faithfulness_pct']}% |",
             f"| Published numeric faithfulness (after Verifier) | {summary['final_numeric_faithfulness_pct']}% |",
             f"| Approved agent overlays | {summary['approved_pct']}% |",
             f"| Checked template fallbacks | {summary['fallback_pct']}% |",
             f"| Repairs attempted | {summary['repairs']} |",
             f"| Injected invented numbers caught | {summary['injected']} injected, {summary['injected_caught_pct']}% never published |",
             f"| Rejections by reason | {summary['rejections_by_reason'] or 'none'} |",
             f"| Latency p50 / p95 (ms): Analyst | {summary['latency_ms']['analyst']['p50']} / {summary['latency_ms']['analyst']['p95']} |",
             f"| Latency p50 / p95 (ms): writer | {summary['latency_ms']['writer']['p50']} / {summary['latency_ms']['writer']['p95']} |",
             f"| Latency p50 / p95 (ms): Verifier | {summary['latency_ms']['verifier']['p50']} / {summary['latency_ms']['verifier']['p95']} |",
             "", "| Persona / language | n | Raw | Published | Approved |", "| --- | ---: | ---: | ---: | ---: |"]
    for key, g in summary["by_persona_language"].items():
        lines.append(f"| {key} | {g['n']} | {g['raw_pct']}% | {g['final_pct']}% | {g['approved_pct']}% |")
    if summary.get("foundry_evaluators"):
        lines += ["", "| Foundry evaluator | Mean |", "| --- | ---: |"]
        lines += [f"| {k} | {v} |" for k, v in summary["foundry_evaluators"].items()]
    return "\n".join(lines) + "\n"


def run_foundry_evaluators(records: list[dict], out: Path) -> dict:
    """Optional: Foundry's groundedness, relevance, fluency and coherence on the published text."""
    import os

    from azure.ai.evaluation import (CoherenceEvaluator, FluencyEvaluator, GroundednessEvaluator,
                                     RelevanceEvaluator, evaluate)

    from .numeric_faithfulness import NumericFaithfulnessEvaluator

    endpoint = os.getenv("FOUNDRY_OPENAI_ENDPOINT") or os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").split("/api/")[0]
    config = {"azure_endpoint": endpoint, "azure_deployment": os.getenv("EVAL_MODEL_DEPLOYMENT") or os.getenv("FOUNDRY_MODEL_STRONG"),
              "api_key": os.getenv("FOUNDRY_API_KEY") or None}
    data = out.with_suffix(".jsonl")
    with data.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps({"query": f"Explain this {r['type'].replace('_', ' ')} moment for a {r['persona']} fan.",
                                 "response": f"{r['headline']}. {r['body']}",
                                 "context": json.dumps({k: v for k, v in r.items() if k in {"type", "match_id", "moment_id"}}
                                                       | {"facts": r.get("facts", {})}, ensure_ascii=False)},
                                ensure_ascii=False) + "\n")
    result = evaluate(data=str(data), evaluators={
        "groundedness": GroundednessEvaluator(config), "relevance": RelevanceEvaluator(config),
        "fluency": FluencyEvaluator(config), "coherence": CoherenceEvaluator(config),
        "numeric_faithfulness": NumericFaithfulnessEvaluator()})
    return {k: round(v, 3) for k, v in result.get("metrics", {}).items() if isinstance(v, (int, float))}


async def main_async(args) -> dict:
    import os

    os.environ["AGENT_MODE"] = args.mode
    if args.mode == "foundry":  # offline eval: generous deadlines, the real-time budget is not the question here
        for stage, seconds in (("ANALYST", 20), ("WRITER", 20), ("VERIFIER", 20), ("TOTAL", 120)):
            os.environ.setdefault(f"AGENT_{stage}_TIMEOUT_S", str(seconds))
    config = AgentConfig.from_env()
    library = MatchLibrary(Settings().data_dir, max_loaded=2)
    tools = EvidenceTools(library)
    fast = create_model(config, "fast")
    strong = create_model(config, "strong") if "strong" in {config.analyst_model_role, config.verifier_model_role} else None
    budget = DailyTokenBudget(args.token_cap)
    rng = random.Random(args.seed)
    rows = load_rows(args.limit, args.seed)
    records: list[dict] = []
    started = time.time()
    try:
        for i, row in enumerate(rows, 1):
            got = await eval_moment(row, library=library, tools=tools, fast=fast, strong=strong, config=config,
                                    budget=budget, inject=args.inject, rng=rng)
            for r in got:
                r["facts"] = row["facts"]
            records.extend(got)
            if not args.quiet:
                print(f"[eval] {i}/{len(rows)} {row['match_id']} {row['moment_id']} {row['type']:16} "
                      f"{sum(r['outcome'] == 'approved' for r in got)}/{len(got)} approved")
    finally:
        for model in {fast, strong} - {None}:
            if hasattr(model, "aclose"):
                await model.aclose()
    meta = {"mode": args.mode, "inject": args.inject, "seed": args.seed, "limit": args.limit,
            "fast_model": getattr(fast, "name", None), "strong_model": getattr(strong, "name", None),
            "tokens_used": budget.used, "seconds": round(time.time() - started, 1),
            "finished_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}
    summary = summarise(records, meta)
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    out = RESULTS / f"{stamp}-{args.mode}.json"
    if args.foundry_evaluators:
        try:
            summary["foundry_evaluators"] = run_foundry_evaluators(records, out)
        except Exception as exc:  # optional extra: never lose the main result
            summary["foundry_evaluators_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    if not args.no_write:
        out.write_text(json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=1), encoding="utf-8")
        (RESULTS / "latest.md").write_text(markdown(summary), encoding="utf-8")
    print(markdown(summary))
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", choices=["stub", "foundry"], default="stub")
    ap.add_argument("--limit", type=int, default=30, help="eval moments, balanced across moment types (0 = all 107)")
    ap.add_argument("--inject", type=float, default=0.0, help="share of first drafts given an invented number")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--token-cap", type=int, default=3_000_000)
    ap.add_argument("--foundry-evaluators", action="store_true", help="also run azure-ai-evaluation quality evaluators")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    if args.mode == "foundry":
        try:
            from dotenv import load_dotenv
            load_dotenv(ROOT / ".env")
        except ImportError:
            pass
    summary = asyncio.run(main_async(args))
    return 0 if summary["final_numeric_faithfulness_pct"] == 100.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
