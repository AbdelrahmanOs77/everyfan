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
- [x] Run offline checks, then the real 30-moment evaluation with a bounded
  token budget and no invented-number injection.
- [x] Verify published numeric faithfulness is exactly 100%, independent of
  agent approval/fallback rates. Report missing drafts and rejection reasons.
- [x] Prepare result files, README tables and the review handoff for a PR.
- [ ] Owner B independently reviews the results. No human approval is implied.

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

## Completed real run

Code revision: `8a9b91b7379acbf49bbfea61d51ade85cf0b8c05`. Finished 2026-10-26 20:51 UTC.
All 30 sampled moments match the original evidence engine, and all
236 expected (moment, persona, language, club) slots are present exactly once.
The audit recomputed raw and final numeric scores from saved text and verified
fact snapshots, then reproduced every summary metric.

| Measurement | Result |
| --- | --- |
| Raw valid first drafts | 211 / 236 |
| Missing first drafts | 25 |
| Raw numerically faithful | 192 / 211 (91.0%) |
| Final numerically faithful | 236 / 236 (100.0%) |
| Agent-approved final drafts | 149 (63.1%) |
| Checked template fallbacks | 87 (36.9%) |
| Repairs attempted | 70 |
| Provider-reported / conservative charged tokens | 519,131 / 519,131 |
| Completion calls / unknown-usage calls | 502 / 0 |
| Budget-denied calls / outstanding reservations | 0 / 0 |
| Wall time including pacing and startup | 1295.1 seconds |

All stages used `everyfan-fast`, with the fast Analyst and Verifier roles.
Evidence was read through in-process `EvidenceTools`; this run does not establish
MCP HTTP transport or Azure trace ingestion. Stage latency in `latest.md` excludes
pacing waits and startup; Analyst latency is shared by the slots for each moment,
and the reported percentiles are weighted by slots. This is an offline profile,
not the live 5.5-second workflow budget.

## Rejections and interpretation

| Reason label | Rejected attempts |
| --- | ---: |
| UNKNOWN_ENTITY | 58 |
| NUMBER_NOT_IN_EVIDENCE | 39 |
| INVALID_DRAFT | 31 |
| UNSUPPORTED_CAUSALITY | 14 |
| TONE | 11 |
| SCHEMA | 4 |

Reason counts include failed repair attempts, so they are not a count of unique
slots. The 25 missing first drafts are excluded from the raw denominator;
they remain included in the 236-output final denominator via checked fallbacks.
Numeric faithfulness measures supported numeric tokens in headline/body, not
complete factuality, fluency or coherence. A conservative entity check can also
reject usable wording; its reason label is not a human-confirmed hallucination.
English Favorite Club approval was 25.0%, a quality limitation
that remains visible in the per-persona report. No cases were selectively rerun
or removed. The optional paid injection run and Foundry quality judges were not run.

The offline injected-number artifact separately reports 66.1% raw and
100.0% final faithfulness, with all 80 injected drafts repaired and zero
model tokens. Its stub approval rate is not a real-model quality measurement.

## Committed evidence and Owner B handoff

- [Foundry report](../evals/results/latest.md) and [raw/final records](../evals/results/20261026-203019-foundry.json).
- [Evidence/coverage audit](../evals/results/20261026-203019-foundry.audit.json); source dataset Git SHA-256
  `06a9d4de0dcc5af47d9d4b866aa8be02ef8a6964889d117b0180ea52600a3090`.
- Foundry result LF-normalized SHA-256:
  `bc1031708392d0f1a5d7888f25e1cba05dc6157f05aa518582de089695d05afc`. Git's CRLF normalization does not change JSON values.
- [Offline injection report](../evals/results/stub-injected.md) and
  [records](../evals/results/20261026-203544-stub.json).

The README now contains the evaluation table and agents/MCP/Foundry section.
Owner B should check the denominators, raw/final score reproduction, source
counts, rejection labels and limits above before approving the PR. This work
prepares that review; it does not record Owner B's approval or deploy a revision.

## Review outcome and Step 6 handoff

The user chose to perform the review in place of Owner B, confirmed that review
was complete and reported merging PR #5. The resulting main commit is `2aa91ff`.
This records the user's approval; it does not claim Owner B personally reviewed
it. Measurement artifacts retain their original review-time metadata.

The final frontend handoff is in [HANDOFF_OWNER_D.md](HANDOFF_OWNER_D.md), with
the implementation/deployment status in [OWNER_D.md](OWNER_D.md). No additional
paid evaluation was needed for that handoff.
