"""Routine commentary is literal source-event narration, never a model call."""

import pytest
from fastapi.testclient import TestClient

from backend.api.feed import event_msg
from backend.api.hub import Channel, message
from backend.services.consumer import MatchState
from shared.schemas import SyntheticEvent
from tests.test_agents_advanced_stats import event


def test_completed_pass_names_both_players_in_each_language_and_waits_for_ball(derby):
    from backend.agents.play_by_play import event_commentary

    e = event(1, 10).model_copy(update={"duration_s": 2.5})
    line = event_commentary(e, derby.metadata)
    assert line["show_at_s"] == 12.5
    players = {p.player_id: p for p in derby.metadata.home.players}
    for lang, name in (("en", "name"), ("ar", "name_ar")):
        assert getattr(players[e.player_id], name) in line["text"][lang]
        assert getattr(players[e.receiver_id], name) in line["text"][lang]


@pytest.mark.parametrize("kind,outcome", [
    ("period_start", None), ("period_end", None), ("kickoff", None),
    ("pass", "completed"), ("pass", "intercepted"), ("pass", "out"),
    ("carry", "completed"), ("recovery", None), ("tackle", "won"), ("tackle", "lost"),
    ("interception", None), ("duel", "won"), ("duel", "lost"), ("pressure", None),
    ("shot", "goal"), ("shot", "saved"), ("shot", "off_target"), ("shot", "blocked"), ("shot", "post"),
    ("save", None), ("goal", None), ("foul", None), ("card", "yellow"), ("card", "red"),
    ("card", "second_yellow"), ("substitution", None), ("corner", None), ("free_kick", None),
    ("throw_in", None), ("goal_kick", None), ("possession_change", None),
])
def test_every_supported_action_has_bilingual_commentary_without_numbers(derby, kind, outcome):
    from backend.agents.play_by_play import event_commentary

    e = event(1, 10, kind=kind, outcome=outcome)
    line = event_commentary(e, derby.metadata)
    assert line["show_at_s"] == 10
    assert all(isinstance(line["text"][lang], str) and line["text"][lang] for lang in ("en", "ar"))
    assert not any(c.isdigit() for text in line["text"].values() for c in text)


def test_failed_passes_and_shots_report_only_the_recorded_outcome(derby):
    from backend.agents.play_by_play import event_commentary

    out = event_commentary(event(1, 10, outcome="out"), derby.metadata)["text"]["en"]
    assert "out of play" in out
    assert "throw-in" not in out  # Wait for the actual restart event to name it.
    cut = event_commentary(event(2, 10, outcome="intercepted"), derby.metadata)["text"]["en"]
    assert "cut out" in cut
    shot = event_commentary(event(3, 10, kind="shot", outcome="off_target"), derby.metadata)["text"]["en"]
    assert "off target" in shot


def test_substitution_does_not_reverse_incoming_and_outgoing_players(derby):
    from backend.agents.play_by_play import event_commentary

    e = event(1, 10, kind="substitution", outcome=None)
    line = event_commentary(e, derby.metadata)["text"]["en"]
    assert "comes on for" in line
    players = {p.player_id: p for p in derby.metadata.home.players}
    assert line.index(players[e.receiver_id].name) < line.index(players[e.player_id].name)


def test_optional_names_are_safe_and_duration_never_runs_beyond_full_time(derby):
    from backend.agents.play_by_play import event_commentary

    e = event(1, 5399).model_copy(update={"player_id": None, "receiver_id": None, "duration_s": 5})
    line = event_commentary(e, derby.metadata)
    assert line["show_at_s"] == 5400
    assert "None" not in str(line)
    assert "undefined" not in str(line)


def test_viewer_annotation_leaves_the_frozen_event_data_unchanged(derby):
    e = event(1, 10)
    state = MatchState.new(derby.metadata, "run-test")
    msg = event_msg(e, state)
    assert msg["data"] == e.model_dump(exclude_none=True)
    assert SyntheticEvent.model_validate(msg["data"]) == e
    assert msg["commentary"]["text"]["en"]


def test_late_joiner_gets_only_delivered_recent_actions_from_current_run():
    channel = Channel("match_001", delay_s=0)
    for seq in range(70):
        channel.publish(message("event", "match_001", "r1", seq, {"event_id": f"evt_{seq:05}"}))
    actions = [m for m in channel.snapshot_messages() if m["type"] == "event"]
    assert len(actions) == 50
    assert actions[0]["game_time_s"] == 20
    channel.publish(message("reset", "match_001", "r2", 0, {"reason": "seek"}))
    assert not [m for m in channel.snapshot_messages() if m["type"] == "event"]


@pytest.mark.parametrize("mode", ["demo", "live"])
def test_existing_demo_and_live_sockets_include_routine_commentary(tmp_path, monkeypatch, mode):
    from backend.api.main import create_app
    from tests.test_api import make_settings, collect

    monkeypatch.setenv("AGENT_MODE", "off")
    with TestClient(create_app(make_settings(tmp_path, broadcast_delay_s=0))) as client:
        if mode == "live":
            assert client.post("/api/matches/match_001/start", params={"speed": 20}).status_code == 200
        route = f"/ws/{'demo' if mode == 'demo' else 'matches'}/match_001?tracking_hz=0"
        with client.websocket_connect(route) as ws:
            messages = collect(ws, lambda got: any(m["type"] == "event" and m["data"]["type"] == "pass" for m in got))
        passes = [m for m in messages if m["type"] == "event" and m["data"]["type"] == "pass"]
        assert passes[0]["commentary"]["show_at_s"] >= passes[0]["game_time_s"]
        assert passes[0]["commentary"]["text"]["ar"]
