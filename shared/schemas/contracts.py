"""EveryFan shared data contracts (frozen).

Every service in EveryFan exchanges data through these models. Changing a field
here requires agreement from every owner that consumes it (see README).

Contracts
---------
A   SyntheticEvent    one football event (simulator -> stream -> analytics)
A2  TrackingFrame     player + ball positions at 2 Hz (simulator -> analytics/UI)
B   Moment            significant moment detected by analytics
C   Overlay           approved, timed overlay (also the public feed format)
D   InsightBrief      Analyst agent -> persona writers
E   ScenarioSpec      parameters that drive the simulator
--  MatchMetadata     teams, players, pitch (first message of every stream)
--  StreamEnvelope    wrapper for everything sent over Event Hubs / local bus

Pitch reference frame: 105 x 68 m. Origin (0, 0) is the home team's bottom-left
corner. The home team attacks left -> right (towards x = 105) in BOTH halves; the
away team attacks right -> left. Game clock is continuous seconds: period 1 is
[0, 2700), period 2 is [2700, 5400]. There is no stoppage time.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"

PITCH_LENGTH_M = 105.0
PITCH_WIDTH_M = 68.0
HALF_DURATION_S = 2700
MATCH_DURATION_S = 5400

X = Annotated[float, Field(ge=0.0, le=PITCH_LENGTH_M)]
Y = Annotated[float, Field(ge=0.0, le=PITCH_WIDTH_M)]
Unit = Annotated[float, Field(ge=0.0, le=1.0)]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Open(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Match metadata
# ---------------------------------------------------------------------------

Position = Literal["GK", "RB", "CB", "LB", "DM", "CM", "AM", "RW", "LW", "ST"]


class PlayerInfo(_Frozen):
    player_id: str = Field(examples=["nil_07"])
    team_id: str
    name: str
    short_name: str
    name_ar: str | None = None
    shirt_number: int = Field(ge=1, le=99)
    position: Position
    starter: bool


class TeamInfo(_Frozen):
    team_id: str = Field(examples=["nile_fc"])
    name: str
    short_name: str = Field(max_length=4)
    name_ar: str | None = None
    side: Literal["home", "away"]
    formation: str = Field(examples=["4-3-3"])
    primary_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    secondary_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    players: list[PlayerInfo]


class MatchMetadata(_Frozen):
    schema_version: str = SCHEMA_VERSION
    match_id: str
    scenario_id: str
    seed: int
    competition: str
    venue: str
    pitch_length_m: float = PITCH_LENGTH_M
    pitch_width_m: float = PITCH_WIDTH_M
    period_starts_s: list[int] = [0, HALF_DURATION_S]
    match_duration_s: int = MATCH_DURATION_S
    home: TeamInfo
    away: TeamInfo
    synthetic: Literal[True] = True


# ---------------------------------------------------------------------------
# Contract A - synthetic event
# ---------------------------------------------------------------------------

EventType = Literal[
    "period_start",
    "period_end",
    "kickoff",
    "pass",
    "carry",
    "recovery",
    "tackle",
    "interception",
    "duel",
    "pressure",
    "shot",
    "save",
    "goal",
    "foul",
    "card",
    "substitution",
    "corner",
    "free_kick",
    "throw_in",
    "goal_kick",
    "possession_change",
]

# Outcome vocabulary per event type (validated below).
OUTCOMES: dict[str, set[str]] = {
    "pass": {"completed", "intercepted", "out"},
    "carry": {"completed"},
    "shot": {"goal", "saved", "off_target", "blocked", "post"},
    "tackle": {"won", "lost"},
    "duel": {"won", "lost"},
    "card": {"yellow", "second_yellow", "red"},
}


class SyntheticEvent(_Frozen):
    """Contract A. Immutable. `seq` is the total order within a match."""

    schema_version: str = SCHEMA_VERSION
    event_id: str = Field(pattern=r"^evt_\d{5}$", examples=["evt_00042"])
    match_id: str
    seq: int = Field(ge=1)
    game_clock_s: int = Field(ge=0, le=MATCH_DURATION_S)
    game_time_s: float = Field(ge=0.0, le=MATCH_DURATION_S, description="Precise time; game_clock_s = floor(game_time_s)")
    period: Literal[1, 2]
    type: EventType
    team_id: str | None = None
    player_id: str | None = None
    receiver_id: str | None = None
    start_x_m: X | None = None
    start_y_m: Y | None = None
    end_x_m: X | None = None
    end_y_m: Y | None = None
    duration_s: float | None = Field(default=None, ge=0.0)
    pressure_level: Unit | None = None
    outcome: str | None = None
    # Ball samples every 0.1 s during passes, carries and shots: [t_rel_s, x_m, y_m].
    ball_path: list[tuple[float, float, float]] | None = None
    related_event_id: str | None = None
    qualifiers: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> "SyntheticEvent":
        allowed = OUTCOMES.get(self.type)
        if allowed is not None and self.outcome not in allowed:
            raise ValueError(f"outcome {self.outcome!r} not allowed for {self.type}")
        if self.type not in ("period_start", "period_end") and self.team_id is None:
            raise ValueError(f"{self.type} event needs team_id")
        return self


# ---------------------------------------------------------------------------
# Contract A2 - tracking frame (2 Hz)
# ---------------------------------------------------------------------------


class BallPosition(_Frozen):
    x_m: float
    y_m: float


class PlayerPosition(_Frozen):
    player_id: str
    team_id: str
    x_m: X
    y_m: Y


class TrackingFrame(_Frozen):
    schema_version: str = SCHEMA_VERSION
    match_id: str
    frame: int = Field(ge=0)
    game_clock_s: float = Field(ge=0.0, le=MATCH_DURATION_S)
    period: Literal[1, 2]
    ball: BallPosition
    players: list[PlayerPosition]


# ---------------------------------------------------------------------------
# Contract B - detected moment (owner B)
# ---------------------------------------------------------------------------

MomentType = Literal[
    "goal",
    "big_chance",
    "momentum_shift",
    "pressing_shift",
    "control_to_chaos",
    "rhythm_change",
    "killer_pass",
    "player_milestone",
    "red_card",
]

FactValue = Union[int, float, str, bool]


class Moment(_Frozen):
    schema_version: str = SCHEMA_VERSION
    moment_id: str = Field(pattern=r"^mom_\d{3,}$")
    match_id: str
    game_clock_s: int = Field(ge=0, le=MATCH_DURATION_S)
    type: MomentType
    importance: Unit
    team_id: str | None = None
    player_id: str | None = None
    evidence_event_ids: list[str] = Field(min_length=1)
    verified_facts: dict[str, FactValue]
    rule_id: str


# ---------------------------------------------------------------------------
# Contract D - insight brief (Analyst agent -> persona writers, owner C)
# ---------------------------------------------------------------------------

Persona = Literal["beginner", "tactical", "player", "club", "metric"]


class InsightBrief(_Frozen):
    schema_version: str = SCHEMA_VERSION
    moment_id: str
    match_id: str
    claim: str = Field(max_length=240)
    facts: dict[str, FactValue]
    evidence_event_ids: list[str] = Field(min_length=1)
    focus_player_id: str | None = None
    confidence: Literal["high", "medium", "low"]
    target_personas: list[Persona]


# ---------------------------------------------------------------------------
# Contract C - approved overlay (also the public feed format, owner C/D)
# ---------------------------------------------------------------------------


class Overlay(_Frozen):
    schema_version: str = SCHEMA_VERSION
    overlay_id: str
    moment_id: str
    match_id: str
    persona: Persona
    language: str = Field(pattern=r"^[a-z]{2}(-[A-Z]{2})?$", examples=["en", "ar"])
    dir: Literal["ltr", "rtl"]
    template_id: Literal["lower_third", "stat_card", "player_tag", "score_bug_note"]
    slot: Literal["lower_third", "top_left", "top_right", "pitch", "side_panel"]
    priority: int = Field(ge=1, le=5)
    headline: str = Field(max_length=60)
    body: str = Field(max_length=160)
    fields: dict[str, FactValue] = Field(default_factory=dict)
    evidence_event_ids: list[str] = Field(min_length=1)
    show_at_s: int = Field(ge=0, le=MATCH_DURATION_S)
    ttl_s: int = Field(ge=1, le=60)
    verification_status: Literal["approved", "rejected", "fallback"]
    source: Literal["agent", "template"]
    trace_id: str | None = None
    model: str | None = None
    prompt_version: str | None = None


# ---------------------------------------------------------------------------
# Contract E - scenario spec (drives the simulator)
# ---------------------------------------------------------------------------


class TeamParams(_Open):
    team_id: str
    strength: Unit = 0.5          # passing quality, retention, chance creation
    press_intensity: Unit = 0.5   # how high and hard the team presses
    tempo: Annotated[float, Field(ge=0.5, le=2.0)] = 1.0  # >1 = faster ball circulation


class Phase(_Open):
    """A window where one team's parameters change (momentum swings, press spells)."""

    from_minute: Annotated[float, Field(ge=0, le=90)]
    to_minute: Annotated[float, Field(ge=0, le=90)]
    team_id: str
    strength_delta: Annotated[float, Field(ge=-0.5, le=0.5)] = 0.0
    press_intensity: Unit | None = None
    tempo: Annotated[float, Field(ge=0.5, le=2.0)] | None = None
    label: str | None = None

    @model_validator(mode="after")
    def _order(self) -> "Phase":
        if self.to_minute <= self.from_minute:
            raise ValueError("to_minute must be after from_minute")
        return self


