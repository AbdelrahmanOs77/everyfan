"""EveryFan Owner A command line.

  python -m backend.cli generate --all                      # build every scenario into data/
  python -m backend.cli validate --all                      # realism + consistency checks
  python -m backend.cli replay --scenario derby_balanced --speed 20            # local end-to-end
  python -m backend.cli replay --scenario derby_balanced --speed 20 --transport eventhubs
  python -m backend.cli consume --transport eventhubs       # second terminal: live state from Event Hubs
  python -m backend.cli eh-check                            # send one message and read it back
  python -m backend.cli export-schemas                      # JSON Schema files for every contract
  python -m backend.cli build-demo                          # cached demo match bundle (Judge mode)
  python -m backend.cli serve                               # run the API on http://localhost:8000
  python -m backend.cli smoke --url https://<your-app>      # end-to-end check of a deployment
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from shared.schemas import (
    ControlEnvelope,
    ControlMessage,
    InsightBrief,
    MatchMetadata,
    Moment,
    Overlay,
    ScenarioSpec,
    SyntheticEvent,
    TrackingFrame,
    envelope_adapter,
)

from backend.services.consumer import JsonlEventSink, MatchStateConsumer
from backend.services.stream import make_publisher, make_subscriber, transport_name
from backend.simulator.generator import DEFAULT_DATA_DIR, generate, list_scenarios, load_match, load_scenario, write_match
from backend.simulator.replay import ReplayController
from backend.simulator.validator import validate_match

ROOT = Path(__file__).resolve().parents[1]


def _match_folder(scenario_id: str, data_dir: Path) -> Path:
    spec = load_scenario(scenario_id)
    folder = data_dir / spec.match_id
    if not (folder / "events.jsonl").exists():
        print(f"[generate] {scenario_id} -> {folder}")
        write_match(generate(spec), data_dir)
    return folder


def cmd_generate(args) -> int:
    for sid in (list_scenarios() if args.all else [args.scenario]):
        t0 = time.time()
        folder = write_match(generate(load_scenario(sid)), args.data_dir)
        s = json.loads((folder / "summary.json").read_text())
        print(f"{sid:16} {s['match_id']}  score {s['final_score']['home']}-{s['final_score']['away']}  "
              f"events {s['events_total']}  frames {s['frames_total']}  "
              f"max shot {s['max_shot_speed_kmh']} km/h  ({time.time() - t0:.1f}s)  -> {folder}")
    return 0


def cmd_validate(args) -> int:
    failed = 0
    for sid in (list_scenarios() if args.all else [args.scenario]):
        rep = validate_match(*load_match(_match_folder(sid, args.data_dir)))
        print(f"{sid:16} {'OK  ' if rep.ok else 'FAIL'} {rep.stats}")
        for err in rep.errors[:20]:
            print("    ", err)
        failed += not rep.ok
    return 1 if failed else 0


def _printer(verbose: bool):
    last_minute = {"m": -1}
    shown = {"goal", "card", "substitution", "period_start", "period_end"}

    def on_event(e: SyntheticEvent, state) -> None:
        minute = e.game_clock_s // 60
        if e.type in shown:
            who = e.player_id or ""
            extra = e.outcome or e.qualifiers.get("player_in_id", "")
            print(f"  {state.scoreline()}   {e.type.upper():12} {who} {extra}")
        elif verbose and minute % 5 == 0 and minute != last_minute["m"]:
            print(f"  {state.scoreline()}   events {state.events_applied}  dup {state.duplicates_dropped}")
        last_minute["m"] = minute

    return on_event


async def _replay(args) -> int:
    meta, events, frames = load_match(_match_folder(args.scenario, args.data_dir))
    publisher = make_publisher(args.transport)
    ctrl = ReplayController(meta, events, frames, publisher, speed=args.speed,
                            include_tracking=not args.no_tracking, start_at_s=args.from_minute * 60)
    print(f"[replay] {meta.match_id} via {transport_name(args.transport)} at {args.speed}x "
          f"from {args.from_minute}' (run {ctrl.run_id})")
    consumer_task = None
    consumer = None
    if transport_name(args.transport) == "local" or args.consume:
        subscriber = make_subscriber(args.transport)
        sink = JsonlEventSink(args.sink) if args.sink else None
        consumer = MatchStateConsumer(on_event=_printer(args.verbose), sink=sink)
        consumer_task = asyncio.create_task(consumer.consume(subscriber, stop_when_finished=True))
        await asyncio.sleep(0.5 if args.consume else 0)
    t0 = time.time()
    try:
        status = await ctrl.run()
    finally:
        await publisher.close()
    if consumer_task:
        await asyncio.wait_for(consumer_task, timeout=60)
        state = consumer.states.get(meta.match_id)
        if state:
            print(f"[consumer] {json.dumps(state.to_dict())}")
    print(f"[replay] sent {status['sent']} messages in {time.time() - t0:.1f}s wall time")
    return 0


async def _consume(args) -> int:
    subscriber = make_subscriber(args.transport, from_start=args.from_start)
    consumer = MatchStateConsumer(on_event=_printer(True),
                                  on_reset=lambda s: print(f"[consumer] new run {s.run_id} for {s.match_id}"),
                                  sink=JsonlEventSink(args.sink) if args.sink else None)
    print(f"[consumer] listening on {transport_name(args.transport)} (Ctrl+C to stop)")
    try:
        await consumer.consume(subscriber, stop_when_finished=args.once)
    finally:
        await subscriber.close()
        for s in consumer.states.values():
            print(f"[consumer] {json.dumps(s.to_dict())}")
    return 0


async def _eh_check(_args) -> int:
    """Round trip one control message through Event Hubs."""
    run_id = f"check_{int(time.time())}"
    subscriber = make_subscriber("eventhubs")
    received = asyncio.get_running_loop().create_future()

    async def listen():
        async for env in subscriber:
            if env.run_id == run_id and not received.done():
                received.set_result(env)

    task = asyncio.create_task(listen())
    await asyncio.sleep(5)  # give the receiver time to attach at "@latest"
    publisher = make_publisher("eventhubs")
    msg = ControlEnvelope(match_id="eh_check", run_id=run_id, game_time_s=0.0,
                          payload=ControlMessage(action="run_started", detail="connectivity check"))
    t0 = time.time()
    await publisher.send([msg])
    await publisher.close()
    try:
        await asyncio.wait_for(received, timeout=30)
        print(f"[eh-check] OK: sent and received through Event Hubs in {time.time() - t0:.2f}s")
        code = 0
    except asyncio.TimeoutError:
        print("[eh-check] FAILED: message sent but not received within 30 s")
        code = 1
    await subscriber.close()
    task.cancel()
    return code


async def _build_demo(args) -> int:
    from backend.api.demo import DemoStore, build_bundle
    from backend.api.hub import ViewerHub
    from backend.api.library import MatchLibrary
    from backend.api.plugins import PipelineContext, load_plugins
    from backend.api.settings import Settings
    from backend.services.budget import DailyTokenBudget

    settings = Settings()
    plugins = [p for p in (args.plugins.split(",") if args.plugins else settings.plugins) if p]
    library = MatchLibrary(args.data_dir, max_loaded=1)
    out = Path(args.out) if args.out else settings.demo_dir
    for sid in (list_scenarios() if args.all else [args.scenario]):
        spec = load_scenario(sid)
        match = await library.get(spec.match_id)
        ctx = PipelineContext(ViewerHub(0), DailyTokenBudget(settings.daily_token_cap), settings, library)
        ctx.demo = DemoStore(out)
        load_plugins(ctx, plugins)
        if len(ctx.loaded_plugins) != len(plugins):
            print(f"[build-demo] some plugins failed to load: wanted {plugins}, loaded {ctx.loaded_plugins}")
            return 1
        t0 = time.time()
        bundle = await build_bundle(match, ctx)
        path = bundle.save(out)
        print(f"[build-demo] {sid:16} {bundle.counts()}  plugins {bundle.plugins}  errors {ctx.errors}  "
              f"({time.time() - t0:.1f}s) -> {path}")
        if ctx.errors:
            return 1
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    uvicorn.run("backend.api.main:app", host=args.host, port=args.port, reload=args.reload,
                proxy_headers=True, forwarded_allow_ips="*")
    return 0


async def _smoke(args) -> int:
    """End-to-end check of a running deployment. Exit code 0 only if every check passes."""
    import httpx
    import websockets

    base = args.url.rstrip("/")
    ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> bool:
        results.append((name, ok, detail))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")
        return ok

    async def ws_collect(url: str, until, timeout: float, send: dict | None = None) -> list[dict]:
        got: list[dict] = []
        async with websockets.connect(url, open_timeout=20, max_size=2**22) as ws:
            if send:
                await ws.send(json.dumps(send))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.monotonic()))
                except asyncio.TimeoutError:
                    break
                got.append(json.loads(raw))
                if until(got):
                    break
        return got

    print(f"[smoke] {base}")
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
        t0 = time.monotonic()
        try:
            r = await http.get(f"{base}/api/health")
        except httpx.HTTPError as exc:
            check("health responds", False, f"cannot reach {base}: {exc!r}")
            print("[smoke] 0 checks passed; is the URL right and the app running? (az containerapp logs show ...)")
            return 1
        h = r.json() if r.status_code == 200 else {}
        check("health responds", r.status_code == 200, f"{r.status_code} in {time.monotonic() - t0:.2f}s")
        if h:
            check("stream transport", not h.get("transport_fallback_reason"),
                  f"{h.get('transport')} (configured {h.get('transport_configured')})"
                  + (f" FALLBACK: {h['transport_fallback_reason']}" if h.get("transport_fallback_reason") else ""))
            bundles = {b["match_id"]: b for b in h.get("demo_bundles", [])}
            demo = bundles.get(args.match)
            check("demo bundle present and current", bool(demo) and not demo.get("stale"),
                  str(demo.get("counts") if demo else "missing"))
            check("plugins loaded without errors", h["pipeline"]["errors"] == 0, str(h["pipeline"]["plugins"]))
            print(f"        budget: {h.get('budget')}")
        r = await http.get(f"{base}/api/scenarios")
        check("scenarios listed", r.status_code == 200 and len(r.json()) >= 1, f"{len(r.json()) if r.status_code == 200 else r.status_code}")
        r = await http.get(f"{base}/api/matches/{args.match}/events", params={"types": "goal"})
        goals = r.json() if r.status_code == 200 else []
        check("goal events served", len(goals) >= 1, f"{len(goals)} goals")
        if args.origin:
            r = await http.get(f"{base}/api/health", headers={"Origin": args.origin})
            allowed = r.headers.get("access-control-allow-origin")
            check("CORS allows the frontend", allowed in (args.origin, "*"), f"allow-origin={allowed}")

    first_goal_min = (goals[0]["game_clock_s"] // 60) if goals else 12
    start = max(0, first_goal_min - 1)
    t0 = time.monotonic()
    try:
        msgs = await ws_collect(f"{ws_base}/ws/demo/{args.match}?speed=60&from_minute={start}&persona=tactical&lang=en",
                            lambda g: any(m["type"] == "overlay" for m in g), timeout=45)
    except Exception as exc:
        msgs = []
        print(f"        demo WebSocket error: {exc!r}")
    kinds = {m["type"] for m in msgs}
    check("demo WebSocket streams match data", {"hello", "metadata", "event", "tracking"} <= kinds,
          f"{len(msgs)} messages, types {sorted(kinds)}")
    ov = next((m for m in msgs if m["type"] == "overlay"), None)
    check("demo overlay delivered", ov is not None,
          f"'{ov['data']['headline']}' after {time.monotonic() - t0:.1f}s" if ov else "none within 45 s")

    if args.live:
        async with httpx.AsyncClient(timeout=30) as http:
            headers = {"X-Admin-Token": args.admin_token} if args.admin_token else {}
            r = await http.post(f"{base}/api/matches/{args.match}/start", params={"speed": 20, "from_minute": start},
                                headers=headers)
            ok = check("live start accepted", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
            token = r.json().get("control_token") if ok else None
            if ok:
                delay = h.get("broadcast_delay_s", 6) if h else 6
                try:
                    msgs = await ws_collect(f"{ws_base}/ws/matches/{args.match}?tracking_hz=0",
                                            lambda g: sum(m["type"] == "event" for m in g) >= 5, timeout=delay + 30)
                except Exception as exc:
                    msgs = []
                    print(f"        live WebSocket error: {exc!r}")
                n = sum(m["type"] == "event" for m in msgs)
                check("live events arrive through the stream", n >= 5, f"{n} events (delay {delay}s)")
                r = await http.post(f"{base}/api/matches/{args.match}/stop", headers={"X-Control-Token": token, **headers})
                check("live stop with control token", r.status_code == 200, str(r.status_code))
                r = await http.get(f"{base}/api/health")
                hh = r.json()
                check("stream still healthy after live run", not hh.get("transport_fallback_reason"),
                      f"messages received {hh['stream']['messages_received']}")

    failed = [n for n, ok, _ in results if not ok]
    print(f"[smoke] {len(results) - len(failed)}/{len(results)} checks passed" + (f"; failed: {failed}" if failed else ""))
    return 1 if failed else 0


def cmd_export_schemas(args) -> int:
    out = ROOT / "shared" / "schemas" / "json"
    out.mkdir(parents=True, exist_ok=True)
    models = {
        "A_synthetic_event": SyntheticEvent, "A2_tracking_frame": TrackingFrame, "B_moment": Moment,
        "C_overlay": Overlay, "D_insight_brief": InsightBrief, "E_scenario_spec": ScenarioSpec,
        "match_metadata": MatchMetadata,
    }
    for name, model in models.items():
        (out / f"{name}.schema.json").write_text(json.dumps(model.model_json_schema(), indent=2), encoding="utf-8")
    (out / "stream_envelope.schema.json").write_text(json.dumps(envelope_adapter.json_schema(), indent=2), encoding="utf-8")
    print(f"[schemas] wrote {len(models) + 1} files to {out}")
    return 0


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env")


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    ap = argparse.ArgumentParser(prog="everyfan")
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("generate", "validate"):
        p = sub.add_parser(name)
        g = p.add_mutually_exclusive_group()
        g.add_argument("--scenario", default="derby_balanced", choices=list_scenarios())
        g.add_argument("--all", action="store_true")

    p = sub.add_parser("replay")
    p.add_argument("--scenario", default="derby_balanced", choices=list_scenarios())
    p.add_argument("--speed", type=float, default=20.0, help="1, 5, 20 ... or 0 for as fast as possible")
    p.add_argument("--from-minute", type=float, default=0.0)
    p.add_argument("--transport", choices=["local", "eventhubs"], default=None)
    p.add_argument("--no-tracking", action="store_true")
    p.add_argument("--consume", action="store_true", help="also consume (Event Hubs) in this process")
    p.add_argument("--sink", help="write applied events to this JSONL file")
    p.add_argument("--verbose", action="store_true")

    p = sub.add_parser("consume")
    p.add_argument("--transport", choices=["local", "eventhubs"], default="eventhubs")
    p.add_argument("--from-start", action="store_true", help="read retained messages, not only new ones")
    p.add_argument("--once", action="store_true", help="exit after one run finishes")
    p.add_argument("--sink")

    sub.add_parser("eh-check")
    sub.add_parser("export-schemas")

    p = sub.add_parser("build-demo")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--scenario", default="derby_balanced", choices=list_scenarios())
    g.add_argument("--all", action="store_true")
    p.add_argument("--plugins", help="comma-separated plugin specs (default: PIPELINE_PLUGINS)")
    p.add_argument("--out", help="output folder (default: demo/)")

    p = sub.add_parser("serve")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")

    p = sub.add_parser("smoke")
    p.add_argument("--url", required=True, help="e.g. https://everyfan-api.<env>.<region>.azurecontainerapps.io")
    p.add_argument("--match", default="match_001")
    p.add_argument("--origin", help="frontend origin to check CORS for")
    p.add_argument("--live", action="store_true", help="also start a short live run (uses the stream and plugins)")
    p.add_argument("--admin-token", help="ADMIN_TOKEN, lets --live take over a running broadcast")

    args = ap.parse_args(argv)
    if args.cmd == "generate":
        return cmd_generate(args)
    if args.cmd == "validate":
        return cmd_validate(args)
    if args.cmd == "export-schemas":
        return cmd_export_schemas(args)
    if args.cmd == "serve":
        return cmd_serve(args)
    runner = {"replay": _replay, "consume": _consume, "eh-check": _eh_check, "build-demo": _build_demo,
              "smoke": _smoke}[args.cmd]
    try:
        return asyncio.run(runner(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
