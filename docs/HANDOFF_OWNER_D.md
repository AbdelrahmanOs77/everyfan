# Handoff to Owner D (frontend and delivery)

The backend is finished: every screen in the plan maps to an endpoint or WebSocket message below, and
everything works with zero model cost in demo mode. Full contract: [API.md](API.md).

- API: `https://everyfan-api.graybay-511bafbd.uaenorth.azurecontainerapps.io` (interactive docs at `/docs`)
- Local: `python -m backend.cli serve` → `http://localhost:8000` (CORS allows `http://localhost:5173`)
- Production CORS: tell Owner A the Static Web App URL; it goes in `FRONTEND_ORIGIN`.

## Judge mode → API

| Button / test step | Call |
| --- | --- |
| Watch demo match | `WS /ws/demo/match_001?speed=20` (private, cached, zero cost; controls are JSON text frames) |
| Run live | `POST /api/matches/match_001/start?speed=5` → keep `control_token`; `WS /ws/matches/match_001` |
| Break it | `POST /api/demo/break-it?persona=tactical&lang=en` → show `draft` (red), `verdict.reason_code` and `detail`, then `repaired_or_fallback_overlay` (green) |
| Switch to Arabic | the implemented viewer keeps one unfiltered socket and selects `language=ar` locally; overlays carry `dir: "rtl"`; names from metadata `name_ar` |
| Pick a player | Player Focus: keep overlays where `persona == "player"` and `fields.player_id` is the chosen player; ticker from `GET /api/matches/{id}/players/{player_id}/stats?at_s=<clock>` |
| Pick a club | Favorite Club: `persona=club&club=nile_fc` on the socket (or filter `fields.club_id`) |

## Screens → data

| Screen (plan 8.2) | Source |
| --- | --- |
| 2D pitch, dots, ball | `tracking` messages: `{"frame","period","ball":[x,y],"players":[[id,x,y],...]}`; pitch 105 × 68 m, origin bottom-left, home attacks right in both halves |
| Team colours, names, shirt numbers | `metadata` message (after every `reset`) |
| Score bug, clock | `state` messages; drive the clock from the latest `tracking`/`state` `game_time_s` |
| Name tags + threshold badges | `moment` with `type == "player_milestone"`: `verified_facts.badge` = `sprint` (`top_speed_kmh`), `rocket` (`shot_speed_kmh`), `distance` (`distance_km`), `killer_pass` (`pass_difficulty`) |
| Overlay cards | `overlay` messages (Contract C), see timing rules below; `slot` = `lower_third`, `side_panel`, `pitch` |
| Four-way view | one demo socket **without** `persona`/`lang` filters; split overlays client-side into beginner/en, tactical/en, player/en, beginner/ar (or tactical/ar). Same `moment_id`, same numbers |
| Why this matters | `GET /api/matches/{id}/evidence/{moment_id}`: facts, rule text, resolved events, names; show `overlay.trace_id` |
| Indices strip | `GET /api/matches/{id}/stats?at_s=<clock>` every 5 s: control, chaos, rhythm, PPDA, momentum |
| Latency readout (Tactical) | `fields.generated_ms` of `fields.budget_ms`: "generated in 2.4 s of 5.5 s" |
| Repair badge | `fields.attempts == 2` and `fields.reason_codes` (e.g. `NUMBER_NOT_IN_EVIDENCE`) |
| Agent vs template badge | `source` (`agent` / `template`) + `verification_status` (`approved` / `fallback`) |
| Match recap | at `control.action == "run_finished"` (or a button): `GET /api/matches/{id}/recap?persona=&lang=&club=` → `headline`, `body`, `key_moments`, `dir`; mid-match add `until_s=<clock>` for "So far" |
| Public feed page | `GET /api/matches/{id}/overlays` (+ `GET /api/spec/overlay`) |
| Status badge | `GET /api/health`: `status`, `agents.mode`, `budget.live_ai_enabled` |

## Timing rules (the part that is easy to get wrong)

1. On `reset`: clear the pitch, the overlay queue and the timeline. A seek or new run always starts with one.
2. Overlays may arrive **before** their play (live delays the picture by 6 s, not overlays). Queue them and show
   each when the clock reaches `show_at_s`, for `ttl_s` seconds. One card per `slot`; lower `priority` number wins.
3. Show each `overlay_id` once. The same moment has one overlay per persona × language (× club).
4. `dir: "rtl"` → right-to-left card, Arabic punctuation; numbers stay Western digits.

## Personas and languages

| Persona | Template slot | What changes |
| --- | --- | --- |
| `beginner` | lower third | plain words, one term explained |
| `tactical` | side panel stat card | metrics vs. baseline |
| `player` | pitch tag (`fields.player_id`) | the moment's focus player |
| `club` | lower third (`fields.club_id`) | partisan for the fan's club, respectful to the rival |

Languages: `en`, `ar`. Changing persona or language changes the words, never the numbers (tests enforce it).

## Demo bundles available now

All four matches are available (`match_001` derby 2–2 is the demo match). The
deployed health response checked on 2026-10-27 Cairo time reports 218 overlays
for `match_001`: 146 approved agent outputs, 72 checked template fallbacks and ten
recorded recaps. The other three bundles contain 128–188 checked templates;
their recaps use the deterministic backend path. Demo playback makes no model
calls. These bundle counts are distinct from the 236-output evaluation sample.

The user completed the Step 5 review in place of Owner B and merged PR #5
(`2aa91ff`). The implementation is now in `frontend`; see [OWNER_D.md](OWNER_D.md)
and [TESTING_GUIDE.md](TESTING_GUIDE.md). The current account's Azure location
policy prevents Static Web Apps provisioning; public hosting and Owner A's exact
frontend-origin CORS update remain open. The deployed API revision remains
`93b141ef1793`; the Step 5 evaluator/docs merge does not itself deploy a backend.

## Acceptance checks for the frontend (plan 8.4)

- [x] Score and clock match backend state through a full replay and seek.
- [x] Four-way view uses the same moment on one socket, with no generated stats.
- [x] Timing/duplicate/expiry/priority/reset checks and rejected-output exclusion.
- [x] Arabic cards render RTL; recorded overlay native review completed in Step 4.
- [x] Keyboard controls, automated contrast/accessibility and phone layout checks.
- [x] Break it shows rejection → replacement.
- [ ] Native-speaker signoff for the newly written Arabic interface strings.
- [ ] Works from a phone on mobile data in a private window.
