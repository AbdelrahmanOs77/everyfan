"""Code-only air scheduling: one bilingual overlay per persona per cooldown."""

from dataclasses import dataclass
from typing import Literal, MutableMapping

from shared.schemas import Moment

from .names import focus_player
from .templates import LANGUAGES, PERSONAS


@dataclass(frozen=True)
class AirPlanItem:
    persona: Literal["beginner", "tactical", "player"]
    language: Literal["en", "ar"]
    slot: Literal["lower_third", "side_panel", "pitch"]
    template_id: Literal["lower_third", "stat_card", "player_tag"]
    priority: int
    ttl_s: int = 8


def produce(moment: Moment, air_history: MutableMapping[tuple[str, str], int]) -> list[AirPlanItem]:
    urgent = moment.type in {"goal", "red_card"}
    if moment.importance < 0.5 and not urgent:
        return []
    items = []
    for persona in PERSONAS:
        if persona == "player" and focus_player(moment) is None:
            continue
        key = moment.match_id, persona
        previous = air_history.get(key)
        if not urgent and previous is not None and moment.game_clock_s - previous < 45:
            continue
        slot, template = {"beginner": ("lower_third", "lower_third"), "tactical": ("side_panel", "stat_card"),
                          "player": ("pitch", "player_tag")}[persona]
        for lang in LANGUAGES:
            items.append(AirPlanItem(persona, lang, slot, template, 1 if urgent else 3))
        # Reserve the air slot synchronously, before any background model call can yield.
        # The workflow must reset this history when a replay starts or seeks.
        air_history[key] = max(previous or 0, moment.game_clock_s)
    return items
