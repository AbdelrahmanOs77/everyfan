"""A paced recording must not silently save an unfinished pipeline."""

import asyncio
import json

import pytest

from backend.agents.record_demo import RecordingContext
from backend.api.hub import ViewerHub
from backend.services.budget import DailyTokenBudget
from backend.agents.review_demo import apply_arabic_edits, review_bundle
from backend.agents.names import NameAllowlist
from backend.agents.templates import template_overlays
from backend.api.demo import DemoBundle, fingerprint
from tests.test_agents_templates import ROWS, eval_moment


def test_recording_drain_timeout_rejects_partial_work():
    async def run():
        ctx = RecordingContext(ViewerHub(0), DailyTokenBudget(100))
        task = ctx.spawn(asyncio.sleep(60))
        try:
            with pytest.raises(TimeoutError, match="unfinished"):
                await ctx.drain(timeout=.01)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_recording_drain_waits_for_completion():
    async def run():
        ctx = RecordingContext(ViewerHub(0), DailyTokenBudget(100))
        completed = []

        async def finish():
            await asyncio.sleep(.01)
            completed.append(True)

        ctx.spawn(finish())
        await ctx.drain(timeout=1)
        assert completed and not ctx.status()['background_tasks']
    asyncio.run(run())


@pytest.fixture
def review_sample(derby, tmp_path):
    moment = eval_moment(next(r for r in ROWS if r['match_id'] == 'match_001' and r['moment_id'] == 'mom_044'))
    overlays = template_overlays(moment, NameAllowlist(derby.metadata))
    items = [{'type': 'moment', 'game_time_s': moment.game_clock_s, 'data': moment.model_dump()}]
    items += [{'type': 'overlay', 'game_time_s': o.show_at_s, 'data': o.model_dump()} for o in overlays]
    bundle = DemoBundle('match_001', 'derby_balanced', fingerprint(derby.events), [], items)
    return bundle.save(tmp_path), derby


def test_review_exports_stable_ids_and_rejects_invented_numbers(review_sample):
    path, match = review_sample
    report = review_bundle(path, match, require_complete=False)
    assert report['valid']
    assert 'ov_mom_044_tactical_ar' in path.with_name('arabic_review.txt').read_text(encoding='utf-8')
    raw = json.loads(path.read_text(encoding='utf-8'))
    next(i for i in raw['items'] if i['type'] == 'overlay')['data']['body'] = '999999'
    path.write_text(json.dumps(raw), encoding='utf-8')
    assert any('NUMBER_NOT_IN_EVIDENCE' in error for error in review_bundle(path, match, require_complete=False)['errors'])


def test_arabic_edits_preserve_numbers_names_and_other_fields(review_sample):
    path, match = review_sample
    raw = json.loads(path.read_text(encoding='utf-8'))
    overlay = next(i['data'] for i in raw['items'] if i['type'] == 'overlay' and i['data']['language'] == 'ar')
    edited_body = overlay['body'] + ' '
    changes = {overlay['overlay_id']: {'body': edited_body}}
    apply_arabic_edits(path, match, changes)
    changed = json.loads(path.read_text(encoding='utf-8'))
    actual = next(i['data'] for i in changed['items'] if i['type'] == 'overlay' and i['data']['overlay_id'] == overlay['overlay_id'])
    assert actual == {**overlay, 'body': edited_body}
    saved = path.read_bytes()
    with pytest.raises(ValueError, match='numbers'):
        apply_arabic_edits(path, match, {overlay['overlay_id']: {'body': overlay['body'] + ' 999999'}})
    assert path.read_bytes() == saved
    with pytest.raises(ValueError, match='names'):
        apply_arabic_edits(path, match, {overlay['overlay_id']: {'headline': overlay['headline'].replace('حسن نور', 'لاعب آخر'),
                                                              'body': overlay['body'].replace('حسن نور', 'لاعب آخر')}})
    assert path.read_bytes() == saved


def test_review_rejects_partial_bundle_as_complete(review_sample):
    path, match = review_sample
    report = review_bundle(path, match)
    assert not report['valid'] and any('Incomplete' in error for error in report['errors'])
