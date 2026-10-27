"""Auditable fan dashboards over Contract A; never changes the frozen contracts.

Window semantics match the evidence engine: (at_s - window_s, at_s]. Every
aggregate is calculated here, not by the browser. Spatial views retain event IDs.
"""

from collections import defaultdict
import math

from shared.schemas import MatchMetadata, SyntheticEvent

from .engine import MatchAnalytics, r1

DEFINITIONS = {
    "forward_passes_10m": "Completed passes gaining at least 10 m along the team's attacking x direction; not a provider-standard progressive-pass model.",
    "final_third_entries": "Completed passes or carries crossing from outside into the attacking final third.",
    "box_entries": "Completed passes or carries crossing from outside into the opponent penalty box.",
    "final_third_share_pct": "Team share of both teams' completed passes ending in their own attacking final third; a pass-based territory proxy, not possession or all touches.",
    "high_recoveries": "Recovery events located in the team's attacking final third.",
    "shot_conversion_pct": "Shot events with outcome goal divided by shot events; goals are not counted twice via goal events.",
    "ppda": "Opponent passes in their own 60% divided by our tackles, interceptions and fouls in that zone; null when no defensive action is observed.",
    "pass_network": "Directed completed-pass counts; nodes are average observed pass origins/receptions, not formation or tracking positions. Up to 12 strongest links shown.",
    "territory": "Counts of completed-pass endpoints in a 6 by 4 grid, normalized so both teams attack toward increasing x.",
    "comparison": "Current window versus the whole match so far at the same second. Count deltas compare different durations; rates and percentages are better intensity comparisons.",
    "window": "Left-open, right-closed time window; clipped to kickoff. No events later than at_s are included.",
}


def positioned(event):
    return all(v is not None for v in (event.start_x_m, event.start_y_m, event.end_x_m, event.end_y_m))


def percentage(numerator, denominator):
    return r1(100 * numerator / denominator) if denominator else None


def team_metrics(analytics, events, team_id, window, at):
    own = [e for e in events if e.team_id == team_id]
    passes = [e for e in own if e.type == "pass"]
    completed = [e for e in passes if e.outcome == "completed"]
    moves = [e for e in own if e.type in ("pass", "carry") and e.outcome == "completed" and positioned(e)]
    shots = [e for e in own if e.type == "shot"]
    duels = [e for e in own if e.type == "duel"]
    distances = [analytics.goal_distance_m(team_id, e.start_x_m, e.start_y_m)
                 for e in shots if e.start_x_m is not None and e.start_y_m is not None]
    pass_distances = [math.dist((e.start_x_m, e.start_y_m), (e.end_x_m, e.end_y_m))
                      for e in passes if positioned(e)]
    opponent_passes, defensive_actions = analytics.ppda_parts(team_id, window, at)
    return {
        "possession_pct": r1(None if (share := analytics.possession_share(team_id, window, at)) is None else 100 * share),
        "pass_accuracy_pct": percentage(len(completed), len(passes)),
        "ppda": r1(opponent_passes / defensive_actions) if defensive_actions else None,
        "opponent_passes_ppda_zone": opponent_passes,
        "defensive_actions_ppda_zone": defensive_actions,
        "control_index": r1(analytics.control_index(team_id, window, at)),
        "momentum": r1(analytics.momentum(team_id, at)),
        "passes": len(passes), "passes_completed": len(completed),
        "passes_per_min": r1(len(passes) / analytics._minutes(window, at)) if at > 0 else None,
        "passes_per_possession": r1(analytics.passes_per_possession(team_id, window, at)),
        "mean_pass_distance_m": r1(sum(pass_distances) / len(pass_distances)) if pass_distances else None,
        "forward_passes_10m": sum(positioned(e) and analytics.forward_m(team_id, e.start_x_m, e.end_x_m) >= 10 for e in completed),
        "final_third_entries": sum(not analytics.in_final_third(team_id, e.start_x_m) and analytics.in_final_third(team_id, e.end_x_m) for e in moves),
        "box_entries": sum(not analytics.in_opp_box(team_id, e.start_x_m, e.start_y_m) and analytics.in_opp_box(team_id, e.end_x_m, e.end_y_m) for e in moves),
        "final_third_passes": sum(e.end_x_m is not None and analytics.in_final_third(team_id, e.end_x_m) for e in completed),
        "shots": len(shots), "shots_on_target": sum(e.outcome in ("goal", "saved") for e in shots),
        "shot_conversion_pct": percentage(sum(e.outcome == "goal" for e in shots), len(shots)),
        "avg_shot_distance_m": r1(sum(distances) / len(distances)) if distances else None,
        "goals": sum(e.type == "goal" for e in own),
        "recoveries": sum(e.type == "recovery" for e in own),
        "high_recoveries": sum(e.type == "recovery" and e.start_x_m is not None and analytics.in_final_third(team_id, e.start_x_m) for e in own),
        "tackles_won": sum(e.type == "tackle" and e.outcome == "won" for e in own),
        "interceptions": sum(e.type == "interception" for e in own),
        "duels_won": sum(e.outcome == "won" for e in duels), "duels_total": len(duels),
        "duel_win_pct": percentage(sum(e.outcome == "won" for e in duels), len(duels)),
        "corners": sum(e.type == "corner" for e in own), "fouls": sum(e.type == "foul" for e in own),
    }


