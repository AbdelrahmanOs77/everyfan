# Owner A — Simulator, Streaming, API & Delivery

Generates a realistic, fully synthetic football match from a scenario, replays it at any speed, streams it
through Azure Event Hubs, keeps the live match state, and serves it to viewers over REST and WebSockets
with a broadcast delay, a cached demo mode for judges, and cost/abuse protection. Deployed with one command.

## Status: every Owner A task in the plan is done

| Plan task | Where |
| --- | --- |
| Freeze contracts A, A2, E (+ B, C, D, envelope) | `shared/schemas/contracts.py`, JSON Schema in `shared/schemas/json/` |
| Simulator + tracking + `derby_balanced`; replay 1x/5x/20x; local adapter | `backend/simulator/`, `backend/services/stream/local.py` |
| Event Hubs producer/consumer behind the same interface; quality validator | `backend/services/stream/eventhubs.py`, `backend/services/consumer.py`, `backend/simulator/validator.py` |
| Container Apps deploy, managed identity, min replicas | `Dockerfile`, `deployment/azure/main.bicep`, `deployment/deploy.ps1` / `.sh`, `.github/workflows/image.yml` |
| Cached demo match; rate limits; token cap | `backend/api/demo.py`, `demo/*.bundle.json`, `backend/services/ratelimit.py`, `backend/services/budget.py` |
| Budget alerts; final smoke test | Bicep budget resource, `python -m backend.cli smoke` |
| API the others build on | `backend/api/` — contract in [API.md](API.md) |
| Runbook for deployment and the judging period | [DEPLOYMENT.md](DEPLOYMENT.md) |

## Quick start (no Azure needed)

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1     macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt

python -m backend.cli generate --all          # 4 matches into data/  (~4 s each)
python -m backend.cli validate --all          # realism + consistency rules R1-R9
python -m backend.cli replay --speed 20       # live local replay of the demo match in the terminal
python -m backend.cli serve                   # API on http://localhost:8000 (docs at /docs)
python -m backend.cli smoke --url http://localhost:8000 --live   # 13 end-to-end checks
pytest -q                                     # all tests
```

## Scenarios (`backend/simulator/scenarios/`)

| Scenario | match_id | Story | Final |
| --- | --- | --- | --- |
| `derby_balanced` (demo) | match_001 | Nile score 12', Delta control 18–36' and lead 49', Nile high press 54–67', Hassan Nour (nil_10) 104 km/h equaliser 63', frantic 80–90' | 2–2 |
| `late_comeback` | match_002 | Nile 2–0 up at 51', Delta all-out attack from 70', goals 77' and 87' | 2–2 |
| `red_card_60` | match_003 | Nile lead 28', Tarek Mansour (nil_04) red at 60', Delta equalise 74' | 1–1 |
| `press_vs_block` | match_004 | Nile press and dominate, Delta score on the counter | 1–1 |

Measured on the demo match (so Owner B's moment rules have something to find):

| Window | Nile possession | Nile PPDA | Shots N–D | Turnovers/min |
| --- | --- | --- | --- | --- |
| 18–36' Delta control | 38% | 5.3 | 4–6 | 3.6 |
| 54–67' Nile high press | 70% | **1.7** | 4–0 | 3.0 |
| 80–90' end to end | 45% | 2.2 | 1–3 | **6.9** |

Add a scenario by dropping a new JSON file (Contract E) in the folder; `forced_events` script goals,
red cards and big chances; `phases` change a team's strength, press and tempo for a window.
Only scripted goals happen (`allow_organic_goals: false`), so the score is always what the script says.

## Data model (frozen contracts, `shared/schemas/contracts.py`)

- **Pitch:** 105 × 68 m, origin at the home team's bottom-left corner. Home (Nile FC) attacks
  towards x = 105 in **both halves**. Clock is continuous: period 1 = 0–2700 s, period 2 = 2700–5400 s, no stoppage time.
- **Contract A — SyntheticEvent:** `seq` is the total order. `game_clock_s` (int) = floor(`game_time_s`).
  Passes, carries and shots carry a `ball_path` sampled every 0.1 s: `[t_rel_s, x_m, y_m]`.
  Speed = path length ÷ `duration_s` × 3.6. Receivers of `foul`, `tackle`, `duel` are opponents; for
  `substitution` the receiver is the player coming on. Goals carry `home_score`/`away_score` and `assist_player_id`.
- **Contract A2 — TrackingFrame:** 2 Hz, 10,801 frames per match, ball + every player on the pitch.
  Player speed and distance come from consecutive frames (same period only).
- **Contracts B, C, D:** Moment, Overlay, InsightBrief — owned by B and C, defined here so everyone shares one file.
- **Contract E — ScenarioSpec.** **MatchMetadata** (teams, players, colours) is the first message of every stream.
- JSON Schema copies are in `shared/schemas/json/` (CI fails if they drift).

## Stream protocol

Every message is a `StreamEnvelope` with `kind` = `metadata` | `event` | `tracking` | `control`,
plus `match_id`, `run_id`, `game_time_s`. Order per run: metadata → `run_started` control → events and
tracking interleaved by time → `run_finished`. A new `run_id` (new replay or seek) means **reset your state**.
On Event Hubs the partition key is `match_id`, so one match stays in order.

## How teammates plug in

**Owners B and C (analytics, agents): write a pipeline plugin.** The API already consumes the stream
(de-duplicated, ordered, reset on every new run) and calls your handlers; you publish moments and overlays,
which are validated against Contracts B and C and sent to viewers. The same plugin also builds the cached
demo match. Full example in [API.md](API.md#for-owners-b-and-c-pipeline-plugins).

```python
# backend/analytics/plugin.py   ->   PIPELINE_PLUGINS=backend.analytics.plugin:register,...
def register(ctx):
    @ctx.on_event
    async def on_event(event, state):          # SyntheticEvent + MatchState (score, clock, possession)
        moment = detector.update(event, state)
        if moment:
            await ctx.publish_moment(moment)
