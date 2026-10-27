"""Stable-ID tactical change facts and checked bilingual coach notes."""

from pydantic import BaseModel, Field

from backend.analytics.live_tactics import LiveTactics
from .config import AgentConfig
from .feature_writer import write_feature


class CoachNote(BaseModel):
    note_id: str
    match_id: str
    team_id: str
    game_clock_s: float
    trigger: str
    facts: dict
    evidence: dict
    headline: str
    body: str
    persona: str = "tactical"
    language: str
    verification_status: str
    source: str
    trace_id: str | None = None
    formations: dict = Field(default_factory=dict)


def coach_facts(ev, config=None):
    if hasattr(ev, "coach_facts"):
        return ev.coach_facts
    cfg = config or AgentConfig()
    live = ev.live_tactics if hasattr(ev, "live_tactics") else LiveTactics(ev)
    ev.live_tactics = live
    idx, notes, cooldown, previous = ev.tactics, [], {}, {}
    _, counters, pressing = live.event_features()
    area_prefix = {}
    for tid in ev.teams:
        prefix, count = [0.0], [0]
        for i in range(len(idx.times)):
            value = live.frame_shape(tid, i)["area_m2"]
            prefix.append(prefix[-1] + (value or 0))
            count.append(count[-1] + (value is not None))
        area_prefix[tid] = prefix, count

    def area_mean(tid, at, window):
        lo, hi = idx.bounds(at, window)
        values, counts = area_prefix[tid]
        n = counts[hi] - counts[lo]
        return (values[hi] - values[lo]) / n if n else None

    for at in range(cfg.coach_interval_s, int(ev.meta.match_duration_s) + 1, cfg.coach_interval_s):
        for tid in ev.teams:
            stable = live.stable(tid, at, cfg.coach_window_s, cfg.coach_hold_s)
            phases = live._formation_at(tid, at, cfg.coach_window_s)
            prior = previous.get(tid)
            line = ev.tracking.window(at, cfg.coach_window_s)["teams"][tid]["defensive_line_height_m"]
            baseline = ev.tracking.window(max(0, at - cfg.coach_window_s), cfg.coach_baseline_s)["teams"][tid]["defensive_line_height_m"]
            area_now, area_before = area_mean(tid, at, cfg.coach_window_s), area_mean(tid, max(0, at - cfg.coach_window_s), cfg.coach_baseline_s)
            possible = []
            if prior:
                for phase in stable:
                    if stable[phase] and prior["stable"].get(phase) and stable[phase] != prior["stable"][phase]:
                        possible.append(("formation_change", {"phase": phase, "before_label": prior["stable"][phase], "after_label": stable[phase]}))
            if at >= cfg.coach_baseline_s and line is not None and baseline is not None and abs(line - baseline) >= cfg.coach_line_change_m:
                possible.append(("line_height_change", {"before_m": round(baseline, 2), "after_m": round(line, 2), "change_m": round(line - baseline, 2)}))
            if at >= cfg.coach_baseline_s and area_before and area_now is not None and abs(area_now / area_before - 1) * 100 >= cfg.coach_area_change_pct:
                possible.append(("compactness_change", {"before_m2": round(area_before, 2), "after_m2": round(area_now, 2), "change_pct": round((area_now / area_before - 1) * 100, 2)}))
            actions = [p for p in pressing if p["team_id"] == tid and at - cfg.coach_baseline_s < p["at_s"] <= at]
            zones = {}
            for p in actions:
                key = p["column"], p["row"]
                zones[key] = zones.get(key, 0) + 1
            zone = min(zones, key=lambda z: (-zones[z], z)) if zones else None
            if prior and zone and prior["zone"] and (zone[0] < ev.cfg["advanced_features"]["pressing_columns"] / 2) != (prior["zone"][0] < ev.cfg["advanced_features"]["pressing_columns"] / 2):
                possible.append(("pressing_zone_shift", {"before_column": prior["zone"][0], "after_column": zone[0]}))
            threat = [c for c in counters if c["team_id"] == tid and at - cfg.coach_baseline_s < c["at_s"] <= at]
            if len(threat) >= cfg.coach_counter_min:
                possible.append(("counter_threat", {"counter_count": len(threat), "window_s": cfg.coach_baseline_s}))
            for trigger, facts in possible:
                key = tid, trigger
                if at - cooldown.get(key, -cfg.coach_cooldown_s) < cfg.coach_cooldown_s:
                    continue
                cooldown[key] = at
                notes.append({"match_id": ev.match_id, "team_id": tid, "game_clock_s": at, "trigger": trigger,
                              "facts": facts, "evidence": {"frame_range": idx.evidence(at, min(at, cfg.coach_baseline_s)),
                                  "evidence_event_ids": [e.event_id for e in ev.events if at - cfg.coach_baseline_s < e.game_time_s <= at]},
                              "formations": {"before": prior["stable_phases"] if prior and trigger == "formation_change" else prior["phases"] if prior else {}, "after": phases}})
            if prior:
                stable = {phase: stable[phase] or prior["stable"].get(phase) for phase in stable}
            stable_phases = dict(prior["stable_phases"]) if prior else {}
            for phase, observed in phases.items():
                if observed and stable.get(phase) == observed["label"]:
                    stable_phases[phase] = observed
            previous[tid] = {"stable": stable, "zone": zone, "phases": phases, "stable_phases": stable_phases}
    for i, note in enumerate(sorted(notes, key=lambda n: (n["game_clock_s"], n["team_id"], n["trigger"])), 1):
        note["note_id"] = f"coach_{i:03}"
    ev.coach_facts = sorted(notes, key=lambda n: (n["game_clock_s"], n["team_id"], n["trigger"]))
    return ev.coach_facts


