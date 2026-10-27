"""Causal tactical snapshots: every displayed label/count/area is computed here."""

from functools import lru_cache

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from .advanced import advanced_stats
from .geometry import area, formation, hull

DEFINITIONS = {
    "formation": "Largest depth-gap splitting into three/four lines; four must beat three by configured separation margin. Phase means require minimum observed frames. Labels are geometric observations, not coaching intent.",
    "shape": "Convex hull area of observed outfield positions; width, length and deepest-four height reuse tracking metrics. Missing players are never interpolated.",
    "space_control": "Nearest-player space control — distance only, not a pitch-control model with speed or ball physics. Grid-cell centres; equal nearest distances belong to neither side.",
    "lines": "Deepest outfield depth and mean of deepest four from own goal. Offside line is the second-last defender including goalkeeper, position only; no offside decisions.",
    "line_breaking": "Completed forward passes bypassing the configured minimum opponent outfield players at a causal nearby frame. Opponent formation-line means strictly between pass endpoints are counted.",
    "counters": "Own-half ball win followed by same-team shot inside the configured interval, with no opponent possession change. A shot belongs to its most recent qualifying win; chains carry original event IDs.",
    "pressing": "Team pressure, tackle, interception and foul events binned in attack-normalized zones; rates per elapsed window minute. Nearest team player-to-ball distance at causal nearby frame is a proximity measure, not proof of a pressing intention.",
    "evidence": "Frame ranges cover measured windows; event IDs identify their source records. No sample after at_s is used, including event-to-frame alignment.",
}


class TacticalSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    match_id: str
    at_s: float
    window_s: float
    teams: dict[str, dict]
    definitions: dict[str, str] = Field(default_factory=lambda: DEFINITIONS)
    evidence: dict


