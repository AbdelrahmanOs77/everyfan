"""Literal bilingual action calls from Contract A, separate from model-written insights."""

from shared.schemas import MatchMetadata, SyntheticEvent


def _describe(e: SyntheticEvent, meta: MatchMetadata, ar: bool) -> str:
    players = {p.player_id: p for t in (meta.home, meta.away) for p in t.players}
    teams = {t.team_id: t for t in (meta.home, meta.away)}

    def name(entity):
        return (entity.name_ar or entity.name) if ar else entity.name

    team = name(teams[e.team_id]) if e.team_id in teams else ("الفريق" if ar else "the team")
    actor = name(players[e.player_id]) if e.player_id in players else team
    receiver = name(players[e.receiver_id]) if e.receiver_id in players else None
    kind = e.type
    if kind == "pass":
        if e.outcome == "out":
            return f"تمريرة من {actor} تخرج من الملعب." if ar else f"{actor} passes; the ball goes out of play."
        if e.outcome == "intercepted":
            return f"تمريرة من {actor} يقطعها المنافس." if ar else f"{actor} looks for a pass, but it is cut out."
        cross = e.qualifiers.get("cross") is True
        if receiver:
            return (f"عرضية من {actor} تصل إلى {receiver}." if cross else f"{actor} يمرر إلى {receiver}.") if ar else (
                f"{actor} crosses to {receiver}." if cross else
                (f"{actor} finds {receiver}." if e.seq % 2 else f"{actor} plays the ball to {receiver}."))
        return f"تمريرة مكتملة من {actor}." if ar else f"{actor} completes a pass."
    if kind == "shot":
        outcomes = {
            "goal": (f"{actor} shoots!", f"{actor} يسدد!"),
            "saved": (f"{actor} shoots — saved!", f"تسديدة من {actor} يتصدى لها الحارس!"),
            "off_target": (f"{actor} shoots off target.", f"تسديدة من {actor} خارج المرمى."),
            "blocked": (f"{actor}'s shot is blocked.", f"تسديدة من {actor} تُحجب."),
            "post": (f"{actor} hits the post!", f"تسديدة من {actor} ترتطم بالقائم!"),
        }
        return outcomes[e.outcome][ar]
    if kind == "card":
        cards = {"yellow": ("Yellow card", "بطاقة صفراء"), "second_yellow": ("Second yellow card", "بطاقة صفراء ثانية"),
                 "red": ("Red card", "بطاقة حمراء")}
        return f"{cards[e.outcome][ar]}: {actor}."
    if kind == "substitution":
        if receiver:
            return f"{receiver} يدخل بدلاً من {actor}." if ar else f"{receiver} comes on for {actor}."
        return f"تبديل: خروج {actor}." if ar else f"Substitution: {actor} goes off."
    if kind in ("tackle", "duel"):
        if kind == "tackle":
            return (f"{actor} ينجح في التدخل." if e.outcome == "won" else f"{actor} لا ينجح في التدخل.") if ar else (
                f"{actor} wins the tackle." if e.outcome == "won" else f"{actor} cannot win the tackle.")
        return (f"{actor} يفوز بالالتحام." if e.outcome == "won" else f"{actor} يخسر الالتحام.") if ar else (
            f"{actor} wins the duel." if e.outcome == "won" else f"{actor} loses the duel.")
    if kind == "foul":
        return (f"{actor} يرتكب مخالفة ضد {receiver}." if receiver else f"مخالفة على {actor}.") if ar else (
            f"{actor} fouls {receiver}." if receiver else f"Foul by {actor}.")
    calls = {
        "period_start": (("The first half gets underway." if e.period == 1 else "The second half gets underway."),
                         ("بداية الشوط الأول." if e.period == 1 else "بداية الشوط الثاني.")),
        "period_end": (("The whistle for half-time." if e.period == 1 else "The final whistle."),
                       ("صافرة نهاية الشوط الأول." if e.period == 1 else "صافرة نهاية المباراة.")),
        "kickoff": (f"{team} get play started.", f"{team} يبدأ اللعب."),
        "carry": (f"{actor} carries the ball.", f"{actor} يتقدم بالكرة."),
        "recovery": (f"{actor} recovers the ball.", f"{actor} يستعيد الكرة."),
        "interception": (f"{actor} intercepts the ball.", f"{actor} يعترض الكرة."),
        "pressure": (f"{actor} applies pressure.", f"{actor} يضغط على حامل الكرة."),
        "save": (f"{actor} makes the save.", f"{actor} يتصدى للتسديدة."),
        "goal": (f"GOAL! {actor} scores for {team}!", f"هدف! {actor} يسجل لصالح {team}!"),
        "corner": (f"Corner to {team}.", f"ركنية لصالح {team}."),
        "free_kick": (f"Free kick to {team}.", f"ركلة حرة لصالح {team}."),
        "throw_in": (f"Throw-in to {team}.", f"رمية تماس لصالح {team}."),
        "goal_kick": (f"Goal kick to {team}.", f"ركلة مرمى لصالح {team}."),
        "possession_change": (f"{team} have possession.", f"الكرة الآن مع {team}."),
    }
    return calls[kind][ar]


def event_commentary(e: SyntheticEvent, meta: MatchMetadata) -> dict:
    """Results air at the end of the recorded action, not before the ball arrives."""
    duration = (e.duration_s or 0) if e.type in ("pass", "carry", "shot") else 0
    return {"show_at_s": min(meta.match_duration_s, round(e.game_time_s + duration, 2)),
            "text": {"en": _describe(e, meta, False), "ar": _describe(e, meta, True)}}
