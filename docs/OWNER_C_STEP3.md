# Owner C — Step 3 Foundry handoff

Checked on 26 October 2026. Active scope is Step 3 Owner C; Owner A has completed
Steps 1–2. The local branch is based on the merged integration, `0f67460`.

## Step 3a: ready for private handoff

| Check | Observed result |
| --- | --- |
| Foundry resource | `everyfan-ai-resource`, resource group `damlink-ocr-rg` |
| `everyfan-fast` provisioning | `Succeeded` |
| `everyfan-strong` provisioning | `Succeeded` |
| Resource-key inference, fast | Returned `READY`; 24 reported tokens |
| Resource-key inference, strong | Returned `READY`; 68 reported tokens |
| Existing KEY 1 | Retrieved without regeneration |
| Private handoff artifact | Saved under ignored `.venv/handoff/` |
| Secret in Git/chat | No |
| Sent to Owner A | Not sent; user must transfer privately |

The private file is `E:\hackathon\.venv\handoff\owner-c-foundry-handoff.env`.
It contains the existing key and these non-secret settings:

```dotenv
FOUNDRY_PROJECT_ENDPOINT=https://everyfan-ai-resource.services.ai.azure.com/api/projects/everyfan-ai
FOUNDRY_MODEL_FAST=everyfan-fast
FOUNDRY_MODEL_STRONG=everyfan-strong
AGENT_ANALYST_MODEL_ROLE=fast
AGENT_VERIFIER_MODEL_ROLE=fast
```

Transfer the private file or its settings to Owner A through the team's private
channel. Do not commit it or paste its key into group chat, an issue or a report.
Owner A can use the values in their ignored `deployment/integration.env` for
Step 3c. No deployment settings or resource keys were changed by this handoff.

## Step 3d: pending Owner A's integration enablement

Read-only checks of the deployed API observed:

- Image version: `0f6746035f9a`.
- Pipeline: `backend.api.template_plugin:register` and
  `backend.analytics.plugin:register`.
- Agent status: `loaded=false`.
- Current live feed: six overlays, zero `agent/approved` overlays.
- No approved-agent trace IDs were available for Azure trace correlation.

After Owner A applies Step 3c and runs the smoke test, check
`/api/matches/match_001/overlays?source=live` again. Completion requires at least
one overlay with `source=agent` and `verification_status=approved`. Use its
`trace_id` to locate the workflow in Application Insights in Owner A/B's account,
or obtain the screenshot from Owner A. API deployment, identity changes and
Application Insights provisioning remain Owner A's work.

Machine-readable, non-secret check evidence is saved locally at
`.venv/handoff/owner-c-step3-verification.json`.

## Local validation

- Full suite: **559 passed** on Python 3.12. API/template tests use off mode;
  workflow tests explicitly use stub models.
- `python -m pyflakes backend shared tests`: clean (evaluation modules also clean).
- Required offline evaluation gate: 30 moments, 236 overlays, **100.0%** published
  numeric faithfulness; all 80 injected-number drafts were caught and repaired.
- Dependency check: no broken requirements.

These offline evaluation results are not live-model quality scores. Real-model
work in this step consisted of the two separately reported authentication checks.
