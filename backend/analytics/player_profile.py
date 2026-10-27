"""Player profiles with explicit playing time, independent peers and causal tracks."""

import statistics
from bisect import bisect_right
from functools import lru_cache

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from .advanced import _frame_range

DEFINITIONS = {
    "minutes_played": "Time on pitch from starters, substitution and red/second-yellow events, clipped at at_s. No bench time in per-90 denominators.",
    "benchmark": "Other matches only, full-time peers in the same configured position group and at least 30 minutes. Midrank percentile=(below+0.5*equal)/n*100. Count/distance metrics per 90; accuracy percentages and top speed retain their natural units. Below 15 minutes is unreliable.",
    "role_index": "EveryFan role index (heuristic): 10 * sum(weight * percentile/100)/sum(weights). Null until reliable and a reference pool exists. No player rating or prediction.",
    "heatmap": "Raw tracking sample counts in configured pitch cells in the selected window; coordinates retain original pitch space.",
    "sprints": "Existing causal three-frame smoothed speed and strict sprint duration. Count once at qualification in window; start may precede window. Ongoing bout ends at last known sample, never at its future endpoint.",
    "fatigue": "Physical output per on-pitch minute in 15-minute blocks; percentage versus the first block. Output comparison, not a diagnosis of tiredness.",
    "matchup": "Opponent with smallest mean Euclidean separation over shared observed frames. Nearest-share uses frames with both observed. Duels/tackles only when receiver_id explicitly identifies this pair.",
    "off_ball_runs": "Own possession, minimum distance from ball, smoothed speed above configured threshold, and minimum forward depth gain. Possession/speed/distance/gaps/period change end the bout. Received pass must be completed and known within the configured follow-up window.",
    "evidence": "Source event IDs and causal frame ranges. No current-match future data enters measurements, sprint endpoints, output blocks, progress or reference membership.",
}


class PlayerProfile(BaseModel):
    model_config = ConfigDict(extra="allow")
    player: dict
    at_s: float
    minutes_played: float
    definitions: dict[str, str] = Field(default_factory=lambda: DEFINITIONS)
    evidence: dict


def percentile(value, peers):
    return round(100 * (sum(x < value for x in peers) + .5 * sum(x == value for x in peers)) / len(peers), 2) if peers else None


