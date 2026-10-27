# Continuous match commentary

All four fan interfaces now show every recorded action as running play-by-play,
alongside existing persona-specific analysis. Coverage includes passes
(completed, intercepted and out), carries, shots and outcomes, saves, goals,
recoveries, interceptions, tackles, duels, pressure, fouls, cards, corners, free
kicks, throw-ins, goal kicks, possession changes, substitutions and whistles.

`backend/agents/play_by_play.py` produces short English/Arabic calls directly from
immutable source events and metadata names. Routine calls require no model calls,
new statistical scores or inferred events. Player/club interests highlight
matching actions without hiding the rest of the match.

## Transport and evidence

Existing live and demo event envelopes receive an optional root annotation:

```text
type: event
match_id / run_id / game_time_s
data: original, unchanged Contract A event
commentary:
  show_at_s
  text: { en, ar }
```

The frozen schemas and original `data` remain unchanged. Old clients ignore the
annotation; the viewer also accepts older servers without it. Source links open
the original event endpoint. Deployment requires the updated backend/frontend;
recorded bundles need no regeneration because routine calls use replayed events.

Pass/carry/shot outcomes display at source event time plus recorded duration,
bounded by match duration. Other calls use the source time. Results therefore
wait for the ball to arrive. The browser uses the backend timestamp and never
advances the picture clock on an event. Existing live broadcast delay applies to
the action and its commentary together.

Live-join history contains the last 50 delivered event envelopes. Pending delayed
events and other runs are excluded. The browser deduplicates IDs, waits for the
picture clock, orders by display time/source sequence, and clears history on a
seek/reset. Show earlier plays expands the current connection's history.

## Viewing and verification

The latest call is prominent, with compact recent rows, timestamps and source
links. Arabic uses RTL and metadata `name_ar`. Watch at match speed selects 1x;
existing pause/seek/acceleration controls remain available. The latest call is a
polite screen-reader status; history does not announce every backlog entry or
force scrolling away from an earlier action being read.

`tests/test_agents_play_by_play.py` covers every action/outcome, bilingual names,
failed-pass/shot wording, substitutions, missing names, completion timing,
unchanged event contracts, bounded/reset live snapshots and both sockets with
agents off. Frontend unit tests cover clock gating, deduplication, ordering,
seek resets and older-server compatibility.

Browser checks cover routine passes before major moments, evidence, history,
speed control, one connection across fans, Arabic accessibility and mobile layout.
The full replay compares commentary IDs against all source events throughout the
match, including ordinary restarts.

Verification on 27 October 2026: **651 Python tests pass**, Pyflakes is clean,
the frontend build and **11 timing/unit tests pass**. The required stub injection
gate reports **100% published faithfulness (236/236)** with all **80** injected
invented-number drafts caught. The full-replay browser check reconciles all
commentary event IDs with the complete source match.
All **10 browser scenarios** are verified, including the dedicated routine-call,
Arabic/mobile and all-source-events full-replay checks.
