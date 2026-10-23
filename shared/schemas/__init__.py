"""EveryFan shared contracts. Import from here, not from the module directly."""

from pydantic import TypeAdapter

from .contracts import (
    HALF_DURATION_S,
    MATCH_DURATION_S,
    PITCH_LENGTH_M,
    PITCH_WIDTH_M,
    SCHEMA_VERSION,
    BallPosition,
    ControlEnvelope,
    ControlMessage,
    EventEnvelope,
    ForcedEvent,
    InsightBrief,
    MatchMetadata,
    MetadataEnvelope,
    Moment,
    Overlay,
    Phase,
    PlayerInfo,
    PlayerPosition,
    ScenarioSpec,
    StreamEnvelope,
    SyntheticEvent,
    TeamInfo,
    TeamParams,
    TrackingEnvelope,
    TrackingFrame,
)

envelope_adapter: TypeAdapter = TypeAdapter(StreamEnvelope)


def parse_envelope(data: bytes | str):
    """Parse and validate one stream message (JSON) into a typed envelope."""
    return envelope_adapter.validate_json(data)


def dump_envelope(envelope) -> str:
    return envelope.model_dump_json(exclude_none=True)


__all__ = [
    "HALF_DURATION_S",
    "MATCH_DURATION_S",
    "PITCH_LENGTH_M",
    "PITCH_WIDTH_M",
    "SCHEMA_VERSION",
    "BallPosition",
    "ControlEnvelope",
    "ControlMessage",
    "EventEnvelope",
    "ForcedEvent",
    "InsightBrief",
    "MatchMetadata",
    "MetadataEnvelope",
    "Moment",
    "Overlay",
    "Phase",
    "PlayerInfo",
    "PlayerPosition",
    "ScenarioSpec",
    "StreamEnvelope",
    "SyntheticEvent",
    "TeamInfo",
    "TeamParams",
    "TrackingEnvelope",
    "TrackingFrame",
    "envelope_adapter",
    "parse_envelope",
    "dump_envelope",
]
