# Owner C — ship the approved recorded demo

Runbook Step 4c promotes the reviewed Foundry recording to
`demo/match_001.bundle.json`. The user's native Arabic approval applies to SHA-256
`df33a43d026ec893ec31160b7eb6a70d13a57ed7c8aff977f853ba03cc3fa768`;
the local shipping copy has that exact hash. Git normalizes its CRLF line endings
to LF, so the committed artifact has SHA-256
`31ff7dc77665ef4b7d5082655c8913d82212850937fc78dd35ad33a37a2b94c6`.
Both the complete parsed JSON and the source bytes after line-ending
normalization match the committed artifact exactly. Recording and review results
are in `OWNER_C_STEP4.md`.

## Shipping change

- Branch: `codex/owner-c-phase-7-ship-demo`, based on the prior local recording
  commits and the team's merged integration.
- The cached demo contains 209 moments, 218 overlays (146 `agent/approved`,
  72 checked `template/fallback`) and ten `agent/approved` recaps.
- Recording/review tools, the bounded recap prompt and their tests accompany the
  artifact so reviewers can reproduce its preparation.
- The integration recap test explicitly clears only its in-memory recap cache
  to continue exercising deterministic fallback. Owner C's shipping test checks
  that all ten stored agent recaps are returned unchanged with inference off.
- No credentials, private environment files or deployment tokens are included.

## Verification

The shipping bundle passed the evidence, contract, provenance, Arabic and
completeness checks. The local API, with `AGENT_MODE=off`, reports the expected
agent sources and ten recaps, serves all 218 overlays, and returns every cached
recap with its reviewed wording and correct language direction. Reports remain
Git-ignored in `.venv/handoff/step4c-verification/`.

Required gates passed using `.venv/py312/Scripts/python.exe`: 566 offline pytest
tests, Pyflakes for `backend shared tests evals`, and the offline stub evaluation
with 30% injected invented numbers. The stub evaluation reached 100% published
numeric faithfulness; it is not a Foundry quality score.

The shipping regression check failed as expected with the old template-only
bundle. The approved file was restored and its hash rechecked before the full
green suite. The LF-normalized Git artifact also passed the bundle evidence
checks before pushing.

## Owner A merge and deployment checklist

1. Review this branch's pull request and merge only after GitHub CI passes.
2. Wait for the `image` workflow on the merged `main` commit. Use its published
   immutable image tag: `ghcr.io/abdelrahmanos77/everyfan-backend:<merge-sha12>`.
   The Dockerfile already copies `demo/` into `/app/demo`; no new runtime model
   calls or recording-time timeout overrides are needed for cached playback.
3. Save the currently deployed image tag for rollback. The public API baseline
   checked before this handoff reported version `0f6746035f9a`, 218 template
   fallbacks and zero cached recaps for `match_001`.
4. From Owner A's deployment checkout and authenticated Azure account, use the
   existing `deployment/update-image.ps1 -Image <published-image-tag>` procedure
   in `DEPLOYMENT.md`, with the project virtual environment active.
5. Verify the deployed `/api/health` returns `status: ok`, the new version,
   `pipeline.errors: 0`, and the following `demo_bundles` entry:

   ```json
   {
     "match_id": "match_001",
     "stale": false,
     "overlay_sources": {"agent/approved": 146, "template/fallback": 72},
     "recaps": 10
   }
   ```

6. Run the existing deployment smoke check. Check the demo overlay feed and an
   Arabic recap with `source=demo`; confirm RTL wording and cached agent
   provenance. Cached demo success does not establish live-model latency or
   Foundry tracing readiness.

If the new revision is unhealthy, the bundle is stale, or agent sources/recaps
are missing, redeploy the saved previous immutable image with the same update
script and confirm health and smoke checks recover. Do not rotate keys or change
Foundry quota to ship this cached artifact.

Owner A's merge, image build and Azure deployment remain pending. Step 4c is
complete only after the deployed health check meets the criteria above.
