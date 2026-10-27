# Advanced Player, Tactical and agent features

Implemented from [the supplied plan](EVERYFAN_ADVANCED_FEATURES.md), 28 October 2026.
Existing Beginner, Player, Tactical, My Club statistics and commentary remain available.
Frozen contracts are unchanged. New response models live in their owning modules.

## Player interface

| Feature | Data and calculation |
| --- | --- |
| P1 Role benchmark | Same-position peers from **other matches**, full-time, at least 30 on-pitch minutes. Counts and distances are `value / minutes × 90`; pass/duel percentages and top speed retain natural units. Midrank percentile is `(below + .5 × equal) / n × 100`. Player minutes below 15, or no peers, make the comparison unreliable. The response includes peer match/player IDs and source evidence. |
| P2 Progress | P1 at 900-second checkpoints plus the requested clock. Raw values, percentile and role index are retained at each checkpoint. |
| P3 Role index | **EveryFan role index (heuristic)** = `10 × Σ(weight × percentile / 100) / Σ(weight)`, rounded to one decimal. Null when unreliable. Only available, configured metrics enter the denominator. Every contribution and weight is returned. This is not a player rating or prediction. |
| P4 Movement | Raw sample counts/shares in a 21 × 14 grid over the selected window, with a last-60-second trail. Original pitch coordinates; missing samples are not filled. |
| P5 Sprint map | Existing smoothed speed strictly above 25.2 km/h for strictly more than one second. One bout is counted at its qualification timestamp, matching the existing sprint counter. Start/end positions, period, maximum speed, measured path distance and frame evidence are returned. Ongoing bouts stop at the last known sample. |
| P6 Output curve | 900-second blocks: distance and high-intensity distance per **on-pitch** minute, sprint count, top speed, and distance/min as a percentage of the first block. No output is called a fatigue diagnosis. If the first block has no measurable output, the percentage is null. |
| P7 Matchup | Opposing outfield player with the lowest mean Euclidean separation over shared observed frames. Includes nearest-opponent frame share, shared-frame count and explicit recorded pair duels/tackles; opponent IDs may come from receiver_id or opponent qualifiers. Both players' count/distance metrics are normalized per 90, with rate/speed units retained. Proximity is not an inferred duel. |
| P8 Off-ball runs | Own possession, at least 5 m from the ball, smoothed speed above 18 km/h, forward depth gain at least 10 m. Speed/possession/distance failure, gaps or half changes end a bout. Box/final-third endpoints and a known completed pass within three seconds of the endpoint are returned. |

The per-90 clarification above deliberately avoids multiplying percentages and top speeds by playing-time rates.
All numbers are computed in Python; frontend arithmetic only draws chart/pitch geometry.
GK benchmark metrics are saves, passing accuracy and distance. FB/CB add defensive metrics;
MID/AM add creativity/progression; W/ST add shots, box entries and sprints.
Weights and the exact group/metric maps are in `backend/analytics/config.yaml → advanced_features`.

## Tactical interface

The **Live pitch** tab has eight independently toggleable SVG layers. Defaults are formation,
shape and passing links. Preferences use optional localStorage. Live positions drive the drawing;
displayed labels, counts, areas, distances and shares come from the endpoint.

| Feature | Definition |
| --- | --- |
| T1 Formation | Outfield mean positions split by possession phase, at least 20 phase frames. Sort own-goal depth, split at the largest gaps into three/four lines. Separation = smallest adjacent mean-depth gap / max(mean within-line spread, 1 m). Four lines must improve the score by 25%. Ties use player IDs. Stability requires the same observed label across the last 180 seconds at 30-second evaluation checkpoints. Formation timelines and shared-pitch badges are included. |
| T2 Shape | Monotonic-chain convex hull and shoelace area of observed outfield positions. Current/window/match area, width, length and deepest-four line height. Live hull/line polylines are drawing geometry. |
| T3 Passing links | Top eight directed completed-pass links in the last 300 seconds, with original event IDs. Links join current player positions; width reflects the recorded count. |
| T4 Space | Nearest player, including GKs, at centres of a 1 m grid. Equal distances go to neither team. Current and window mean shares for whole pitch, opponent half and attacking third. The D3 Voronoi drawing is **distance only**, not a speed/physics pitch-control model. |
| T5 Lines | Deepest outfield depth and mean depth of the deepest four, from own goal; current/window/match values and a line-height history. Position-only offside line uses the second-last defender including GK. No offside decision is inferred. |
| T6 Line breaking | Completed forward pass bypassing at least three opponent outfield players strictly between endpoints. Align to the most recent causal frame within .5 seconds, never a future sample. Opponent T1 out-of-possession mean lines between endpoints are counted; unavailable phase formation gives zero observed lines. Missing nearby frames are counted as skipped. |
| T7 Counters | Most recent own-half ball win (recovery/interception/won tackle) followed by own shot within 15 seconds, without opponent possession change. Fast break ≤10 seconds. Original event chains, pass counts, duration and outcome are retained. My Club compares match counter totals. |
| T8 Pressing | Pressure/tackle/interception/foul events in attack-normalized 6 × 4 cells. Counts, per-minute rate, original IDs and nearest team-player distance to the tracked ball, plus existing PPDA. Proximity does not establish intent. |

