# Owner C — Step 5 evaluation

Scope: run the main Foundry evaluation on 30 balanced moments, retain auditable
JSON and Markdown results, and prepare the README evaluation and agent/MCP/
Foundry sections for Owner B's review. The optional second paid injection run and
model-based quality judges are outside this run. The required injected-number
check remains an offline stub evaluation.

Branch: `codex/owner-c-step-5-evaluation`, based on the team's merged Step 4 demo
at `93b141e`.

## Work and acceptance criteria

- [x] Add regression checks for Arabic-adjacent digits and honest raw-draft
  coverage; retain the exact facts and raw text used by the evaluator.
- [x] Pace real-model slots under the existing deployment quota, initialize
  clients outside measured stage work, and expose charged versus reported usage.
- [ ] Run offline checks, then the real 30-moment evaluation with a bounded
  token budget and no invented-number injection.
- [ ] Verify published numeric faithfulness is exactly 100%, independent of
  agent approval/fallback rates. Report missing drafts and rejection reasons.
- [ ] Commit results and README tables, document limitations, and open a PR
  for Owner B's review. No claim of Owner B's approval is implied.

No Azure resource, key, quota, deployed API or frozen schema changes are needed.
Evaluation code changes reuse the existing Analyst, writers, Verifier and
evidence tools; they do not implement a second football evidence engine.

## Reproduction

```powershell
$env:AGENT_ANALYST_TIMEOUT_S = '20'
$env:AGENT_WRITER_TIMEOUT_S = '20'
$env:AGENT_VERIFIER_TIMEOUT_S = '20'
$env:AGENT_TOTAL_TIMEOUT_S = '120'
& '.venv/py312/Scripts/python.exe' -u -X utf8 -m evals.run_agent_eval `
  --mode foundry --limit 30 --token-cap 3000000 --tpm 24000 `
  --env-file .venv/handoff/owner-c-foundry-handoff.env
```

The private settings file is Git-ignored. Pacing waits occur between sequential
slots, outside stage deadlines. Azure enforces estimated token and request rates,
which differ from billing usage; pacing does not guarantee the absence of 429s.
See [Microsoft's rate-limit guidance](https://learn.microsoft.com/en-us/azure/foundry-classic/openai/how-to/quota#understanding-rate-limits).
The runner saves incomplete checkpoints after each moment, explicitly labelled
`complete: false`; only a fully finished result may be used for the README.

Pre-run verification: 573 offline tests passed, Pyflakes was clean for
`backend shared tests evals`, and the required stub injection gate published
100% numerically faithful output. The new matcher, raw-evidence audit, missing
draft denominator, usage accounting and pacing tests run without Azure or a
real model.
