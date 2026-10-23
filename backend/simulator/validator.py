"""Physical-realism and consistency checks for a generated match (runs in CI).

Rules
  R1  player speed <= 37 km/h between consecutive frames of the same period
  R2  ball speed on every ball_path <= 140 km/h
  R3  event seq is 1..N with no gaps; game_time_s never decreases
  R4  period 1 events in [0, 2700], period 2 events in [2700, 5400]
  R5  11 players per side in every frame, minus players sent off
  R6  goals per team == final score; goal qualifiers carry the running score
  R7  every player_id / receiver_id in an event belongs to the right team (or the opponent for receivers of fouls/tackles/duels)
  R8  every event's coordinates are inside the pitch (enforced by the schema)
  R9  tracking frames are 0.5 s apart, frame index matches time
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shared.schemas import HALF_DURATION_S, MatchMetadata, SyntheticEvent, TrackingFrame

MAX_PLAYER_KMH = 37.0
MAX_BALL_KMH = 140.0
OPPONENT_RECEIVER_TYPES = {"foul", "tackle", "duel"}


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def fail(self, rule: str, msg: str) -> None:
        if len(self.errors) < 200:
            self.errors.append(f"{rule}: {msg}")


def validate_match(meta: MatchMetadata, events: list[SyntheticEvent], frames: list[TrackingFrame]) -> ValidationReport:
    rep = ValidationReport()
    team_of = {p.player_id: t.team_id for t in (meta.home, meta.away) for p in t.players}
    teams = {meta.home.team_id, meta.away.team_id}

    # R3, R4, R2, R7, R6
    last_t = -1.0
    goals = {tid: 0 for tid in teams}
    sent_off: list[tuple[float, str]] = []
    max_ball = 0.0
    for i, e in enumerate(events, start=1):
        if e.seq != i:
            rep.fail("R3", f"{e.event_id} has seq {e.seq}, expected {i}")
        if e.game_time_s < last_t:
            rep.fail("R3", f"{e.event_id} goes back in time ({e.game_time_s} < {last_t})")
        last_t = e.game_time_s
        if e.game_clock_s != math.floor(e.game_time_s):
            rep.fail("R3", f"{e.event_id} game_clock_s != floor(game_time_s)")
        lo, hi = (0, HALF_DURATION_S) if e.period == 1 else (HALF_DURATION_S, 2 * HALF_DURATION_S)
        if not lo <= e.game_time_s <= hi:
            rep.fail("R4", f"{e.event_id} at {e.game_time_s}s is outside period {e.period}")
        if e.team_id is not None and e.team_id not in teams:
            rep.fail("R7", f"{e.event_id} unknown team {e.team_id}")
        if e.player_id is not None and team_of.get(e.player_id) != e.team_id:
            rep.fail("R7", f"{e.event_id} player {e.player_id} is not in {e.team_id}")
        if e.receiver_id is not None:
            rteam = team_of.get(e.receiver_id)
            same = e.type not in OPPONENT_RECEIVER_TYPES
            if rteam is None or (rteam == e.team_id) != same:
                rep.fail("R7", f"{e.event_id} receiver {e.receiver_id} on wrong team for {e.type}")
        if e.ball_path and e.duration_s:
            length = sum(math.dist(a[1:], b[1:]) for a, b in zip(e.ball_path, e.ball_path[1:]))
            kmh = length / e.duration_s * 3.6
            max_ball = max(max_ball, kmh)
            if kmh > MAX_BALL_KMH:
                rep.fail("R2", f"{e.event_id} ball speed {kmh:.1f} km/h")
        if e.type == "goal":
            goals[e.team_id] += 1
            q = e.qualifiers
            side_score = (q.get("home_score"), q.get("away_score"))
            if side_score != (goals[meta.home.team_id], goals[meta.away.team_id]):
                rep.fail("R6", f"{e.event_id} running score {side_score} does not match goals")
        if e.type == "card" and e.outcome in ("red", "second_yellow"):
            sent_off.append((e.game_time_s, e.team_id))

    goal_shots = sum(1 for e in events if e.type == "shot" and e.outcome == "goal")
    if goal_shots != sum(goals.values()):
        rep.fail("R6", f"{goal_shots} goal shots but {sum(goals.values())} goal events")

    # R1, R5, R9
    prev: dict[str, tuple[float, float, int]] = {}
    max_player = 0.0
    for k, f in enumerate(frames):
        if f.frame != k or abs(f.game_clock_s - k * 0.5) > 1e-9:
            rep.fail("R9", f"frame {k} has index {f.frame} / time {f.game_clock_s}")
        for tid in teams:
            red = sum(1 for t, team in sent_off if team == tid and t <= f.game_clock_s - 1.0)
            n = sum(1 for p in f.players if p.team_id == tid)
            # During the second after a red card either count is acceptable.
            red_now = sum(1 for t, team in sent_off if team == tid and t <= f.game_clock_s)
            if n not in {11 - red, 11 - red_now}:
                rep.fail("R5", f"frame {k}: {tid} has {n} players, expected {11 - red_now}")
        for p in f.players:
            if team_of.get(p.player_id) != p.team_id:
                rep.fail("R7", f"frame {k}: {p.player_id} listed for {p.team_id}")
            last = prev.get(p.player_id)
            if last and last[2] == f.period:
                kmh = math.dist(last[:2], (p.x_m, p.y_m)) / 0.5 * 3.6
                max_player = max(max_player, kmh)
                if kmh > MAX_PLAYER_KMH:
                    rep.fail("R1", f"frame {k}: {p.player_id} moved at {kmh:.1f} km/h")
            prev[p.player_id] = (p.x_m, p.y_m, f.period)

    rep.stats = {
        "events": len(events),
        "frames": len(frames),
        "score": {meta.home.team_id: goals[meta.home.team_id], meta.away.team_id: goals[meta.away.team_id]},
        "max_ball_speed_kmh": round(max_ball, 1),
        "max_player_speed_kmh": round(max_player, 1),
        "sent_off": len(sent_off),
    }
    return rep
