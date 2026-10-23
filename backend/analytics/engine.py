"""Deterministic match statistics (plan section 6.1): feed events in seq order, ask for numbers at time t.

    a = MatchAnalytics(metadata)
    for e in events: a.add(e)
    a.snapshot()                       # score, possession, PPDA, control, chaos, rhythm, momentum
    a.ppda("nile_fc", window_s=300)    # rolling or (window_s=None) whole match

`add` is cheap (no window maths); rolling metrics are computed on demand from the event list,
so the same events always give the same numbers. Tracking-based player stats live in PlayerTracker.
"""

from __future__ import annotations

import bisect
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from shared.schemas import MatchMetadata, SyntheticEvent, TrackingFrame

from .config import load_config

RESTARTS = {"kickoff", "throw_in", "free_kick", "corner", "goal_kick"}
TURNOVER_TYPES = {"possession_change"}


def path_length_m(path) -> float:
    return sum(math.dist(a[1:], b[1:]) for a, b in zip(path, path[1:]))


def ball_speed_kmh(e: SyntheticEvent) -> float | None:
    """Ball / shot speed: ball_path length (m) / duration (s) x 3.6."""
    if not e.ball_path or not e.duration_s:
        return None
    return path_length_m(e.ball_path) / e.duration_s * 3.6


def r1(x: float | None) -> float | None:
    return None if x is None else round(float(x), 1)


def r2(x: float | None) -> float | None:
    return None if x is None else round(float(x), 2)


def minute_of(clock_s: float) -> int:
    return int(clock_s) // 60 + 1  # football convention: 12:06 is the 13th minute


@dataclass
class PlayerEventStats:
    passes: int = 0
    passes_completed: int = 0
    key_passes: int = 0
    killer_passes: int = 0
    shots: int = 0
    shots_on_target: int = 0
    goals: int = 0
    assists: int = 0
    tackles_won: int = 0
    interceptions: int = 0
    fouls: int = 0
    max_shot_speed_kmh: float = 0.0
    total_pass_distance_m: float = 0.0
    last_event_id: str | None = None

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "last_event_id"}
        d["pass_accuracy"] = r2(self.passes_completed / self.passes) if self.passes else None
        d["max_shot_speed_kmh"] = r1(self.max_shot_speed_kmh)
        d["total_pass_distance_m"] = r1(self.total_pass_distance_m)
        return d


