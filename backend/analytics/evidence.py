"""Evidence: the deterministic facts behind every moment, at any point of a match.

Backs the evidence REST API (backend/analytics/api.py) and Owner C's read-only MCP tools:

    MCP tool               ->  MatchEvidence method          ->  REST
    get_match_state        ->  state_at(at_s)                ->  GET /api/matches/{id}/stats?at_s=
    get_recent_events      ->  recent_events(at_s, window_s) ->  GET /api/matches/{id}/recent-events?at_s=&window_s=&team_id=
    get_player_statistics  ->  player_stats(player_id, at_s) ->  GET /api/matches/{id}/players/{player_id}/stats?at_s=
    get_moment_evidence    ->  evidence(moment_id)           ->  GET /api/matches/{id}/evidence/{moment_id}
    compare_to_baseline    ->  baseline(metric, window_s)    ->  GET /api/matches/{id}/baseline?metric=&window_s=&at_s=

It replays the whole match through the same MomentDetector the live plugin uses, in the same
order as Owner A's replay, so moment IDs and numbers are identical to what viewers saw live.
`at_s` always means "as known at that second": nothing from later in the match leaks in.
"""

from __future__ import annotations

import bisect
from array import array

from shared.schemas import MatchMetadata, Moment, SyntheticEvent, TrackingFrame

from .config import load_config
from .engine import MatchAnalytics, PlayerTracker, minute_of, r1
from .moments import MomentDetector, rule_descriptions
from .tracking_index import PlayerPositions
from .advanced import TrackingMetricsIndex
from .tactics_index import TacticsIndex

METRICS = ("possession_pct", "pass_accuracy_pct", "ppda", "control_index", "shots", "passes",
           "chaos_index", "turnovers_per_min", "passes_per_min")


def replay_order(events: list[SyntheticEvent], frames: list[TrackingFrame]) -> list[tuple[str, object]]:
    """Same order as backend.simulator.replay.ReplayController: by time, events before frames."""
    items = [(e.game_time_s, 0, e.seq, "event", e) for e in events]
    items += [(f.game_clock_s, 1, 0, "tracking", f) for f in frames]
    items.sort(key=lambda i: (i[0], i[1], i[2]))
    return [(kind, obj) for *_rest, kind, obj in items]


class _Timeline:
    """Per-player cumulative distance and top speed, sampled every second."""

    __slots__ = ("secs", "dist_m", "top_kmh")

    def __init__(self) -> None:
        self.secs, self.dist_m, self.top_kmh = array("d"), array("f"), array("f")

    def at(self, t: float) -> tuple[float, float] | None:
        i = bisect.bisect_right(self.secs, t) - 1
        return None if i < 0 else (self.dist_m[i], self.top_kmh[i])


