import pytest
from pydantic import ValidationError

from shared.schemas import (
    ControlEnvelope,
    ControlMessage,
    EventEnvelope,
    ForcedEvent,
    Overlay,
    ScenarioSpec,
    SyntheticEvent,
    dump_envelope,
    parse_envelope,
)

BASE = dict(event_id="evt_00042", match_id="match_001", seq=42, game_clock_s=4032, game_time_s=4032.4,
            period=2, type="pass", team_id="nile_fc", player_id="nil_07", receiver_id="nil_09",
            start_x_m=36.0, start_y_m=24.0, end_x_m=65.0, end_y_m=38.0, duration_s=1.3,
            pressure_level=0.8, outcome="completed")


def test_contract_a_example_is_valid():
    e = SyntheticEvent(**BASE)
    assert e.outcome == "completed"


@pytest.mark.parametrize("change", [
    {"outcome": "goal"},              # not a pass outcome
    {"start_x_m": 106.0},             # off the pitch
    {"pressure_level": 1.5},          # out of range
    {"event_id": "42"},               # wrong id format
    {"team_id": None},                # pass needs a team
    {"unknown_field": 1},             # contracts are closed
])
def test_contract_a_rejects_bad_events(change):
    with pytest.raises(ValidationError):
        SyntheticEvent(**{**BASE, **change})


def test_events_are_immutable():
    e = SyntheticEvent(**BASE)
    with pytest.raises(ValidationError):
        e.outcome = "intercepted"


def test_envelope_round_trip():
    env = EventEnvelope(match_id="match_001", run_id="run_x", game_time_s=4032.4, payload=SyntheticEvent(**BASE))
    back = parse_envelope(dump_envelope(env))
    assert back == env and back.kind == "event"
    ctrl = ControlEnvelope(match_id="m", run_id="r", game_time_s=0, payload=ControlMessage(action="paused"))
    assert parse_envelope(dump_envelope(ctrl)).payload.action == "paused"


def test_scenario_rejects_unknown_team_and_half_time_events():
    with pytest.raises(ValidationError):
        ScenarioSpec(scenario_id="x", match_id="m", title="t", description="d", seed=1,
                     home={"team_id": "nile_fc"}, away={"team_id": "delta_utd"},
                     forced_events=[{"minute": 10, "type": "goal", "team_id": "ghost_fc"}])
    with pytest.raises(ValidationError):
        ForcedEvent(minute=45, type="goal", team_id="nile_fc")


def test_overlay_limits():
    ok = dict(overlay_id="ov_1", moment_id="mom_012", match_id="m", persona="tactical", language="ar", dir="rtl",
              template_id="stat_card", slot="lower_third", priority=2, headline="h", body="b",
              evidence_event_ids=["evt_00001"], show_at_s=10, ttl_s=7, verification_status="approved",
              source="agent")
    Overlay(**ok)
    with pytest.raises(ValidationError):
        Overlay(**{**ok, "headline": "x" * 61})
