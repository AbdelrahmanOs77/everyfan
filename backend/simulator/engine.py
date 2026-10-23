"""Deterministic possession-chain match simulator.

Given a ScenarioSpec (seed + team parameters + scripted story beats) it produces:
  * match metadata
  * an ordered list of SyntheticEvent (Contract A)
  * 2 Hz TrackingFrames (Contract A2) via `tracking.build_tracking`

Same spec -> byte-identical output. Only `random.Random(seed)` is used for randomness.

Coordinates: decisions are made in the attacking team's frame (attacking towards
x = 105) and converted to the absolute pitch frame with `to_abs` (home = identity,
away = mirrored). Only absolute coordinates are ever written out.
"""

from __future__ import annotations

import bisect
import math
import random
from dataclasses import dataclass, field

from shared.schemas import (
    HALF_DURATION_S,
    MATCH_DURATION_S,
    PITCH_LENGTH_M,
    PITCH_WIDTH_M,
    MatchMetadata,
    ScenarioSpec,
    SyntheticEvent,
)

from .teams import CLUBS, build_team_info, player_id

L, W = PITCH_LENGTH_M, PITCH_WIDTH_M
CX, CY = L / 2, W / 2
GOAL_HALF_WIDTH = 3.66


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def to_abs(side: str, x: float, y: float) -> tuple[float, float]:
    """Team frame -> absolute frame (the mapping is its own inverse)."""
    return (x, y) if side == "home" else (L - x, W - y)


to_team = to_abs


def other(side: str) -> str:
    return "away" if side == "home" else "home"


@dataclass
class SimPlayer:
    id: str
    team_id: str
    side: str
    position: str
    top_speed: float          # m/s
    anchor: tuple[float, float] | None
    roam: tuple[float, float, float, float, float]  # ax, ay, period_x, period_y, phase
    active: bool = False
    sent_off: bool = False
    yellows: int = 0


@dataclass
class Timelines:
    """Everything the tracking builder needs to reconstruct player movement."""

    ball: list[tuple[float, float, float]] = field(default_factory=list)       # (t, x, y)
    possession: list[tuple[float, str]] = field(default_factory=list)          # (t, side)
    carrier: list[tuple[float, str | None]] = field(default_factory=list)      # (t, player_id)
    roster: list[tuple[float, str, bool]] = field(default_factory=list)        # (t, player_id, active)


def value_at(timeline: list[tuple], t: float, default=None):
    """Latest value at or before t in a (t, value) timeline."""
    idx = bisect.bisect_right(timeline, t, key=lambda e: e[0]) - 1
    return timeline[idx][1] if idx >= 0 else default


