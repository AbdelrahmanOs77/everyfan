# Owner C — agents

## Current status

Phase 1 is implemented on `owner-c-phase-1-templates`, based on `ad0f898`.
English and Arabic fallbacks cover all nine Contract B moment types for beginner,
tactical, and player personas. Player overlays require a focus player in metadata.
The plugin subscribes to analytics, processes importance >= 0.5, deduplicates moments
per replay, and invalidates pending overlays when a replay resets.

This phase makes no model calls. `AGENT_MODE=off` is the default. The scaffold
accepts `stub` and `foundry` settings for later phases; both still publish templates
until the model workflow is implemented. Nothing here claims live AI generation.

The existing goal and red-card helpers are reused. Owner C replaces red-card body
text with verified minute and `players_left` facts, adds the missing player persona,
and avoids calculating remaining minutes or assuming a single dismissal.

Phase 2 adds the deterministic verifier, optional budgeted semantic check, and
Break-it helper on `owner-c-phase-2-verifier`. Phases 3–8 are pending, starting
with the MCP evidence server. Per the user's instruction, phases are committed
locally and exported for later team review/merge while GitHub access is unavailable.
The original plan is preserved in [OWNER_C_PLAN.md](OWNER_C_PLAN.md).

## Run locally (PowerShell)

```powershell
$env:PIPELINE_PLUGINS = "backend.analytics.plugin:register,backend.agents.plugin:register"
$env:AGENT_MODE = "off"
.\.venv\py312\Scripts\python.exe -m backend.cli serve
```

On other machines use the Python 3.12 virtual environment created there.
Remove `backend.api.template_plugin:register` from this plugin list to avoid duplicate goals.
No Event Hubs, Cosmos credentials, or Foundry deployment is needed for local playback.

For a disposable demo bundle, leaving committed team bundles intact:

```powershell
.\.venv\py312\Scripts\python.exe -m backend.cli build-demo --all --out .venv/owner-c-demo
```

All moment timestamps and evidence IDs are copied from analytics. Every displayed
measurement comes from `moment.verified_facts`. Arabic display names come from
match metadata. Tactical overlays use a side-panel stat card; player overlays use
a pitch player tag with `fields.player_id`.

## Validation

```powershell
.\.venv\py312\Scripts\python.exe -m pytest -q
.\.venv\py312\Scripts\python.exe -m pyflakes backend shared tests
```

Acceptance tests cover the 107 eval moments, all nine moment types including
player milestones, Arabic names/direction, exact displayed numeric grounding,
stable IDs, duplicate callbacks, stale replay tasks, and a full simulator →
analytics → template → recorded overlay replay. Config validation and the offline
stub interface are also tested. No new runtime dependencies are required.

Validated locally on Python 3.12.13: **181 tests passed**, pyflakes clean.
A deliberately inverted importance threshold was caught by the regression test
and restored before the final passing run. Disposable demo builds finished with
zero plugin errors for every scenario:

| Match | Moments | Overlays |
| --- | ---: | ---: |
| match_001 | 209 | 166 |
| match_002 | 192 | 142 |
| match_003 | 198 | 120 |
| match_004 | 170 | 84 |

Moments below importance 0.5 remain in the analytics feed but are deliberately
skipped by this agent plugin. The 63:03 Hassan Nour goal is `mom_044` in match_001.

## Phase 2 — verifier and Break-it

`verify(draft, brief, moment, names, persona)` is a synchronous, offline check
returning a `Verdict` with `status`, `reason_code`, and `detail`. It checks in order:

1. Contract C, headline/body limits, match/moment identity, persona, timing, language and direction.
2. Numeric grounding in the brief or moment, including numeric card fields and
   numeric strings. Arabic-Indic and Eastern Arabic-Indic digits are normalized.
   Decimal values tolerate 0.05 rounding; integers require exact matches;
   percentages support fraction-to-percent and integer-percent rendering.
   The code-derived display minute is allowed. `fields.generated_ms` and
   `fields.budget_ms` are exempt runtime measurements.
3. Names against metadata, including structured text fields. English detection is
   conservative capitalization plus ordinary football vocabulary. Arabic detection
   uses club cues and likely personal names. This is a heuristic, not comprehensive
   named-entity recognition: lowercase English or unfamiliar Arabic entities can
   evade it, and generated text also requires the semantic check.
4. Evidence IDs within the brief and original moment.
5. Immediately explained beginner jargon and the player persona's focus ID/name.

Reason codes: `TOO_LONG`, `SCHEMA`, `NUMBER_NOT_IN_EVIDENCE`, `UNKNOWN_ENTITY`,
`BAD_EVIDENCE_ID`, `TONE`, `UNSUPPORTED_CAUSALITY`.

