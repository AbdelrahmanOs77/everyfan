"""Bilingual Contract C fallbacks. All displayed measurements come from verified facts."""

from backend.api.template_plugin import goal_overlays, red_card_overlays
from shared.schemas import Moment, Overlay

from .names import NameAllowlist, focus_player

PERSONAS = ("beginner", "tactical", "player")
# Favorite Club is written once per club, so each fan sees the moment from their own side.
CLUB_PERSONA = "club"
ALL_PERSONAS = (*PERSONAS, CLUB_PERSONA)
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


# ---------------------------------------------------------------------------
# Favorite Club persona: partisan framing for the chosen club, factual, respectful to the rival.
# One overlay per (club, language); `fields.club_id` says which club's fans it is for.
# ---------------------------------------------------------------------------

def _club_text(moment: Moment, names: NameAllowlist, club: str, lang: str) -> tuple[str, str] | None:
    """(headline, body) for fans of `club`, or None to use the generic wording."""
    f = moment.verified_facts
    ar = lang == "ar"
    ours = moment.team_id == club
    rival_id = next(t for t in names.teams if t != club)
    me, rival = names.team(club, lang), names.team(rival_id, lang)

    def who(key: str) -> str | None:
        pid = f.get(key)
        return names.player(pid, lang) if isinstance(pid, str) and pid in names.players else None

    kind = moment.type
    if kind == "goal" and {"minute", "home_score", "away_score"} <= f.keys():
        scorer = who("scorer_id")
        score = f"{f['home_score']}-{f['away_score']}"
        if ar:
            lead = f"{scorer} يسجل" if scorer else "هدف"
            return ((f"هدف لصالح {me}", f"{lead} في الدقيقة {f['minute']}. النتيجة {score}.") if ours else
                    (f"هدف ضد {me}", f"{lead} لصالح {rival} في الدقيقة {f['minute']}. النتيجة {score}."))
        lead = f"{scorer} scores" if scorer else "A goal"
        return ((f"Goal for {me}!", f"{lead} in minute {f['minute']}. Score {score}.") if ours else
                (f"Setback for {me}", f"{lead} for {rival} in minute {f['minute']}. Score {score}."))
    if kind == "red_card" and "minute" in f:
        player = who("player_id")
        if ar:
            lead = f"طرد {player} في الدقيقة {f['minute']}." if player else f"طرد في الدقيقة {f['minute']}."
            if ours:
                tail = f" عدد لاعبي {me} الآن {f['players_left']}." if "players_left" in f else ""
                return f"بطاقة حمراء ضد {me}", lead + tail
            tail = (f" عدد لاعبي {rival} الآن {f['players_left']} أمام {me}." if "players_left" in f
                    else f" يواصل {rival} أمام {me} بنقص عددي.")
            return f"بطاقة حمراء ضد {rival}", lead + tail
        lead = f"{player} is sent off in minute {f['minute']}." if player else f"Sent off in minute {f['minute']}."
        if ours:
            tail = f" {me} play with {f['players_left']}." if "players_left" in f else ""
            return f"Blow for {me}", lead + tail
        tail = (f" {rival} play with {f['players_left']} against {me}." if "players_left" in f
                else f" {rival} play on against {me} a player down.")
        return f"Red card against {rival}", lead + tail
    if kind == "big_chance" and {"shot_distance_m", "shot_speed_kmh"} <= f.keys():
        shooter = who("shooter_id")
        d, s = f["shot_distance_m"], f["shot_speed_kmh"]
        if ar:
            lead = f"تسديدة {shooter}" if shooter else "تسديدة"
            side = "" if ours else f" لصالح {rival}"
            return (f"فرصة خطيرة لصالح {me}" if ours else f"خطر على مرمى {me}",
                    f"{lead}{side} من مسافة {d} م بسرعة {s} كم/س.")
        lead = f"{shooter} shoots" if shooter else "A shot"
        side = "" if ours else f" for {rival}"
        return (f"So close for {me}!" if ours else f"Let-off for {me}", f"{lead}{side} from {d} m at {s} km/h.")
    if kind == "momentum_shift" and "possession_pct_last_5" in f:
        p, team = f["possession_pct_last_5"], (me if ours else rival)
        if ar:
            return (f"{me} يفرض أفضليته" if ours else f"ضغط على {me}", f"استحوذ {team} على {p}٪ من الكرة مؤخراً.")
        return (f"{me} on top" if ours else f"{me} under pressure", f"{team} have had {p}% of the ball recently.")
    if kind == "pressing_shift" and "regains_in_zone_last_5" in f:
        n, team = f["regains_in_zone_last_5"], (me if ours else rival)
        if ar:
            return (f"{me} يضغط بقوة" if ours else f"{rival} يضغط على {me}",
                    f"استعاد {team} الكرة {n} مرات في منطقة الضغط مؤخراً.")
        return (f"{me} pressing high" if ours else f"{rival} pressing {me}",
                f"{team} won the ball back {n} times in the pressing zone recently.")
    if kind == "killer_pass" and {"pass_distance_m", "seconds_to_shot"} <= f.keys():
        passer = who("passer_id")
        d, t = f["pass_distance_m"], f["seconds_to_shot"]
        if ar:
            lead = f"تمريرة {passer}" if passer else "تمريرة"
            side = "" if ours else f" لصالح {rival}"
            return (f"خطورة من {me}" if ours else f"تهديد على مرمى {me}",
                    f"{lead}{side} لمسافة {d} م تبعتها تسديدة بعد {t} ثوانٍ.")
        lead = f"A {d} m pass from {passer}" if passer else f"A {d} m pass"
        side = "" if ours else f" for {rival}"
        return (f"Danger from {me}" if ours else f"Warning for {me}",
                f"{lead}{side} was followed by a shot {t} seconds later.")
    return None


