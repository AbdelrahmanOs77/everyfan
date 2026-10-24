"""Moment detector (plan section 6.3): events + tracking in, Contract B moments out.

    det = MomentDetector(metadata)
    for e in events:  moments = det.update(e)            # 0..n moments per event
    for f in frames:  moments = det.update_tracking(f)   # speed / distance badges

IDs are stable for a given match, whatever the replay speed or seek point:
  * event moments are mom_001, mom_002, ... in event order;
  * tracking badges (sprint, distance) are mom_5001+ in frame order;
  * Owner A's template moments use mom_9001+.
So a moment_id always means the same moment, and cached overlays keyed on it keep matching.
"""

from __future__ import annotations

import math

from shared.schemas import MatchMetadata, Moment, SyntheticEvent, TrackingFrame

from .config import load_config
from .engine import MatchAnalytics, PlayerTracker, minute_of, r1, r2

TRACKING_ID_BASE = 5000

RULE_IDS = {
    "goal": "GOAL_V1",
    "red_card": "RED_CARD_V1",
    "big_chance": "BIG_CHANCE_V1",
    "killer_pass": "KILLER_PASS_V1",
    "momentum_shift": "MOMENTUM_SHIFT_V1",
    "pressing_shift": "PRESS_SHIFT_V1",
    "control_to_chaos": "CONTROL_TO_CHAOS_V1",
    "rhythm_change": "RHYTHM_CHANGE_V1",
    "player_milestone": "PLAYER_MILESTONE_V1",
}


def rule_descriptions(cfg: dict | None = None) -> dict[str, str]:
    """Human-readable rule text, generated from the live config (served by the evidence API)."""
    c = (cfg or load_config())["moments"]
    b = (cfg or load_config())["badges"]
    return {
        "GOAL_V1": "A goal event. Facts: scorer, minute, score after the goal, shot speed and distance, passes in the move.",
        "RED_CARD_V1": "A red or second-yellow card.",
        "BIG_CHANCE_V1": (f"Unblocked, non-goal shot from inside the box within {c['big_chance']['max_distance_m']} m "
                          f"under pressure <= {c['big_chance']['max_pressure_in_box']}, or a shot on target above "
                          f"{c['big_chance']['on_target_speed_kmh']} km/h."),
        "KILLER_PASS_V1": (f"Completed pass with difficulty > {b['killer_pass_difficulty']} followed by a shot from the "
                           f"same team within {c['killer_pass']['shot_within_s']} s."),
        "MOMENTUM_SHIFT_V1": (f"The team leading on momentum (decayed sum of shots 3, box entries 2, final-third passes 1, "
                              f"corners 1) changes, with a gap above {c['momentum_shift']['min_gap']}."),
        "PRESS_SHIFT_V1": (f"Team PPDA over the last 5 minutes below {c['pressing_shift']['ratio']} x its match PPDA "
                           f"for {c['pressing_shift']['hold_s']} s (after {c['pressing_shift']['min_clock_s'] // 60}', "
                           f"at least {c['pressing_shift']['min_defensive_actions']} defensive actions in the window)."),
        "CONTROL_TO_CHAOS_V1": (f"Chaos index (last 5 minutes) crosses {c['control_to_chaos']['threshold']} from below "
                                f"(re-arms below {c['control_to_chaos']['rearm_below']})."),
        "RHYTHM_CHANGE_V1": f"Game-rhythm label changes and holds for {c['rhythm_change']['hold_s']} s.",
        "PLAYER_MILESTONE_V1": (f"Badge: sprint above {b['sprint_kmh']} km/h, shot above {b['rocket_kmh']} km/h, "
                                f"every {b['distance_step_km']} km covered, or a completed pass with difficulty above "
                                f"{b['killer_pass_difficulty']}."),
    }


