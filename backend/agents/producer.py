"""Code-only air scheduling: one bilingual overlay per persona per cooldown."""

from dataclasses import dataclass
from typing import Literal, MutableMapping, Sequence

from shared.schemas import Moment

from .names import focus_player
from .templates import LANGUAGES, PERSONAS

LAYOUT = {"beginner": ("lower_third", "lower_third"), "tactical": ("side_panel", "stat_card"),
          "player": ("pitch", "player_tag"), "club": ("lower_third", "lower_third")}


@dataclass(frozen=True)
class AirPlanItem:
    persona: Literal["beginner", "tactical", "player", "club"]
    language: Literal["en", "ar"]
    slot: Literal["lower_third", "side_panel", "pitch"]
    template_id: Literal["lower_third", "stat_card", "player_tag"]
    priority: int
    ttl_s: int = 8
    club_id: str | None = None  # Favorite Club only: whose fans this overlay is written for


def produce(moment: Moment, air_history: MutableMapping[tuple[str, str], int],
            clubs: Sequence[str] = ()) -> list[AirPlanItem]:
    """Air plan for one moment. `clubs` enables the Favorite Club persona (one item per club)."""
    urgent = moment.type in {"goal", "red_card"}
    if moment.importance < 0.5 and not urgent:
        return []
    items = []
    personas = list(PERSONAS) + (["club"] if clubs and moment.team_id in clubs else [])
    for persona in personas:
        if persona == "player" and focus_player(moment) is None:
            continue
        key = moment.match_id, persona
        previous = air_history.get(key)
        if not urgent and previous is not None and moment.game_clock_s - previous < 45:
            continue
        slot, template = LAYOUT[persona]
        for club in (clubs if persona == "club" else (None,)):
            for lang in LANGUAGES:
                items.append(AirPlanItem(persona, lang, slot, template, 1 if urgent else 3, club_id=club))
        # Reserve the air slot synchronously, before any background model call can yield.
        # The workflow must reset this history when a replay starts or seeks.
        air_history[key] = max(previous or 0, moment.game_clock_s)
    return items
