"""Owner B command line.

    python -m backend.analytics report [match_001]     moments of a match, readable
    python -m backend.analytics golden                 refresh tests/golden/*.moments.json (after reviewing a rule change)
    python -m backend.analytics export-eval            evals/moments_eval.jsonl: agent-eligible moments + facts + evidence for Owner C
    python -m backend.analytics cosmos-check           write + read one document in Cosmos DB (uses COSMOS_* from .env)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from backend.simulator.generator import generate, list_scenarios, load_scenario

from .config import load_config
from .evidence import MatchEvidence

ROOT = Path(__file__).resolve().parents[2]


def _evidence(scenario_id: str) -> MatchEvidence:
    m = generate(load_scenario(scenario_id))
    return MatchEvidence(m.metadata, m.events, m.frames)


def _scenario_for(match_id: str) -> str:
    for sid in list_scenarios():
        if load_scenario(sid).match_id == match_id:
            return sid
    raise SystemExit(f"unknown match {match_id}")


def cmd_report(args) -> int:
    ev = _evidence(_scenario_for(args.match))
    for m in ev.moments:
        if m.type == "player_milestone" and not args.all:
            continue
        mm, ss = divmod(m.game_clock_s, 60)
        print(f"{m.moment_id:9} {mm:02d}:{ss:02d}  {m.type:17} {m.team_id or '-':10} {m.importance:.1f}  "
              f"{json.dumps(m.verified_facts, ensure_ascii=False)}")
    hidden = sum(m.type == "player_milestone" for m in ev.moments)
    if hidden and not args.all:
        print(f"... plus {hidden} player milestones (--all to show)")
    return 0


def cmd_golden(_args) -> int:
    out = ROOT / "tests" / "golden"
    out.mkdir(parents=True, exist_ok=True)
    for sid in list_scenarios():
        ev = _evidence(sid)
        rows = [[m.moment_id, m.game_clock_s, m.type, m.rule_id, m.team_id] for m in ev.moments
                if m.type != "player_milestone"]
        path = out / f"{ev.match_id}.moments.json"
        path.write_text("[\n" + ",\n".join("  " + json.dumps(r) for r in rows) + "\n]\n", encoding="utf-8")
        print(f"[golden] {sid:16} {len(rows):3} moments -> {path.relative_to(ROOT)}")
    return 0


def cmd_export_eval(args) -> int:
    """One line per agent-eligible moment: what the Analyst and writers receive, plus the facts to check against."""
    threshold = load_config()["moments"]["min_importance_for_agents"]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(out, "w", encoding="utf-8") as fh:
        for sid in list_scenarios():
            ev = _evidence(sid)
            for m in ev.moments:
                if m.importance < threshold:
                    continue
                e = ev.evidence(m.moment_id)
                fh.write(json.dumps({
                    "match_id": ev.match_id, "moment_id": m.moment_id, "type": m.type, "minute": e["minute"],
                    "importance": m.importance, "team_id": m.team_id, "player_id": m.player_id,
                    "facts": m.verified_facts, "evidence_event_ids": m.evidence_event_ids, "rule_id": m.rule_id,
                    "rule": e["rule"]["description"], "names": e["names"],
                    "state": ev.state_at(m.game_clock_s),
                }, ensure_ascii=False) + "\n")
                n += 1
    print(f"[export-eval] {n} moments -> {out}")
    return 0


async def _cosmos_check() -> int:
    from .store import get_store

    store = get_store()
    if store is None:
        print("[cosmos-check] COSMOS_ENDPOINT is not set (put it in .env)")
        return 1
    doc_id = f"check_{int(time.time())}"
    store.audit("healthcheck", "cosmos_check", {"id": doc_id})
    await store.flush(30)
    status = store.status()
    if status["written"] != 1:
        print(f"[cosmos-check] FAILED: {status['last_error']}")
        print("  * 'Forbidden' / 'RBAC': give yourself the Cosmos DB Built-in Data Contributor role (see docs/OWNER_B.md)")
        print("  * 'NotFound': create the database and the 5 containers first")
        return 1
    client, cred = store._client()
    try:
        c = client.get_database_client(store.database).get_container_client("audit")
        item = await c.read_item(doc_id, partition_key="healthcheck")
        print(f"[cosmos-check] OK: wrote and read back audit/{item['id']} in {store.endpoint} ({status['auth']})")
    finally:
        await client.close()
        if cred is not None:
            await cred.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    p = argparse.ArgumentParser(prog="python -m backend.analytics")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report")
    r.add_argument("match", nargs="?", default="match_001")
    r.add_argument("--all", action="store_true")
    sub.add_parser("golden")
    x = sub.add_parser("export-eval")
    x.add_argument("--out", default=str(ROOT / "evals" / "moments_eval.jsonl"))
    sub.add_parser("cosmos-check")
    args = p.parse_args(argv)
    if args.cmd == "report":
        return cmd_report(args)
    if args.cmd == "golden":
        return cmd_golden(args)
    if args.cmd == "export-eval":
        return cmd_export_eval(args)
    return asyncio.run(_cosmos_check())


if __name__ == "__main__":
    sys.exit(main())
