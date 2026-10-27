"""Match-independent benchmark rows, built once per library and configuration."""

import asyncio
from weakref import WeakKeyDictionary

from .evidence import MatchEvidence
from .player_profile import reference_rows

_pools = WeakKeyDictionary()


class ReferencePool:
    def __init__(self, library):
        self.library, self.rows, self.lock = library, {}, asyncio.Lock()

    async def other_matches(self, match_id):
        async with self.lock:
            for item in self.library.catalog() if hasattr(self.library, "catalog") else []:
                mid = item["match_id"]
                if mid == match_id or mid in self.rows:
                    continue
                match = await self.library.get(mid)

                def build():
                    ev = MatchEvidence(match.metadata, match.events, match.frames)
                    return reference_rows(ev)

                self.rows[mid] = await asyncio.to_thread(build)
        return [row for mid, rows in self.rows.items() if mid != match_id for row in rows]


async def reference_pool(library, match_id):
    if library not in _pools:
        _pools[library] = ReferencePool(library)
    return await _pools[library].other_matches(match_id)
