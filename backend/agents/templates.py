"""Bilingual Contract C fallbacks. All displayed measurements come from verified facts."""

from backend.api.template_plugin import goal_overlays, red_card_overlays
from shared.schemas import Moment, Overlay

from .names import NameAllowlist, focus_player

PERSONAS = ("beginner", "tactical", "player")
LANGUAGES = ("en", "ar")

TITLES = {
    "goal": ("Goal", "هدف"),
    "red_card": ("Red card", "بطاقة حمراء"),
    "big_chance": ("Big chance", "فرصة خطيرة"),
    "momentum_shift": ("Momentum shifts", "تحول في زخم اللعب"),
    "pressing_shift": ("Pressing changes", "تغير في الضغط"),
    "control_to_chaos": ("Play becomes unsettled", "تراجع الاستقرار في اللعب"),
    "killer_pass": ("A pass creates a shot", "تمريرة تصنع تسديدة"),
    "rhythm_change": ("Match rhythm changes", "تغير إيقاع المباراة"),
    "player_milestone": ("Player highlight", "لقطة لاعب"),
}


def _text(moment: Moment, lang: str, persona: str) -> str:
    f = moment.verified_facts
    ar = lang == "ar"
    kind = moment.type
    if kind == "big_chance":
        return (f"تسديدة من مسافة {f['shot_distance_m']} م بسرعة {f['shot_speed_kmh']} كم/س."
                if ar else f"A shot from {f['shot_distance_m']} m at {f['shot_speed_kmh']} km/h.")
    if kind == "momentum_shift":
        if persona == "tactical":
            return (f"مؤشر الزخم {f['momentum']} مقابل {f['momentum_opponent']} للمنافس."
                    if ar else f"Momentum index {f['momentum']} versus the opponent's {f['momentum_opponent']}.")
        return (f"الاستحواذ — حصة الفريق من الكرة — {f['possession_pct_last_5']}٪ في الفترة الأخيرة."
                if ar else f"Possession means the team's share of the ball: {f['possession_pct_last_5']}% recently.")
    if kind == "pressing_shift":
        if persona == "tactical":
            return (f"مؤشر PPDA الآن {f['ppda_last_5']} مقابل {f['ppda_match']} كمتوسط المباراة."
                    if ar else f"PPDA now {f['ppda_last_5']} versus a match baseline of {f['ppda_match']}.")
        return (f"الضغط — محاولة استعادة الكرة — شهد {f['regains_in_zone_last_5']} استردادات في المنطقة مؤخراً."
                if ar else f"Pressing means trying to win the ball back: {f['regains_in_zone_last_5']} recent regains in the zone.")
    if kind == "control_to_chaos":
        if persona == "tactical":
            return (f"مؤشر الفوضى {f['chaos_index_last_5']}، وتغير الاستحواذ {f['turnovers_per_min_last_5']} مرة/دقيقة."
                    if ar else f"Chaos index {f['chaos_index_last_5']}; possession changes {f['turnovers_per_min_last_5']} times per minute.")
        return (f"تتبادل الفرق الكرة بمعدل {f['turnovers_per_min_last_5']} مرة في الدقيقة مؤخراً."
                if ar else f"The ball has changed sides {f['turnovers_per_min_last_5']} times per minute recently.")
    if kind == "killer_pass":
        return (f"تمريرة لمسافة {f['pass_distance_m']} م تبعتها تسديدة بعد {f['seconds_to_shot']} ثوانٍ."
                if ar else f"A {f['pass_distance_m']} m pass was followed by a shot {f['seconds_to_shot']} seconds later.")
    if kind == "rhythm_change":
        labels = {"slow": "بطيء", "balanced": "متوازن", "frantic": "سريع", "fast": "سريع"}
        if ar:
            # Only translate known labels; never invent a classification.
            label = labels.get(str(f.get("rhythm_to")))
            prefix = f"الإيقاع الآن {label}. " if label else ""
            return f"{prefix}معدل التمريرات {f['passes_per_min_last_5']} في الدقيقة."
        return f"Pass rate now {f['passes_per_min_last_5']} per minute; median gap {f['median_pass_gap_s']} seconds."
    if kind == "player_milestone":
        for key, unit_en, unit_ar in (("shot_speed_kmh", "Shot speed", "سرعة التسديدة"),
                                     ("top_speed_kmh", "Top speed", "السرعة القصوى"),
                                     ("distance_km", "Distance covered", "المسافة المقطوعة"),
                                     ("pass_distance_m", "Pass distance", "مسافة التمريرة")):
            if key in f:
                unit = ("km/h", "كم/س") if key.endswith("kmh") else (("km", "كم") if key.endswith("km") else ("m", "م"))
                return f"{unit_ar if ar else unit_en}: {f[key]} {unit[ar]}."
        return "لقطة موثقة من أداء اللاعب." if ar else "An evidence-backed player highlight."
    if kind == "red_card":
        # The older template assumes ten players and computes remaining minutes.
        # Multiple dismissals invalidate that assumption: use B's players_left fact.
        if "players_left" in f:
            return (f"طرد في الدقيقة {f['minute']}. عدد لاعبي الفريق المتبقين: {f['players_left']}."
                    if ar else f"Sent off in minute {f['minute']}. Players remaining: {f['players_left']}.")
        return (f"طرد في الدقيقة {f['minute']}." if ar else f"Sent off in minute {f['minute']}.")
    if kind == "goal":
        return (f"هدف في الدقيقة {f['minute']}. النتيجة {f['home_score']}-{f['away_score']}."
                if ar else f"Goal in minute {f['minute']}. Score {f['home_score']}-{f['away_score']}.")
    raise ValueError(f"Unsupported moment type: {kind}")