class MatchEngine:
    def __init__(self, spec: ScenarioSpec):
        self.spec = spec
        self.rng = random.Random(spec.seed)
        self.match_id = spec.match_id
        self.team_of = {"home": spec.home.team_id, "away": spec.away.team_id}
        self.side_of = {spec.home.team_id: "home", spec.away.team_id: "away"}
        self.params = {"home": spec.home, "away": spec.away}

        self.players: dict[str, SimPlayer] = {}
        for side in ("home", "away"):
            club = CLUBS[self.team_of[side]]
            for slot in club["squad"]:
                pid = player_id(club, slot.shirt)
                self.players[pid] = SimPlayer(
                    id=pid,
                    team_id=club["team_id"],
                    side=side,
                    position=slot.position,
                    top_speed=slot.top_speed_kmh / 3.6,
                    anchor=slot.anchor,
                    roam=self._roam(slot.position),
                    active=slot.anchor is not None,
                )

        self.tl = Timelines()
        for p in self.players.values():
            if p.active:
                self.tl.roster.append((0.0, p.id, True))

        self.events: list[dict] = []
        self.seq = 0
        self.t = 0.0
        self.period = 1
        self.poss = "home"
        self.carrier: SimPlayer | None = None
        self.ball = (CX, CY)
        self.score = {"home": 0, "away": 0}
        self.forced = sorted(spec.forced_events, key=lambda f: f.minute)
        self.forced_done = [False] * len(self.forced)
        self.subbed_in: set[str] = set()
        self.subs = self._plan_substitutions() if spec.substitutions else []

    # ------------------------------------------------------------------ setup

    def _roam(self, position: str) -> tuple[float, float, float, float, float]:
        r = self.rng
        amp = 1.5 if position == "GK" else r.uniform(2.5, 4.5)
        return (amp, amp * 0.8, r.uniform(24, 48), r.uniform(26, 56), r.uniform(0, 2 * math.pi))

    def _plan_substitutions(self) -> list[dict]:
        plan = []
        for side in ("home", "away"):
            bench = [p for p in self.players.values() if p.side == side and not p.active]
            minutes = sorted([self.rng.uniform(61, 68), self.rng.uniform(70, 77), self.rng.uniform(78, 84)])
            for minute, sub in zip(minutes, bench):
                plan.append({"t": minute * 60, "side": side, "in": sub.id, "done": False})
        plan.sort(key=lambda s: s["t"])
        return plan

    # ------------------------------------------------------------ team params

    def team_params(self, side: str, t: float) -> tuple[float, float, float]:
        base = self.params[side]
        strength, press, tempo = base.strength, base.press_intensity, base.tempo
        minute = t / 60.0
        for ph in self.spec.phases:
            if ph.team_id == self.team_of[side] and ph.from_minute <= minute < ph.to_minute:
                strength += ph.strength_delta
                press = ph.press_intensity if ph.press_intensity is not None else press
                tempo = ph.tempo if ph.tempo is not None else tempo
        sent = sum(1 for p in self.players.values() if p.side == side and p.sent_off)
        return clamp(strength - 0.08 * sent, 0.05, 0.95), clamp(press - 0.15 * sent, 0.0, 1.0), tempo

    # --------------------------------------------------------- positioning

    def formation_target(self, p: SimPlayer, t: float, ball: tuple[float, float], poss: str) -> tuple[float, float]:
        """Where a player 'wants' to be. Shared by the event engine and tracking."""
        bx, by = to_team(p.side, *ball)
        ax, ay = p.anchor or (50.0, 34.0)
        rx, ry, px, py, ph = p.roam
        if p.position == "GK":
            x = clamp(4.0 + max(0.0, bx - 35.0) * 0.12, 1.5, 17.0)
            y = CY + (by - CY) * 0.15
        else:
            attacking = poss == p.side
            _, press, _ = self.team_params(p.side, t)
            shift = (bx - CX) * 0.5
            offset = 7.0 if attacking else -10.0 + 16.0 * press
            x = ax + shift + offset
            y = ay + (by - CY) * 0.28
            y = CY + (y - CY) * (1.12 if attacking else 0.85)
            x += rx * math.sin(2 * math.pi * t / px + ph)
            y += ry * math.sin(2 * math.pi * t / py + ph * 1.7)
        return to_abs(p.side, clamp(x, 1.0, L - 1.0), clamp(y, 1.0, W - 1.0))

    def pos(self, p: SimPlayer) -> tuple[float, float]:
        if self.carrier is p:
            return self.ball
        return self.formation_target(p, self.t, self.ball, self.poss)

    def active(self, side: str, outfield_only: bool = False) -> list[SimPlayer]:
        return [
            p for p in self.players.values()
            if p.side == side and p.active and not (outfield_only and p.position == "GK")
        ]

    def nearest(self, side: str, point: tuple[float, float], outfield_only: bool = True,
                exclude: SimPlayer | None = None) -> SimPlayer:
        cands = [p for p in self.active(side, outfield_only) if p is not exclude]
        return min(cands, key=lambda p: (math.dist(self.pos(p), point), p.id))

    def goalkeeper(self, side: str) -> SimPlayer:
        return next(p for p in self.active(side) if p.position == "GK")

    # -------------------------------------------------------------- emission

    def emit(self, etype: str, side: str | None = None, player: SimPlayer | None = None,
             t: float | None = None, **kw) -> dict:
        t = self.t if t is None else t
        t = round(min(t, float(HALF_DURATION_S) if self.period == 1 else float(MATCH_DURATION_S)), 2)
        self.seq += 1
        ev = {
            "event_id": f"evt_{self.seq:05d}",
            "match_id": self.match_id,
            "seq": self.seq,
            "game_clock_s": int(math.floor(t)),
            "game_time_s": round(t, 2),
            "period": self.period,
            "type": etype,
            "team_id": self.team_of[side] if side else None,
            "player_id": player.id if player else None,
        }
        for key, val in kw.items():
            if val is None:
                continue
            if key.endswith(("_x_m", "_y_m")):
                lim = L if key.endswith("_x_m") else W
                val = round(clamp(val, 0.0, lim), 2)
            ev[key] = val
        self.events.append(ev)
        return ev

    def set_ball(self, t: float, xy: tuple[float, float]) -> None:
        xy = (round(clamp(xy[0], 0.0, L), 2), round(clamp(xy[1], 0.0, W), 2))
        self.ball = xy
        self.tl.ball.append((round(t, 3), xy[0], xy[1]))

    def set_carrier(self, p: SimPlayer | None, t: float | None = None) -> None:
        self.carrier = p
        self.tl.carrier.append((round(self.t if t is None else t, 3), p.id if p else None))

    def change_possession(self, side: str, player: SimPlayer, reason: str, t: float | None = None) -> None:
        t = self.t if t is None else t
        if side != self.poss:
            self.poss = side
            self.tl.possession.append((round(t, 3), side))
            self.emit("possession_change", side, player, t=t, qualifiers={"reason": reason},
                      start_x_m=self.ball[0], start_y_m=self.ball[1])
        self.set_carrier(player, t)

    def path(self, start: tuple[float, float], end: tuple[float, float], duration: float) -> list[list[float]]:
        n = max(1, int(duration / 0.1))
        pts = []
        for i in range(n + 1):
            ts = min(i * 0.1, duration)
            f = ts / duration if duration > 0 else 1.0
            pts.append([round(ts, 2), round(start[0] + (end[0] - start[0]) * f, 2),
                        round(start[1] + (end[1] - start[1]) * f, 2)])
        if pts[-1][0] < round(duration, 2):
            pts.append([round(duration, 2), round(end[0], 2), round(end[1], 2)])
        return pts

    def pressure_level(self, att: str) -> float:
        _, press, _ = self.team_params(other(att), self.t)
        x, _ = to_team(att, *self.ball)
        if x < 35:
            base = 0.15 + 0.7 * press
        elif x < 70:
            base = 0.25 + 0.35 * press
        else:
            base = 0.45 + 0.2 * press
        return round(clamp(base + self.rng.uniform(-0.18, 0.18), 0.0, 1.0), 2)

    def control_time(self, side: str, lo: float = 0.7, hi: float = 2.4) -> float:
        _, _, tempo = self.team_params(side, self.t)
        return self.rng.uniform(lo, hi) / tempo ** 1.5

    def dead_time(self, side: str, lo: float, hi: float) -> float:
        """Ball out of play; faster teams restart quicker."""
        _, _, tempo = self.team_params(side, self.t)
        return self.rng.uniform(lo, hi) / tempo ** 1.5

    # --------------------------------------------------------------- actions

    def do_pass(self, passer: SimPlayer, receiver: SimPlayer, end: tuple[float, float],
                pressure: float, force: str | None = None, qualifiers: dict | None = None) -> bool:
        """Returns True if the attacking team keeps the ball."""
        side = passer.side
        start = self.ball
        dist = math.dist(start, end)
        speed = clamp(11.0 + 0.3 * dist, 10.0, 26.0)
        dur = max(0.4, dist / speed)
        strength, _, _ = self.team_params(side, self.t)
        ex, ey = to_team(side, *end)
        sx, _ = to_team(side, *start)
        in_box = ex > 88.5 and abs(ey - CY) < 20.16
        p_ok = (0.99 - 0.005 * max(dist - 12, 0) - 0.2 * pressure + 0.55 * (strength - 0.5)
                - (0.08 if in_box else 0) - 0.04 * max(ex - sx, 0) / 20)
        p_ok = clamp(p_ok, 0.3, 0.97)
        ok = force == "complete" or (force is None and self.rng.random() < p_ok)
        t0 = self.t
        if ok:
            self.emit("pass", side, passer, receiver_id=receiver.id, start_x_m=start[0], start_y_m=start[1],
                      end_x_m=end[0], end_y_m=end[1], duration_s=round(dur, 2), pressure_level=pressure,
                      outcome="completed", ball_path=self.path(start, end, dur), qualifiers=qualifiers or {})
            self.set_carrier(None, t0)
            self.t = t0 + dur
            self.set_ball(self.t, end)
            self.set_carrier(receiver)
            return True

        # Failed pass: out of play or intercepted.
        if self.rng.random() < 0.2:
            out_y = 0.0 if end[1] < CY else W
            end = (clamp(end[0], 2.0, L - 2.0), out_y)
            dist = math.dist(start, end)
            dur = max(0.4, dist / speed)
            self.emit("pass", side, passer, receiver_id=receiver.id, start_x_m=start[0], start_y_m=start[1],
                      end_x_m=end[0], end_y_m=end[1], duration_s=round(dur, 2), pressure_level=pressure,
                      outcome="out", ball_path=self.path(start, end, dur))
            self.set_carrier(None, t0)
            self.t = t0 + dur
            self.set_ball(self.t, end)
            self.restart_throw_in(other(side), end)
            return False

        f = self.rng.uniform(0.45, 0.95)
        cut = (start[0] + (end[0] - start[0]) * f, start[1] + (end[1] - start[1]) * f)
        dur = max(0.3, math.dist(start, cut) / speed)
        self.emit("pass", side, passer, receiver_id=receiver.id, start_x_m=start[0], start_y_m=start[1],
                  end_x_m=cut[0], end_y_m=cut[1], duration_s=round(dur, 2), pressure_level=pressure,
                  outcome="intercepted", ball_path=self.path(start, cut, dur))
        self.set_carrier(None, t0)
        self.t = t0 + dur
        self.set_ball(self.t, cut)
        thief = self.nearest(other(side), cut)
        self.emit("interception", other(side), thief, start_x_m=cut[0], start_y_m=cut[1])
        self.change_possession(other(side), thief, "interception")
        self.t += self.control_time(other(side), 0.5, 1.5)
        return False

    def do_carry(self, carrier: SimPlayer, end_team: tuple[float, float]) -> None:
        side = carrier.side
        ex, ey = clamp(end_team[0], 1.0, L - 3.0), clamp(end_team[1], 1.5, W - 1.5)
        end = to_abs(side, ex, ey)
        start = self.ball
        dist = math.dist(start, end)
        if dist < 1.0:
            self.t += 0.8
            return
        dur = dist / self.rng.uniform(4.5, 7.0)
        self.emit("carry", side, carrier, start_x_m=start[0], start_y_m=start[1], end_x_m=end[0], end_y_m=end[1],
                  duration_s=round(dur, 2), outcome="completed", ball_path=self.path(start, end, dur))
        self.t += dur
        self.set_ball(self.t, end)

    def do_shot(self, shooter: SimPlayer, outcome: str, speed_kmh: float) -> None:
        side = shooter.side
        start = self.ball
        sx, sy = to_team(side, *start)
        if outcome in ("goal", "saved"):
            ty = CY + self.rng.uniform(-GOAL_HALF_WIDTH + 0.3, GOAL_HALF_WIDTH - 0.3)
            tx = L if outcome == "goal" else L - 1.2
        elif outcome == "post":
            ty, tx = CY + self.rng.choice([-1, 1]) * GOAL_HALF_WIDTH, L
        elif outcome == "off_target":
            ty, tx = CY + self.rng.choice([-1, 1]) * self.rng.uniform(4.2, 9.0), L
        else:  # blocked
            f = self.rng.uniform(0.12, 0.35)
            tx = sx + (L - sx) * f
            ty = sy + (CY - sy) * f
        end = to_abs(side, tx, ty)
        dist = math.dist(start, end)
        dur = max(0.15, dist / (speed_kmh / 3.6))
        t0 = self.t
        shot = self.emit("shot", side, shooter, start_x_m=start[0], start_y_m=start[1], end_x_m=end[0],
                         end_y_m=end[1], duration_s=round(dur, 3), pressure_level=self.pressure_level(side),
                         outcome=outcome, ball_path=self.path(start, end, dur))
        self.set_carrier(None, t0)
        self.t = t0 + dur
        self.set_ball(self.t, end)
        opp = other(side)

        if outcome == "goal":
            self.score[side] += 1
            assist = self.events[-2]["player_id"] if len(self.events) > 1 and self.events[-2]["type"] == "pass" \
                and self.events[-2].get("receiver_id") == shooter.id else None
            q = {"home_score": self.score["home"], "away_score": self.score["away"]}
            if assist:
                q["assist_player_id"] = assist
            self.emit("goal", side, shooter, related_event_id=shot["event_id"], start_x_m=start[0],
                      start_y_m=start[1], qualifiers=q)
            self.t += self.rng.uniform(50, 70)  # celebration
            self.kickoff(opp)
        elif outcome == "saved":
            gk = self.goalkeeper(opp)
            self.emit("save", opp, gk, related_event_id=shot["event_id"], start_x_m=end[0], start_y_m=end[1])
            if self.rng.random() < 0.35:
                self.restart_corner(side)
            else:
                self.change_possession(opp, gk, "save")
                self.t += self.rng.uniform(4, 10)
        elif outcome == "off_target":
            self.restart_goal_kick(opp)
        else:  # blocked / post -> loose ball
            if self.rng.random() < 0.25:
                self.restart_corner(side)
                return
            winner_side = side if self.rng.random() < 0.45 else opp
            self.t += self.rng.uniform(0.6, 1.5)
            spot = to_abs(side, clamp(tx - self.rng.uniform(2, 9), 60, L - 4), clamp(ty + self.rng.uniform(-6, 6), 8, W - 8))
            self.set_ball(self.t, spot)
            winner = self.nearest(winner_side, spot)
            self.emit("recovery", winner_side, winner, start_x_m=spot[0], start_y_m=spot[1])
            self.change_possession(winner_side, winner, "loose_ball")

    # -------------------------------------------------------------- restarts

    def kickoff(self, side: str) -> None:
        end = HALF_DURATION_S if self.period == 1 else MATCH_DURATION_S
        if self.t > end - 5:
            return
        self.set_ball(self.t, (CX, CY))
        taker = next((p for p in self.active(side, True) if p.position == "ST"), None) or self.active(side, True)[0]
        self.emit("kickoff", side, taker, start_x_m=CX, start_y_m=CY)
        self.change_possession(side, taker, "kickoff")
        self.t += 0.5

    def restart_throw_in(self, side: str, spot: tuple[float, float]) -> None:
        self.t += self.dead_time(side, 8, 18)
        taker = self.nearest(side, spot)
        self.set_ball(self.t, spot)
        self.emit("throw_in", side, taker, start_x_m=spot[0], start_y_m=spot[1])
        self.change_possession(side, taker, "throw_in")
        self.t += 0.6

    def restart_goal_kick(self, side: str) -> None:
        self.t += self.dead_time(side, 18, 32)
        gk = self.goalkeeper(side)
        spot = to_abs(side, 5.5, CY + self.rng.choice([-9.0, 9.0]))
        self.set_ball(self.t, spot)
        self.emit("goal_kick", side, gk, start_x_m=spot[0], start_y_m=spot[1])
        self.change_possession(side, gk, "goal_kick")

    def restart_free_kick(self, side: str, spot: tuple[float, float], taker: SimPlayer) -> None:
        self.t += self.dead_time(side, 12, 28)
        self.set_ball(self.t, spot)
        self.emit("free_kick", side, taker, start_x_m=spot[0], start_y_m=spot[1])
        self.change_possession(side, taker, "free_kick")

    def restart_corner(self, side: str) -> None:
        self.t += self.rng.uniform(18, 32)
        cy = self.rng.choice([0.5, W - 0.5])
        spot = to_abs(side, L - 0.5, cy)
        self.set_ball(self.t, spot)
        taker = self.nearest(side, spot)
        self.emit("corner", side, taker, start_x_m=spot[0], start_y_m=spot[1])
        self.change_possession(side, taker, "corner")
        self.t += 1.0
        targets = [p for p in self.active(side, True) if p is not taker and p.position in ("ST", "CB", "AM", "CM", "DM")]
        receiver = self.rng.choice(targets)
        end = to_abs(side, self.rng.uniform(94, 101), CY + self.rng.uniform(-7, 7))
        if self.rng.random() < 0.38:
            self.do_pass(taker, receiver, end, 0.7, force="complete", qualifiers={"cross": True})
            outcome = self.rng.choices(["saved", "off_target", "blocked"], [0.35, 0.45, 0.2])[0]
            self.do_shot(receiver, outcome, self.rng.uniform(42, 72))
        else:
            self.do_pass(taker, receiver, end, 0.9, force="fail", qualifiers={"cross": True})

    # -------------------------------------------------------------- the step

    def step(self) -> None:
        side, opp = self.poss, other(self.poss)
        carrier = self.carrier or self.nearest(side, self.ball, outfield_only=False)
        if self.carrier is None:
            self.set_carrier(carrier)
        att_s, _, _ = self.team_params(side, self.t)
        def_s, _, _ = self.team_params(opp, self.t)
        x, y = to_team(side, *self.ball)
        pressure = self.pressure_level(side)
        in_box = x > 88.5 and abs(y - CY) < 20.16

        if self.rng.random() < 0.22 * pressure:
            presser = self.nearest(opp, self.ball)
            self.emit("pressure", opp, presser, start_x_m=self.ball[0], start_y_m=self.ball[1],
                      pressure_level=pressure)

        p_foul = 0.0 if in_box else 0.012 + 0.022 * pressure
        _, def_press, _ = self.team_params(opp, self.t)
        press_zone = 1.0 if x < 45 else 0.25  # pressing bites in the attacker's own half
        p_tackle = clamp(0.02 + 0.10 * pressure + 0.08 * (def_s - att_s) + 0.14 * def_press ** 2 * press_zone, 0.01, 0.3)
        if carrier.position == "GK":
            p_foul, p_tackle = 0.0, 0.0
        p_shot = (0.1 + 0.14 * (att_s - 0.5)) if in_box else (0.022 if x > 76 and abs(y - CY) < 22 else 0.0)
        p_carry = 0.0 if carrier.position == "GK" else 0.14 + 0.12 * (1 - pressure)

        r = self.rng.random()
        if r < p_foul:
            self.action_foul(carrier, self.nearest(opp, self.ball))
        elif r < p_foul + p_tackle:
            self.action_tackle(carrier, self.nearest(opp, self.ball), att_s, def_s)
        elif r < p_foul + p_tackle + p_shot:
            dist_goal = math.dist((x, y), (L, CY))
            speed = clamp(self.rng.gauss(64 + 0.45 * dist_goal, 11), 40, 102)
            outcome = self.rng.choices(["saved", "off_target", "blocked", "post"], [0.36, 0.37, 0.23, 0.04])[0]
            if self.spec.allow_organic_goals and self.rng.random() < clamp(0.32 - 0.012 * dist_goal, 0.02, 0.3):
                outcome = "goal"
            self.do_shot(carrier, outcome, speed)
        elif r < p_foul + p_tackle + p_shot + p_carry:
            self.do_carry(carrier, (x + self.rng.uniform(4, 13) * (0.6 + att_s), y + self.rng.gauss(0, 4)))
            self.t += self.control_time(side, 0.2, 0.8)
        else:
            receiver, end = self.choose_pass(carrier, att_s)
            kept = self.do_pass(carrier, receiver, end, pressure)
            if kept:
                if pressure > 0.55 and self.rng.random() < 0.22:
                    self.action_duel(receiver, att_s, def_s)
                else:
                    self.t += self.control_time(side)

    def choose_pass(self, carrier: SimPlayer, att_s: float) -> tuple[SimPlayer, tuple[float, float]]:
        side = carrier.side
        x, y = to_team(side, *self.ball)
        cands, weights = [], []
        for p in self.active(side):
            if p is carrier or (p.position == "GK" and x > 40):
                continue
            px, py = to_team(side, *self.pos(p))
            dx, dist = px - x, math.dist((x, y), (px, py))
            w = math.exp(-((dist - 17) / 13) ** 2) + 0.05
            w *= 1 + max(dx, 0) / 25 * 0.9
            if dx < -15:
                w *= 0.45
            if carrier.position == "GK" and dist > 35:
                w *= 1.6  # goalkeepers go long
            cands.append(p)
            weights.append(w)
        receiver = self.rng.choices(cands, weights)[0]
        rx, ry = self.pos(receiver)
        end = (clamp(rx + self.rng.uniform(-1.5, 1.5), 0.5, L - 0.5), clamp(ry + self.rng.uniform(-1.5, 1.5), 0.5, W - 0.5))
        return receiver, end

    def action_foul(self, victim: SimPlayer, fouler: SimPlayer, card: str | None = None) -> None:
        side = fouler.side
        self.emit("foul", side, fouler, receiver_id=victim.id, start_x_m=self.ball[0], start_y_m=self.ball[1])
        # Organic cards are yellows only, and never a second one: red cards come from the script.
        if card is None and self.rng.random() < 0.13 and fouler.yellows == 0:
            card = "yellow"
        if card == "yellow":
            fouler.yellows += 1
            if fouler.yellows >= 2:
                card = "second_yellow"
        if card:
            self.emit("card", side, fouler, outcome=card)
            if card in ("red", "second_yellow"):
                self.send_off(fouler)
        x, y = to_team(victim.side, *self.ball)
        if x > 88.5 and abs(y - CY) < 20.16:  # keep it simple: no penalties
            x = 86.5
        spot = to_abs(victim.side, x, y)
        self.restart_free_kick(victim.side, spot, victim if victim.active else self.nearest(victim.side, spot))

    def action_tackle(self, carrier: SimPlayer, tackler: SimPlayer, att_s: float, def_s: float) -> None:
        if self.rng.random() < 0.72 + 0.2 * (def_s - att_s):
            self.emit("tackle", tackler.side, tackler, outcome="won", receiver_id=carrier.id,
                      start_x_m=self.ball[0], start_y_m=self.ball[1])
            self.change_possession(tackler.side, tackler, "tackle")
            self.t += self.control_time(tackler.side, 0.5, 1.6)
        else:
            self.emit("tackle", tackler.side, tackler, outcome="lost", receiver_id=carrier.id,
                      start_x_m=self.ball[0], start_y_m=self.ball[1])
            self.t += 0.6

    def action_duel(self, holder: SimPlayer, att_s: float, def_s: float) -> None:
        opp = other(holder.side)
        rival = self.nearest(opp, self.ball)
        won = self.rng.random() < 0.5 + 0.3 * (att_s - def_s)
        self.emit("duel", holder.side, holder, receiver_id=rival.id, outcome="won" if won else "lost",
                  start_x_m=self.ball[0], start_y_m=self.ball[1])
        self.t += 0.7
        if not won:
            self.emit("recovery", opp, rival, start_x_m=self.ball[0], start_y_m=self.ball[1])
            self.change_possession(opp, rival, "duel")
            self.t += self.control_time(opp, 0.4, 1.2)

    def send_off(self, p: SimPlayer) -> None:
        p.active, p.sent_off = False, True
        self.tl.roster.append((round(self.t, 3), p.id, False))
        if self.carrier is p:
            self.set_carrier(None)

    # ------------------------------------------------------ scripted story beats

    def run_forced(self, f) -> None:
        side = self.side_of[f.team_id]
        if f.type == "goal":
            self.scripted_attack(side, "goal", f.player_id, f.shot_speed_kmh)
        elif f.type == "big_chance":
            self.scripted_attack(side, "saved", f.player_id, f.shot_speed_kmh)
        else:
            opp = other(side)
            fouler = self.players[f.player_id] if f.player_id else self.nearest(side, self.ball)
            victim = self.nearest(opp, self.ball)
            self.action_foul(victim, fouler, card="red" if f.type == "red_card" else "yellow")

    def scripted_attack(self, side: str, outcome: str, shooter_id: str | None, speed: float | None) -> None:
        if self.carrier is None:
            self.set_carrier(self.nearest(self.poss, self.ball, outfield_only=False))
        if self.poss != side:
            winner = self.nearest(side, self.ball)
            self.emit("recovery", side, winner, start_x_m=self.ball[0], start_y_m=self.ball[1])
            self.change_possession(side, winner, "recovery")
            self.t += 0.6
        for _ in range(6):
            x, y = to_team(side, *self.ball)
            if x >= 72:
                break
            ahead = []
            for p in self.active(side, True):
                if p is self.carrier:
                    continue
                px, py = to_team(side, *self.pos(p))
                if 6 < px - x < 32:
                    ahead.append((abs(py - CY) + abs(px - x - 18), p.id, p))
            if not ahead:
                self.do_carry(self.carrier, (x + self.rng.uniform(9, 14), y + self.rng.gauss(0, 3)))
                continue
            ahead.sort()
            receiver = self.rng.choice(ahead[:3])[2]
            rx, ry = self.pos(receiver)
            self.do_pass(self.carrier, receiver, (rx, ry), self.pressure_level(side), force="complete")
            self.t += self.control_time(side, 0.5, 1.2)

        shooter = self.players.get(shooter_id) if shooter_id else None
        if shooter is None or not shooter.active or shooter.side != side:
            prefs = ["ST", "LW", "RW", "AM", "CM"]
            shooter = sorted(self.active(side, True), key=lambda p: (prefs.index(p.position) if p.position in prefs else 9, p.id))[0]
        long_shot = speed is not None and speed >= 95
        spot = (self.rng.uniform(82.5, 87.5), CY + self.rng.uniform(-9, 9)) if long_shot \
            else (self.rng.uniform(92, 99), CY + self.rng.uniform(-7, 7))
        if self.carrier is shooter:
            self.do_carry(shooter, spot)
        else:
            self.do_pass(self.carrier, shooter, to_abs(side, *spot), 0.5, force="complete")
            self.t += self.rng.uniform(0.3, 0.8)
        self.do_shot(shooter, outcome, speed or self.rng.uniform(72, 94))

    def maybe_substitute(self) -> None:
        for sub in self.subs:
            if sub["done"] or self.t < sub["t"]:
                continue
            sub["done"] = True
            side = sub["side"]
            incoming = self.players[sub["in"]]
            protected = {f.player_id for f in self.forced if f.player_id}  # scripted players stay on
            eligible = [p for p in self.active(side, True)
                        if p is not self.carrier and p.id not in protected and p.id not in self.subbed_in]
            same = [p for p in eligible if p.position == incoming.position]
            pool = same or eligible
            out = sorted(pool, key=lambda p: p.id)[-1]
            incoming.anchor = out.anchor
            out.active, incoming.active = False, True
            self.subbed_in.add(incoming.id)
            self.tl.roster.append((round(self.t, 3), out.id, False))
            self.tl.roster.append((round(self.t, 3), incoming.id, True))
            self.emit("substitution", side, out, receiver_id=incoming.id,
                      qualifiers={"player_out_id": out.id, "player_in_id": incoming.id})
            self.t += 20.0

    # ------------------------------------------------------------------ run

    def play_period(self, period: int) -> None:
        self.period = period
        start = 0 if period == 1 else HALF_DURATION_S
        end = start + HALF_DURATION_S
        self.t = float(start)
        self.emit("period_start", qualifiers={"period": period})
        self.kickoff("home" if period == 1 else "away")
        while self.t < end - 6:
            due = next((i for i, f in enumerate(self.forced)
                        if not self.forced_done[i] and f.minute * 60 <= self.t and start <= f.minute * 60 < end), None)
            if due is not None:
                self.forced_done[due] = True
                self.run_forced(self.forced[due])
                continue
            self.maybe_substitute()
            self.step()
        self.t = float(end)
        self.set_carrier(None)
        self.emit("period_end", t=float(end), qualifiers={"period": period})

    def run(self) -> tuple[MatchMetadata, list[SyntheticEvent], Timelines]:
        self.tl.possession.append((0.0, "home"))
        self.set_ball(0.0, (CX, CY))
        self.play_period(1)
        self.play_period(2)
        missed = [f for f, done in zip(self.forced, self.forced_done) if not done]
        if missed:
            raise RuntimeError(f"forced events not executed: {missed}")
        meta = MatchMetadata(
            match_id=self.match_id,
            scenario_id=self.spec.scenario_id,
            seed=self.spec.seed,
            competition="EveryFan Synthetic League",
            venue="Synthetic Stadium",
            home=build_team_info(self.team_of["home"], "home"),
            away=build_team_info(self.team_of["away"], "away"),
        )
        events = [SyntheticEvent(**e) for e in self.events]
        return meta, events, self.tl
