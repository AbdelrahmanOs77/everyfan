# Owner B: Match Intelligence & Evidence

## Advanced Player/Tactical integration, 28 October 2026

[Advanced feature definitions](ADVANCED_FEATURES_GUIDE.md) document P1–P8 and T1–T8, including
formation separation, hull/line geometry, nearest-player grid shares, event/frame alignment,
line-breaking passes, counters/pressing, minutes/per-90 normalization, peer percentiles, weighted role
index, output blocks, explicit pair matchups and off-ball runs. All thresholds live in config.yaml;
the existing smoothing/intensity and pitch configuration remains canonical. New modules are
`possession_index.py`, `tactics_index.py`, `geometry.py`, `live_tactics.py`, `player_profile.py`,
and `reference_pool.py`. `MatchEvidence` builds the compact tracking index beside existing indexes.
New response models return definitions and causal source evidence. Cross-owner edits are recorded in
[INTEGRATION.md](INTEGRATION.md). Measured endpoint timings: [ADVANCED_PERFORMANCE.json](ADVANCED_PERFORMANCE.json).

Every number on screen comes from here: deterministic Python over the event and tracking stream.
The analytics run as a pipeline plugin, so Owner A's code is untouched except one guarded line that
mounts the evidence API in `backend/api/main.py`.

```text
backend/analytics/
  config.yaml   every weight and threshold (published below)
  engine.py     MatchAnalytics (metrics, indices) + PlayerTracker (speed, distance)
  moments.py    MomentDetector: rules, cooldowns, Contract B moments, stable IDs
  plugin.py     live pipeline plugin: publish moments, back-fill after seeks, Cosmos writes
  store.py      Cosmos DB writer (optional, background, idempotent upserts)
  evidence.py   facts at any second; powers the evidence API and Owner C's MCP tools
  api.py        REST endpoints (below)
  __main__.py   report / golden / export-eval / cosmos-check
tests/test_analytics.py, tests/golden/*.moments.json, evals/moments_eval.jsonl
```

## Status

| Plan task | Where |
| --- | --- |
| `config.yaml` with formulas and thresholds | `backend/analytics/config.yaml` |
| Pass, possession, speed, control, chaos, rhythm, PPDA, momentum | `engine.py` |
| Moment detector + cooldowns | `moments.py` |
| Live plugin (`backend.analytics.plugin:register`) | `plugin.py` |
| Cosmos DB persistence | `store.py` (on when `COSMOS_ENDPOINT` is set) |
| Evidence API | `api.py`, `evidence.py` |
| Determinism acceptance test, golden tests | `tests/test_analytics.py`, `tests/golden/` |
| Eval dataset for Owner C | `evals/moments_eval.jsonl` (`python -m backend.analytics export-eval`) |
| Demo bundles include analytics moments | `demo/*.bundle.json` (rebuilt with template + analytics plugins) |

## Run it

```bash
python -m backend.analytics report match_001        # the moments of the demo match
pytest -q tests/test_analytics.py                    # 20 tests
# live, next to Owner A's template overlays:
PIPELINE_PLUGINS=backend.api.template_plugin:register,backend.analytics.plugin:register python -m backend.cli serve
```

## Metrics (plan 6.1)

Pitch is 105 × 68 m, and home (Nile FC) attacks towards x = 105 in both halves. "Last 5" means the
rolling window `(t − 300 s, t]`. Every value below lives in `config.yaml`.