def template_overlays(moment: Moment, names: NameAllowlist) -> list[Overlay]:
    """Produce all supported personas/languages; player requires a known focus player."""
    if moment.match_id != names.meta.match_id:
        raise ValueError("Moment and metadata must describe the same match")
    player_id = focus_player(moment)
    if player_id not in names.players:
        player_id = None
    # Reuse Owner A's goal/red-card templates when their required metadata is available.
    reused = {}
    f = moment.verified_facts
    if moment.team_id in names.teams:
        goal_keys = {"scorer_id", "minute", "home_score", "away_score", "passes_in_move", "shot_speed_kmh", "shot_distance_m"}
        if moment.type == "goal" and goal_keys <= f.keys() and f["scorer_id"] in names.players:
            reused = {(o.persona, o.language): o for o in goal_overlays(moment, names)}
        elif moment.type == "red_card" and {"player_id", "minute"} <= f.keys() and f["player_id"] in names.players:
            reused = {(o.persona, o.language): o for o in red_card_overlays(moment, names)}
    result = []
    for persona in PERSONAS:
        if persona == "player" and player_id is None:
            continue
        for lang in LANGUAGES:
            ar = lang == "ar"
            title = TITLES[moment.type][ar]
            subject = (names.player(player_id, lang) if player_id else
                       names.team(moment.team_id, lang) if moment.team_id in names.teams else "")
            headline = f"{title}: {subject}" if subject else title
            # Keep full metadata names in the body if a headline would exceed the contract.
            if len(headline) > 60:
                headline = title
            body = _text(moment, lang, persona)
            if subject:
                body = f"{subject}: {body}"
            if len(body) > 160:
                body = _text(moment, lang, persona)
            fields = dict(f)
            if persona == "player":
                fields["player_id"] = player_id
            old = reused.get((persona, lang))
            if old and moment.type == "goal":
                headline, body = old.headline, old.body
            elif old:
                headline = old.headline
            result.append(Overlay(
                overlay_id=f"ov_{moment.moment_id}_{persona}_{lang}", moment_id=moment.moment_id,
                match_id=moment.match_id, persona=persona, language=lang, dir="rtl" if ar else "ltr",
                template_id="player_tag" if persona == "player" else "stat_card" if persona == "tactical" else "lower_third",
                slot="pitch" if persona == "player" else "side_panel" if persona == "tactical" else "lower_third",
                priority=1 if moment.type in {"goal", "red_card"} else 3,
                headline=headline, body=body, fields=fields, evidence_event_ids=moment.evidence_event_ids,
                show_at_s=moment.game_clock_s, ttl_s=8, verification_status="fallback", source="template",
                prompt_version="template_v1",
            ))
    return result