class MatchEvidence:
    def __init__(self, meta: MatchMetadata, events: list[SyntheticEvent], frames: list[TrackingFrame],
                 cfg: dict | None = None) -> None:
        self.meta, self.events, self.cfg = meta, events, cfg or load_config()
        self.match_id = meta.match_id
        self.times = [e.game_time_s for e in events]
        self.event_by_id = {e.event_id: e for e in events}
        self.players = {p.player_id: p for t in (meta.home, meta.away) for p in t.players}
        self.teams = {meta.home.team_id: meta.home, meta.away.team_id: meta.away}
        self.rules = rule_descriptions(self.cfg)

        det = MomentDetector(meta, self.cfg)
        self.timelines: dict[str, _Timeline] = {}
        self.positions: dict[str, PlayerPositions] = {}
        self.tracking = TrackingMetricsIndex(meta, self.cfg)
        self.tactics = TacticsIndex(meta, events)
        last_sec = -1
        for kind, obj in replay_order(events, frames):
            if kind == "event":
                det.update(obj)
            else:
                det.update_tracking(obj)
                self.tracking.append(obj, det.tracker)
                self.tactics.append(obj, det.tracker)
                for point in obj.players:
                    if point.player_id not in self.positions:
                        self.positions[point.player_id] = PlayerPositions()
                    self.positions[point.player_id].append(obj, point)
                sec = int(obj.game_clock_s)
                if sec != last_sec:
                    last_sec = sec
                    self._sample(det.tracker, obj.game_clock_s)
        self._detected: list[Moment] = list(det.moments)  # detection order = live publish order
        self.moments: list[Moment] = sorted(det.moments, key=lambda m: (m.game_clock_s, m.moment_id))
        self.moment_by_id = {m.moment_id: m for m in self.moments}
        self.final = det.a

    def _sample(self, tracker: PlayerTracker, sec: float) -> None:
        for pid, tr in tracker.tracks.items():
            tl = self.timelines.get(pid)
            if tl is None:
                tl = self.timelines[pid] = _Timeline()
            tl.secs.append(sec)
            tl.dist_m.append(tr.distance_m)
            tl.top_kmh.append(tr.top_speed_kmh)

    # ------------------------------------------------------------ helpers

    def _analytics_at(self, at_s: float | None) -> MatchAnalytics:
        if not self.times or at_s is None or at_s >= self.times[-1]:
            return self.final
        a = MatchAnalytics(self.meta, self.cfg)
        for e in self.events[:bisect.bisect_right(self.times, at_s)]:
            a.add(e)
        a.now = at_s
        return a

    def _clip(self, at_s: float | None) -> float:
        return (self.times[-1] if self.times else 0.0) if at_s is None else max(0.0, min(float(at_s), 5400.0))

    def _event_view(self, e: SyntheticEvent) -> dict:
        d = e.model_dump(mode="json", exclude_none=True)
        d.pop("ball_path", None)
        d.pop("schema_version", None)
        d["minute"] = minute_of(e.game_clock_s)
        return d

    # ------------------------------------------------------------- queries

    def tracking_samples(self, player_id: str, at_s: float = 5400, window_s: float = 5400,
                         offset: int = 0, limit: int = 200) -> dict | None:
        if player_id not in self.players:
            return None
        positions = self.positions.get(player_id)
        return {"match_id": self.match_id, "player_id": player_id, "at_s": at_s, "window_s": window_s,
                **(positions.samples(at_s, window_s, offset, limit) if positions else
                   {"total": 0, "offset": offset, "next_offset": None, "samples": []})}

    def moments_in_publish_order(self) -> list[Moment]:
        return list(self._detected)

    def list_moments(self, until_s: float | None = None, types: set[str] | None = None,
                     min_importance: float = 0.0) -> list[dict]:
        out = []
        for m in self.moments:
            if until_s is not None and m.game_clock_s > until_s:
                break
            if (types is None or m.type in types) and m.importance >= min_importance:
                out.append(m.model_dump(mode="json", exclude_none=True))
        return out

    def evidence(self, moment_id: str) -> dict | None:
        m = self.moment_by_id.get(moment_id)
        if m is None:
            return None
        events = [self._event_view(self.event_by_id[eid]) for eid in m.evidence_event_ids if eid in self.event_by_id]
        return {
            "moment": m.model_dump(mode="json", exclude_none=True),
            "minute": minute_of(m.game_clock_s),
            "rule": {"rule_id": m.rule_id, "description": self.rules.get(m.rule_id, ""),
                     "config_version": self.cfg.get("version")},
            "facts": m.verified_facts,
            "evidence_events": events,
            "all_evidence_resolved": len(events) == len(m.evidence_event_ids),
            "names": self._names_for(m),
        }

    def _names_for(self, m: Moment) -> dict:
        """English and Arabic names for every player and team the moment mentions (Verifier allowlist)."""
        ids = {m.team_id, m.player_id, *[v for v in m.verified_facts.values() if isinstance(v, str)]}
        out = {}
        for i in ids:
            if i in self.players:
                p = self.players[i]
                out[i] = {"name": p.name, "short_name": p.short_name, "name_ar": p.name_ar, "team_id": p.team_id}
            elif i in self.teams:
                t = self.teams[i]
                out[i] = {"name": t.name, "short_name": t.short_name, "name_ar": t.name_ar}
        return out

    def state_at(self, at_s: float | None = None) -> dict:
        t = self._clip(at_s)
        a = self._analytics_at(t)
        snap = a.snapshot(t)
        snap["match_id"] = self.match_id
        snap["period"] = 1 if t < 2700 else 2
        snap["moments_so_far"] = sum(1 for m in self.moments if m.game_clock_s <= t)
        snap["evidence_event_ids"] = [e.event_id for e in self.events if e.game_time_s <= t]
        return snap

    def recent_events(self, at_s: float | None = None, window_s: float = 60, team_id: str | None = None,
                      types: set[str] | None = None, limit: int = 200) -> list[dict]:
        t = self._clip(at_s)
        lo = bisect.bisect_right(self.times, t - window_s)
        hi = bisect.bisect_right(self.times, t)
        out = [self._event_view(e) for e in self.events[lo:hi]
               if (team_id is None or e.team_id == team_id) and (types is None or e.type in types)]
        return out[-limit:]

    def player_stats(self, player_id: str, at_s: float | None = None) -> dict | None:
        p = self.players.get(player_id)
        if p is None:
            return None
        t = self._clip(at_s)
        a = self._analytics_at(t)
        stats = a.players[player_id].to_dict() if player_id in a.players else {}
        tl = self.timelines.get(player_id)
        sample = tl.at(t) if tl else None
        badges = [m.verified_facts.get("badge") for m in self.moments
                  if m.type == "player_milestone" and m.player_id == player_id and m.game_clock_s <= t]
        return {
            "match_id": self.match_id, "player_id": player_id, "name": p.name, "name_ar": p.name_ar,
            "team_id": p.team_id, "shirt_number": p.shirt_number, "position": p.position, "at_s": int(t),
            "events": stats,
            "distance_km": round(sample[0] / 1000, 2) if sample else 0.0,
            "top_speed_kmh": r1(sample[1]) if sample else 0.0,
            "badges": badges,
        }

    def baseline(self, metric: str, window_s: float = 300, at_s: float | None = None,
                 team_id: str | None = None) -> dict:
        """Current value over the last `window_s` vs the match so far (both as known at `at_s`)."""
        if metric not in METRICS:
            raise ValueError(f"unknown metric {metric!r}; one of {', '.join(METRICS)}")
        t = self._clip(at_s)
        a = self._analytics_at(t)
        teams = [team_id] if team_id else [a.home, a.away]

        def value(tid: str | None, w: float | None):
            if metric == "possession_pct":
                v = a.possession_share(tid, w, t)
                return None if v is None else 100 * v
            if metric == "pass_accuracy_pct":
                v = a.pass_accuracy(tid, w, t)
                return None if v is None else 100 * v
            if metric == "ppda":
                return a.ppda(tid, w, t)
            if metric == "control_index":
                return a.control_index(tid, w, t)
            if metric in ("shots", "passes"):
                kind = metric[:-1]
                n = sum(1 for e in a.window_events(w, t) if e.type == kind and e.team_id == tid)
                return n / a._minutes(w, t)  # per minute, so windows of different length compare
            if metric == "chaos_index":
                return a.chaos_index(w, t)
            if metric == "turnovers_per_min":
                return len(a.turnovers(w, t)) / a._minutes(w, t)
            return a.rhythm(w, t)["passes_per_min"]

        match_level = metric in ("chaos_index", "turnovers_per_min", "passes_per_min")
        rows = []
        for tid in ([None] if match_level else teams):
            cur, base = value(tid, window_s), value(tid, None)
            rows.append({"team_id": tid, "current": r1(cur), "match_baseline": r1(base),
                         "delta": r1(cur - base) if cur is not None and base is not None else None})
        unit = "per_min" if metric in ("shots", "passes") else None
        return {"match_id": self.match_id, "metric": metric, "unit": unit, "window_s": window_s, "at_s": int(t),
                "minute": minute_of(t), "rows": rows}
