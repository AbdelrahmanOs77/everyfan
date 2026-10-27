"""Evidence-backed half/full/so-far reports; independently scoped half and match tables."""

from pydantic import BaseModel, ConfigDict

from backend.analytics.advanced import advanced_stats
from backend.analytics.live_tactics import tactical_snapshot
from backend.analytics.player_profile import PlayerProfiles
from .feature_writer import write_feature


class MatchReport(BaseModel):
    model_config = ConfigDict(extra="allow")
    match_id: str
    phase: str
    at_s: float
    persona: str
    language: str
    club_id: str | None = None
    facts: dict
    evidence: dict


async def match_report(ev, phase="so_far", at_s=5400, persona="beginner", language="en", club_id=None,
                       *, model=None, budget=None, config=None, reference=(), published_overlays=None):
    if phase not in {"half", "full", "so_far"}:
        raise ValueError("unknown report phase")
    if phase == "half" and at_s < 2700 or phase == "full" and at_s < 5400:
        raise ValueError("report phase is not available at this clock")
    if persona == "club" and club_id not in ev.teams:
        raise ValueError("club_id required")
    at = 2700 if phase == "half" else 5400 if phase == "full" else at_s
    start = 0 if at <= 2700 else 2700
    window = max(1, at - start)
    stats = advanced_stats(ev.meta, ev.events, at_s=at, window_s=window, cfg=ev.cfg, tracking_index=ev.tracking)
    tactics = tactical_snapshot(ev, at, min(300, max(1, at)), include_space=True)
    half_breaks = tactical_snapshot(ev, at, window, include_space=False)
    profiles = ev.profiles if hasattr(ev, "profiles") else PlayerProfiles(ev)
    ev.profiles = profiles
    leaders = {}
    for metric in ("goals", "key_passes", "distance_km", "high_intensity_m", "tackles_won", "interceptions", "defensive_actions", "top_speed_kmh"):
        values = [(pid, profiles.metrics(pid, at)["values"].get(metric) if metric != "defensive_actions" else
                   profiles.metrics(pid, at)["values"]["tackles_won"] + profiles.metrics(pid, at)["values"]["interceptions"]) for pid in ev.players]
        values = [(pid, value) for pid, value in values if value is not None]
        leaders[metric] = [{"player_id": pid, "value": value} for pid, value in sorted(values, key=lambda p: (-p[1], p[0]))[:3]]
    if reference:
        roles = [(pid, profiles.benchmark(pid, at, reference)[1]["value"]) for pid in ev.players]
        leaders["role_index_heuristic"] = [{"player_id": pid, "value": value} for pid, value in sorted((r for r in roles if r[1] is not None), key=lambda r: (-r[1], r[0]))[:3]]
    from .coach import coach_facts
    notes = [n for n in coach_facts(ev, config) if n["game_clock_s"] <= at]
    goals = [e.model_dump(mode="json", exclude_none=True, exclude={"ball_path"}) for e in ev.events if e.type == "goal" and e.game_time_s <= at]
    published_ids = {o["moment_id"] for o in published_overlays if o.get("verification_status") in {"approved", "template"}} if published_overlays is not None else None
    moments = sorted((m for m in ev.moments if start < m.game_clock_s <= at and (published_ids is None or m.moment_id in published_ids)), key=lambda m: (-m.importance, m.game_clock_s))[:8]
    facts = {"score": {tid: team["match"]["goals"] for tid, team in stats["teams"].items()}, "scorers": goals,
             "moments": [m.model_dump(mode="json") for m in moments],
             "numbers": {tid: {"half": team["current"], "match": team["match"],
                                "line_breaking": {"half": half_breaks["teams"][tid]["line_breaking"]["count"],
                                                  "match": tactics["teams"][tid]["line_breaking"]["match_count"]}} for tid, team in stats["teams"].items()},
             "tactics": {tid: {k: v for k, v in team.items() if k not in {"formation_timeline", "line_timeline"}} for tid, team in tactics["teams"].items()}, "standouts": leaders, "coach_notes": notes,
             "what_to_watch": [n["facts"] for n in notes[-3:]] if phase == "half" else []}
    ar = language == "ar"
    h, a = ev.meta.home, ev.meta.away
    headline = ("تقرير بين الشوطين" if phase == "half" else "تقرير نهاية المباراة" if phase == "full" else "تقرير المباراة حتى الآن") if ar else (
        "Half-time report" if phase == "half" else "Full-time report" if phase == "full" else "Match report so far")
    body = (f"{h.name_ar}: {facts['score'][h.team_id]}؛ {a.name_ar}: {facts['score'][a.team_id]}." if ar else
            f"{h.name} {facts['score'][h.team_id]}, {a.name} {facts['score'][a.team_id]}.")
    body += (" الاستحواذ: " if ar else " Possession: ") + f"{facts['numbers'][h.team_id]['match']['possession_pct']}% / {facts['numbers'][a.team_id]['match']['possession_pct']}%."
    shapes = [tactics["teams"][team.team_id] for team in (h, a)]
    labels = [s["formation"]["in_possession"]["label"] if s["formation"]["in_possession"] else "—" for s in shapes]
    body += (" التشكيل مع الكرة: " if ar else " With-ball formations: ") + " / ".join(labels) + "."
    body += (" ارتفاع خط الدفاع بالمتر: " if ar else " Defensive line heights (m): ") + " / ".join(str(s["shape"]["defensive_line_height_m"]) for s in shapes) + "."
    body += (" المرتدات في الفترة الأخيرة: " if ar else " Recent counters: ") + " / ".join(str(s["counters"]["count"]) for s in shapes) + "."
    if persona == "club":
        team = ev.teams[club_id]
        body = (team.name_ar if ar else team.name) + ": " + body
    body = body.replace("None", "—")
    written = await write_feature({"headline": headline, "body": body}, facts, ev.meta, at, model=model, budget=budget, config=config, persona=persona, language=language)
    report = MatchReport(match_id=ev.match_id, phase=phase, at_s=at, persona=persona, language=language, club_id=club_id,
                         facts=facts, evidence={"evidence_event_ids": [e.event_id for e in ev.events if e.game_time_s <= at],
                                              "frame_range": ev.tactics.evidence(at)}, **written).model_dump(mode="json")
    report["dir"] = "rtl" if ar else "ltr"
    report["definitions"] = {"report": "Score/scorers and measured facts known at the report cutoff; half and match tables are independently scoped. Standouts are category leaders, never a player-of-the-match verdict.",
                             "story": "Top deterministic detected moments in the half; source evidence retained. Reports do not infer unpublished model opinions."}
    return report
