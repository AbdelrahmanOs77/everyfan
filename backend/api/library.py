"""Loads generated matches on demand (LRU: a match uses ~155 MB in memory)."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from shared.schemas import MatchMetadata, ScenarioSpec, SyntheticEvent, TrackingFrame

from backend.simulator.generator import generate, list_scenarios, load_match, load_scenario, write_match


@dataclass
class LoadedMatch:
    spec: ScenarioSpec
    metadata: MatchMetadata
    events: list[SyntheticEvent]
    frames: list[TrackingFrame]


class MatchLibrary:
    def __init__(self, data_dir: Path, max_loaded: int = 2) -> None:
        self.data_dir = Path(data_dir)
        self.max_loaded = max(1, max_loaded)
        self.specs: dict[str, ScenarioSpec] = {}
        for sid in list_scenarios():
            spec = load_scenario(sid)
            self.specs[spec.match_id] = spec
        self._loaded: OrderedDict[str, LoadedMatch] = OrderedDict()
        self._lock = asyncio.Lock()

    def catalog(self) -> list[dict]:
        return [{"match_id": s.match_id, "scenario_id": s.scenario_id, "title": s.title,
                 "description": s.description, "home_team_id": s.home.team_id, "away_team_id": s.away.team_id}
                for s in sorted(self.specs.values(), key=lambda s: s.match_id)]

    def has(self, match_id: str) -> bool:
        return match_id in self.specs

    def _load_sync(self, match_id: str) -> LoadedMatch:
        spec = self.specs[match_id]
        folder = self.data_dir / match_id
        if not (folder / "events.jsonl").exists():
            write_match(generate(spec), self.data_dir)
        meta, events, frames = load_match(folder)
        return LoadedMatch(spec, meta, events, frames)

    async def get(self, match_id: str) -> LoadedMatch:
        if match_id not in self.specs:
            raise KeyError(match_id)
        async with self._lock:
            if match_id in self._loaded:
                self._loaded.move_to_end(match_id)
                return self._loaded[match_id]
            m = await asyncio.to_thread(self._load_sync, match_id)
            self._loaded[match_id] = m
            while len(self._loaded) > self.max_loaded:
                self._loaded.popitem(last=False)
            return m

    def loaded(self) -> list[str]:
        return list(self._loaded)
