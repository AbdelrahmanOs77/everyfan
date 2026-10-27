import asyncio
from types import SimpleNamespace

import pytest

from backend.agents.advanced_demo import pack, unpack
from backend.agents.coach import coach_facts, coach_notes
from backend.agents.feature_writer import FeatureText, feature_verdict
from backend.agents.plugin import AgentsPlugin
from backend.agents.reports import match_report
from backend.analytics.advanced import advanced_stats
from backend.analytics.evidence import MatchEvidence
from tests.test_agents_advanced_stats import event
from tests.test_agents_tracking_metrics import frame, point


def test_report_half_numbers_and_evidence_have_no_future(derby):
    events = [event(1, 10), event(2, 2800, "goal", outcome=None).model_copy(update={"qualifiers": {"home_score": 1, "away_score": 0}})]
    frames = [frame(0, [point("nil_06", "nile_fc", 20)]), frame(6000, [point("nil_06", "nile_fc", 90)])]
    ev = MatchEvidence(derby.metadata, events, frames)
    report = asyncio.run(match_report(ev, "half", 5400))
    past = MatchEvidence(derby.metadata, events[:1], frames[:1])
    other = asyncio.run(match_report(past, "half", 2700))
    assert report["facts"] == other["facts"]
    assert report["evidence"] == other["evidence"]
    assert "evt_00002" not in report["evidence"]["evidence_event_ids"]
    expected = advanced_stats(ev.meta, ev.events, at_s=2700, window_s=2700, cfg=ev.cfg, tracking_index=ev.tracking)
    for team in ev.teams:
        assert report["facts"]["numbers"][team]["half"] == expected["teams"][team]["current"]
    assert report["dir"] == "ltr"
    assert feature_verdict(FeatureText(**report["answer"]), report["facts"], ev.meta, 2700) is None
    arabic = asyncio.run(match_report(ev, "half", 2700, language="ar"))
    assert arabic["dir"] == "rtl"
    assert feature_verdict(FeatureText(**arabic["answer"]), arabic["facts"], ev.meta, 2700) is None
    with pytest.raises(ValueError, match="not available"):
        asyncio.run(match_report(ev, "full", 2700))


def test_coach_ids_hold_time_and_truncated_future_are_stable(derby):
    meta = derby.metadata.model_copy(update={"match_duration_s": 900})
    ids = [p.player_id for p in meta.home.players if p.starter and p.position != "GK"]
    frames = []
    for n in range(1801):
        counts = (4, 4, 2) if n < 600 else (5, 3, 2)
        points, j = [], 0
        for line, count in enumerate(counts):
            for y in range(count):
                points.append(point(ids[j], meta.home.team_id, 20 + line * 25, 5 + y * 10))
                j += 1
        frames.append(frame(n, points))
    events = [event(1, 0, "kickoff", outcome=None)]
    ev = MatchEvidence(meta, events, frames)
    notes = coach_facts(ev)
    changes = [n for n in notes if n["trigger"] == "formation_change" and n["team_id"] == meta.home.team_id]
    assert len(changes) == 1
    assert changes[0]["game_clock_s"] >= 480
    assert changes[0]["facts"]["before_label"] == "4-4-2"
    assert changes[0]["facts"]["after_label"] == "5-3-2"
    past = MatchEvidence(meta, events, frames[:1201])
    assert [n for n in notes if n["game_clock_s"] <= 600] == [n for n in coach_facts(past) if n["game_clock_s"] <= 600]
    for language in ("en", "ar"):
        result = asyncio.run(coach_notes(ev, 900, language))
        assert all(n["source"] == "template" and n["game_clock_s"] <= 900 for n in result)
        assert all(feature_verdict(FeatureText(headline=n["headline"], body=n["body"]), n["facts"], meta, n["game_clock_s"]) is None for n in result)


def test_seek_catchup_suppresses_feature_scheduling():
    plugin = AgentsPlugin.__new__(AgentsPlugin)
    plugin.config = SimpleNamespace(coach_interval_s=30)
    plugin.ctx = SimpleNamespace(recording=None, analytics=SimpleNamespace(catching_up={"m": True}))
    plugin.advanced_ticks = {"m": None}
    calls = []
    plugin._schedule_features = lambda *args: calls.append(args)
    state = SimpleNamespace(match_id="m", game_time_s=1800)
    plugin.on_tracking(SimpleNamespace(match_id="m", game_clock_s=0), state)
    plugin.on_tracking(SimpleNamespace(match_id="m", game_clock_s=300), state)
    assert calls == []
    plugin.ctx.analytics.catching_up["m"] = False
    plugin.on_control(SimpleNamespace(action="seeked"), state)
    plugin.on_tracking(SimpleNamespace(match_id="m", game_clock_s=1800), state)
    assert calls == []
    plugin.on_tracking(SimpleNamespace(match_id="m", game_clock_s=1830), state)
    assert calls == [(state, 1830)]


def test_demo_packing_preserves_repeated_evidence():
    facts = {"evidence_event_ids": [f"evt_{n:05}" for n in range(200)]}
    original = {"a": facts, "b": facts}
    packed = pack(original)
    assert unpack(packed) == original
    assert len(packed["objects"]) < 4


def test_report_cached_half_is_unavailable_before_half_time(derby, monkeypatch, tmp_path):
    from collections import OrderedDict
    from fastapi.testclient import TestClient
    from backend.api.main import create_app
    from tests.test_api import make_settings
    import backend.agents.feature_api as api

    ev = MatchEvidence(derby.metadata, [], [])
    ev.reports = OrderedDict({("half", 0, "beginner", "en", None, "demo"): {"at_s": 2700}})

    async def evidence(*args):
        return ev

    monkeypatch.setattr(api, "get_match_evidence", evidence)
    with TestClient(create_app(make_settings(tmp_path))) as client:
        response = client.get("/api/matches/match_001/report?phase=half&at_s=10")
        assert response.status_code == 422


def test_off_mode_keeps_advanced_work_off_the_commentary_path():
    plugin = AgentsPlugin.__new__(AgentsPlugin)
    plugin.config = SimpleNamespace(mode="off")
    # No context/background scheduler is needed in off mode.
    plugin._schedule_features(SimpleNamespace(match_id="m"), 30)
