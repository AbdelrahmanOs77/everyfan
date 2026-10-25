"""Metadata is the sole source of display names in either language."""

from backend.api.template_plugin import _Names
from shared.schemas import Moment


class NameAllowlist(_Names):
    @property
    def allowed(self) -> frozenset[str]:
        return frozenset(name for entity in [*self.players.values(), *self.teams.values()]
                         for name in (entity.name, entity.short_name, entity.name_ar) if name)


def focus_player(moment: Moment) -> str | None:
    if moment.player_id:
        return moment.player_id
    for key in ("scorer_id", "player_id", "passer_id", "shooter_id"):
        value = moment.verified_facts.get(key)
        if isinstance(value, str):
            return value
    return None