| Metric | Formula | Scope |
| --- | --- | --- |
| Pass accuracy | completed ÷ attempted | team, player, rolling 5 min, match |
| Pass distance | √((x₂−x₁)² + (y₂−y₁)²) | per pass |
| Pass difficulty (0–1) | 0.35·min(dist/40, 1) + 0.35·pressure + 0.20·min(forward_m/30, 1) + 0.10·[ends in final third] | per pass (heuristic, not xPass) |
| Ball / shot speed | ball_path length ÷ duration_s × 3.6 | per pass, shot |
| Player speed | frame displacement ÷ 0.5 s × 3.6, moving average over 3 frames | per player |
| Distance covered | sum of frame-to-frame displacements (same period, consecutive frames) | per player |
| Possession % | seconds credited to the team in possession since the last `possession_change`/`kickoff` ÷ total | team, rolling, match |
| Control index (0–100) | 100 × (0.4·pass accuracy + 0.3·min(passes per possession / 8, 1) + 0.3·possession share) | team, rolling 5 min |
| Chaos index (0–100) | 100 × (0.4·min(turnovers per min / **6**, 1) + 0.4·share of possessions ≤ 2 passes + 0.2·min(duels+fouls per min / 2, 1)) | match, rolling 5 min |
| Game rhythm | passes per minute (both teams): < 9.5 slow build-up, > 15 frantic, else balanced (+ median seconds between passes) | match, rolling 5 min |
| PPDA | opponent passes in their own 60% ÷ our tackles + interceptions + fouls in that zone (lower = harder press) | team, rolling 5 min, match |
| Momentum | Σ weight·e^(−Δt/120 s): shot 3, box entry 2, final-third pass 1, corner 1 | team |

**Calibration check.** On the demo match these formulas reproduce Owner A's measured windows exactly
(see `test_metrics_reproduce_owner_a_measured_windows`):

| Window | Nile possession | Nile PPDA |
| --- | --- | --- |
| 18–36′ | 38% | 5.3 |
| 54–67′ | 70% | 1.7 |
| 80–90′ | 45% | 2.2 |

## Selected-window tracking metrics

`advanced.py` adds deterministic team shape and per-player high-intensity
measurements to **both** `advanced-stats` and `fan-stats`, under the same
top-level `tracking` object. Calculations use `(at_s - window_s, at_s]`; the
whole-match tracking window (`window_s=5400`) also includes the kickoff sample.
There is no browser-side metric calculation and no change to frozen contracts.

| Metric | Formula | Configuration / unit |
| --- | --- | --- |
| Mean team width | For each selected frame, `max(y) - min(y)` over its observed outfield players; arithmetic mean of those frame widths | metres |
| Mean team length | For each selected frame, `max(x) - min(x)` over its observed outfield players; arithmetic mean of those frame lengths | metres |
| Defensive line height | Convert each outfield x-coordinate to depth from own goal: home `x`, away `pitch_length_m - x`. Average the four smallest depths per frame, then average those frame values | `metrics.team_shape.defensive_line_players: 4`; metres |
| Distance above threshold | Sum actual frame-to-frame path displacements whose existing smoothed speed at the interval endpoint is **strictly greater than 19.8 km/h**; prorate the first qualifying interval if the window boundary cuts through it | `metrics.high_intensity.distance_threshold_kmh: 19.8`; metres |
| Sprints | Count continuous above-25.2-km/h bouts **once** when their accumulated sampled duration first becomes **strictly greater than 1 s**, provided that qualification endpoint is in the selected window | `metrics.high_intensity.sprint_threshold_kmh: 25.2`, `sprint_min_duration_s: 1.0`; count |

Goalkeepers are excluded by metadata `position == "GK"`, not by shirt number or
coordinates. Only players actually present in a frame contribute; substituted
or sent-off players never acquire invented positions. Frames without outfield
players supply no shape measurement. A frame with fewer than four outfield
players supplies width/length but no defensive-line sample. Each valid frame has
equal weight. Home attacks toward increasing x and away toward decreasing x in
both halves, matching the simulator's coordinate convention.

High-intensity measurements reuse the **unrounded existing three-frame moving
average** and the same frame displacement already computed by `PlayerTracker`.
Each speed sample classifies its preceding 0.5-second interval. The first speed
requires three consecutive valid steps (four positions); warm-up has no smoothed
speed. Distance uses the actual path length, not smoothed speed multiplied by
time. Only intervals ending at or before `at_s` qualify; a future interval is
never partially consumed. Within an observed interval, its distance contribution
is proportional to its overlap with the selected window.