class LiveTactics:
    def __init__(self, evidence):
        self.ev, self.index = evidence, evidence.tactics
        self.cfg = evidence.cfg["advanced_features"]
        self._space = {}
        self._frame_shape = {}
        step = self.cfg["grid_step_m"]
        xs = np.arange(step / 2, self.index.meta.pitch_length_m, step, dtype=np.float32)
        ys = np.arange(step / 2, self.index.meta.pitch_width_m, step, dtype=np.float32)
        self._grid = np.stack(np.meshgrid(xs, ys), axis=-1).reshape(-1, 2)

    def phases(self, tid, at, window):
        idx, cfg = self.index, self.cfg
        lo, hi = idx.bounds(at, window)
        columns = idx.team_columns(tid)
        out = {}
        for phase, own in (("in_possession", True), ("out_of_possession", False)):
            rows = [i for i in range(lo, hi) if idx.owner[i] is not None and (idx.owner[i] == tid) == own]
            if len(rows) < cfg["phase_min_frames"]:
                out[phase] = None
                continue
            points = []
            for col in columns:
                samples = idx.positions[rows, col]
                valid = samples[np.isfinite(samples[:, 0])]
                if len(valid):
                    mean = valid.mean(axis=0)
                    points.append((idx.ids[col], float(mean[0]), float(mean[1])))
            label = formation(points, tid == idx.meta.home.team_id, idx.meta.pitch_length_m,
                              cfg["formation_four_line_margin"], cfg["formation_min_spread_m"])
            out[phase] = {**label, "frame_count": len(rows)} if label else None
        return out

    @lru_cache(maxsize=4096)
    def _formation_at(self, tid, at, window):
        return self.phases(tid, at, window)

    def stable(self, tid, at, window, hold=None):
        hold, step = hold or self.cfg["stable_formation_s"], self.cfg["history_step_s"]
        current = self._formation_at(tid, at, window)
        output = {}
        for phase in current:
            label = current[phase]["label"] if current[phase] else None
            previous = [self._formation_at(tid, t, window)[phase] for t in range(max(0, int(at - hold)), int(at) + 1, step)]
            output[phase] = label if at >= hold and label and all(p and p["label"] == label for p in previous) else None
        return output

    def frame_shape(self, tid, i):
        key = tid, i
        if key in self._frame_shape:
            return self._frame_shape[key]
        idx = self.index
        points = idx.positions[i, idx.team_columns(tid)]
        points = points[np.isfinite(points[:, 0])]
        polygon = hull(points.tolist())
        depths = sorted(float(p[0]) if tid == idx.meta.home.team_id else idx.meta.pitch_length_m - float(p[0]) for p in points)
        all_points = idx.positions[i, idx.team_columns(tid, False)]
        all_x = sorted(float(p[0]) for p in all_points if np.isfinite(p[0]))
        offside = (all_x[1] if tid == idx.meta.home.team_id else all_x[-2]) if len(all_x) >= 2 else None
        result = {"hull": polygon, "area_m2": round(area(polygon), 2) if len(points) else None,
                  "width_m": round(float(np.ptp(points[:, 1])), 2) if len(points) else None,
                  "length_m": round(float(np.ptp(points[:, 0])), 2) if len(points) else None,
                  "defensive_line_height_m": round(sum(depths[:self.ev.cfg["metrics"]["team_shape"]["defensive_line_players"]]) / self.ev.cfg["metrics"]["team_shape"]["defensive_line_players"], 2) if len(depths) >= self.ev.cfg["metrics"]["team_shape"]["defensive_line_players"] else None,
                  "deepest_outfield_m": round(depths[0], 2) if depths else None,
                  "offside_x_m": offside}
        self._frame_shape[key] = result
        return result

    def space(self, i):
        if i in self._space:
            return self._space[i]
        idx, grid = self.index, self._grid
        positions = idx.positions[i]
        valid = np.isfinite(positions[:, 0])
        if not valid.any():
            return {tid: {"whole_pct": None, "opponent_half_pct": None, "final_third_pct": None} for tid in self.ev.teams}
        x, y = positions[valid, 0], positions[valid, 1]
        distance = (grid[:, 0, None] - x) ** 2 + (grid[:, 1, None] - y) ** 2
        minimum = distance.min(axis=1)
        unique = (distance == minimum[:, None]).sum(axis=1) == 1
        winner = np.flatnonzero(valid)[distance.argmin(axis=1)]
        result = {}
        for tid in self.ev.teams:
            own = np.isin(winner, idx.team_columns(tid, False)) & unique
            depth = grid[:, 0] if tid == idx.meta.home.team_id else idx.meta.pitch_length_m - grid[:, 0]
            masks = {"whole_pct": np.ones(len(grid), dtype=bool), "opponent_half_pct": depth > idx.meta.pitch_length_m / 2,
                     "final_third_pct": depth >= idx.meta.pitch_length_m * 2 / 3}
            result[tid] = {key: round(float(own[mask].mean() * 100), 2) for key, mask in masks.items()}
        self._space[i] = result
        return result

    @lru_cache(maxsize=1)
    def event_features(self):
        idx, cfg = self.index, self.cfg
        breaks, counters, pressing = [], [], []
        wins = {}
        events = self.ev.events
        for n, e in enumerate(events):
            tid = e.team_id
            if tid not in self.ev.teams:
                continue
            i = idx.nearest(e.game_time_s, cfg["event_frame_tolerance_s"])
            depth = lambda x: x if tid == idx.meta.home.team_id else idx.meta.pitch_length_m - x
            if e.type == "possession_change":
                wins = {team: item for team, item in wins.items() if team == tid}
            if e.type in ("recovery", "interception", "tackle") and (e.type != "tackle" or e.outcome == "won") and e.start_x_m is not None:
                if depth(e.start_x_m) < idx.meta.pitch_length_m / 2:
                    wins[tid] = (n, e)
            if e.type == "shot" and tid in wins:
                start_n, start = wins.pop(tid)
                duration = e.game_time_s - start.game_time_s
                if duration <= cfg["counter_window_s"]:
                    chain = [x for x in events[start_n:n + 1] if x.team_id == tid]
                    counters.append({"team_id": tid, "at_s": e.game_time_s, "start_s": start.game_time_s,
                                     "duration_s": round(duration, 2), "fast_break": duration <= cfg["fast_break_s"],
                                     "passes": sum(x.type == "pass" for x in chain), "shot_outcome": e.outcome,
                                     "chain": [x.model_dump(mode="json", exclude_none=True, exclude={"ball_path"}) for x in chain],
                                     "evidence_event_ids": [x.event_id for x in chain]})
            if e.type == "pass" and e.outcome == "completed" and e.start_x_m is not None and e.end_x_m is not None and depth(e.end_x_m) > depth(e.start_x_m):
                opp = next(t for t in self.ev.teams if t != tid)
                if i is None:
                    breaks.append({"team_id": tid, "at_s": e.game_time_s, "event_id": e.event_id, "skipped": True})
                else:
                    points = idx.positions[i, idx.team_columns(opp)]
                    bypassed = sum(depth(e.start_x_m) < depth(float(p[0])) < depth(e.end_x_m) for p in points if np.isfinite(p[0]))
                    if bypassed >= cfg["line_break_players"]:
                        phases = self._formation_at(opp, e.game_time_s, cfg["formation_window_s"])
                        lines = phases["out_of_possession"]
                        count = sum(depth(e.start_x_m) < idx.meta.pitch_length_m - line["mean_depth_m"] < depth(e.end_x_m)
                                    for line in lines["lines"]) if lines else 0
                        breaks.append({"team_id": tid, "at_s": e.game_time_s, "event_id": e.event_id, "skipped": False,
                                       "players_bypassed": bypassed, "lines_broken": count,
                                       "start_xy": [e.start_x_m, e.start_y_m], "end_xy": [e.end_x_m, e.end_y_m],
                                       "frame": idx.frames[i], "evidence_event_ids": [e.event_id]})
            if e.type in ("pressure", "tackle", "interception", "foul") and e.start_x_m is not None and e.start_y_m is not None:
                nearest = None
                if i is not None:
                    points = idx.positions[i, idx.team_columns(tid, False)]
                    points = points[np.isfinite(points[:, 0])]
                    ball = np.asarray(idx.ball[2 * i:2 * i + 2])
                    nearest = round(float(np.sqrt(((points - ball) ** 2).sum(axis=1)).min()), 2) if len(points) else None
                pressing.append({"team_id": tid, "at_s": e.game_time_s, "event_id": e.event_id, "type": e.type,
                                 "column": min(cfg["pressing_columns"] - 1, int(depth(e.start_x_m) / idx.meta.pitch_length_m * cfg["pressing_columns"])),
                                 "row": min(cfg["pressing_rows"] - 1, int(e.start_y_m / idx.meta.pitch_width_m * cfg["pressing_rows"])),
                                 "nearest_presser_m": nearest})
        return breaks, counters, pressing

    @lru_cache(maxsize=128)
    def snapshot(self, at, window=60, team_id=None, include_space=True):
        ev, idx = self.ev, self.index
        lo, hi = idx.bounds(at, window)
        advanced = advanced_stats(ev.meta, ev.events, at_s=at, window_s=window, cfg=ev.cfg, tracking_index=ev.tracking)
        breaks, counters, pressing = self.event_features()
        out = {}
        for tid in ev.teams:
            if team_id and tid != team_id:
                continue
            phases = self._formation_at(tid, at, window)
            shapes = [self.frame_shape(tid, i) for i in range(lo, hi)]
            baseline = [self.frame_shape(tid, i) for i in range(hi)]

            def mean(items, key):
                values = [s[key] for s in items if s[key] is not None]
                return round(sum(values) / len(values), 2) if values else None

            known_breaks = [b for b in breaks if b["team_id"] == tid and b["at_s"] <= at]
            selected_breaks = [b for b in known_breaks if at - window < b["at_s"]]
            selected_counters = [c for c in counters if c["team_id"] == tid and at - window < c["at_s"] <= at]
            cells = {}
            for p in pressing:
                if p["team_id"] != tid or not at - window < p["at_s"] <= at:
                    continue
                cell = cells.setdefault((p["column"], p["row"]), {"column": p["column"], "row": p["row"], "count": 0,
                                                                            "evidence_event_ids": [], "distances": []})
                cell["count"] += 1
                cell["evidence_event_ids"].append(p["event_id"])
                if p["nearest_presser_m"] is not None:
                    cell["distances"].append(p["nearest_presser_m"])
            for cell in cells.values():
                cell["rate_per_min"] = round(cell["count"] / max(min(at, window) / 60, 1e-9), 2)
                distances = cell.pop("distances")
                cell["nearest_presser_m"] = round(sum(distances) / len(distances), 2) if distances else None
            control = None
            if include_space and hi > lo:
                values = [self.space(i)[tid] for i in range(lo, hi)]
                control = {"current": self.space(hi - 1)[tid], "window": {
                    key: round(sum(v[key] for v in values if v[key] is not None) / sum(v[key] is not None for v in values), 2)
                    if any(v[key] is not None for v in values) else None for key in values[0]}}
            out[tid] = {"formation": {**phases, "stable_label": self.stable(tid, at, window)},
                        "line_timeline": [{"at_s": t, "height_m": ev.tracking.window(t, self.cfg["formation_window_s"])["teams"][tid]["defensive_line_height_m"]} for t in range(0, int(at) + 1, self.cfg["history_step_s"])],
                        "formation_timeline": [{"at_s": t, **self._formation_at(tid, t, window)} for t in range(0, int(at) + 1, self.cfg["history_step_s"])],
                        "shape": {**advanced["tracking"]["teams"][tid], "current": shapes[-1] if shapes else None,
                                  "area_m2": mean(shapes, "area_m2"), "match_area_m2": mean(baseline, "area_m2"),
                                  "match_width_m": mean(baseline, "width_m"), "match_length_m": mean(baseline, "length_m")},
                        "lines": {"current": shapes[-1] if shapes else None, "window_deepest_m": mean(shapes, "deepest_outfield_m"),
                                  "match_deepest_m": mean(baseline, "deepest_outfield_m"),
                                  "window_four_m": mean(shapes, "defensive_line_height_m"),
                                  "match_four_m": mean(baseline, "defensive_line_height_m")},
                        "links": advanced_stats(ev.meta, ev.events, at_s=at, window_s=self.cfg["links_window_s"], cfg=ev.cfg)["teams"][tid]["pass_network"]["edges"][:self.cfg["max_links"]],
                        "control": control,
                        "line_breaking": {"count": sum(not b["skipped"] for b in selected_breaks), "match_count": sum(not b["skipped"] for b in known_breaks),
                                          "skipped": sum(b["skipped"] for b in selected_breaks), "passes": [b for b in selected_breaks if not b["skipped"]]},
                        "counters": {"count": len(selected_counters), "match_count": sum(c["team_id"] == tid and c["at_s"] <= at for c in counters),
                                     "fast_breaks": sum(c["fast_break"] for c in selected_counters), "items": selected_counters},
                        "pressing": {"cells": list(cells.values()), "ppda": advanced["teams"][tid]["current"]["ppda"]}}
        return TacticalSnapshot(match_id=ev.match_id, at_s=at, window_s=window, teams=out,
                                evidence={"frame_range": idx.evidence(at, window), "match_frame_range": idx.evidence(at),
                                          "evidence_event_ids": [e.event_id for e in ev.events if e.game_time_s <= at]}).model_dump(mode="json")


def tactical_snapshot(ev, at_s=5400, window_s=60, team_id=None, include_space=True):
    if not hasattr(ev, "live_tactics"):
        ev.live_tactics = LiveTactics(ev)
    return ev.live_tactics.snapshot(at_s, window_s, team_id, include_space)