class ForcedEvent(_Open):
    minute: Annotated[float, Field(ge=1, le=88.5)]
    type: Literal["goal", "red_card", "yellow_card", "big_chance"]
    team_id: str
    player_id: str | None = None
    shot_speed_kmh: Annotated[float, Field(ge=40, le=125)] | None = None

    @model_validator(mode="after")
    def _not_at_half_time(self) -> "ForcedEvent":
        if 43.5 < self.minute < 46.5:
            raise ValueError("forced events cannot be scheduled between 43.5' and 46.5'")
        return self


class ScenarioSpec(_Open):
    schema_version: str = SCHEMA_VERSION
    scenario_id: str = Field(pattern=r"^[a-z0-9_]+$")
    match_id: str
    title: str
    description: str
    seed: int = Field(ge=0)
    home: TeamParams
    away: TeamParams
    phases: list[Phase] = Field(default_factory=list)
    forced_events: list[ForcedEvent] = Field(default_factory=list)
    allow_organic_goals: bool = False
    substitutions: bool = True

    @model_validator(mode="after")
    def _teams(self) -> "ScenarioSpec":
        ids = {self.home.team_id, self.away.team_id}
        if len(ids) != 2:
            raise ValueError("home and away must be different teams")
        for item in [*self.phases, *self.forced_events]:
            if item.team_id not in ids:
                raise ValueError(f"unknown team_id {item.team_id!r}")
        return self