Home attacks +x, away −x in both halves; away depth is pitch length minus x.
All spatial thresholds, weights and grid sizes are configurable. Physical thresholds reuse
`metrics.high_intensity` and `metrics.player_speed`; pitch dimensions reuse `pitch`.

## Ask, coach and reports

**Ask the match** is available in every fan interface. The side drawer has six suggested questions,
four-item bounded history, as-of clock, source badge and evidence dialog. Demo free text uses guarded
keyword routing and deterministic answers; a matching recording may be reused. Live mode uses
the configured fast router and checked writer, bounded by the daily token budget and workflow deadline.
Questions are untrusted data. Unsupported names request clarification, future questions and predictions
are refused. Tools are limited to three calls and clipped at the question clock. A resolved
historical range lowers the answer's as-of clock, and last-N-minute queries
set the bounded evidence window. The live structured router can classify supported phrasing without
stub keywords; hard injection/prediction guards still run before the router. The writer gets only
resolved facts, names, persona and language. Numeric/name/tone/future/prediction/causality checks allow
one repair before a template fallback. Deadlines return an explicit evidence-unavailable fallback.
No free-text question is written to audit logs.

**Coach notes** have their own model, not a frozen Contract B moment. Every 30 match-seconds,
code checks stable formation changes, defensive line shift ≥8 m, hull area change ≥25%, dominant
pressing-zone half changes, and at least two counters in ten minutes. Baselines exclude the latest
60-second window. Cooldown is 300 seconds per team/trigger. Chronological IDs remain stable after seeks;
reset/seek catch-up emits no burst. The feed includes before/after formation diagrams and evidence.
Templates describe measurements, never the coach's intention.

**Reports** open at half/full time and on demand. They include score/scorers, published verified
moment references when available, separately scoped half/match numbers, recent tactical picture,
category leaders (including the role heuristic), coach facts and halftime observations to follow.
They are dismissable; replay continues underneath. Only as-of facts are used. Phase availability is
checked **before** returning cached reports. Cache keys include persona, language and club; so-far
reports also include the clock. A bare analytics provider without a published feed uses deterministic
detected moments, identified as such in its definitions.

All three use existing budget reservations, telemetry and audit/brief queues. Models never calculate
football numbers. Tests and committed recordings use off/stub mode, never Azure or a real model.
Automatic background agent preparation is disabled in off mode; the read endpoints still return
deterministic notes/reports. Enabled agents defer heavy preparation briefly so immediate commentary
can publish first, and discard work from superseded replay generations.

## API and evidence

See [API.md](API.md#advanced-player-tactics-and-agents-28-october-2026).
Windows are `(max(0, at_s − window_s), at_s]`; the existing whole-match tracking mode also includes
the kickoff frame. Event evidence is bounded at `at_s`. Tracking ranges return first/last frame,
from/to seconds and observed sample count. Match baseline ranges are also included in tactics evidence.
Progress/peer data retain their own cutoffs and match IDs. Percentiles use other matches only.

MCP now has seven protected read-only tools; the new `get_tactical_snapshot` and
`get_player_profile` call the same providers as REST. The API-key requirement and 401 behavior are unchanged.

## Offline recordings and validation

```powershell
$env:AGENT_MODE='off'
.\.venv\py312\Scripts\python.exe -m backend.agents.record_demo --advanced-only --mode stub --out demo
.\.venv\py312\Scripts\python.exe -m evals.run_ask_eval --mode stub --inject 0.3
.\.venv\py312\Scripts\python.exe -m evals.run_advanced_performance
```

Each of the four bundles includes 20 reports, ten coach variants and 144 suggested Q&A records:
four personas × two languages × six questions × three clocks (20, 60, 88 minutes).
Club reports/coach variants exist separately for each club. Optional advanced content is packed by
content hash to share repeated facts/evidence; endpoint responses are expanded without changing contracts.
Existing overlay items and fingerprints are preserved.

Measured results are in [ASK_EVAL_RESULTS.json](ASK_EVAL_RESULTS.json) and
[ADVANCED_PERFORMANCE.json](ADVANCED_PERFORMANCE.json). Performance measures actual HTTP responses over
20 changing clocks after warm-up; cold index/reference construction is reported separately.
Ask evaluation warms the peer provider first and reports that warm-up separately; a cold live workflow
that exceeds its deadline publishes an explicit evidence-unavailable fallback, which has its own regression test.
Cold requests can take seconds, so UI loading/error/retry states are explicit.

Automated browser checks include English/Arabic, RTL, a 375 px viewport, WCAG A/AA scans,
layer interaction, profile loading, chat evidence, reports and page errors.
**Native Arabic editorial review and a deployed Foundry/live smoke test remain human/environment checks.**
They are not represented as completed by stub evaluation. Automatic merging/deployment is outside this implementation.