A speed at or below the sprint threshold, missing frame IDs, a player leaving
the tracked frame sequence, or a period change breaks a sprint bout. After a
gap/half change, speed smoothing warms up again. At 2 Hz, two eligible intervals
give exactly 1 s and do **not** qualify; the third gives 1.5 s and qualifies once.
Ongoing bouts do not require a future end frame. History before the left boundary
is retained for continuity: a bout that qualified before the window does not
count again, while one that first qualifies inside it counts once. This metric
is separate from the existing once-per-player sprint badge above 30 km/h.

No complete smoothed speed samples in a selected window means `null`, displayed
as a dash; observed low-speed samples produce real zeros. The same rule applies
to absent team-shape samples. These are measurements from synthetic tracking,
not player ratings or predictions.

Response layout:

```text
tracking
  at_s / window_start_s / window_s
  thresholds                       the three configured high-intensity thresholds
  defensive_line_players
  teams[team_id]
    mean_width_m / mean_length_m / defensive_line_height_m
    defensive_line_sample_count
    evidence                       first_frame, last_frame, from_s, to_s, sample_count
  players[player_id]
    distance_above_threshold_m / sprints / speed_sample_count
    window_evidence                selected frame range
    evidence                       causal source frame range, including prior history
```

Source ranges always end at a known frame, never a future one. Player ranges
include earlier tracking needed to reconstruct smoothing and bout continuity.
Raw coordinates remain available through the paginated
`/api/matches/{id}/players/{pid}/tracking-samples?at_s=&window_s=&offset=&limit=`
endpoint; follow `next_offset` for the complete range. Team shape provides
per-player source links and excludes the goalkeeper using match metadata.
Frame IDs describe a bounded range, not a promise that missing frames exist.

`TrackingMetricsIndex` caches compact per-frame shape means and cumulative
intensity values during the existing evidence replay. Window queries use binary
search and prefix differences. The sprint state is captured at each frame;
future frames cannot retroactively qualify an earlier window.

Hand-calculated checks in `tests/test_agents_tracking_metrics.py` cover mirrored
directions, goalkeeper exclusion, strict thresholds and duration, fractional
window overlap, multiple bouts, warm-up/gaps/half changes, left boundaries,
missing data, both REST responses and future-frame exclusion. The UI shows a
**Team shape** card in Tactical and **High-intensity performance** in Player,
with selectable one-, five-, fifteen-minute or match-so-far intensity windows.

Verification on 27 October 2026: the full Python suite passes **612 tests**;
Pyflakes is clean; the frontend production build and formatting pass. The
required stub evaluation reports **100% published numeric faithfulness (236/236)**
and catches all **80** injected invented-number drafts without real model calls.
All **9 browser scenarios** are verified: the original eight pass unchanged;
the added tracking-card scenario passes after correcting its evidence-panel
interaction. It checks both teams, all four shape/intensity windows, raw-source
links, English/Arabic accessibility and narrow mobile layout. A local proxy
smoke check also confirms identical tracking payloads from both endpoints.

## Badges (plan 6.2) → `player_milestone` moments

| Badge (`verified_facts.badge`) | Trigger | Facts |
| --- | --- | --- |
| `sprint` | smoothed speed above 30 km/h, first time for that player | `top_speed_kmh`, `frame` |
| `distance` | every 2 km covered | `distance_km`, `frame` |
| `rocket` | shot above 100 km/h | `shot_speed_kmh` |
| `killer_pass` | completed pass with difficulty above 0.75 | `pass_difficulty`, `pass_distance_m` |

## Moment rules (plan 6.3)