class MatchAnalytics:
    """Running statistics for one run of one match."""

    def __init__(self, meta: MatchMetadata, cfg: dict | None = None) -> None:
        self.meta = meta
        self.cfg = cfg or load_config()
        p = self.cfg["pitch"]
        self.L, self.W = p["length_m"], p["width_m"]
        self.box_depth, self.box_half = p["box_depth_m"], p["box_half_width_m"]
        self.third = p["final_third_m"]
        self.window_s = self.cfg["rolling_window_s"]
        self.home, self.away = meta.home.team_id, meta.away.team_id
        self.side = {self.home: "home", self.away: "away"}
        self.opp = {self.home: self.away, self.away: self.home}
        self.player_team = {pl.player_id: t.team_id for t in (meta.home, meta.away) for pl in t.players}

        self.events: list[SyntheticEvent] = []
        self.times: list[float] = []
        self.by_id: dict[str, SyntheticEvent] = {}
        self.pass_info: dict[str, dict] = {}
        self.shot_info: dict[str, dict] = {}
        self.score = {self.home: 0, self.away: 0}
        self.now = 0.0
        # possession: closed segments (t0, t1, team) + the open one
        self.poss_team: str | None = None
        self.poss_since = 0.0
        self.segments: list[tuple[float, float, str]] = []
        self.possession_starts: list[tuple[float, str]] = []      # (t, team)
        self.possession_pass_counts: list[int] = []                # passes in each possession
        # momentum contributions: (t, team, weight, event_id, kind)
        self.momentum_items: list[tuple[float, str, float, str, str]] = []
        self.players: dict[str, PlayerEventStats] = defaultdict(PlayerEventStats)
        self.last_completed_pass: dict[str, SyntheticEvent] = {}   # per team
        self._ppda_cum = {self.home: [0, 0], self.away: [0, 0]}     # whole-match PPDA parts, kept incrementally
        self._ppda_actions = set(self.cfg["metrics"]["ppda"]["defensive_actions"])

    # ------------------------------------------------------------ geometry

    def attacks_right(self, team_id: str) -> bool:
        return self.side[team_id] == "home"  # home attacks towards x = 105 in both halves

    def forward_m(self, team_id: str, x0: float, x1: float) -> float:
        return (x1 - x0) if self.attacks_right(team_id) else (x0 - x1)

    def in_final_third(self, team_id: str, x: float) -> bool:
        return x >= self.L - self.third if self.attacks_right(team_id) else x <= self.third

    def in_opp_box(self, team_id: str, x: float, y: float) -> bool:
        in_y = abs(y - self.W / 2) <= self.box_half
        return in_y and (x >= self.L - self.box_depth if self.attacks_right(team_id) else x <= self.box_depth)

    def in_own_zone(self, team_id: str, x: float) -> bool:
        """Inside `team_id`'s own 60% of the pitch (the PPDA zone when the *other* team presses)."""
        share = self.cfg["metrics"]["ppda"]["zone_share"]
        return x <= self.L * share if self.attacks_right(team_id) else x >= self.L * (1 - share)

    def goal_distance_m(self, team_id: str, x: float, y: float) -> float:
        gx = self.L if self.attacks_right(team_id) else 0.0
        return math.dist((x, y), (gx, self.W / 2))

    # ---------------------------------------------------------- per event

    def pass_difficulty(self, e: SyntheticEvent) -> float:
        c = self.cfg["metrics"]["pass_difficulty"]
        dist = math.dist((e.start_x_m, e.start_y_m), (e.end_x_m, e.end_y_m))
        fwd = max(0.0, self.forward_m(e.team_id, e.start_x_m, e.end_x_m))
        value = (c["w_distance"] * min(dist / c["distance_norm_m"], 1.0)
                 + c["w_pressure"] * (e.pressure_level or 0.0)
                 + c["w_forward"] * min(fwd / c["forward_norm_m"], 1.0)
                 + c["w_final_third"] * float(self.in_final_third(e.team_id, e.end_x_m)))
        return min(max(value, 0.0), 1.0)

    def add(self, e: SyntheticEvent) -> None:
        t = e.game_time_s
        self.events.append(e)
        self.times.append(t)
        self.by_id[e.event_id] = e
        self.now = t
        if e.player_id:
            self.players[e.player_id].last_event_id = e.event_id

        if e.type in ("possession_change", "kickoff") and e.team_id:
            if self.poss_team is not None and t > self.poss_since:
                self.segments.append((self.poss_since, t, self.poss_team))
            self.poss_team, self.poss_since = e.team_id, t
            self.possession_starts.append((t, e.team_id))
            self.possession_pass_counts.append(0)

        if e.team_id in self.side and e.start_x_m is not None:
            if e.type == "pass" and self.in_own_zone(e.team_id, e.start_x_m):
                self._ppda_cum[self.opp[e.team_id]][0] += 1
            elif e.type in self._ppda_actions and self.in_own_zone(self.opp[e.team_id], e.start_x_m):
                self._ppda_cum[e.team_id][1] += 1

        weights = self.cfg["metrics"]["momentum"]["weights"]
        ps = self.players[e.player_id] if e.player_id else None

        if e.type == "pass" and e.team_id and e.end_x_m is not None:
            dist = math.dist((e.start_x_m, e.start_y_m), (e.end_x_m, e.end_y_m))
            info = {"distance_m": dist, "difficulty": self.pass_difficulty(e), "speed_kmh": ball_speed_kmh(e),
                    "completed": e.outcome == "completed"}
            self.pass_info[e.event_id] = info
            if self.possession_pass_counts and self.poss_team == e.team_id:
                self.possession_pass_counts[-1] += 1
            ps.passes += 1
            ps.total_pass_distance_m += dist
            if info["completed"]:
                ps.passes_completed += 1
                self.last_completed_pass[e.team_id] = e
                if info["difficulty"] > self.cfg["badges"]["killer_pass_difficulty"]:
                    ps.killer_passes += 1
                if self.in_opp_box(e.team_id, e.end_x_m, e.end_y_m) and not self.in_opp_box(e.team_id, e.start_x_m, e.start_y_m):
                    self.momentum_items.append((t, e.team_id, weights["box_entry"], e.event_id, "box_entry"))
                elif self.in_final_third(e.team_id, e.end_x_m):
                    self.momentum_items.append((t, e.team_id, weights["final_third_pass"], e.event_id, "final_third_pass"))
        elif e.type == "carry" and e.team_id and e.end_x_m is not None:
            if self.in_opp_box(e.team_id, e.end_x_m, e.end_y_m) and not self.in_opp_box(e.team_id, e.start_x_m, e.start_y_m):
                self.momentum_items.append((t, e.team_id, weights["box_entry"], e.event_id, "box_entry"))
        elif e.type == "shot" and e.team_id:
            speed = ball_speed_kmh(e)
            self.shot_info[e.event_id] = {
                "speed_kmh": speed,
                "distance_m": self.goal_distance_m(e.team_id, e.start_x_m, e.start_y_m),
                "in_box": self.in_opp_box(e.team_id, e.start_x_m, e.start_y_m),
                "on_target": e.outcome in ("goal", "saved"),
            }
            self.momentum_items.append((t, e.team_id, weights["shot"], e.event_id, "shot"))
            ps.shots += 1
            ps.shots_on_target += e.outcome in ("goal", "saved")
            ps.max_shot_speed_kmh = max(ps.max_shot_speed_kmh, speed or 0.0)
            kp = self.last_completed_pass.get(e.team_id)
            if kp is not None and t - kp.game_time_s <= self.cfg["moments"]["killer_pass"]["shot_within_s"]:
                self.players[kp.player_id].key_passes += 1
        elif e.type == "corner" and e.team_id:
            self.momentum_items.append((t, e.team_id, weights["corner"], e.event_id, "corner"))
        elif e.type == "goal" and e.team_id:
            self.score[e.team_id] += 1
            ps.goals += 1
            assist = e.qualifiers.get("assist_player_id")
            if assist:
                self.players[str(assist)].assists += 1
        elif e.type == "tackle" and e.outcome == "won":
            ps.tackles_won += 1
        elif e.type == "interception":
            ps.interceptions += 1
        elif e.type == "foul":
            ps.fouls += 1

    # ------------------------------------------------------------ windows

    def _bounds(self, window_s: float | None, at: float | None) -> tuple[float, float]:
        t = self.now if at is None else at
        return (-1.0 if window_s is None else t - window_s), t

    def window_events(self, window_s: float | None = None, at: float | None = None) -> list[SyntheticEvent]:
        """Events with a < game_time_s <= t."""
        a, t = self._bounds(window_s, at)
        lo = bisect.bisect_right(self.times, a)
        hi = bisect.bisect_right(self.times, t)
        return self.events[lo:hi]

    def _minutes(self, window_s: float | None, at: float | None) -> float:
        a, t = self._bounds(window_s, at)
        return max((t - max(a, 0.0)) / 60.0, 1e-9)

    # ------------------------------------------------------------ metrics

    def pass_accuracy(self, team_id: str, window_s: float | None = None, at: float | None = None) -> float | None:
        ps = [e for e in self.window_events(window_s, at) if e.type == "pass" and e.team_id == team_id]
        return sum(e.outcome == "completed" for e in ps) / len(ps) if ps else None

    def possession_seconds(self, window_s: float | None = None, at: float | None = None) -> dict[str, float]:
        a, t = self._bounds(window_s, at)
        out = {self.home: 0.0, self.away: 0.0}
        segs = list(self.segments)
        if self.poss_team is not None and t > self.poss_since:
            segs.append((self.poss_since, t, self.poss_team))
        for s0, s1, team in segs:
            lo, hi = max(s0, a), min(s1, t)
            if hi > lo:
                out[team] += hi - lo
        return out

    def possession_share(self, team_id: str, window_s: float | None = None, at: float | None = None) -> float | None:
        secs = self.possession_seconds(window_s, at)
        total = sum(secs.values())
        return secs[team_id] / total if total else None

    def passes_per_possession(self, team_id: str, window_s: float | None = None, at: float | None = None) -> float | None:
        passes = sum(1 for e in self.window_events(window_s, at) if e.type == "pass" and e.team_id == team_id)
        a, t = self._bounds(window_s, at)
        started = sum(1 for (ts, tm) in self.possession_starts if a < ts <= t and tm == team_id)
        if passes == 0 and started == 0:
            return None
        return passes / max(started, 1)

    def control_index(self, team_id: str, window_s: float | None = 300, at: float | None = None) -> float | None:
        c = self.cfg["metrics"]["control_index"]
        acc = self.pass_accuracy(team_id, window_s, at)
        ppp = self.passes_per_possession(team_id, window_s, at)
        share = self.possession_share(team_id, window_s, at)
        if acc is None or ppp is None or share is None:
            return None
        return 100 * (c["w_pass_accuracy"] * acc
                      + c["w_passes_per_possession"] * min(ppp / c["passes_per_possession_norm"], 1.0)
                      + c["w_possession"] * share)

    def turnovers(self, window_s: float | None = 300, at: float | None = None) -> list[SyntheticEvent]:
        return [e for e in self.window_events(window_s, at) if e.type in TURNOVER_TYPES]

    def short_possession_share(self, window_s: float | None = 300, at: float | None = None) -> float | None:
        """Share of possessions that ended in the window with <= N passes."""
        a, t = self._bounds(window_s, at)
        limit = self.cfg["metrics"]["chaos_index"]["short_possession_max_passes"]
        starts = self.possession_starts
        counts = []
        for i, (ts, _team) in enumerate(starts):
            end = starts[i + 1][0] if i + 1 < len(starts) else None
            if end is not None and a < end <= t:
                counts.append(self.possession_pass_counts[i])
        return sum(c <= limit for c in counts) / len(counts) if counts else None

    def chaos_index(self, window_s: float | None = 300, at: float | None = None) -> float | None:
        c = self.cfg["metrics"]["chaos_index"]
        mins = self._minutes(window_s, at)
        evs = self.window_events(window_s, at)
        if not evs:
            return None
        to_rate = sum(1 for e in evs if e.type in TURNOVER_TYPES) / mins
        df_rate = sum(1 for e in evs if e.type in ("duel", "foul")) / mins
        short = self.short_possession_share(window_s, at) or 0.0
        return 100 * (c["w_turnovers"] * min(to_rate / c["turnovers_per_min_norm"], 1.0)
                      + c["w_short_possessions"] * short
                      + c["w_duels_fouls"] * min(df_rate / c["duels_fouls_per_min_norm"], 1.0))

    def rhythm(self, window_s: float | None = 300, at: float | None = None) -> dict:
        c = self.cfg["metrics"]["rhythm"]
        passes = [e for e in self.window_events(window_s, at) if e.type == "pass"]
        ppm = len(passes) / self._minutes(window_s, at)
        gaps = [b.game_time_s - a.game_time_s for a, b in zip(passes, passes[1:])]
        median_gap = statistics.median(gaps) if gaps else None
        label = ("slow_build_up" if ppm < c["slow_below_passes_per_min"]
                 else "frantic" if ppm > c["frantic_above_passes_per_min"] else "balanced")
        return {"passes_per_min": ppm, "median_pass_gap_s": median_gap, "label": label}

    def ppda_parts(self, team_id: str, window_s: float | None = 300, at: float | None = None) -> tuple[int, int]:
        """(opponent passes in their own 60%, our defensive actions in that zone)."""
        if window_s is None and (at is None or at >= self.now):
            return tuple(self._ppda_cum[team_id])
        opp = self.opp[team_id]
        actions = self._ppda_actions
        passes = acts = 0
        for e in self.window_events(window_s, at):
            if e.start_x_m is None or not self.in_own_zone(opp, e.start_x_m):
                continue
            if e.type == "pass" and e.team_id == opp:
                passes += 1
            elif e.type in actions and e.team_id == team_id:
                acts += 1
        return passes, acts

    def ppda(self, team_id: str, window_s: float | None = 300, at: float | None = None) -> float | None:
        passes, acts = self.ppda_parts(team_id, window_s, at)
        return passes / acts if acts else None

    def momentum(self, team_id: str, at: float | None = None) -> float:
        t = self.now if at is None else at
        decay = self.cfg["metrics"]["momentum"]["decay_s"]
        total = 0.0
        for ti, team, w, _eid, _kind in reversed(self.momentum_items):
            if ti > t:
                continue
            if t - ti > decay * 8:  # e^-8: negligible, stop scanning
                break
            if team == team_id:
                total += w * math.exp(-(t - ti) / decay)
        return total

    def momentum_evidence(self, team_id: str, at: float | None = None, n: int = 5) -> list[str]:
        t = self.now if at is None else at
        ids = [eid for ti, team, _w, eid, _k in self.momentum_items if team == team_id and t - 300 < ti <= t]
        return ids[-n:]

    # ------------------------------------------------------------ snapshots

    def team_snapshot(self, team_id: str, at: float | None = None) -> dict:
        w = self.window_s
        p5, a5 = self.ppda_parts(team_id, w, at)
        pm, am = self.ppda_parts(team_id, None, at)
        return {
            "team_id": team_id,
            "goals": self.score[team_id] if at is None else sum(
                1 for e in self.window_events(None, at) if e.type == "goal" and e.team_id == team_id),
            "possession_pct_last_5": r1(_pct(self.possession_share(team_id, w, at))),
            "possession_pct_match": r1(_pct(self.possession_share(team_id, None, at))),
            "pass_accuracy_pct_last_5": r1(_pct(self.pass_accuracy(team_id, w, at))),
            "pass_accuracy_pct_match": r1(_pct(self.pass_accuracy(team_id, None, at))),
            "passes_last_5": sum(1 for e in self.window_events(w, at) if e.type == "pass" and e.team_id == team_id),
            "shots_last_5": sum(1 for e in self.window_events(w, at) if e.type == "shot" and e.team_id == team_id),
            "shots_match": sum(1 for e in self.window_events(None, at) if e.type == "shot" and e.team_id == team_id),
            "ppda_last_5": r1(p5 / a5) if a5 else None,
            "ppda_match": r1(pm / am) if am else None,
            "control_index_last_5": r1(self.control_index(team_id, w, at)),
            "momentum": r1(self.momentum(team_id, at)),
        }

    def snapshot(self, at: float | None = None) -> dict:
        t = self.now if at is None else at
        rh = self.rhythm(self.window_s, at)
        teams = {tid: self.team_snapshot(tid, at) for tid in (self.home, self.away)}
        return {
            "game_clock_s": int(t),
            "minute": minute_of(t),
            "score": {tid: s["goals"] for tid, s in teams.items()},
            "teams": teams,
            "chaos_index_last_5": r1(self.chaos_index(self.window_s, at)),
            "turnovers_per_min_last_5": r1(len(self.turnovers(self.window_s, at)) / self._minutes(self.window_s, at)),
            "rhythm_last_5": {"label": rh["label"], "passes_per_min": r1(rh["passes_per_min"]),
                              "median_pass_gap_s": r1(rh["median_pass_gap_s"])},
        }


