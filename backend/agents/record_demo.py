"""Record a complete, paced Foundry demo without the API's short drain timeout."""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from backend.api.demo import DemoBundle, build_bundle
from backend.api.hub import ViewerHub
from backend.api.library import MatchLibrary
from backend.api.plugins import PipelineContext, load_plugins
from backend.api.settings import ROOT, Settings
from backend.services.budget import DailyTokenBudget

from .templates import ALL_PERSONAS, LANGUAGES

PLUGINS = ['backend.analytics.plugin:register', 'backend.agents.plugin:register']


class RecordingContext(PipelineContext):
    async def drain(self, timeout: float = 14400) -> None:
        """Wait for the whole recording; fail instead of accepting partial output."""
        deadline = time.monotonic() + timeout
        while self.status()['background_tasks']:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Recording has unfinished background tasks')
            await super().drain(timeout=min(30, remaining))
            sources = {}
            for item in self.recording or []:
                if item['type'] == 'overlay':
                    key = item['data']['source'] + '/' + item['data']['verification_status']
                    sources[key] = sources.get(key, 0) + 1
            print(json.dumps({'pending': self.status()['background_tasks'], 'overlays': sources,
                              'charged_tokens': self.budget.used}), flush=True)


async def record(args):
    settings = Settings()
    library = MatchLibrary(settings.data_dir, max_loaded=1)
    match = await library.get('match_001')
    ctx = RecordingContext(ViewerHub(0), DailyTokenBudget(args.token_cap), settings, library)
    load_plugins(ctx, PLUGINS)
    if ctx.loaded_plugins != PLUGINS:
        raise RuntimeError('Required pipeline plugins failed to load')
    started = time.monotonic()
    agents = ctx.agents
    failures = {}
    try:
        await agents.runner.prepare()
        bundle = DemoBundle.load(args.out / 'match_001.bundle.json') if args.recaps_only else await build_bundle(match, ctx)
        bundle.save(args.out)  # Preserve completed overlays before spending tokens on recaps.
        for persona in ALL_PERSONAS:
            for club in ((match.metadata.home.team_id, match.metadata.away.team_id) if persona == 'club' else (None,)):
                for language in LANGUAGES:
                    key = f'{persona}|{language}|{club or ""}'
                    if key in bundle.recaps:
                        continue
                    # Share the recording's token pacing with sequential recap requests.
                    ahead = ctx.budget.used / args.tpm * 60 - (time.monotonic() - started)
                    if ahead > 0:
                        await asyncio.sleep(ahead)
                    recap = await agents.recap(match.metadata, bundle.overlays(), persona=persona,
                                               language=language, club_id=club)
                    if recap.source == 'agent' and recap.verification_status == 'approved':
                        bundle.recaps[key] = {**recap.model_dump(), 'feed_source': 'demo', 'run_id': None}
                        bundle.save(args.out)
                    else:
                        failures[key] = recap.reason_code or 'FALLBACK'
                    print(json.dumps({'recap': key, 'source': recap.source, 'reason': recap.reason_code}), flush=True)
        report = {'mode': agents.config.mode, 'profile': 'relaxed' if args.relaxed else 'live',
                  'budget_ms': round(agents.config.total_timeout_s * 1000), 'counts': bundle.counts(),
                  'overlay_sources': bundle.overlay_sources(), 'recaps': len(bundle.recaps),
                  'recap_failures': failures, 'pipeline_errors': ctx.errors,
                  'charged_tokens': ctx.budget.used, 'outstanding_tokens': ctx.budget.reserved,
                  'seconds': round(time.monotonic() - started, 1)}
        (args.out / 'recording-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report), flush=True)
        return report
    finally:
        pending = list(ctx._tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await agents.runner.aclose()


def main():
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['foundry', 'stub'], default='foundry')
    parser.add_argument('--out', type=Path, default=ROOT / '.venv/demo-agents')
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--relaxed', action='store_true')
    parser.add_argument('--recaps-only', action='store_true')
    parser.add_argument('--advanced-only', action='store_true', help='Add all-match advanced reports, coach notes and Q&A; stub mode only')
    parser.add_argument('--token-cap', type=int, default=3000000)
    parser.add_argument('--tpm', type=int, default=24000)
    args = parser.parse_args()
    if args.advanced_only:
        if args.mode != 'stub':
            parser.error('--advanced-only requires --mode stub (zero Azure calls)')
        from .advanced_demo import record_advanced
        asyncio.run(record_advanced(args.out, args.mode))
        return 0
    if args.tpm <= 0 or args.token_cap <= 0:
        parser.error('Token limits must be positive')
    load_dotenv(ROOT / '.env')
    if args.env_file:
        load_dotenv(args.env_file, override=True)
    os.environ.update(AGENT_MODE=args.mode, AGENT_TOOLS='inprocess', AGENT_BUILD_CONCURRENCY='1',
                      AGENT_BUILD_TPM=str(args.tpm))
    os.environ.setdefault('AGENT_ANALYST_MODEL_ROLE', 'fast')
    os.environ.setdefault('AGENT_VERIFIER_MODEL_ROLE', 'fast')
    if args.relaxed:
        for stage, seconds in [('PRODUCER', 30), ('ANALYST', 30), ('WRITER', 30), ('VERIFIER', 30), ('TOTAL', 120)]:
            os.environ[f'AGENT_{stage}_TIMEOUT_S'] = str(seconds)
    report = asyncio.run(record(args))
    return int(report['pipeline_errors'] != 0 or report['recaps'] != 10)


if __name__ == '__main__':
    raise SystemExit(main())
