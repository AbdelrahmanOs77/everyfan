# Owner C — demo recording and Arabic review

Active scope: runbook Steps 4a and 4b, `match_001` / `derby_balanced`.

## Recording

The recorder uses the integrated analytics/agents pipeline and real Foundry
inference. A bounded pilot under live deadlines produced two approved overlays
and four template fallbacks, so the full recording uses the runbook's relaxed
profile: 30-second stage limits and a 120-second total overlay budget. This is
recorded in `fields.budget_ms`; it is not a live latency claim.

```powershell
& '.venv/py312/Scripts/python.exe' -u -X utf8 -m backend.agents.record_demo `
  --env-file .venv/handoff/owner-c-foundry-handoff.env `
  --relaxed --out .venv/demo-agents
```

The private environment file remains Git-ignored. The recorder caps its token
budget at 3,000,000 and paces workflows at 24,000 charged tokens per minute.
Reported charged tokens include conservative charges when model usage is
unknown after a timeout; they are not a provider billing total.

The original API demo builder stops draining after 600 seconds, shorter than a
quota-paced Foundry recording. Owner C's `RecordingContext` waits for complete
output, prints progress, and raises on timeout instead of silently accepting a
partial bundle. Models are prepared before the first moment and closed after
work completes. Completed overlays are saved before recap generation, and
`--recaps-only` can retry missing recaps without regenerating overlays.

## Arabic review

```powershell
& '.venv/py312/Scripts/python.exe' -X utf8 -m backend.agents.review_demo `
  .venv/demo-agents/match_001.bundle.json
```

The review tool checks the recording against the original evidence engine,
including the complete moment/overlay set, contract fields, evidence IDs, names,
numbers, timing, source provenance, RTL direction and recap evidence. It exports
`arabic_review.txt` and `arabic_review.json` with stable IDs and timestamps.

Wording corrections go through `apply_arabic_edits`: only Arabic headlines and
bodies may change. Every numeric token and player/team identity must remain
present with its original count, and each edited overlay must pass the verifier
again. Diacritic/ya spelling variants can be corrected to metadata `name_ar`;
changing the underlying name is rejected. Digits attached to Arabic conjunctions
are checked too. Code-owned diagnostic fields are excluded from football-copy
entity checks, consistently with the existing workflow cache validator.
Original copy is preserved in `match_001.pre-arabic-review.bundle.json`; the
changes are recorded in `arabic_changes.json`. Recap evidence excerpts follow
the reviewed overlay wording while their IDs and facts stay fixed.

The assistant performs an AI editorial review. Native-speaker human signoff is
a separate review status and must not be inferred from automated checks.

## Verified result

| Check | Result |
| --- | --- |
| Match / scenario | `match_001` / `derby_balanced` |
| Recorded moments | 209 |
| Recorded overlays | 218 |
| Real agent-approved overlays | 146 (67.0%) |
| Checked template fallbacks | 72 |
| Approved agent recaps | 10 |
| Pipeline errors / outstanding token reservations | 0 / 0 |
| Arabic items read | 114 (109 overlays and five recaps) |
| Arabic items corrected | 70 (65 overlays and five recaps) |
| Full artifact evidence checks | Passed, no errors |
| Original-to-reviewed integrity | Numeric tokens, identities and protected fields preserved |
| Local API feed | All 218 overlays served |
| Local API recaps | All ten served as `agent/approved`, correct language/direction |
| Arabic WebSocket delivery | `ov_mom_044_tactical_ar`, with inference off |
| Full offline tests | 565 passed |
| Pyflakes | Clean for backend/shared/tests/evals |
| Required offline injected-number evaluation | 100.0% published numeric faithfulness |

The first recap attempts exceeded the 600-character body limit. The new versioned
`recap_v2.md` prompt targets a short character budget without relaxing validation.
Only missing recaps were retried; the expensive overlay recording was preserved.
The final ten recaps use `recap_v2`.

Recording plus recap retries charged 548,628 tokens. Including the bounded pilot
and the separately reported recap diagnostic call, accounting totals 577,667
tokens, below the configured recording cap. Conservative unknown-usage charges
are included; this is not a billing export. Recording/retry execution took
1,363.4 seconds, excluding editorial review and local tests.

Arabic corrections included grammar, natural football terminology, the distinction
between pass difficulty and accuracy, median timing terminology, mistaken outcome
descriptions, misleading possession wording, and unsupported offside/motivation
claims. Numeric values, evidence IDs, persona/club identities, timing and source
provenance were preserved. The original copy and complete correction audit remain
available locally.

Artifacts are in `.venv/demo-agents/`: `match_001.bundle.json`,
`arabic_review.txt`, `arabic_review.json`, `arabic_changes.json`,
`verification-report.json`, `api-verification.json`, `review-integrity.json` and
`recording-summary.json`.
The final bundle SHA-256 is
`df33a43d026ec893ec31160b7eb6a70d13a57ed7c8aff977f853ba03cc3fa768`.

**Review status:** AI editorial review completed. Human native-speaker signoff
remains pending. The bundle is prepared for the Step 4b human check and subsequent
Step 4c handoff; no production demo publication is part of this work.