```

Persisting raw events to Cosmos DB: an `on_event` handler, or a `sink` with `.write(event, run_id)` on
`MatchStateConsumer` for a standalone worker.

For offline work (formulas, golden tests, evaluation sets) just load the files:
`meta, events, frames = backend.simulator.generator.load_match("data/match_001")`.

**Owner D (frontend):** everything is in [API.md](API.md): REST, the two WebSockets, message types,
overlay timing, Arabic names and RTL, close codes.

## Azure Event Hubs

Basic tier is enough: 1 consumer group (`$Default`), 256 KB max message (ours are ≤ 2 KB), 1-day retention.
A full match is about 13,200 messages. Consumers start at `@latest` and need no checkpoint storage.

```bash
python -m backend.cli eh-check                                       # round trip one message
python -m backend.cli consume                                        # terminal 1: live state from Event Hubs
python -m backend.cli replay --speed 20 --transport eventhubs        # terminal 2: publish the match
```

Auth: `EVENT_HUB_NAMESPACE` + `az login` (needs the *Azure Event Hubs Data Owner* role on the namespace),
or `EVENT_HUB_CONNECTION_STR` for a first test. In Container Apps use a managed identity with
*Data Sender* and *Data Receiver* roles. See `.env.example`.

## Validator rules (CI)

R1 player ≤ 37 km/h · R2 ball ≤ 140 km/h · R3 seq gap-free, time never goes back · R4 events inside their period ·
R5 11 per side minus red cards in every frame · R6 goals = score · R7 players belong to the right team ·
R8 coordinates on the pitch · R9 frames exactly 0.5 s apart.

## API, demo mode and protection (summary — full contract in [API.md](API.md))

- **Live** (`/ws/matches/{id}`): replay → Event Hubs → consumer → plugins → viewers, 6 s broadcast delay.
  Overlays skip the delay so they land exactly at `show_at_s`. One shared broadcast per match; the starter gets
  a control token. Idle broadcasts stop after 5 minutes. Falls back to the local bus if Event Hubs fails and
  switches back automatically within a minute of it recovering.
- **Demo** (`/ws/demo/{id}`): private playback per viewer from `demo/<match>.bundle.json` (moments + overlays
  recorded once by `build-demo`), events and tracking regenerated deterministically; zero model calls.
  A bundle whose fingerprint no longer matches the simulation is ignored and flagged in `/api/health` (and fails CI).
- **Protection:** per-IP rate limits (start 3/min, control 30/min, reads 240/min), WebSocket caps
  (6 per client, 200 total), max 2 concurrent live broadcasts, allowed speeds, daily model-token cap for agents.
- **Template plugin:** deterministic goal and red-card overlays in English and Arabic for beginner, tactical and
  player personas, with facts computed from the events (score, minute, shot speed, distance, passes in the move).

## Commands

| Command | What it does |
| --- | --- |
| `generate --all` / `validate --all` | build and check every scenario |
| `replay --speed 20 [--transport eventhubs] [--from-minute 60]` | stream a match |
| `consume` | print live state from Event Hubs |
| `eh-check` | one-message round trip through Event Hubs |
| `build-demo [--all] [--plugins ...]` | record the cached demo bundle(s) |
| `serve [--port 8000]` | run the API |
| `smoke --url URL [--origin O] [--live] [--admin-token T]` | end-to-end deployment check |
| `export-schemas` | refresh `shared/schemas/json/` |