def spatial_views(analytics, events, team_id, players):
    edges = defaultdict(list)
    samples = defaultdict(list)
    cells = defaultdict(list)
    shots = []
    for e in events:
        if e.team_id != team_id:
            continue
        if e.type == "pass" and e.outcome == "completed" and positioned(e):
            x = e.end_x_m if analytics.attacks_right(team_id) else analytics.L - e.end_x_m
            cells[(min(5, int(x / analytics.L * 6)), min(3, int(e.end_y_m / analytics.W * 4)))].append(e.event_id)
            if e.player_id in players and e.receiver_id in players and players[e.player_id].team_id == players[e.receiver_id].team_id == team_id:
                edges[(e.player_id, e.receiver_id)].append(e.event_id)
                samples[e.player_id].append((e.start_x_m, e.start_y_m, e.event_id))
                samples[e.receiver_id].append((e.end_x_m, e.end_y_m, e.event_id))
        if e.type == "shot" and e.start_x_m is not None and e.start_y_m is not None:
            info = analytics.shot_info.get(e.event_id, {})
            shots.append({"event_id": e.event_id, "player_id": e.player_id, "game_time_s": e.game_time_s,
                          "x_m": e.start_x_m, "y_m": e.start_y_m, "outcome": e.outcome,
                          "distance_m": r1(info.get("distance_m")), "speed_kmh": r1(info.get("speed_kmh"))})
    network = {
        "nodes": [{"player_id": pid, "x_m": r1(sum(p[0] for p in points) / len(points)),
                   "y_m": r1(sum(p[1] for p in points) / len(points)),
                   "evidence_event_ids": sorted({p[2] for p in points})} for pid, points in sorted(samples.items())],
        "edges": [{"from_player_id": pair[0], "to_player_id": pair[1], "completed_passes": len(ids),
                   "evidence_event_ids": ids} for pair, ids in sorted(edges.items(), key=lambda item: (-len(item[1]), item[0]))[:12]],
    }
    territory = [{"column": col, "row": row, "completed_passes": len(ids), "evidence_event_ids": ids}
                 for (col, row), ids in sorted(cells.items())]
    return {"pass_network": network, "shot_map": shots, "territory": territory}


def advanced_stats(meta: MatchMetadata, events: list[SyntheticEvent], *, at_s: float = 5400,
                   window_s: float = 300, cfg=None) -> dict:
    if not 0 <= at_s <= meta.match_duration_s or not 0 < window_s <= meta.match_duration_s:
        raise ValueError("at_s and window_s must be within match duration")
    known = [e for e in events if e.game_time_s <= at_s]
    analytics = MatchAnalytics(meta, cfg)
    for e in known:
        analytics.add(e)
    analytics.now = at_s
    current = [e for e in known if at_s - window_s < e.game_time_s]
    players = {p.player_id: p for t in (meta.home, meta.away) for p in t.players}
    teams = {}
    for team in (meta.home, meta.away):
        teams[team.team_id] = {
            "current": team_metrics(analytics, current, team.team_id, window_s, at_s),
            "match": team_metrics(analytics, known, team.team_id, None, at_s),
            **spatial_views(analytics, current, team.team_id, players),
            "evidence_event_ids": [e.event_id for e in current if e.team_id == team.team_id],
        }
    for scope in ("current", "match"):
        total = sum(team[scope]["final_third_passes"] for team in teams.values())
        for team in teams.values():
            team[scope]["final_third_share_pct"] = percentage(team[scope]["final_third_passes"], total)
    for team in teams.values():
        team["deltas"] = {key: r1(value - team["match"][key]) if value is not None and team["match"][key] is not None else None
                          for key, value in team["current"].items()}
    return {"match_id": meta.match_id, "at_s": at_s, "window_s": window_s,
            "window_start_s": max(0, at_s - window_s), "definitions_version": "1.0",
            "definitions": DEFINITIONS, "teams": teams,
            "evidence_event_ids": [e.event_id for e in current]}
