# EveryFan API (for Owner D's frontend and Owner C's agents)

Base URL: `http://localhost:8000` locally (`python -m backend.cli serve`), `https://<app>.azurecontainerapps.io` in Azure.
Interactive docs: `/docs`. All JSON. CORS allows only `FRONTEND_ORIGIN`.

## Two ways to watch a match

| | Demo (Judge mode default) | Live |
| --- | --- | --- |
| WebSocket | `/ws/demo/{match_id}` | `/ws/matches/{match_id}` |
| Who controls it | each viewer, privately | whoever started it (control token) |
| Model cost | zero (cached bundle) | real agents, daily token cap |
| Stream path | in-process | Event Hubs → consumer → pipeline |
| Broadcast delay | none | `BROADCAST_DELAY_S` (6 s) |

Use demo for "Watch demo match" and live for "Run live". Both send the **same message format**, so one renderer works for both.

## REST

| Method & path | Purpose | Notes |
| --- | --- | --- |
| `GET /api/health` | status, transport, budget, demo bundles | use for an "all systems" badge |
| `GET /api/scenarios` | list of matches | `match_id`, `title`, `description` |
| `GET /api/matches/{id}/metadata` | teams, players, colours, Arabic names | `name_ar` on teams and players |
| `GET /api/matches/{id}/events?from_s=&to_s=&types=goal,shot&limit=` | events from the dataset | evidence panel, max 2000 |
| `GET /api/matches/{id}/events/{event_id}` | one event | resolve `evidence_event_ids` |
| `GET /api/matches/{id}/state` | live replay status + match state | |
| `POST /api/matches/{id}/start?speed=20&from_minute=0` | start a live broadcast | returns `control_token`; 409 if one is running, 429 rate limit, 503 too many |
| `POST /api/matches/{id}/pause` · `/resume` · `/stop` | control live | header `X-Control-Token` (or `X-Admin-Token`) else 423 |
| `POST /api/matches/{id}/speed?value=5` | change speed | allowed: `ALLOWED_SPEEDS` (1, 5, 10, 20) |
| `POST /api/matches/{id}/seek?minute=63` | jump | state is rebuilt instantly |
| `GET /api/budget` | today's token use | `live_ai_enabled=false` when the cap is reached |
| `GET /api/demo` | cached bundles | counts of moments and overlays |
| `GET /api/spec/overlay` | Contract C JSON Schema | |

Errors are `{"detail": "..."}` with the status codes above.

## WebSocket query parameters

`persona` (`beginner|tactical|player|club|metric`) and `lang` (`en|ar|...`) filter **overlays** only; omit them to get every overlay.
`tracking_hz` = `2` (default), `1`, or `0` (no tracking). Demo also takes `speed` (0.5–60) and `from_minute`.

Demo controls, sent by the client as text frames:
```json
{"action": "pause"}   {"action": "resume"}   {"action": "speed", "value": 5}
{"action": "seek", "value": 63}   {"action": "restart"}
```
Live viewers send nothing (keep-alives are fine); control live through REST with the token.

Close codes: `4404` unknown match, `4429` too many connections from you, `4408` client too slow.

## Messages (server → client)

Every frame: `{"type", "match_id", "run_id", "game_time_s", "data"}`.

| type | data | when |
| --- | --- | --- |
| `hello` | `mode`, `broadcast_delay_s`, demo `bundle` counts | first frame |
| `reset` | `{reason}` | new run or seek: **clear the screen and timeline** |
| `metadata` | MatchMetadata | after every reset |
| `state` | score, clock, period, possession, players on pitch, sent off | after each event |
| `event` | SyntheticEvent (Contract A) | every event, in order |
| `tracking` | `{"frame", "period", "ball": [x, y], "players": [[id, x, y], ...]}` | 2 Hz |
| `moment` | Moment (Contract B) | when detected |
| `overlay` | Overlay (Contract C) | see timing below |
| `control` | `{action, speed}` | run_started, paused, resumed, seeked, run_finished |
| `replay` | `{state, speed, game_time_s, progress, mode}` | every 1 s (demo) / 5 s (live) |

### Clock and overlay timing (the important part)

* Drive the on-screen clock from the latest `tracking` (or `state`) `game_time_s`. It keeps moving during goal celebrations.
* An overlay can arrive **before** the play it describes (live mode delays the picture, not overlays). Keep a queue and show each overlay when the clock reaches `show_at_s`, for `ttl_s` seconds. Higher `priority` (1 = highest) wins a slot.
* `dir: "rtl"` → render right-to-left (Arabic). Player and team names in Arabic are in metadata `name_ar`.
* Pitch: 105 × 68 m, origin bottom-left, home attacks to the right (x = 105) in both halves.

### Example

```json
{"type":"overlay","match_id":"match_001","run_id":"run_20261027...","game_time_s":3783.0,
 "data":{"overlay_id":"ov_mom_9004_tactical_en","moment_id":"mom_9004","persona":"tactical","language":"en",
 "dir":"ltr","template_id":"lower_third","slot":"lower_third","priority":1,"headline":"Goal 64' - Nile FC",
 "body":"Hassan Nour scores from 21 m after a single pass. Shot speed 104 km/h. Nile FC 2-2 Delta United.",
 "fields":{"shot_speed_kmh":104,"shot_distance_m":21},"evidence_event_ids":["evt_01728","evt_01729"],
 "show_at_s":3783,"ttl_s":8,"verification_status":"fallback","source":"template","prompt_version":"template_v1"}}
```

## For Owners B and C: pipeline plugins

Add your module to `PIPELINE_PLUGINS` (comma-separated) and expose `register(ctx)`:

```python
def register(ctx):
    @ctx.on_reset
    def reset(state): ...                       # new run: clear your per-match state

    @ctx.on_event
    async def on_event(event, state):           # every event, exactly once, in order
        moment = detector.update(event, state)
        if moment:
            await ctx.publish_moment(moment)    # validated against Contract B
            ctx.spawn(explain(moment))          # model calls in the background, never inline

    @ctx.on_tracking
    def on_tracking(frame, state): ...          # 2 Hz positions (speed badges, distance)

async def explain(moment):
    if not await ctx.budget.try_reserve(2000):          # daily cap reached
        for ov in cached_or_template(moment): await ctx.publish_overlay(ov)
        return
    overlay, used = await run_agents(moment)
    await ctx.budget.settle(2000, used)
    await ctx.publish_overlay(overlay)                  # validated against Contract C
```

* `ctx.demo.bundles["match_001"].overlays_for(moment_id, persona, lang)` returns cached overlays (fallback).
* `backend.api.template_plugin.goal_overlays / red_card_overlays` are ready-made deterministic fallbacks.
* When your plugin replaces the template one, remove `backend.api.template_plugin:register` from the list
  and rebuild the demo: `python -m backend.cli build-demo` (then commit `demo/*.bundle.json`).
  Template moments use ids `mom_9001+`, so yours (`mom_001+`) never collide.
* A handler that raises is logged and counted in `/api/health` → `pipeline.errors`; the match keeps running.
