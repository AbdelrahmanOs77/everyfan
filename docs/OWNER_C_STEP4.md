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
bodies may change. Every numeric token and metadata name must remain present
with its original count, and each edited overlay must pass the verifier again.
Original copy is preserved in `match_001.pre-arabic-review.bundle.json`; the
changes are recorded in `arabic_changes.json`. Recap evidence excerpts follow
the reviewed overlay wording while their IDs and facts stay fixed.

The assistant performs an AI editorial review. Native-speaker human signoff is
a separate review status and must not be inferred from automated checks.

## Result status

Recording and final Arabic review are in progress. Final measured counts,
artifact verification and local API delivery results will be recorded here
after completion. Output remains under `.venv/demo-agents/` for review.
