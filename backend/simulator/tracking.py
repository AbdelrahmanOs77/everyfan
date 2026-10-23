"""Builds 2 Hz tracking frames (Contract A2) from the event engine's timelines.

Each player moves towards a target with capped speed (his top speed) and capped
acceleration (4 m/s^2), so speeds and distances are physically plausible and can
be measured by analytics. Targets:
  * the ball carrier runs to the ball
  * the nearest defender presses the ball (stops ~1.8 m short)
  * everyone else follows `MatchEngine.formation_target`
"""

from __future__ import annotations

import bisect
import math

from shared.schemas import (
    HALF_DURATION_S,
    MATCH_DURATION_S,
    PITCH_LENGTH_M,
    PITCH_WIDTH_M,
    BallPosition,
    PlayerPosition,
    TrackingFrame,
)

from .engine import CX, CY, MatchEngine, clamp, other, to_abs, to_team, value_at

DT = 0.5
MAX_DV = 2.0  # m/s change per 0.5 s step = 4 m/s^2


def _interp_ball(kf_t: list[float], kf: list[tuple[float, float, float]], t: float) -> tuple[float, float]:
    i = bisect.bisect_right(kf_t, t)
    if i == 0:
        return kf[0][1], kf[0][2]
    if i >= len(kf):
        return kf[-1][1], kf[-1][2]
    t0, x0, y0 = kf[i - 1]
    t1, x1, y1 = kf[i]
    if t1 <= t0:
        return x1, y1
    f = (t - t0) / (t1 - t0)
    return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f


def _kickoff_position(engine: MatchEngine, pid: str, t: float, kick_side: str) -> tuple[float, float]:
    p = engine.players[pid]
    x, y = engine.formation_target(p, t, (CX, CY), kick_side)
    tx, ty = to_team(p.side, x, y)
    tx = min(tx, CX - 1.5)
    if p.side == kick_side and p.position == "ST":
        tx, ty = CX - 0.3, CY
    return to_abs(p.side, tx, ty)


def build_tracking(engine: MatchEngine) -> list[TrackingFrame]:
    tl = engine.tl
    kf_t = [k[0] for k in tl.ball]
    roster = sorted(tl.roster, key=lambda r: r[0])
    r_idx = 0
    active: set[str] = set()
    state: dict[str, list[float]] = {}  # pid -> [x, y, vx, vy]
    frames: list[TrackingFrame] = []
    n_frames = int(MATCH_DURATION_S / DT) + 1

    for k in range(n_frames):
        t = k * DT
        period = 1 if t < HALF_DURATION_S else 2

        # Roster changes (kick-off line-up, substitutions, red cards).
        while r_idx < len(roster) and roster[r_idx][0] <= t:
            _, pid, is_active = roster[r_idx]
            r_idx += 1
            if is_active:
                active.add(pid)
                if pid not in state and t > 0:
                    p = engine.players[pid]
                    sx, sy = to_abs(p.side, CX - 3.0, 0.5)  # enters from the touchline
                    state[pid] = [sx, sy, 0.0, 0.0]
            else:
                active.discard(pid)
                state.pop(pid, None)

        if t in (0.0, float(HALF_DURATION_S)):
            kick_side = "home" if t == 0 else "away"
            for pid in active:
                x, y = _kickoff_position(engine, pid, t, kick_side)
                state[pid] = [x, y, 0.0, 0.0]

        ball = _interp_ball(kf_t, tl.ball, t)
        poss = value_at(tl.possession, t, "home")
        carrier = value_at(tl.carrier, t, None)
        defenders = [pid for pid in active
                     if engine.players[pid].side == other(poss) and engine.players[pid].position != "GK"]
        presser = min(defenders, key=lambda pid: (math.dist(state[pid][:2], ball), pid)) if defenders else None

        positions = []
        for pid in sorted(active):
            p = engine.players[pid]
            x, y, vx, vy = state[pid]
            if pid == carrier:
                tx, ty = ball
            elif pid == presser:
                d = math.dist((x, y), ball) or 1.0
                tx, ty = ball[0] + (x - ball[0]) / d * 1.8, ball[1] + (y - ball[1]) / d * 1.8
            else:
                tx, ty = engine.formation_target(p, t, ball, poss)

            dvx, dvy = (tx - x) / 1.0, (ty - y) / 1.0
            sp = math.hypot(dvx, dvy)
            if sp > p.top_speed:
                dvx, dvy = dvx / sp * p.top_speed, dvy / sp * p.top_speed
            ax, ay = dvx - vx, dvy - vy
            a = math.hypot(ax, ay)
            if a > MAX_DV:
                ax, ay = ax / a * MAX_DV, ay / a * MAX_DV
            vx, vy = vx + ax, vy + ay
            sp = math.hypot(vx, vy)
            if sp > p.top_speed:
                vx, vy = vx / sp * p.top_speed, vy / sp * p.top_speed
            nx = clamp(x + vx * DT, 0.0, PITCH_LENGTH_M)
            ny = clamp(y + vy * DT, 0.0, PITCH_WIDTH_M)
            if k == 0 or t == HALF_DURATION_S:
                nx, ny, vx, vy = x, y, 0.0, 0.0
            state[pid] = [nx, ny, (nx - x) / DT if k else 0.0, (ny - y) / DT if k else 0.0]
            positions.append(PlayerPosition.model_construct(
                player_id=pid, team_id=p.team_id, x_m=round(nx, 2), y_m=round(ny, 2)))

        frames.append(TrackingFrame.model_construct(
            schema_version="1.0",
            match_id=engine.match_id,
            frame=k,
            game_clock_s=t,
            period=period,
            ball=BallPosition.model_construct(x_m=round(ball[0], 2), y_m=round(ball[1], 2)),
            players=positions,
        ))
    return frames