| Type | rule_id | Trigger | Importance |
| --- | --- | --- | --- |
| goal | GOAL_V1 | goal event | 1.0 |
| red_card | RED_CARD_V1 | red or second yellow | 0.9 |
| big_chance | BIG_CHANCE_V1 | unblocked non-goal shot from inside the box within 13 m under pressure ≤ 0.5, or a shot on target above 100 km/h | 0.8 |
| momentum_shift | MOMENTUM_SHIFT_V1 | momentum leader changes team with a gap above **8** | 0.7 |
| pressing_shift | PRESS_SHIFT_V1 | PPDA last 5 min < 0.6 × match PPDA for 60 s (after 15′, ≥ 5 defensive actions in the window; re-arms above 0.8×) | 0.7 |
| control_to_chaos | CONTROL_TO_CHAOS_V1 | chaos index crosses **65** from below (re-arms below 50) | 0.6 |
| killer_pass | KILLER_PASS_V1 | difficulty > 0.75 completed pass, then a shot by the same team within 10 s | 0.6 |
| rhythm_change | RHYTHM_CHANGE_V1 | rhythm label changes and holds 2 minutes | 0.5 |
| player_milestone | PLAYER_MILESTONE_V1 | badge above | 0.4 |

The rules wait for a full 5-minute window before they fire. The same type fires at most once per
90 match-seconds; goals, red cards and milestones are exempt from that cooldown.
Moments with importance ≥ 0.5 are meant for the agents; milestones are template-only player tags.

**Tuned from the plan's starting values** after measuring the simulator:

- Chaos turnover norm went from 3 to 6. This simulator averages 3.8 possession changes a minute, so 3 saturated.
- The chaos threshold went from 60 to 65.
- The momentum gap went from 3 to 8. One shot plus one box entry is already 5 on this scale, so 3 flipped about 11 times a match.
- Big chance now uses pressure ≤ 0.5 within 13 m instead of pressure < 0.4. The scripted 86:07 chance is a saved 12 m shot under 0.48 pressure.
- Pressing shift has a 60 s hold, which filters one-off blips.

### What the demo match produces (`match_001`, 35 moments + 174 milestones)

| Clock | Moment | Story beat |
| --- | --- | --- |
| 12:06 | goal (Nile 1-0) | |
| 17:16 · 20:08 | momentum_shift, pressing_shift (Delta) | Delta take control, 18–36′ |
| 31:04 · 49:02 | goals (1-1, 1-2) | |
| 54:41 · 58:10 | momentum_shift, pressing_shift (Nile, PPDA 1.8 vs 4.3) | Nile high press, 54–67′ |
| 63:03 | goal (2-2), rocket badge, 104 km/h | Hassan Nour's equaliser |
| 81:09 · 86:07 · 87:47 | control_to_chaos, Delta big chance, rhythm → frantic | End to end, 80–90′ |

### Moment IDs are stable

Event moments are numbered `mom_001`, `mom_002`, … in event order. Tracking badges use `mom_5001+`,
and Owner A's templates use `mom_9001+`. After a seek, the replay first bursts every earlier event. The
plugin processes that burst so its state and IDs match a full run, but it does not re-publish those
moments; it then back-fills the skipped tracking so distance badges stay right. A `moment_id`
therefore always means the same moment, and Owner C's cache key `(match_id, moment_id, persona, language)`
keeps working across replays and seeks. Tests: `test_seek_keeps_moment_ids_and_does_not_replay_history`
and `test_live_plugin_publishes_exactly_the_evidence_moments`.

## Evidence API (read-only, deterministic, rate-limited like other reads)

| Endpoint | Returns | Owner C's MCP tool |
| --- | --- | --- |
| `GET /api/matches/{id}/moments?until_s=&types=&min_importance=` | Contract B moments | |
| `GET /api/matches/{id}/evidence/{moment_id}` | moment, facts, rule text, resolved evidence events, EN/AR names (Verifier allowlist) | `get_moment_evidence` |
| `GET /api/matches/{id}/stats?at_s=` | score, possession, pass accuracy, PPDA, control, chaos, rhythm, momentum at that second | `get_match_state` |
| `GET /api/matches/{id}/recent-events?at_s=&window_s=&team_id=&types=` | events in the window | `get_recent_events` |
| `GET /api/matches/{id}/players/{player_id}/stats?at_s=` | passes, shots, goals, distance, top speed, badges | `get_player_statistics` |
| `GET /api/matches/{id}/baseline?metric=&window_s=&at_s=&team_id=` | last window vs match so far, per team | `compare_to_baseline` |
| `GET /api/analytics/config` | the full config + rule descriptions | |
| `GET /api/analytics/status` | live plugin + Cosmos writer status | |