# ---------------------------------------------------------------------------
# Stream envelope (Event Hubs / local bus message body)
# ---------------------------------------------------------------------------


class ControlMessage(_Frozen):
    action: Literal["run_started", "paused", "resumed", "speed_changed", "run_finished", "seeked"]
    speed: float | None = None
    detail: str | None = None


class _EnvelopeBase(_Frozen):
    schema_version: str = SCHEMA_VERSION
    match_id: str
    run_id: str = Field(description="Unique per replay run; consumers reset state on a new run_id")
    game_time_s: float = Field(ge=0.0, description="Precise game time used for ordering and pacing")


class MetadataEnvelope(_EnvelopeBase):
    kind: Literal["metadata"] = "metadata"
    payload: MatchMetadata


class EventEnvelope(_EnvelopeBase):
    kind: Literal["event"] = "event"
    payload: SyntheticEvent


class TrackingEnvelope(_EnvelopeBase):
    kind: Literal["tracking"] = "tracking"
    payload: TrackingFrame


class ControlEnvelope(_EnvelopeBase):
    kind: Literal["control"] = "control"
    payload: ControlMessage


StreamEnvelope = Annotated[
    Union[MetadataEnvelope, EventEnvelope, TrackingEnvelope, ControlEnvelope],
    Field(discriminator="kind"),
]
