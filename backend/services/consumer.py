"""Stream consumer: validates, de-duplicates, orders and applies match events.

    consumer = MatchStateConsumer(on_event=analytics.handle_event)   # owner B plugs in here
    await consumer.consume(make_subscriber())

Guarantees for downstream handlers:
  * events arrive exactly once per run (duplicates by event_id are dropped)
  * events arrive in seq order (a small reorder buffer absorbs out-of-order delivery)
  * a new run_id (new replay or backwards seek) resets the match state
  * handlers receive the already-updated MatchState
"""

from __future__ import annotations

import heapq
import inspect
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from shared.schemas import MatchMetadata, SyntheticEvent, TrackingFrame

from .stream import Envelope, Subscriber

Handler = Callable[..., Any | Awaitable[Any]]


class EventSink(Protocol):
    """Where raw events are persisted (owner B adds a Cosmos DB sink)."""

    def write(self, event: SyntheticEvent, run_id: str) -> None: ...


class JsonlEventSink:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: SyntheticEvent, run_id: str) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"run_id": run_id, **event.model_dump(exclude_none=True)}) + "\n")


@dataclass
class MatchState:
    match_id: str
    run_id: str
    metadata: MatchMetadata
    period: int = 1
    clock_s: int = 0
    game_time_s: float = 0.0
    score: dict[str, int] = field(default_factory=dict)
    possession_team_id: str | None = None
    on_pitch: dict[str, set[str]] = field(default_factory=dict)
    sent_off: list[str] = field(default_factory=list)
    cards: list[dict] = field(default_factory=list)
    last_event_id: str | None = None
    next_seq: int = 1
    events_applied: int = 0
    duplicates_dropped: int = 0
    reordered: int = 0
    gaps_skipped: int = 0
    replay_status: str = "running"
    last_frame: TrackingFrame | None = None
    seen: set[str] = field(default_factory=set, repr=False)
    buffer: list[tuple[int, str, SyntheticEvent]] = field(default_factory=list, repr=False)

    @classmethod
    def new(cls, meta: MatchMetadata, run_id: str) -> "MatchState":
        return cls(
            match_id=meta.match_id,
            run_id=run_id,
            metadata=meta,
            score={meta.home.team_id: 0, meta.away.team_id: 0},
            on_pitch={t.team_id: {p.player_id for p in t.players if p.starter} for t in (meta.home, meta.away)},
        )

    def scoreline(self) -> str:
        h, a = self.metadata.home, self.metadata.away
        mm, ss = divmod(self.clock_s, 60)
        return f"{mm:02d}:{ss:02d}  {h.name} {self.score[h.team_id]}-{self.score[a.team_id]} {a.name}"

    def to_dict(self) -> dict:
        return {
            "match_id": self.match_id,
            "run_id": self.run_id,
            "period": self.period,
            "clock_s": self.clock_s,
            "game_time_s": self.game_time_s,
            "score": self.score,
            "possession_team_id": self.possession_team_id,
            "players_on_pitch": {k: len(v) for k, v in self.on_pitch.items()},
            "sent_off": self.sent_off,
            "last_event_id": self.last_event_id,
            "events_applied": self.events_applied,
            "duplicates_dropped": self.duplicates_dropped,
            "reordered": self.reordered,
            "gaps_skipped": self.gaps_skipped,
            "replay_status": self.replay_status,
        }

    def apply(self, e: SyntheticEvent) -> None:
        self.clock_s = e.game_clock_s
        self.game_time_s = e.game_time_s
        self.period = e.period
        self.last_event_id = e.event_id
        if e.type == "goal" and e.team_id:
            self.score[e.team_id] += 1
        elif e.type in ("possession_change", "kickoff") and e.team_id:
            self.possession_team_id = e.team_id
        elif e.type == "card" and e.player_id:
            self.cards.append({"player_id": e.player_id, "card": e.outcome, "clock_s": e.game_clock_s})
            if e.outcome in ("red", "second_yellow"):
                self.sent_off.append(e.player_id)
                self.on_pitch[e.team_id].discard(e.player_id)
        elif e.type == "substitution" and e.team_id:
            self.on_pitch[e.team_id].discard(e.player_id)
            if e.receiver_id:
                self.on_pitch[e.team_id].add(e.receiver_id)
        self.events_applied += 1


class MatchStateConsumer:
    def __init__(self, on_event: Handler | None = None, on_tracking: Handler | None = None,
                 on_reset: Handler | None = None, on_control: Handler | None = None,
                 sink: EventSink | None = None, reorder_window: int = 64) -> None:
        self.on_event, self.on_tracking = on_event, on_tracking
        self.on_reset, self.on_control = on_reset, on_control
        self.sink = sink
        self.reorder_window = reorder_window
        self.states: dict[str, MatchState] = {}
        self.ignored_without_metadata = 0
        self.messages_received = 0
        self.last_message_at: float | None = None

    @staticmethod
    async def _call(handler: Handler | None, *args) -> None:
        if handler is None:
            return
        result = handler(*args)
        if inspect.isawaitable(result):
            await result

    async def consume(self, subscriber: Subscriber, stop_when_finished: bool = False) -> None:
        async for env in subscriber:
            await self.handle(env)
            if stop_when_finished and env.kind == "control" and env.payload.action == "run_finished":
                break

    async def handle(self, env: Envelope) -> None:
        self.messages_received += 1
        self.last_message_at = time.time()
        if env.kind == "metadata":
            state = MatchState.new(env.payload, env.run_id)
            self.states[env.match_id] = state
            await self._call(self.on_reset, state)
            return

        state = self.states.get(env.match_id)
        if state is None or state.run_id != env.run_id:
            self.ignored_without_metadata += 1  # joined mid-run: wait for the next run's metadata
            return

        if env.kind == "event":
            await self._accept(state, env.payload)
        elif env.kind == "tracking":
            state.last_frame = env.payload
            if env.payload.game_clock_s >= state.game_time_s:  # keep the clock moving during dead balls
                state.game_time_s = env.payload.game_clock_s
                state.clock_s = int(env.payload.game_clock_s)
            await self._call(self.on_tracking, env.payload, state)
        elif env.kind == "control":
            action = env.payload.action
            state.replay_status = {"paused": "paused", "run_finished": "finished"}.get(action, "running")
            if action == "run_finished":
                await self._flush(state, force=True)
            await self._call(self.on_control, env.payload, state)

    async def _accept(self, state: MatchState, e: SyntheticEvent) -> None:
        if e.event_id in state.seen or e.seq < state.next_seq:
            state.duplicates_dropped += 1
            return
        state.seen.add(e.event_id)
        if e.seq != state.next_seq:
            state.reordered += 1
        heapq.heappush(state.buffer, (e.seq, e.event_id, e))
        await self._flush(state)

    async def _flush(self, state: MatchState, force: bool = False) -> None:
        while state.buffer:
            seq = state.buffer[0][0]
            if seq != state.next_seq:
                if not force and len(state.buffer) <= self.reorder_window:
                    return
                state.gaps_skipped += seq - state.next_seq  # give up waiting for missing events
                state.next_seq = seq
            _, _, e = heapq.heappop(state.buffer)
            state.next_seq = e.seq + 1
            state.apply(e)
            if self.sink:
                self.sink.write(e, state.run_id)
            await self._call(self.on_event, e, state)