def club_overlays(moment: Moment, names: NameAllowlist, clubs=None) -> list[Overlay]:
    """Favorite Club fallbacks for every club (or `clubs`), both languages. Team moments only."""
    if moment.match_id != names.meta.match_id:
        raise ValueError("Moment and metadata must describe the same match")
    if moment.team_id not in names.teams:
        return []  # match-level moments (rhythm, chaos) have no side to support
    result = []
    for club in (clubs if clubs is not None else names.teams):
        if club not in names.teams:
            continue
        for lang in LANGUAGES:
            ar = lang == "ar"
            text = _club_text(moment, names, club, lang)
            if text is None:
                me = names.team(club, lang)
                if moment.team_id == club:
                    subject = me
                else:
                    rival = names.team(moment.team_id, lang)
                    subject = f"{rival} أمام {me}" if ar else f"{rival} against {me}"
                text = TITLES[moment.type][ar], f"{subject}: {_text(moment, lang, 'beginner')}"
            headline, body = text
            if len(headline) > 60:
                headline = TITLES[moment.type][ar]
            if len(body) > 160:
                body = _text(moment, lang, "beginner")
            fields = {**moment.verified_facts, "club_id": club}
            result.append(Overlay(
                overlay_id=f"ov_{moment.moment_id}_club_{club}_{lang}", moment_id=moment.moment_id,
                match_id=moment.match_id, persona=CLUB_PERSONA, language=lang, dir="rtl" if ar else "ltr",
                template_id="lower_third", slot="lower_third",
                priority=1 if moment.type in {"goal", "red_card"} else 3,
                headline=headline, body=body, fields=fields, evidence_event_ids=moment.evidence_event_ids,
                show_at_s=moment.game_clock_s, ttl_s=8, verification_status="fallback", source="template",
                prompt_version="template_v1",
            ))
    return result


def overlay_key(overlay) -> tuple[str, str, str | None]:
    """(persona, language, club_id): identifies one air slot of one moment."""
    club = overlay.fields.get("club_id") if overlay.persona == CLUB_PERSONA else None
    return overlay.persona, overlay.language, club


def all_template_overlays(moment: Moment, names: NameAllowlist) -> list[Overlay]:
    return template_overlays(moment, names) + club_overlays(moment, names)


def template_for(moment: Moment, names: NameAllowlist, persona: str, language: str,
                 club_id: str | None = None) -> Overlay | None:
    """The checked fallback for one air slot, or None if that persona does not apply."""
    if persona == CLUB_PERSONA:
        if club_id is None:
            return None
        found = club_overlays(moment, names, [club_id])
    else:
        found = template_overlays(moment, names)
    return next((o for o in found if overlay_key(o) == (persona, language, club_id if persona == CLUB_PERSONA else None)), None)