def _pct(x: float | None) -> float | None:
    return None if x is None else 100 * x


# ---------------------------------------------------------------- tracking


@dataclass
class _Track:
    x: float
    y: float
    period: int
    frame: int
    speeds: list[float] = field(default_factory=list)
    distance_m: float = 0.0
    top_speed_kmh: float = 0.0


class PlayerTracker:
    """Player speed (smoothed over 3 frames) and distance covered from 2 Hz tracking.

    update(frame) returns badge crossings: [("sprint", player_id, speed), ("distance", player_id, km)].
    Sprint fires once per player (first time above the threshold); distance every 2 km.
    """

    def __init__(self, cfg: dict | None = None) -> None:
        self.cfg = cfg or load_config()
        ps = self.cfg["metrics"]["player_speed"]
        self.dt, self.n = ps["frame_dt_s"], ps["smoothing_frames"]
        b = self.cfg["badges"]
        self.sprint_kmh, self.step_m = b["sprint_kmh"], b["distance_step_km"] * 1000
        self.tracks: dict[str, _Track] = {}
        self.sprinted: set[str] = set()
        self.last_frame: int | None = None

    def update(self, f: TrackingFrame) -> list[tuple[str, str, float]]:
        out = []
        self.last_frame = f.frame
        for p in f.players:
            tr = self.tracks.get(p.player_id)
            if tr is None:
                self.tracks[p.player_id] = _Track(p.x_m, p.y_m, f.period, f.frame)
                continue
            if tr.period == f.period and f.frame - tr.frame == 1:
                d = math.dist((tr.x, tr.y), (p.x_m, p.y_m))
                before = tr.distance_m
                tr.distance_m += d
                tr.speeds.append(d / self.dt * 3.6)
                if len(tr.speeds) > self.n:
                    tr.speeds.pop(0)
                if len(tr.speeds) == self.n:
                    smooth = sum(tr.speeds) / self.n
                    tr.top_speed_kmh = max(tr.top_speed_kmh, smooth)
                    if smooth > self.sprint_kmh and p.player_id not in self.sprinted:
                        self.sprinted.add(p.player_id)
                        out.append(("sprint", p.player_id, smooth))
                if int(tr.distance_m // self.step_m) > int(before // self.step_m):
                    out.append(("distance", p.player_id, int(tr.distance_m // self.step_m) * self.step_m / 1000))
            else:
                tr.speeds.clear()  # new half or a gap (substitution): restart smoothing
            tr.x, tr.y, tr.period, tr.frame = p.x_m, p.y_m, f.period, f.frame
        return out

    def player(self, player_id: str) -> dict | None:
        tr = self.tracks.get(player_id)
        if tr is None:
            return None
        return {"distance_km": round(tr.distance_m / 1000, 2), "top_speed_kmh": r1(tr.top_speed_kmh)}
