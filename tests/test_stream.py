import asyncio
import time

from shared.schemas import EventEnvelope, MetadataEnvelope

from backend.services.consumer import MatchStateConsumer
from backend.services.stream import LocalBus
from backend.simulator.replay import ReplayController


async def _run(match, speed=0, **kw):
    bus = LocalBus()
    sub = bus.subscribe()
    consumer = MatchStateConsumer()
    task = asyncio.create_task(consumer.consume(sub, stop_when_finished=True))
    ctrl = ReplayController(match.metadata, match.events, match.frames, bus.publisher(), speed=speed, **kw)
    status = await ctrl.run()
    await asyncio.wait_for(task, 10)
    return consumer.states[match.metadata.match_id], status, ctrl


async def test_full_replay_reaches_correct_final_state(derby):
    state, status, _ = await _run(derby)
    assert state.score == {"nile_fc": 2, "delta_utd": 2}
    assert state.events_applied == len(derby.events)
    assert state.duplicates_dropped == 0 and state.gaps_skipped == 0
    assert state.replay_status == "finished"
    assert status["sent"] == len(derby.events) + len(derby.frames) + 3  # metadata + 2 control messages


async def test_start_from_minute_catches_up_state(derby):
    state, _, _ = await _run(derby, start_at_s=64 * 60, include_tracking=False)
    assert state.events_applied == len(derby.events)
    assert state.score == {"nile_fc": 2, "delta_utd": 2}


async def _feed(consumer, match, envs):
    meta = MetadataEnvelope(match_id=match.metadata.match_id, run_id="r1", game_time_s=0, payload=match.metadata)
    await consumer.handle(meta)
    for env in envs:
        await consumer.handle(env)


def _envs(match, run_id="r1", n=300):
    return [EventEnvelope(match_id=match.metadata.match_id, run_id=run_id, game_time_s=e.game_time_s, payload=e)
            for e in match.events[:n]]


async def test_duplicates_are_dropped(derby):
    consumer = MatchStateConsumer()
    envs = _envs(derby)
    await _feed(consumer, derby, envs + envs[:50])
    state = consumer.states["match_001"]
    assert state.events_applied == 300 and state.duplicates_dropped == 50


async def test_out_of_order_events_are_reordered(derby):
    seen = []
    consumer = MatchStateConsumer(on_event=lambda e, s: seen.append(e.seq))
    envs = _envs(derby, n=100)
    shuffled = envs[:10] + envs[12:20] + [envs[11], envs[10]] + envs[20:]
    await _feed(consumer, derby, shuffled)
    assert seen == list(range(1, 101))
    assert consumer.states["match_001"].reordered > 0


async def test_new_run_resets_state(derby):
    consumer = MatchStateConsumer()
    await _feed(consumer, derby, _envs(derby, n=500))
    await consumer.handle(MetadataEnvelope(match_id="match_001", run_id="r2", game_time_s=0, payload=derby.metadata))
    state = consumer.states["match_001"]
    assert state.run_id == "r2" and state.events_applied == 0
    await consumer.handle(_envs(derby, run_id="r1", n=1)[0])  # stale run is ignored
    assert state.events_applied == 0


async def test_paced_replay_respects_speed_and_pause(derby):
    bus = LocalBus()
    ctrl = ReplayController(derby.metadata, derby.events, derby.frames, bus.publisher(), speed=600)
    task = asyncio.create_task(ctrl.run())
    await asyncio.sleep(0.3)                 # ~180 s of game time at 600x
    gt = ctrl.game_time()
    assert 100 < gt < 260
    ctrl.pause()
    frozen = ctrl.game_time()
    await asyncio.sleep(0.2)
    assert ctrl.game_time() == frozen and ctrl.status()["state"] == "paused"
    ctrl.resume()
    ctrl.set_speed(0)                        # finish as fast as possible
    t0 = time.monotonic()
    status = await asyncio.wait_for(task, 20)
    assert status["state"] == "finished" and time.monotonic() - t0 < 20
