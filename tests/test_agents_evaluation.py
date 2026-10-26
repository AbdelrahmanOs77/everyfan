"""Evaluation must expose missing drafts and catch numbers touching Arabic text."""

import asyncio
from types import SimpleNamespace

import pytest

from backend.agents.config import AgentConfig
from backend.agents.llm import StubModel
from backend.agents.names import NameAllowlist
from backend.agents.templates import template_for
from backend.agents.verifier import brief_from_moment, verify
from backend.services.budget import DailyTokenBudget
from evals import run_agent_eval as runner
from evals.numeric_faithfulness import numeric_faithfulness
from tests.test_agents_templates import ROWS, eval_moment


@pytest.mark.parametrize('invented', ['و999999', 'و٩٩٩٩٩٩'])
def test_arabic_adjacent_numbers_are_evaluated_and_rejected(derby, invented):
    row = next(r for r in ROWS if r['match_id'] == 'match_001' and r['moment_id'] == 'mom_044')
    moment = eval_moment(row)
    names = NameAllowlist(derby.metadata)
    draft = template_for(moment, names, 'tactical', 'ar').model_dump()
    draft['body'] += ' ' + invented
    assert numeric_faithfulness(draft['body'], row['facts'], moment.game_clock_s)['score'] == 0
    assert verify(draft, brief_from_moment(moment), moment, names, 'tactical').reason_code == 'NUMBER_NOT_IN_EVIDENCE'
    draft = template_for(moment, names, 'tactical', 'ar').model_dump()
    draft['fields']['display_copy'] = invented
    assert verify(draft, brief_from_moment(moment), moment, names, 'tactical').reason_code == 'NUMBER_NOT_IN_EVIDENCE'


def test_summary_keeps_missing_raw_drafts_out_of_the_raw_denominator():
    base = {'match_id': 'm', 'moment_id': 'a', 'persona': 'tactical', 'language': 'ar',
            'reasons': [], 'injected': False, 'final': 1.0}
    summary = runner.summarise([base | {'raw': 1.0, 'outcome': 'approved'},
                                base | {'raw': None, 'outcome': 'fallback'}], {})
    assert summary['raw_drafts'] == 1 and summary['missing_raw_drafts'] == 1
    assert summary['raw_numeric_faithfulness_pct'] == 100.0
    assert summary['approved_pct'] == summary['fallback_pct'] == 50.0
    unsafe = runner.summarise([base | {'raw': None, 'outcome': 'fallback', 'fallback_checked': False}], {})
    assert not unsafe['all_published_faithful']


def test_eval_records_reproduce_raw_and_final_scores(derby, monkeypatch):
    row = next(r for r in ROWS if r['match_id'] == 'match_001' and r['moment_id'] == 'mom_044')
    moment = eval_moment(row)

    async def analyze(*args, **kwargs):
        return brief_from_moment(moment).model_copy(update={'facts': moment.verified_facts | {'tool_fact': 7}})

    async def get(match_id):
        return SimpleNamespace(metadata=derby.metadata)

    monkeypatch.setattr(runner, 'analyze', analyze)
    records = asyncio.run(runner.eval_moment(row, library=SimpleNamespace(get=get), tools=None,
                                            fast=StubModel(), strong=StubModel(), config=AgentConfig(mode='stub'),
                                            budget=DailyTokenBudget(100000), inject=0, rng=None))
    assert records
    for record in records:
        assert record['facts']['tool_fact'] == 7
        assert record['game_clock_s'] == moment.game_clock_s
        for prefix, score in (('raw_', 'raw'), ('', 'final')):
            text = record[prefix + 'headline'] + '\n' + record[prefix + 'body']
            assert numeric_faithfulness(text, record['facts'], record['game_clock_s'])['score'] == record[score]


def test_usage_reports_success_and_cancelled_calls_separately():
    class Model:
        name = 'offline-fixture'

        async def complete(self, cancel=False):
            if cancel:
                raise asyncio.CancelledError()
            return 'fixture', 7

    async def run():
        measured = runner.MeasuredModel(Model())
        assert await measured.complete() == ('fixture', 7)
        with pytest.raises(asyncio.CancelledError):
            await measured.complete(cancel=True)
        assert measured.requests == 2 and measured.reported_tokens == 7
        assert measured.unknown_usage_calls == 1

    asyncio.run(run())


def test_token_pacing_waits_outside_stage_work(monkeypatch):
    waited = []

    async def sleep(seconds):
        waited.append(seconds)

    monkeypatch.setattr(runner.time, 'monotonic', lambda: 0)
    pacer = runner.TokenPacer(SimpleNamespace(used=12000), 24000)
    monkeypatch.setattr(runner.time, 'monotonic', lambda: 10)
    monkeypatch.setattr(runner.asyncio, 'sleep', sleep)
    asyncio.run(pacer.wait())
    assert waited == [20]


def test_foundry_slot_pacing_uses_only_offline_models(derby, monkeypatch):
    row = next(r for r in ROWS if r['match_id'] == 'match_001' and r['moment_id'] == 'mom_044')
    order = []

    async def analyze(*args, **kwargs):
        order.append('analyst')
        return brief_from_moment(eval_moment(row))

    async def get(match_id):
        return SimpleNamespace(metadata=derby.metadata)

    async def wait():
        order.append('pace')

    monkeypatch.setattr(runner, 'analyze', analyze)
    records = asyncio.run(runner.eval_moment(row, library=SimpleNamespace(get=get), tools=None,
                                            fast=StubModel(), strong=StubModel(), config=AgentConfig(mode='stub'),
                                            budget=DailyTokenBudget(100000), inject=0, rng=None,
                                            pacer=SimpleNamespace(wait=wait)))
    assert order[:2] == ['pace', 'analyst']
    assert order.count('pace') == len(records) + 1
