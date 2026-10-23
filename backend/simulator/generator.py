"""Generate a full synthetic match from a scenario and write it to disk.

Output folder data/<match_id>/:
  metadata.json   MatchMetadata
  events.jsonl    one SyntheticEvent (Contract A) per line, ordered by seq
  tracking.jsonl  one TrackingFrame (Contract A2) per line, 2 Hz
  summary.json    counts, score, speeds and SHA-256 hashes (used by the determinism test)
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from shared.schemas import MatchMetadata, ScenarioSpec, SyntheticEvent, TrackingFrame

from .engine import MatchEngine
from .tracking import build_tracking

SCENARIO_DIR = Path(__file__).parent / "scenarios"
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@dataclass
class GeneratedMatch:
    spec: ScenarioSpec
    metadata: MatchMetadata
    events: list[SyntheticEvent]
    frames: list[TrackingFrame]


def list_scenarios() -> list[str]:
    return sorted(p.stem for p in SCENARIO_DIR.glob("*.json"))


def load_scenario(scenario_id: str) -> ScenarioSpec:
    path = SCENARIO_DIR / f"{scenario_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"unknown scenario {scenario_id!r}; available: {list_scenarios()}")
    return ScenarioSpec.model_validate_json(path.read_text(encoding="utf-8"))


def generate(spec: ScenarioSpec) -> GeneratedMatch:
    engine = MatchEngine(spec)
    meta, events, _ = engine.run()
    frames = build_tracking(engine)
    return GeneratedMatch(spec, meta, events, frames)


def _jsonl(models) -> bytes:
    return "".join(m.model_dump_json(exclude_none=True) + "\n" for m in models).encode("utf-8")


def summarize(match: GeneratedMatch, events_bytes: bytes, tracking_bytes: bytes) -> dict:
    meta = match.metadata
    team_name = {meta.home.team_id: "home", meta.away.team_id: "away"}
    types = Counter(e.type for e in match.events)
    per_team = {side: Counter() for side in ("home", "away")}
    max_shot = 0.0
    for e in match.events:
        if e.team_id is None:
            continue
        side = team_name[e.team_id]
        if e.type == "pass":
            per_team[side]["passes"] += 1
            per_team[side]["passes_completed"] += e.outcome == "completed"
        elif e.type == "shot":
            per_team[side]["shots"] += 1
            if e.ball_path and e.duration_s:
                length = sum(math.dist(a[1:], b[1:]) for a, b in zip(e.ball_path, e.ball_path[1:]))
                max_shot = max(max_shot, length / e.duration_s * 3.6)
        elif e.type == "goal":
            per_team[side]["goals"] += 1

    # Distance and top speed from tracking.
    last: dict[str, tuple[float, float, int]] = {}
    dist: Counter = Counter()
    top: dict[str, float] = {}
    for f in match.frames:
        for p in f.players:
            prev = last.get(p.player_id)
            if prev and prev[2] == f.period:
                d = math.dist(prev[:2], (p.x_m, p.y_m))
                dist[p.player_id] += d
                top[p.player_id] = max(top.get(p.player_id, 0.0), d / 0.5 * 3.6)
            last[p.player_id] = (p.x_m, p.y_m, f.period)

    first = {pl.player_id for pl in match.frames[0].players}
    final = {pl.player_id for pl in match.frames[-1].players}
    gks = {p.player_id for t in (meta.home, meta.away) for p in t.players if p.position == "GK"}
    full_match = sorted((first & final) - gks)
    avg_km = sum(dist[p] for p in full_match) / max(len(full_match), 1) / 1000
    return {
        "match_id": meta.match_id,
        "scenario_id": match.spec.scenario_id,
        "seed": match.spec.seed,
        "title": match.spec.title,
        "final_score": {"home": per_team["home"]["goals"], "away": per_team["away"]["goals"]},
        "events_total": len(match.events),
        "frames_total": len(match.frames),
        "event_types": dict(sorted(types.items())),
        "teams": {
            side: {
                "team_id": getattr(meta, side).team_id,
                "passes": c["passes"],
                "pass_accuracy": round(c["passes_completed"] / c["passes"], 3) if c["passes"] else None,
                "shots": c["shots"],
                "goals": c["goals"],
            }
            for side, c in per_team.items()
        },
        "max_shot_speed_kmh": round(max_shot, 1),
        "max_player_speed_kmh": round(max(top.values()), 1),
        "avg_distance_full_match_km": round(avg_km, 2),
        "sha256": {
            "events": hashlib.sha256(events_bytes).hexdigest(),
            "tracking": hashlib.sha256(tracking_bytes).hexdigest(),
        },
    }


def write_match(match: GeneratedMatch, data_dir: Path = DEFAULT_DATA_DIR) -> Path:
    out = Path(data_dir) / match.metadata.match_id
    out.mkdir(parents=True, exist_ok=True)
    events_bytes = _jsonl(match.events)
    tracking_bytes = _jsonl(match.frames)
    (out / "metadata.json").write_text(match.metadata.model_dump_json(indent=2), encoding="utf-8")
    (out / "events.jsonl").write_bytes(events_bytes)
    (out / "tracking.jsonl").write_bytes(tracking_bytes)
    (out / "scenario.json").write_text(match.spec.model_dump_json(indent=2), encoding="utf-8")
    summary = summarize(match, events_bytes, tracking_bytes)
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return out


def load_match(folder: Path) -> tuple[MatchMetadata, list[SyntheticEvent], list[TrackingFrame]]:
    folder = Path(folder)
    meta = MatchMetadata.model_validate_json((folder / "metadata.json").read_text(encoding="utf-8"))
    with open(folder / "events.jsonl", encoding="utf-8") as fh:
        events = [SyntheticEvent.model_validate_json(line) for line in fh if line.strip()]
    with open(folder / "tracking.jsonl", encoding="utf-8") as fh:
        frames = [TrackingFrame.model_validate_json(line) for line in fh if line.strip()]
    return meta, events, frames