`await verify_with_model(..., model=client, budget=ctx.budget)` runs these checks
before the optional semantic model call. It skips that call for StubModel, reserves
tokens before calling, and settles real usage afterwards. Exceptions, malformed
responses, denied budgets, and deadlines reject the draft so the caller can use
fallback. Unknown token usage is conservatively charged to the reservation.
The default semantic deadline is 1 s; the earlier 3.562 s Foundry smoke check means
we must measure/tune live model latency during workflow integration.

Numeric membership alone does not prove that a number is attached to the right
claim or that a causal explanation is supported. Semantic validation complements
these code checks. No verifier result automatically publishes a draft in Phase 2;
the full repair/publish workflow arrives in Phase 5.

For Owner A, the exact handoff is:

```python
from backend.agents.breakit import run_break_it

result = await run_break_it(match_id, moment_id, persona, lang)
# {draft, verdict, repaired_or_fallback_overlay}
```

Defaults are `match_001`, Hassan Nour's goal at 63:03 (`mom_044`), `tactical`, `en`.
The helper loads the match through MatchLibrary and resolves real analytics
evidence. It creates an intentionally corrupted copy, runs the actual verifier,
and returns a verified deterministic template as fallback. It makes no model
calls and never publishes the bad draft. Invalid persona/language or missing
player raises ValueError; unknown match/moment raises KeyError. Owner A can map
these to 422/404 when adding `POST /api/demo/break-it`. No API route was added here.

Phase 2 validation: **336 tests passed** on Python 3.12.13, including 155 verifier
tests; pyflakes clean. The numeric regression tests caught a deliberately inverted
numeric guard before it was restored for the final passing run. A real local
Break-it call rejected `999999` m and returned the original `21` m / `104` km/h /
`2-2` template for `mom_044`. The reviewable JSON example is in the ignored local
file `.venv/handoff/owner-c-break-it.json`. All Phase 2 tests use offline code or
fake models; none call Azure.

## Foundry setup

The `everyfan-ai` project is now provisioned in UAE North, under Foundry resource
`everyfan-ai-resource` in resource group `damlink-ocr-rg`, using Azure for Students.
Subscription quota and the account model catalog were checked before deploying:

| Purpose | Deployment name | Model | Version | SKU / capacity |
| --- | --- | --- | --- | --- |
| Writers | everyfan-fast | gpt-4.1-mini | 2025-04-14 | GlobalStandard / 30 |
| Analyst and semantic verifier | everyfan-strong | gpt-5-mini | 2025-08-07 | GlobalStandard / 10 |

Both deployments report `Succeeded`. Capacity controls rate limits; these are
pay-per-token deployments, with no provisioned throughput purchase.

Project endpoint:
`https://everyfan-ai-resource.services.ai.azure.com/api/projects/everyfan-ai`

Local settings are saved in the ignored `.env`, with `AGENT_MODE=off` until the
Foundry workflow is implemented. No keys or tokens are stored there. Local model
authentication uses the existing Azure CLI login; production managed identity
access still needs coordination with Owner A.

Azure MCP confirmed quota, deployment inventory, and successful English/Arabic
writer output. The checker accepted the verified 104 km/h and rejected a draft
claiming 999 km/h. The Foundry management MCP connector failed authentication, so
deployment operations used the signed-in Azure CLI. Existing resources, roles,
API deployment, and committed demo bundles were not modified.

A bounded Python Responses API smoke request also completed successfully with
the same correct/invented verdicts, using 192 tokens. Its single observed request
time was 3,562 ms, which exceeds the plan's 2.5 s Analyst deadline. This is not a
latency benchmark; the workflow must enforce its deadlines and template fallback,
and compare the fast model for that step before relying on live timing.

For project REST calls, use the `https://ai.azure.com/.default` token scope. The
Cognitive Services token scope returned 401 on this project endpoint. See the
[official SDK/REST quickstart](https://learn.microsoft.com/en-us/azure/foundry/quickstarts/get-started-code).
Never paste credentials into chat or commit them.

## Team handoff (draft; not sent)

For Owner A after Phase 1 merges: the plugin is `backend.agents.plugin:register`,
loaded after `backend.analytics.plugin:register`. Off mode now provides bilingual
templates for all agent-worthy moment types. Replace the old template plugin when
switching to this path so goals are not shown twice. MCP mounting, Break-it, and
the Foundry workflow will arrive in later phases.

For Owner B: Owner C will write its own briefs through the existing Cosmos store
in Phase 5. Cosmos is in Italy North, per the team handoff. We will check for your
numeric-faithfulness evaluator before adding one.

Owner C implementation and tests were developed with Codex.