async def coach_notes(ev, until_s, language="en", persona="tactical", *, model=None, budget=None, config=None, exclude_ids=()):
    output = []
    for note in coach_facts(ev, config):
        if note["game_clock_s"] > until_s or note["note_id"] in exclude_ids:
            continue
        team = ev.teams[note["team_id"]]
        ar = language == "ar"
        name = team.name_ar or team.name if ar else team.name
        facts = note["facts"]
        labels = {"formation_change": ("Formation change", "تغير التشكيل"), "line_height_change": ("Defensive line change", "تغير خط الدفاع"),
                  "compactness_change": ("Team area change", "تغير مساحة الفريق"), "pressing_zone_shift": ("Pressing zone change", "تغير منطقة الضغط"), "counter_threat": ("Counter-attacking activity", "نشاط الهجمات المرتدة")}
        headline = labels[note["trigger"]][ar]
        field_names = {"phase": "مرحلة اللعب", "before_label": "التشكيل السابق", "after_label": "التشكيل الحالي",
                       "before_m": "قبل بالمتر", "after_m": "بعد بالمتر", "change_m": "التغير بالمتر",
                       "before_m2": "المساحة السابقة", "after_m2": "المساحة الحالية", "change_pct": "نسبة التغير",
                       "before_column": "العمود السابق", "after_column": "العمود الحالي", "counter_count": "المرتدات",
                       "window_s": "الفترة بالثواني"}
        values_ar = {"in_possession": "مع الكرة", "out_of_possession": "دون الكرة"}
        body = name + ": " + "; ".join(f"{field_names.get(key, key) if ar else key.replace('_', ' ')} {values_ar.get(value, value) if ar and isinstance(value, str) else value}" for key, value in facts.items())
        written = await write_feature({"headline": headline, "body": body[:600]}, facts, ev.meta, note["game_clock_s"], model=model, budget=budget, config=config, persona=persona, language=language)
        output.append(CoachNote(**note, headline=written["answer"]["headline"], body=written["answer"]["body"], persona=persona,
                                language=language, source=written["source"], verification_status=written["verification_status"], trace_id=written["trace_id"]).model_dump(mode="json"))
    return output
