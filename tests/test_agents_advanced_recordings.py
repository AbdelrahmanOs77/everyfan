from pathlib import Path

from backend.agents.advanced_demo import unpack
from backend.api.demo import DemoBundle, fingerprint


def test_all_four_advanced_bundles_preserve_identity_and_bound_evidence(matches):
    for match in matches.values():
        bundle = DemoBundle.load(Path("demo") / f"{match.metadata.match_id}.bundle.json")
        assert bundle.fingerprint == fingerprint(match.events)
        data = unpack(bundle.advanced)
        assert data["recording_mode"] == "stub"
        assert len(data["reports"]) == 20
        assert len(data["questions"]) == 144
        assert len(data["coach_notes"]) == 10
        times = {e.event_id: e.game_time_s for e in match.events}
        for report in data["reports"].values():
            at = report["at_s"]
            assert at in (2700, 5400)
            assert all(times[eid] <= at for eid in report["evidence"]["evidence_event_ids"])
            assert report["evidence"]["frame_range"]["to_s"] <= at
        for item in data["questions"]:
            result, at = item["response"], item["request"]["at_s"]
            assert all(times[eid] <= at for eid in result["evidence_event_ids"])
            assert all(r["to_s"] <= at for r in result["frame_ranges"])
        for notes in data["coach_notes"].values():
            assert len({n["note_id"] for n in notes}) == len(notes)
            for note in notes:
                assert all(times[eid] <= note["game_clock_s"] for eid in note["evidence"]["evidence_event_ids"])
                assert note["evidence"]["frame_range"]["to_s"] <= note["game_clock_s"]