class PlayerProfiles:
    def __init__(self, ev):
        self.ev, self.idx, self.cfg = ev, ev.tactics, ev.cfg["advanced_features"]
        self.events = {pid: [e for e in ev.events if e.player_id == pid or e.receiver_id == pid] for pid in ev.players}

    def minutes(self, pid, at, start=0):
        p = self.ev.players[pid]
        active, since, total = p.starter, 0, 0
        for e in self.ev.events:
            if e.game_time_s > at:
                break
            leaves = e.player_id == pid and (e.type == "substitution" or e.type == "card" and e.outcome in ("red", "second_yellow"))
            enters = e.type == "substitution" and e.receiver_id == pid
            if leaves and active:
                total += max(0, e.game_time_s - max(since, start))
                active = False
            if enters and not active:
                active, since = True, e.game_time_s
        if active:
            total += max(0, at - max(since, start))
        return total / 60

    def source(self, pid, at, window=5400):
        idx, col = self.idx, self.idx.columns[pid]
        lo, hi = idx.bounds(at, window)
        rows = [i for i in range(lo, hi) if np.isfinite(idx.positions[i, col, 0])]
        result = _frame_range(idx.times, idx.frames, rows[0], rows[-1] + 1) if rows else None
        if result:
            result["sample_count"] = len(rows)
        return result

    def physical(self, pid, at, window=5400):
        idx, col, n = self.idx, self.idx.columns[pid], len(self.idx.ids)
        lo, hi = idx.bounds(at, window)
        steps = np.asarray(idx.step).reshape(-1, n)[lo:hi, col].copy()
        if len(steps):
            dt = self.ev.cfg["metrics"]["player_speed"]["frame_dt_s"]
            fraction = min(1, max(0, (max(0, at - window) - (idx.times[lo] - dt)) / dt))
            steps[0] *= 1 - fraction
        speeds = np.asarray(idx.speed).reshape(-1, n)[lo:hi, col]
        intensity = self.ev.tracking.window(at, window)["players"][pid]
        return {"distance_km": round(float(np.nansum(steps)) / 1000, 4),
                "top_speed_kmh": round(float(np.nanmax(speeds)), 2) if np.isfinite(speeds).any() else None,
                "high_intensity_m": intensity["distance_above_threshold_m"], "sprints": intensity["sprints"]}

    @lru_cache(maxsize=4096)
    def metrics(self, pid, at):
        ev, p = self.ev, self.ev.players[pid]
        events = [e for e in self.events[pid] if e.game_time_s <= at and e.player_id == pid]
        passes = [e for e in events if e.type == "pass"]
        duels = [e for e in events if e.type == "duel"]
        home = p.team_id == ev.meta.home.team_id
        depth = lambda x: x if home else ev.meta.pitch_length_m - x
        third = ev.meta.pitch_length_m - ev.cfg["pitch"]["final_third_m"]
        box_depth, box_half = ev.cfg["pitch"]["box_depth_m"], ev.cfg["pitch"]["box_half_width_m"]
        in_box = lambda x, y: x >= ev.meta.pitch_length_m - box_depth and y is not None and abs(y - ev.meta.pitch_width_m / 2) <= box_half
        entries, box, forward = 0, 0, 0
        for e in events:
            if e.type not in ("pass", "carry") or e.outcome != "completed" or e.start_x_m is None or e.end_x_m is None:
                continue
            start, end = depth(e.start_x_m), depth(e.end_x_m)
            forward += e.type == "pass" and end - start >= self.cfg["forward_pass_m"]
            entries += start < third <= end
            box += in_box(end, e.end_y_m) and not in_box(start, e.start_y_m)
        key_ids, key_count, last_pass = set(), 0, {}
        for e in ev.events:
            if e.game_time_s > at:
                break
            if e.type == "pass" and e.outcome == "completed":
                last_pass[e.team_id] = e
            if e.type == "shot":
                prior = last_pass.get(e.team_id)
                if prior and prior.player_id == pid and e.game_time_s - prior.game_time_s <= ev.cfg["moments"]["killer_pass"]["shot_within_s"]:
                    key_ids.update((prior.event_id, e.event_id))
                    key_count += 1
        values = {"passes_completed": sum(e.outcome == "completed" for e in passes),
                  "pass_accuracy_pct": round(100 * sum(e.outcome == "completed" for e in passes) / len(passes), 2) if passes else None,
                  "tackles_won": sum(e.type == "tackle" and e.outcome == "won" for e in events),
                  "interceptions": sum(e.type == "interception" for e in events),
                  "duel_win_pct": round(100 * sum(e.outcome == "won" for e in duels) / len(duels), 2) if duels else None,
                  "recoveries": sum(e.type == "recovery" for e in events), "key_passes": key_count,
                  "forward_passes_10m": forward, "final_third_entries": entries, "box_entries": box,
                  "shots": sum(e.type == "shot" for e in events),
                  "shots_on_target": sum(e.type == "shot" and e.outcome in ("goal", "saved") for e in events),
                  "goals": sum(e.type == "goal" for e in events), "saves": sum(e.type == "save" for e in events),
                  **self.physical(pid, at)}
        return {"values": values, "minutes_played": round(self.minutes(pid, at), 4),
                "evidence_event_ids": sorted({e.event_id for e in events} | key_ids), "frame_range": self.source(pid, at)}

    def benchmark(self, pid, at, reference):
        group = self.cfg["position_groups"][self.ev.players[pid].position]
        metrics = self.cfg["benchmark_metrics"].get("outfield", []) + self.cfg["benchmark_metrics"].get(group, []) if group != "GK" else self.cfg["benchmark_metrics"]["GK"]
        current = self.metrics(pid, at)
        minutes = current["minutes_played"]
        peers = [p for p in reference if p["match_id"] != self.ev.match_id and p["group"] == group
                 and p["minutes_played"] >= self.cfg["reference_min_minutes"]]
        rows = []
        for metric in dict.fromkeys(metrics):
            rate = metric in self.cfg["benchmark_rates"]

            def value(record):
                raw = record["values"].get(metric)
                return raw if rate or raw is None else raw * 90 / record["minutes_played"] if record["minutes_played"] else None

            own = value(current)
            pool = [value(p) for p in peers if value(p) is not None]
            rank = percentile(own, pool) if own is not None else None
            if rank is not None and metric in self.cfg["lower_is_better"]:
                rank = 100 - rank
            rows.append({"metric": metric, "value": round(own, 3) if own is not None else None,
                         "normalization": "native" if rate else "per_90", "peer_median": round(statistics.median(pool), 3) if pool else None,
                         "percentile": rank, "pool_size": len(pool), "evidence_event_ids": current["evidence_event_ids"],
                         "frame_range": current["frame_range"]})
        reliable = minutes >= self.cfg["benchmark_min_minutes"] and bool(peers)
        weights = self.cfg["role_weights"][group]
        parts = [{"metric": r["metric"], "weight": weights[r["metric"]], "percentile": r["percentile"]}
                 for r in rows if r["metric"] in weights and r["percentile"] is not None]
        weight_sum = sum(p["weight"] for p in parts)
        for part in parts:
            part["contribution"] = round(10 * part["weight"] * part["percentile"] / 100 / weight_sum, 3)
        role = round(10 * sum(p["weight"] * p["percentile"] / 100 for p in parts) / weight_sum, 1) if reliable and weight_sum else None
        return {"group": group, "reliable": reliable, "pool_size": len(peers),
                "reference_evidence": [{"match_id": p["match_id"], "player_id": p["player_id"],
                    "evidence_event_ids": p.get("evidence_event_ids", []), "frame_range": p.get("frame_range")} for p in peers],
                "peer_ids": [f"{p['match_id']}:{p['player_id']}" for p in peers], "rows": rows}, {
                    "label": "EveryFan role index (heuristic)", "value": role, "parts": parts,
                    "formula": "10 * sum(weight * percentile / 100) / sum(weights)"}

    def bouts(self, pid, at, window, off_ball=False):
        idx, col, n = self.idx, self.idx.columns[pid], len(self.idx.ids)
        speeds = np.asarray(idx.speed).reshape(-1, n)[:, col]
        steps = np.asarray(idx.step).reshape(-1, n)[:, col]
        hi, out, start, duration, qualified = bisect_right(idx.times, at), [], None, 0, None
        p, cfg = self.ev.players[pid], self.cfg
        thresholds = self.ev.cfg["metrics"]["high_intensity"]
        dt = self.ev.cfg["metrics"]["player_speed"]["frame_dt_s"]
        last = None

        def finish(end):
            if start is None or end < start:
                return
            first = start
            if not off_ball and start > 0 and idx.frames[start - 1] + 1 == idx.frames[start] and idx.periods[start - 1] == idx.periods[start] and np.isfinite(idx.positions[start - 1, col, 0]):
                first = start - 1
            a, b = idx.positions[first, col], idx.positions[end, col]
            gain = float(b[0] - a[0]) * (1 if p.team_id == self.ev.meta.home.team_id else -1)
            if off_ball and gain < cfg["off_ball_gain_m"] or not off_ball and qualified is None:
                return
            counted_at = idx.times[end] if off_ball else qualified
            if counted_at <= at - window:
                return
            row = {"start_s": idx.times[first], "end_s": idx.times[end],
                   "start_xy": a.tolist(), "end_xy": b.tolist(), "depth_gain_m": round(gain, 2),
                   "duration_s": round(idx.times[end] - idx.times[first], 2), "period": idx.periods[end],
                   "max_speed_kmh": round(float(np.nanmax(speeds[start:end + 1])), 2),
                   "distance_m": round(float(np.nansum(steps[start:end + 1])), 2),
                   "evidence": _frame_range(idx.times, idx.frames, max(0, start - 3), end + 1),
                   "qualified_at_s": counted_at, "ongoing": end == hi - 1}
            if off_ball:
                depth = float(b[0]) if p.team_id == self.ev.meta.home.team_id else self.ev.meta.pitch_length_m - float(b[0])
                received = next((e for e in self.ev.events if e.type == "pass" and e.outcome == "completed" and e.receiver_id == pid
                                 and row["end_s"] <= e.game_time_s <= min(at, row["end_s"] + cfg["received_pass_s"])), None)
                row.update(box_run=depth >= self.ev.meta.pitch_length_m - self.ev.cfg["pitch"]["box_depth_m"] and abs(float(b[1]) - self.ev.meta.pitch_width_m / 2) <= self.ev.cfg["pitch"]["box_half_width_m"],
                           final_third_run=depth >= self.ev.meta.pitch_length_m - self.ev.cfg["pitch"]["final_third_m"],
                           received_pass_event_id=received.event_id if received else None)
            out.append(row)

        for i in range(hi):
            valid = np.isfinite(speeds[i])
            continuous = last is None or idx.frames[i] == idx.frames[last] + 1 and idx.periods[i] == idx.periods[last]
            if not continuous and start is not None:
                finish(last)
                start, duration, qualified = None, 0, None
            eligible = valid and speeds[i] > (cfg["off_ball_speed_kmh"] if off_ball else thresholds["sprint_threshold_kmh"])
            if off_ball and eligible:
                ball = np.asarray(idx.ball[2 * i:2 * i + 2])
                eligible = idx.owner[i] == p.team_id and float(np.linalg.norm(idx.positions[i, col] - ball)) >= cfg["off_ball_distance_m"]
            if eligible:
                if start is None:
                    start = i
                duration += dt
                if not off_ball and qualified is None and duration > thresholds["sprint_min_duration_s"]:
                    qualified = idx.times[i]
            else:
                if start is not None:
                    finish(i - 1)
                start, duration, qualified = None, 0, None
            last = i
        if start is not None:
            finish(hi - 1)
        return out

    def spatial(self, pid, at, window):
        idx, col = self.idx, self.idx.columns[pid]
        lo, hi = idx.bounds(at, window)
        values = idx.positions[lo:hi, col]
        values = values[np.isfinite(values[:, 0])]
        columns, rows = self.cfg["heatmap_columns"], self.cfg["heatmap_rows"]
        cells = {}
        for x, y in values:
            key = min(columns - 1, int(x / self.ev.meta.pitch_length_m * columns)), min(rows - 1, int(y / self.ev.meta.pitch_width_m * rows))
            cells[key] = cells.get(key, 0) + 1
        trail_lo, trail_hi = idx.bounds(at, min(window, self.cfg["trail_s"]))
        trail = [{"at_s": idx.times[i], "x_m": float(idx.positions[i, col, 0]), "y_m": float(idx.positions[i, col, 1]), "period": idx.periods[i]}
                 for i in range(trail_lo, trail_hi) if np.isfinite(idx.positions[i, col, 0])]
        return {"columns": columns, "rows": rows, "sample_count": len(values),
                "cells": [{"column": c, "row": r, "count": count, "share_pct": round(100 * count / len(values), 2)} for (c, r), count in sorted(cells.items())],
                "evidence": self.source(pid, at, window)}, trail

    def matchup(self, pid, at, window):
        idx, col = self.idx, self.idx.columns[pid]
        lo, hi = idx.bounds(at, window)
        own = idx.positions[lo:hi, col]
        candidates, per_frame = [], []
        for other in idx.ids:
            if self.ev.players[other].team_id == self.ev.players[pid].team_id or self.ev.players[other].position == "GK":
                continue
            rival = idx.positions[lo:hi, idx.columns[other]]
            shared = np.isfinite(own[:, 0]) & np.isfinite(rival[:, 0])
            distances = np.sqrt(((rival - own) ** 2).sum(axis=1))
            if shared.any():
                candidates.append((float(distances[shared].mean()), other, shared))
                per_frame.append((other, np.where(shared, distances, np.inf)))
        if not candidates:
            return None
        mean, other, shared = min(candidates, key=lambda x: (x[0], x[1]))
        matrix = np.stack([d for _, d in per_frame])
        winning = matrix.min(axis=0)
        target = next(d for rival, d in per_frame if rival == other)
        share = float(((target == winning) & ((matrix == winning).sum(axis=0) == 1) & shared).sum() / shared.sum() * 100)
        duels = [e for e in self.ev.events if at - window < e.game_time_s <= at and e.type in ("duel", "tackle")
                 and {e.player_id, e.receiver_id or e.qualifiers.get("opponent_id") or e.qualifiers.get("opponent_player_id")} == {pid, other}]
        wins = sum((e.player_id == pid and e.outcome == "won") or (e.receiver_id == pid and e.outcome == "lost") for e in duels)
        return {"opponent_id": other, "mean_distance_m": round(mean, 2), "nearest_share_pct": round(share, 2),
                "shared_frames": int(shared.sum()), "duels_won": wins, "duels_lost": len(duels) - wins,
                "evidence_event_ids": [e.event_id for e in duels], "frame_range": self.source(pid, at, window),
                "player_metrics": self.per90(pid, at), "opponent_metrics": self.per90(other, at)}

    def per90(self, pid, at):
        record = self.metrics(pid, at)
        minutes = record["minutes_played"]
        return {**record, "normalizations": {key: "native" if key in self.cfg["benchmark_rates"] else "per_90" for key in record["values"]},
                "values": {key: (value if key in self.cfg["benchmark_rates"] or value is None else
                    round(value * 90 / minutes, 3) if minutes else None) for key, value in record["values"].items()}}

    def profile(self, pid, at=5400, window=300, reference=(), sections=None):
        allowed = {"benchmark", "progress", "role_index", "heatmap", "trail", "sprints", "fatigue", "matchup", "off_ball_runs"}
        selected = allowed if sections is None else set(sections)
        if selected - allowed:
            raise ValueError("Unknown sections: " + ", ".join(sorted(selected - allowed)))
        if pid not in self.ev.players:
            raise KeyError(pid)
        base = self.metrics(pid, at)
        result = PlayerProfile(player=self.ev.players[pid].model_dump(mode="json"), at_s=at,
                               minutes_played=base["minutes_played"], evidence={"evidence_event_ids": base["evidence_event_ids"], "frame_range": base["frame_range"]}).model_dump()
        result.update(match_id=self.ev.match_id, window_s=window, window_start_s=max(0, at - window), metrics=base["values"])
        if selected & {"benchmark", "role_index", "progress"}:
            benchmark, role = self.benchmark(pid, at, reference)
            if "benchmark" in selected:
                result["benchmark"] = benchmark
            if "role_index" in selected:
                result["role_index"] = role
            if "progress" in selected:
                step = self.cfg["output_block_s"]
                result["progress"] = [{"at_s": t, "benchmark": self.benchmark(pid, t, reference)[0], "role_index": self.benchmark(pid, t, reference)[1]}
                                      for t in sorted({*range(step, int(at) + 1, step), at})]
        if selected & {"heatmap", "trail"}:
            heatmap, trail = self.spatial(pid, at, window)
            if "heatmap" in selected:
                result["heatmap"] = heatmap
            if "trail" in selected:
                result["trail"] = trail
        if "sprints" in selected:
            result["sprints"] = self.bouts(pid, at, window)
        if "off_ball_runs" in selected:
            runs = self.bouts(pid, at, window, True)
            result["off_ball_runs"] = {"count": len(runs), "items": runs}
        if "matchup" in selected:
            result["matchup"] = self.matchup(pid, at, window)
        if "fatigue" in selected:
            blocks, step = [], self.cfg["output_block_s"]
            for start in range(0, int(at), step):
                end = min(at, start + step)
                minutes = self.minutes(pid, end, start)
                physical = self.physical(pid, end, end - start)
                blocks.append({"start_s": start, "end_s": end, "minutes_played": round(minutes, 3),
                               "distance_per_min_m": round(physical["distance_km"] * 1000 / minutes, 2) if minutes else None,
                               "high_intensity_per_min_m": round(physical["high_intensity_m"] / minutes, 2) if minutes and physical["high_intensity_m"] is not None else None,
                               "sprints": physical["sprints"], "top_speed_kmh": physical["top_speed_kmh"], "evidence": self.source(pid, end, end - start)})
            first = blocks[0]["distance_per_min_m"] if blocks else None
            for block in blocks:
                block["first_block_pct"] = round(100 * block["distance_per_min_m"] / first, 2) if first and block["distance_per_min_m"] is not None else None
            result["fatigue"] = blocks
        return result


def player_profile(ev, player_id, at_s=5400, window_s=300, reference=(), sections=None):
    if not hasattr(ev, "profiles"):
        ev.profiles = PlayerProfiles(ev)
    return ev.profiles.profile(player_id, at_s, window_s, reference, sections)


def reference_rows(ev):
    if not hasattr(ev, "profiles"):
        ev.profiles = PlayerProfiles(ev)
    return [{"match_id": ev.match_id, "player_id": pid,
             "group": ev.cfg["advanced_features"]["position_groups"][p.position],
             **ev.profiles.metrics(pid, ev.meta.match_duration_s)} for pid, p in ev.players.items()]
