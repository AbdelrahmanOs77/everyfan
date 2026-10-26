# Owner C go-live plan

Prepared 26 October 2026. The user approved this plan, completed Owner C's Foundry
preparation in Step 3, then explicitly requested Steps 4a and 4b. The real-agent
demo recording and AI Arabic editorial review are complete; human native-speaker
signoff remains pending. See `docs/OWNER_C_STEP4.md` for results and artifacts.
Evaluation work beyond the required offline gate is deferred.

## Previous checkpoint: Step 3 Owner C

- The team's integration is merged at `0f67460`; the local go-live branch now
  starts from that commit. Existing reports are preserved.
- Both existing Foundry deployments report `Succeeded` and passed real,
  key-authenticated inference checks.
- Existing KEY 1 and the required Foundry settings were saved to a Git-ignored
  private handoff file. No key was regenerated or sent to another person.
- The deployed API reports version `0f6746035f9a`, `agents.loaded=false`, and no
  approved agent overlays in the current live feed. Step 3d depends on Owner A
  enabling integration in Step 3c.
- See `docs/OWNER_C_STEP3.md` for the non-secret handoff and verification status.

The sections below preserve the wider plan and its original audit; they do not
describe additional implementation authorized by the latest narrowed request.

## Sources and current position

- New scope: `D:/Downloads/EveryFan go-live runbook.pdf`, especially steps 3a,
  3d, 4a–4c, 5a and Owner C's documentation contribution in 5b.
- Preserve the phase order in `docs/OWNER_C_PLAN.md` and the repository ownership
  boundaries in `AGENTS.md`.
- Current branch: `codex/owner-c-phase-6-tracing`, implementation commit `142be34`.
- Phases 1–6 already have implementation; actual Azure trace ingestion remains
  unverified. Preserve the existing untracked `OWNER_C_PROGRESS_REPORT.md`.
- The runbook describes a newer integration snapshot. This checkout lacks
  `deployment/build-demo-agents.ps1`, `evals/run_agent_eval.py`, Foundry key
  authentication, `McpEvidenceTools`, and recap implementation. Do not pretend
  those commands already work or rebuild Owner A/B integration code blindly.
- Azure MCP reconnection succeeded: the recorded Azure for Students subscription
  is enabled. The Foundry extension verified `everyfan-ai-resource` in UAE North
  and `Succeeded` provisioning for `everyfan-fast` and `everyfan-strong`.
  The separate Foundry management router still fails authentication. Runtime
  inference, available quota and Azure trace ingestion remain unverified.

## Proposed implementation choices

Keep Python 3.12, the existing pinned Agent Framework/Foundry integration and
existing configured fast/strong deployments. Check current official Python
samples before changing SDK imports. Preserve evidence verification, bounded
repair, deadlines, budget settlement, templates, and offline/stub tests.

Use the newer integration patch/repository as a prerequisite if available.
Otherwise identify the minimum Owner C additions and present the cross-owner
dependencies explicitly. Do not edit Owner A/B files beyond the already permitted
guarded MCP mount, and do not edit frozen contracts.

## Tasks and acceptance criteria

### 1. Reconcile the integration prerequisite

- [ ] Obtain or locate the integration patch/newer checkout and compare it with
  the current local commits before applying anything.
- [ ] Identify existing Owner C implementations, missing Owner C pieces, and
  changes that must remain with Owners A/B.
- [ ] Resolve the runbook's ten-recap target against the integrated persona
  support; the current pipeline implements three core personas.

Verification: a file-level gap list and applicable phase branches; no frozen
schema or prohibited owner changes. Dependency: none.

### 2. Verify Foundry and complete the tracing checkpoint

- [x] Restore Azure MCP subscription access and verify the configured resource
  and deployment provisioning through the Foundry extension.
- [ ] Verify available quota, inference access and any management-router access
  needed for the remaining work.
- [ ] Support or verify the agreed cross-account key authentication path alongside
  local credential authentication, using current official SDK documentation.
- [ ] Verify an approved live overlay and correlate its trace with Application
  Insights after Owner A enables integration; document access dependencies.

Verification: offline authentication-path tests, a separately labelled live
check, and actual Azure trace evidence when accessible. Do not retrieve or print
keys in chat, rotate keys, or send messages to teammates. Prepare a private
handoff checklist for the user. Dependency: task 1; Owner A integration for cloud
overlay/trace verification.

### 3. Phase 7: record the real-agent demo

- [ ] Verify or implement the Owner C recorder support required for `match_001`,
  with quota pacing, bounded spending and trustworthy usage/error reporting.
- [ ] Generate a disposable bundle under `.venv/demo-agents/`; measure approved
  agent output versus fallback output, errors and recap completeness.
- [ ] Preserve production latency limits. If a relaxed recording profile is
  needed, label its budget and measured latency explicitly.

Verification: valid contracts, evidence-grounded overlays/recaps, actual source
counts and zero recording errors. Do not substitute stub output for Foundry
evidence. Dependency: tasks 1–2 and the required integration/recap support.

### 4. Review and package the demo

- [ ] Export Arabic text with stable overlay identifiers and timestamps for native
  review; preserve metadata names and `dir="rtl"`.
- [ ] Apply reviewer wording corrections and rerun verification on the edited
  bundle before staging the shipping artifact.
- [ ] Prepare the demo commit/patch and Owner A deployment checklist. Use the
  authorized local patch workflow if GitHub write access remains unavailable.

Verification: bundle checks, targeted API/integration checks available in the
integrated checkout, and the required full checks. Human Arabic review remains
an explicit prerequisite to claiming that review is complete. Dependency: task 3.

### 5. Phase 8: evaluate and document

- [ ] Verify or implement `evals/run_agent_eval.py` without duplicating Owner B's
  evaluator. Report raw writer numeric faithfulness before verification and
  published faithfulness after repair/fallback; distinguish fallback from agent
  approval and record counts/denominators, reasons, latency and actual usage.
- [ ] Run offline/stub validation first, then the runbook's limited Foundry
  evaluation. Optional injected-number and Foundry quality evaluation runs remain
  separate, clearly labelled results.
- [ ] Produce JSON/Markdown evidence and Owner C documentation covering agents,
  MCP, Foundry, tracing and limitations. Prepare material for Owner B's README
  evaluation review rather than inventing scores or rewriting their work.

Verification: published numeric faithfulness must reach 100% before a passing
claim; any gap is investigated. Live recording and evaluation both consume
tokens and require budget accounting. Dependency: task 4, preserving phase order.

## Completion checks and delivery

Use `.venv/py312/Scripts/python.exe` for all project checks:

```powershell
$env:AGENT_MODE = 'stub'
& '.venv/py312/Scripts/python.exe' -m pytest -q
& '.venv/py312/Scripts/python.exe' -m pyflakes backend shared tests
```

Also lint changed evaluation modules, check dependency consistency when dependencies
change, and run relevant bundle/evaluation validation. All tests stay offline.
Each implementation phase gets its own branch, green checks, local commit and
exported patch. Exclude environment files, credentials and deployment tokens.

Owner A retains merge/deployment, Container App configuration and secrets;
Owner B retains Cosmos configuration and evaluation review; Owner D retains
frontend implementation and browser acceptance. Prepare handoffs without sending
messages on the user's behalf. Do not create a recurring monitoring automation
from the runbook's daily-check table.

## User review before implementation

The immediate dependency is access to the newer integration patch or checkout.
The user can revise scope, priorities, model budgets and optional features before
implementation starts. This document records proposed work, not completed work.