def _facts(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


class MomentDetector:
    def __init__(self, meta: MatchMetadata, cfg: dict | None = None) -> None:
        self.meta = meta
        self.cfg = cfg or load_config()
        self.mc = self.cfg["moments"]
        self.a = MatchAnalytics(meta, self.cfg)
        self.tracker = PlayerTracker(self.cfg)
        self.moments: list[Moment] = []
        self._n = 0
        self._n_track = TRACKING_ID_BASE
        self._last_fired: dict[str, float] = {}
        # rolling-rule state
        self._press_armed = {self.a.home: True, self.a.away: True}
        self._press_since: dict[str, float | None] = {self.a.home: None, self.a.away: None}
        self._chaos_armed: bool | None = None
        self._leader: str | None = None
        self._rhythm: str | None = None
        self._rhythm_candidate: tuple[str, float] | None = None
        self._reds: dict[str, int] = {}

    # -------------------------------------------------------------- helpers

    def _new(self, e_clock: float, mtype: str, team_id: str | None, player_id: str | None, evidence: list[str],
             facts: dict, importance: float | None = None, tracking: bool = False) -> Moment:
        if tracking:
            self._n_track += 1
            mid = f"mom_{self._n_track}"
        else:
            self._n += 1
            mid = f"mom_{self._n:03d}"
        seen, ev = set(), []
        for x in evidence:
            if x and x not in seen:
                seen.add(x)
                ev.append(x)
        m = Moment(moment_id=mid, match_id=self.meta.match_id, game_clock_s=int(e_clock), type=mtype,
                   importance=self.mc[mtype]["importance"] if importance is None else importance,
                   team_id=team_id, player_id=player_id, evidence_event_ids=ev,
                   verified_facts=_facts(facts), rule_id=RULE_IDS[mtype])
        self.moments.append(m)
        return m

    def _cooldown_ok(self, mtype: str, t: float) -> bool:
        last = self._last_fired.get(mtype)
        return last is None or t - last >= self.mc["cooldown_s"]

    def _fired(self, mtype: str, t: float) -> None:
        self._last_fired[mtype] = t

    # --------------------------------------------------------------- events

    def update(self, e: SyntheticEvent) -> list[Moment]:
        a = self.a
        a.add(e)
        out: list[Moment] = []
        t = e.game_time_s

        if e.type == "goal":
            out.append(self._goal(e))
        elif e.type == "card" and e.outcome in ("red", "second_yellow"):
            self._reds[e.team_id] = self._reds.get(e.team_id, 0) + 1
            out.append(self._new(t, "red_card", e.team_id, e.player_id, [e.event_id], {
                "player_id": e.player_id, "minute": minute_of(e.game_clock_s), "card": e.outcome,
                "players_left": 11 - self._reds[e.team_id]}))
        elif e.type == "shot":
            out.extend(self._shot(e))
        elif e.type == "pass" and e.outcome == "completed":
            info = a.pass_info.get(e.event_id)
            if info and info["difficulty"] > self.cfg["badges"]["killer_pass_difficulty"]:
                out.append(self._new(t, "player_milestone", e.team_id, e.player_id, [e.event_id], {
                    "badge": "killer_pass", "player_id": e.player_id, "minute": minute_of(e.game_clock_s),
                    "pass_difficulty": r2(info["difficulty"]), "pass_distance_m": r1(info["distance_m"])}))

        if e.game_clock_s >= self.mc["min_clock_s"]:
            for team in (a.home, a.away):
                m = self._pressing(team, e)
                if m:
                    out.append(m)
            for rule in (self._momentum, self._chaos, self._rhythm_rule):
                m = rule(e)
                if m:
                    out.append(m)
        return out

    def _goal(self, e: SyntheticEvent) -> Moment:
        a = self.a
        shot = a.by_id.get(e.related_event_id) if e.related_event_id else None
        passes, move = 0, []
        for x in reversed(a.events[:-2] if shot else a.events[:-1]):
            if x.type in ("pass", "carry") and x.team_id == e.team_id:
                passes += x.type == "pass"
                move.append(x.event_id)
            elif x.type != "pressure":
                break
        facts = {"scorer_id": e.player_id, "minute": minute_of(e.game_clock_s),
                 "home_score": int(e.qualifiers["home_score"]), "away_score": int(e.qualifiers["away_score"]),
                 "passes_in_move": passes, "assist_id": e.qualifiers.get("assist_player_id")}
        if shot:
            si = a.shot_info[shot.event_id]
            facts["shot_speed_kmh"] = round(si["speed_kmh"] or 0)
            facts["shot_distance_m"] = round(si["distance_m"])
        evidence = list(reversed(move[:3])) + ([shot.event_id] if shot else []) + [e.event_id]
        return self._new(e.game_time_s, "goal", e.team_id, e.player_id, evidence, facts)

    def _shot(self, e: SyntheticEvent) -> list[Moment]:
        a, c, out = self.a, self.mc, []
        t = e.game_time_s
        si = a.shot_info[e.event_id]
        speed = si["speed_kmh"] or 0.0
        bc = c["big_chance"]
        assist = a.last_completed_pass.get(e.team_id)
        assist = assist if assist is not None and t - assist.game_time_s <= c["killer_pass"]["shot_within_s"] else None

        if e.outcome != "goal" and self._cooldown_ok("big_chance", t):
            close = (si["in_box"] and e.outcome != "blocked" and (e.pressure_level or 0) <= bc["max_pressure_in_box"]
                     and si["distance_m"] <= bc["max_distance_m"])
            rocket = si["on_target"] and speed > bc["on_target_speed_kmh"]
            if close or rocket:
                self._fired("big_chance", t)
                out.append(self._new(t, "big_chance", e.team_id, e.player_id,
                                     ([assist.event_id] if assist else []) + [e.event_id], {
                                         "shooter_id": e.player_id, "minute": minute_of(e.game_clock_s),
                                         "shot_speed_kmh": round(speed), "shot_distance_m": round(si["distance_m"]),
                                         "pressure": r2(e.pressure_level), "outcome": e.outcome,
                                         "in_box": si["in_box"]}))

        if assist is not None:
            info = a.pass_info[assist.event_id]
            if info["difficulty"] > self.cfg["badges"]["killer_pass_difficulty"] and self._cooldown_ok("killer_pass", t):
                self._fired("killer_pass", t)
                out.append(self._new(t, "killer_pass", e.team_id, assist.player_id, [assist.event_id, e.event_id], {
                    "passer_id": assist.player_id, "shooter_id": e.player_id, "minute": minute_of(e.game_clock_s),
                    "pass_difficulty": r2(info["difficulty"]), "pass_distance_m": r1(info["distance_m"]),
                    "seconds_to_shot": r1(t - assist.game_time_s), "shot_outcome": e.outcome}))

        if speed > self.cfg["badges"]["rocket_kmh"]:
            out.append(self._new(t, "player_milestone", e.team_id, e.player_id, [e.event_id], {
                "badge": "rocket", "player_id": e.player_id, "minute": minute_of(e.game_clock_s),
                "shot_speed_kmh": round(speed)}))
        return out

    # ------------------------------------------------------- rolling rules

    def _pressing(self, team: str, e: SyntheticEvent) -> Moment | None:
        a, c = self.a, self.mc["pressing_shift"]
        t = e.game_time_s
        if e.game_clock_s < c["min_clock_s"]:
            return None
        p5, a5 = a.ppda_parts(team, a.window_s)
        pm, am = a.ppda_parts(team, None)
        if not a5 or not am:
            self._press_since[team] = None
            return None
        ratio = (p5 / a5) / (pm / am) if pm else 0.0
        if not self._press_armed[team]:
            if ratio > c["rearm_ratio"]:
                self._press_armed[team] = True
            return None
        if ratio < c["ratio"] and a5 >= c["min_defensive_actions"]:
            since = self._press_since[team]
            if since is None:
                self._press_since[team] = t
            elif t - since >= c["hold_s"] and self._cooldown_ok("pressing_shift", t):
                self._press_armed[team], self._press_since[team] = False, None
                self._fired("pressing_shift", t)
                opp = a.opp[team]
                actions = set(self.cfg["metrics"]["ppda"]["defensive_actions"])
                ev = [x.event_id for x in a.window_events(a.window_s)
                      if x.type in actions and x.team_id == team and x.start_x_m is not None
                      and a.in_own_zone(opp, x.start_x_m)][-5:]
                return self._new(t, "pressing_shift", team, None, ev, {
                    "ppda_last_5": r1(p5 / a5), "ppda_match": r1(pm / am),
                    "regains_in_zone_last_5": a5, "opponent_passes_in_zone_last_5": p5,
                    "possession_pct_last_5": r1(100 * (a.possession_share(team, a.window_s) or 0)),
                    "minute": minute_of(e.game_clock_s)})
        else:
            self._press_since[team] = None
        return None

    def _momentum(self, e: SyntheticEvent) -> Moment | None:
        a, c = self.a, self.mc["momentum_shift"]
        t = e.game_time_s
        mh, ma = a.momentum(a.home), a.momentum(a.away)
        leader = a.home if mh - ma > c["min_gap"] else a.away if ma - mh > c["min_gap"] else None
        if leader is None or leader == self._leader:
            return None
        previous, self._leader = self._leader, leader
        if previous is None or not self._cooldown_ok("momentum_shift", t):
            return None
        self._fired("momentum_shift", t)
        opp = a.opp[leader]
        mine, theirs = (mh, ma) if leader == a.home else (ma, mh)
        snap = a.team_snapshot(leader)
        return self._new(t, "momentum_shift", leader, None, a.momentum_evidence(leader) or [e.event_id], {
            "momentum": r1(mine), "momentum_opponent": r1(theirs), "momentum_gap": r1(mine - theirs),
            "shots_last_5": snap["shots_last_5"],
            "shots_last_5_opponent": sum(1 for x in a.window_events(a.window_s) if x.type == "shot" and x.team_id == opp),
            "possession_pct_last_5": snap["possession_pct_last_5"], "minute": minute_of(e.game_clock_s)})

    def _chaos(self, e: SyntheticEvent) -> Moment | None:
        a, c = self.a, self.mc["control_to_chaos"]
        t = e.game_time_s
        chaos = a.chaos_index(a.window_s)
        if chaos is None:
            return None
        if self._chaos_armed is None:
            self._chaos_armed = chaos < c["threshold"]
            return None
        if not self._chaos_armed:
            if chaos < c["rearm_below"]:
                self._chaos_armed = True
            return None
        if chaos < c["threshold"] or not self._cooldown_ok("control_to_chaos", t):
            return None
        self._chaos_armed = False
        self._fired("control_to_chaos", t)
        mins = a._minutes(a.window_s, None)
        evs = a.window_events(a.window_s)
        turnovers = [x.event_id for x in evs if x.type == "possession_change"]
        return self._new(t, "control_to_chaos", None, None, turnovers[-5:] or [e.event_id], {
            "chaos_index_last_5": r1(chaos),
            "turnovers_per_min_last_5": r1(len(turnovers) / mins),
            "short_possession_pct_last_5": r1(100 * (a.short_possession_share(a.window_s) or 0)),
            "duels_fouls_last_5": sum(1 for x in evs if x.type in ("duel", "foul")),
            "minute": minute_of(e.game_clock_s)})

    def _rhythm_rule(self, e: SyntheticEvent) -> Moment | None:
        a, c = self.a, self.mc["rhythm_change"]
        t = e.game_time_s
        rh = a.rhythm(a.window_s)
        label = rh["label"]
        if self._rhythm is None:
            self._rhythm = label
            return None
        if label == self._rhythm:
            self._rhythm_candidate = None
            return None
        if self._rhythm_candidate is None or self._rhythm_candidate[0] != label:
            self._rhythm_candidate = (label, t)
            return None
        if t - self._rhythm_candidate[1] < c["hold_s"] or not self._cooldown_ok("rhythm_change", t):
            return None
        previous, self._rhythm, self._rhythm_candidate = self._rhythm, label, None
        self._fired("rhythm_change", t)
        passes = [x.event_id for x in a.window_events(a.window_s) if x.type == "pass"]
        return self._new(t, "rhythm_change", None, None, passes[-3:] or [e.event_id], {
            "rhythm_from": previous, "rhythm_to": label, "passes_per_min_last_5": r1(rh["passes_per_min"]),
            "median_pass_gap_s": r1(rh["median_pass_gap_s"]), "minute": minute_of(e.game_clock_s)})

    # ------------------------------------------------------------- tracking

    def update_tracking(self, f: TrackingFrame) -> list[Moment]:
        out = []
        for badge, pid, value in self.tracker.update(f):
            ps = self.a.players.get(pid)
            evidence = [ps.last_event_id] if ps and ps.last_event_id else []
            if not evidence and self.a.events:
                evidence = [self.a.events[-1].event_id]
            if not evidence:
                continue  # no event yet to anchor the evidence (cannot happen after kickoff)
            facts = {"badge": badge, "player_id": pid, "minute": minute_of(f.game_clock_s), "frame": f.frame}
            if badge == "sprint":
                facts["top_speed_kmh"] = r1(value)
            else:
                facts["distance_km"] = int(value) if float(value).is_integer() else r1(value)
            team = self.a.player_team.get(pid)
            out.append(self._new(math.floor(f.game_clock_s), "player_milestone", team, pid, evidence, facts,
                                 tracking=True))
        return out
