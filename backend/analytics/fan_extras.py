"""Fan-specific views over existing deterministic analytics and tracking evidence."""

from bisect import bisect_right

from .engine import r1

DEFINITIONS = {
    "average_positions": "Arithmetic mean of actual tracking samples in (at_s - window_s, at_s]; "
                         "window_s=5400 includes kickoff. "
                         "original pitch coordinates, home attacks +x. Sample mean, not a formation or pass-location map.",
    "distance_km": "Existing PlayerTracker cumulative path length, sampled once per match second; "
                   "gaps and half changes excluded; ranking uses unrounded metres, ties use player ID.",
    "top_speed_kmh": "Existing PlayerTracker maximum three-frame smoothed speed from 2 Hz tracking; "
                     "not a sprint count. Ranking uses unrounded speed, ties use player ID.",
    "on_top": "Name a leader only when both rounded last-five-minute control index and current momentum "
              "are strictly higher for the same team. Otherwise mixed or insufficient; no composite score.",
    "key_moments": "Up to three detected moments for the club at or before at_s, highest importance first, "
                   "then earlier clock and moment ID. No fabricated placeholders when fewer are known.",
    "momentum_timeline": "Existing configured momentum: sum(weight * exp(-age / decay_s)) for shots, "
                         "box entries, final-third passes and corners; exclude age > 8 * decay_s. "
                         "One point per 60 match seconds plus at_s; all contributing event IDs returned.",
}


def on_top(teams):
    home, away = list(teams)
    a, b = teams[home], teams[away]
    if a["control_index_last_5"] is None or b["control_index_last_5"] is None:
        return {"status": "insufficient", "team_id": None}
    for tid, own, opp in ((home, a, b), (away, b, a)):
        if own["control_index_last_5"] > opp["control_index_last_5"] and own["momentum"] > opp["momentum"]:
            return {"status": "leading", "team_id": tid}
    return {"status": "mixed", "team_id": None}


def fan_stats(ev, at_s=5400, window_s=300):
    at_s = max(0.0, min(float(at_s), 5400.0))
    a = ev._analytics_at(at_s)
    summaries = {tid: a.team_snapshot(tid, at_s) for tid in ev.teams}
    known = [e.event_id for e in ev.events if e.game_time_s <= at_s]
    teams = {}
    for tid in ev.teams:
        positions, rankings = [], {"distance_km": [], "top_speed_kmh": []}
        raw = []
        for pid, player in sorted(ev.players.items()):
            if player.team_id != tid:
                continue
            index = ev.positions.get(pid)
            mean = index.average(at_s, window_s) if index else None
            if mean:
                positions.append({"player_id": pid, **mean})
            tl = ev.timelines.get(pid)
            sample = tl.at(at_s) if tl else None
            if sample:
                i = bisect_right(tl.secs, at_s) - 1
                raw.append((pid, sample, tl.secs[i]))
        for key, col in (("distance_km", 0), ("top_speed_kmh", 1)):
            rankings[key] = [{"rank": rank, "player_id": pid,
                              "value": round(values[0] / 1000, 2) if col == 0 else r1(values[1]),
                              "tracking_until_s": until}
                             for rank, (pid, values, until) in enumerate(
                                 sorted(raw, key=lambda row: (-row[1][col], row[0]))[:5], 1)]
        moments = sorted((m for m in ev.moments if m.team_id == tid and m.game_clock_s <= at_s),
                         key=lambda m: (-m.importance, m.game_clock_s, m.moment_id))[:3]
        teams[tid] = {"summary": summaries[tid], "average_positions": positions,
                      "leaderboards": rankings,
                      "key_moments": [m.model_dump(mode="json", exclude_none=True) for m in moments]}
    decay = ev.cfg["metrics"]["momentum"]["decay_s"]
    samples = sorted({*range(0, int(at_s) + 1, 60), at_s})
    timeline = [{"at_s": t, "teams": {
        tid: {"value": r1(a.momentum(tid, t)), "evidence_event_ids": sorted({
            eid for ti, team, _w, eid, _kind in a.momentum_items if team == tid and 0 <= t - ti <= 8 * decay})}
        for tid in ev.teams}} for t in samples]
    return {"match_id": ev.match_id, "at_s": at_s, "window_s": window_s,
            "window_start_s": max(0.0, at_s - window_s), "definitions_version": "1.0",
            "definitions": DEFINITIONS, "teams": teams, "on_top": on_top(summaries),
            "control_window_s": a.window_s, "momentum_timeline": timeline, "evidence_event_ids": known}