`metric` is one of `possession_pct, pass_accuracy_pct, ppda, control_index, shots, passes, chaos_index,
turnovers_per_min, passes_per_min`. `at_s` means "as known at that second": nothing from later leaks in.
The API replays the whole match through the same detector, so its numbers equal the live ones.

**In-process alternative for Owner C:** `ctx.analytics.detector(match_id)` (live `MomentDetector`),
`ctx.analytics.snapshot(match_id)`, `ctx.analytics.subscribe(callback)` (called after every published moment),
or `MatchEvidence(meta, events, frames)` directly.

## Cosmos DB

Database `everyfan`, containers `events`, `moments`, `briefs`, `overlays`, `audit`, all partitioned on
`/match_id`, serverless, in the team region (`uaenorth`).

```text
COSMOS_ENDPOINT=https://<account>.documents.azure.com:443/
COSMOS_DATABASE=everyfan
```

- **Auth:** Entra ID by default (managed identity in Azure via `AZURE_CLIENT_ID`, `az login` locally) with the
  *Cosmos DB Built-in Data Contributor* data-plane role (`00000000-0000-0000-0000-000000000002`).
  `COSMOS_KEY` is a fallback, e.g. when the app identity lives in another tenant. Never commit it;
  pass it to Container Apps as a secret.
- **Writes:** events are upserted once each (id = `event_id`) and moments by `moment_id`, so replays create no
  duplicates. Writes are queued in the background and never slow the match. Owner C can reuse the writer:
  `get_store().enqueue("briefs", {...})`.
- **Check:** `python -m backend.analytics cosmos-check` writes and reads back one `audit` document.

Setup (Azure CLI / Cloud Shell, as the account owner):

```bash
RG=rg-everyfan-analytics; ACC=<account>
az cosmosdb sql database create -g $RG -a $ACC -n everyfan
for c in events moments briefs overlays audit; do
  az cosmosdb sql container create -g $RG -a $ACC -d everyfan -n $c -p /match_id; done
# data access for a person (az login) or the API's managed identity (principal ID from Owner A):
az cosmosdb sql role assignment create -g $RG -a $ACC --scope "/" \
  --role-definition-id 00000000-0000-0000-0000-000000000002 --principal-id <principal-id>
```

## Numeric-faithfulness evaluator

`evals/numeric_faithfulness.py` is the "every number comes from evidence" metric, with the Verifier's exact
rules (Arabic-Indic digits, exact integers, ±0.05 decimals, fraction-to-percent, display minute).
`NumericFaithfulnessEvaluator` has the callable shape `azure.ai.evaluation.evaluate()` accepts, so it runs next
to Foundry's groundedness/relevance/fluency/coherence evaluators. `python -m evals.run_agent_eval` uses it on
the eval dataset above to report writer faithfulness before and after the Verifier (see [OWNER_C.md](OWNER_C.md)).

## Cosmos DB from the deployed API

`deployment/enable-integration.ps1 -CosmosAccount <account> -CosmosResourceGroup <rg>` grants the API's managed
identity the data-plane role (same subscription), and sets `COSMOS_ENDPOINT` from `deployment/integration.env`.
If the account is in a different subscription or tenant, put `COSMOS_KEY` in that file instead (stored as a
Container Apps secret). Check with `GET /api/analytics/status` → `cosmos.written` growing and `failed` at 0.
Note: this document says the account is in `uaenorth`; the team handoff said Italy North. Either works (the
API reaches it over HTTPS); just confirm the endpoint.

## For Owner D (frontend)

- `moment` messages are Contract B. For pitch tags, use `type == "player_milestone"` with
  `verified_facts.badge` (`sprint`, `distance`, `rocket`, `killer_pass`) and the value fields above.
- Evidence panel: `GET /api/matches/{id}/evidence/{moment_id}`. Indices strip: `GET /api/matches/{id}/stats?at_s=`
  (call it every few seconds, or compute from the live socket later).
- The demo bundles now carry the analytics moments, so demo mode shows them with zero model cost.
