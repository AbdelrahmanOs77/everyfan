# Owner B: Match Intelligence & Evidence

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

## For Owner D (frontend)

- `moment` messages are Contract B. For pitch tags, use `type == "player_milestone"` with
  `verified_facts.badge` (`sprint`, `distance`, `rocket`, `killer_pass`) and the value fields above.
- Evidence panel: `GET /api/matches/{id}/evidence/{moment_id}`. Indices strip: `GET /api/matches/{id}/stats?at_s=`
  (call it every few seconds, or compute from the live socket later).
- The demo bundles now carry the analytics moments, so demo mode shows them with zero model cost.
