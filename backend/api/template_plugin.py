"""Deterministic template overlays (zero model cost).

* Shows the full Moment (Contract B) -> Overlay (Contract C) path working before the agents exist.
* Is the safe fallback the Verifier substitutes when an agent times out or fails twice
  (`goal_overlays` / `red_card_overlays` can be imported by Owner C).
* Every number comes from the events: score, minute, shot speed from the ball path, shot
  distance, passes in the move.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque

from shared.schemas import MatchMetadata, Moment, Overlay, SyntheticEvent

GOAL_X = {"home": 105.0, "away": 0.0}


def display_minute(clock_s: int) -> int:
    return clock_s // 60 + 1  # football convention: 12:08 is the 13th minute


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def build_up_en(n: int) -> str:
    if n == 0:
        return "after winning the ball and driving forward"
    if n == 1:
        return "after a single pass"
    return f"after a {n}-pass move"


def build_up_ar(n: int) -> str:
    if n == 0:
        return "بعد استخلاص الكرة والانطلاق بها"
    if n == 1:
        return "بعد تمريرة واحدة"
    if n == 2:
        return "بعد تمريرتين"
    if n <= 10:
        return f"بعد هجمة من {n} تمريرات"
    return f"بعد هجمة من {n} تمريرة"


def shot_speed_kmh(shot: SyntheticEvent) -> float | None:
    if not shot.ball_path or not shot.duration_s:
        return None
    length = sum(math.dist(a[1:], b[1:]) for a, b in zip(shot.ball_path, shot.ball_path[1:]))
    return length / shot.duration_s * 3.6


class _Names:
    def __init__(self, meta: MatchMetadata) -> None:
        self.meta = meta
        self.players = {p.player_id: p for t in (meta.home, meta.away) for p in t.players}
        self.teams = {meta.home.team_id: meta.home, meta.away.team_id: meta.away}

    def player(self, pid: str, lang: str) -> str:
        p = self.players[pid]
        return (p.name_ar or p.name) if lang == "ar" else p.name

    def team(self, tid: str, lang: str) -> str:
        t = self.teams[tid]
        return (t.name_ar or t.name) if lang == "ar" else t.name

    def side(self, tid: str) -> str:
        return self.teams[tid].side


def _overlay(moment: Moment, persona: str, lang: str, headline: str, body: str, fields: dict, priority: int,
             ttl: int = 8) -> Overlay:
    return Overlay(
        overlay_id=f"ov_{moment.moment_id}_{persona}_{lang}",
        moment_id=moment.moment_id, match_id=moment.match_id, persona=persona, language=lang,
        dir="rtl" if lang == "ar" else "ltr", template_id="lower_third", slot="lower_third", priority=priority,
        headline=headline[:60], body=body[:160], fields=fields, evidence_event_ids=moment.evidence_event_ids,
        show_at_s=moment.game_clock_s, ttl_s=ttl, verification_status="fallback", source="template",
        prompt_version="template_v1",
    )


def goal_overlays(moment: Moment, names: _Names) -> list[Overlay]:
    f = moment.verified_facts
    pid, tid = str(f["scorer_id"]), str(moment.team_id)
    h, a = f["home_score"], f["away_score"]
    m = f["minute"]
    out = []
    for lang in ("en", "ar"):
        p, t = names.player(pid, lang), names.team(tid, lang)
        home, away = names.team(names.meta.home.team_id, lang), names.team(names.meta.away.team_id, lang)
        score = f"{home} {h}-{a} {away}"
        speed = f.get("shot_speed_kmh")
        dist = f.get("shot_distance_m")
        passes = f.get("passes_in_move")
        if lang == "en":
            out.append(_overlay(moment, "beginner", lang, f"GOAL! {t}", f"{p} scores in the {ordinal(m)} minute. {score}.", {}, 1))
            out.append(_overlay(moment, "tactical", lang, f"Goal {m}' - {t}",
                                f"{p} scores from {dist} m {build_up_en(passes)}. "
                                f"Shot speed {speed} km/h. {score}.", {"shot_speed_kmh": speed,
                                                                      "shot_distance_m": dist}, 1))
            out.append(_overlay(moment, "player", lang, f"{p} scores!",
                                f"{p}'s shot in the {ordinal(m)} minute left the boot at {speed} km/h.",
                                {"player_id": pid, "shot_speed_kmh": speed}, 1))
        else:
            out.append(_overlay(moment, "beginner", lang, f"هدف! {t}", f"{p} يسجل في الدقيقة {m}. {score}", {}, 1))
            out.append(_overlay(moment, "tactical", lang, f"هدف في الدقيقة {m} - {t}",
                                f"{p} يسجل من مسافة {dist} م {build_up_ar(passes)}. "
                                f"سرعة التسديدة {speed} كم/س. {score}", {"shot_speed_kmh": speed,
                                                                          "shot_distance_m": dist}, 1))
            out.append(_overlay(moment, "player", lang, f"{p} يسجل!",
                                f"تسديدة {p} في الدقيقة {m} انطلقت بسرعة {speed} كم/س.",
                                {"player_id": pid, "shot_speed_kmh": speed}, 1))
    return out


def red_card_overlays(moment: Moment, names: _Names) -> list[Overlay]:
    f = moment.verified_facts
    pid, tid, m = str(f["player_id"]), str(moment.team_id), f["minute"]
    out = []
    for lang in ("en", "ar"):
        p, t = names.player(pid, lang), names.team(tid, lang)
        if lang == "en":
            out.append(_overlay(moment, "beginner", lang, f"Red card: {p}",
                                f"{t} are down to 10 players after {p} is sent off in the {ordinal(m)} minute.", {}, 2))
            out.append(_overlay(moment, "tactical", lang, f"Red card {m}' - {t}",
                                f"{p} is sent off. {t} must defend the last {90 - m + 1} minutes with 10.", {}, 2))
        else:
            out.append(_overlay(moment, "beginner", lang, f"بطاقة حمراء: {p}",
                                f"{t} يكمل المباراة بعشرة لاعبين بعد طرد {p} في الدقيقة {m}.", {}, 2))
            out.append(_overlay(moment, "tactical", lang, f"طرد في الدقيقة {m} - {t}",
                                f"طرد {p}. على {t} الدفاع بعشرة لاعبين في الدقائق المتبقية.", {}, 2))
    return out


class TemplatePlugin:
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.recent: dict[str, deque] = defaultdict(lambda: deque(maxlen=40))
        self.counter: dict[str, int] = defaultdict(int)
        self.names: dict[str, _Names] = {}

    def reset(self, state) -> None:
        self.recent[state.match_id].clear()
        self.counter[state.match_id] = 0
        self.names[state.match_id] = _Names(state.metadata)

    def _moment_id(self, match_id: str) -> str:
        self.counter[match_id] += 1
        return f"mom_{9000 + self.counter[match_id]}"  # 9001+ never collides with Owner B's moment ids

    async def on_event(self, e: SyntheticEvent, state) -> None:
        recent = self.recent[e.match_id]
        recent.append(e)
        names = self.names.get(e.match_id)
        if names is None:
            return
        if e.type == "goal":
            shot = next((x for x in reversed(recent) if x.event_id == e.related_event_id), None)
            passes = 0
            for x in reversed(list(recent)[:-2]):
                if x.type in ("pass", "carry") and x.team_id == e.team_id:
                    passes += x.type == "pass"
                elif x.type not in ("pressure",):
                    break
            facts = {"scorer_id": e.player_id, "minute": display_minute(e.game_clock_s),
                     "home_score": int(e.qualifiers["home_score"]), "away_score": int(e.qualifiers["away_score"]),
                     "passes_in_move": passes}
            evidence = [e.event_id]
            if shot:
                evidence.insert(0, shot.event_id)
                goal_x = GOAL_X[names.side(e.team_id)]
                facts["shot_speed_kmh"] = round(shot_speed_kmh(shot) or 0)
                facts["shot_distance_m"] = round(math.dist((shot.start_x_m, shot.start_y_m), (goal_x, 34.0)))
            if "assist_player_id" in e.qualifiers:
                facts["assist_id"] = e.qualifiers["assist_player_id"]
            moment = Moment(moment_id=self._moment_id(e.match_id), match_id=e.match_id, game_clock_s=e.game_clock_s,
                            type="goal", importance=1.0, team_id=e.team_id, player_id=e.player_id,
                            evidence_event_ids=evidence, verified_facts=facts, rule_id="GOAL_TEMPLATE_V1")
            await self.ctx.publish_moment(moment)
            for ov in goal_overlays(moment, names):
                await self.ctx.publish_overlay(ov)
        elif e.type == "card" and e.outcome in ("red", "second_yellow"):
            facts = {"player_id": e.player_id, "minute": display_minute(e.game_clock_s), "card": e.outcome}
            moment = Moment(moment_id=self._moment_id(e.match_id), match_id=e.match_id, game_clock_s=e.game_clock_s,
                            type="red_card", importance=0.8, team_id=e.team_id, player_id=e.player_id,
                            evidence_event_ids=[e.event_id], verified_facts=facts, rule_id="RED_CARD_TEMPLATE_V1")
            await self.ctx.publish_moment(moment)
            for ov in red_card_overlays(moment, names):
                await self.ctx.publish_overlay(ov)


def register(ctx) -> None:
    plugin = TemplatePlugin(ctx)
    ctx.on_reset(plugin.reset)
    ctx.on_event(plugin.on_event)
