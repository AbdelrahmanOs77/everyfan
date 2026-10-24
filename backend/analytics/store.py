"""Cosmos DB persistence (optional): events, moments, briefs, overlays, audit, partitioned on /match_id.

Enabled when COSMOS_ENDPOINT is set; otherwise get_store() returns None and nothing is written.

    COSMOS_ENDPOINT=https://<account>.documents.azure.com:443/
    COSMOS_DATABASE=everyfan
    # auth: managed identity / `az login` (recommended, needs the Cosmos DB Built-in Data Contributor
    # data-plane role), or COSMOS_KEY for a quick test or a cross-tenant setup (keep it out of git).

Writes never block the match: documents go into a bounded in-memory queue and a background task
upserts them. Upserts are idempotent (events by event_id, moments by moment_id), so replays and
restarts do not create duplicates. Owner C can reuse it:

    from backend.analytics.store import get_store
    store = get_store()
    if store: store.enqueue("briefs", {"id": brief.moment_id, **brief.model_dump()})
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid

from shared.schemas import Moment, SyntheticEvent

log = logging.getLogger("everyfan.analytics.store")

CONTAINERS = ("events", "moments", "briefs", "overlays", "audit")


class CosmosStore:
    def __init__(self, endpoint: str, database: str = "everyfan", key: str | None = None,
                 max_queue: int = 20_000, concurrency: int = 8) -> None:
        self.endpoint, self.database, self.key = endpoint, database, key
        self.max_queue, self.concurrency = max_queue, concurrency
        self.queue: asyncio.Queue | None = None
        self._task: asyncio.Task | None = None
        self._events_written: set[tuple[str, str]] = set()
        self._pending: set[asyncio.Task] = set()
        self.written = self.failed = self.dropped = 0
        self.last_error: str | None = None
        self.last_write_at: float | None = None

    # ----------------------------------------------------------- producers

    def enqueue(self, container: str, doc: dict) -> None:
        if container not in CONTAINERS or "match_id" not in doc:
            raise ValueError(f"unknown container {container!r} or document without match_id")
        doc.setdefault("id", uuid.uuid4().hex)
        if self.queue is None:
            self.queue = asyncio.Queue(self.max_queue)
        if self._task is None or self._task.done():
            # A plain task (not ctx.spawn), so the demo builder's drain() never waits on it.
            self._task = asyncio.get_running_loop().create_task(self._writer())
        try:
            self.queue.put_nowait((container, doc))
        except asyncio.QueueFull:
            self.dropped += 1

    def add_event(self, e: SyntheticEvent, run_id: str | None = None) -> None:
        key = (e.match_id, e.event_id)
        if key in self._events_written:  # events are immutable: write each once per process
            return
        self._events_written.add(key)
        self.enqueue("events", {"id": e.event_id, "doc_type": "event", "run_id": run_id,
                                **e.model_dump(mode="json", exclude_none=True)})

    def add_moment(self, m: Moment, run_id: str | None = None) -> None:
        self.enqueue("moments", {"id": m.moment_id, "doc_type": "moment", "run_id": run_id,
                                 "detected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                 **m.model_dump(mode="json", exclude_none=True)})

    def audit(self, match_id: str, kind: str, payload: dict) -> None:
        self.enqueue("audit", {"match_id": match_id, "kind": kind, "at": time.time(), **payload})

    # -------------------------------------------------------------- writer

    def _client(self):
        from azure.cosmos.aio import CosmosClient

        if self.key:
            return CosmosClient(self.endpoint, credential=self.key), None
        from azure.identity.aio import DefaultAzureCredential

        cred = DefaultAzureCredential()  # managed identity in Azure (AZURE_CLIENT_ID), `az login` locally
        return CosmosClient(self.endpoint, credential=cred), cred

    async def _writer(self) -> None:
        client, cred = self._client()
        try:
            db = client.get_database_client(self.database)
            containers = {name: db.get_container_client(name) for name in CONTAINERS}
            pending = self._pending

            async def write(container: str, doc: dict) -> None:
                try:
                    await containers[container].upsert_item(doc)
                    self.written += 1
                    self.last_write_at = time.time()
                except Exception as exc:  # never let storage break the match
                    self.failed += 1
                    self.last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
                    if self.failed in (1, 10, 100) or self.failed % 1000 == 0:
                        log.warning("cosmos write failed (%s so far): %s", self.failed, self.last_error)

            while True:
                container, doc = await self.queue.get()
                if len(pending) >= self.concurrency:
                    await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                task = asyncio.create_task(write(container, doc))
                pending.add(task)
                task.add_done_callback(pending.discard)
        finally:
            await client.close()
            if cred is not None:
                await cred.close()

    async def flush(self, timeout: float = 30) -> None:
        """Wait until the queue is empty (tests and CLI)."""
        deadline = time.monotonic() + timeout
        while (self.queue is not None and not self.queue.empty() or self._pending) and time.monotonic() < deadline:
            await asyncio.sleep(0.1)

    def status(self) -> dict:
        return {"enabled": True, "endpoint": self.endpoint, "database": self.database,
                "auth": "key" if self.key else "entra_id", "written": self.written, "failed": self.failed,
                "dropped": self.dropped, "queued": self.queue.qsize() if self.queue else 0,
                "last_error": self.last_error}


_store: CosmosStore | None = None
_checked = False


def get_store() -> CosmosStore | None:
    """The process-wide store, or None when COSMOS_ENDPOINT is not set."""
    global _store, _checked
    if not _checked:
        _checked = True
        endpoint = os.getenv("COSMOS_ENDPOINT", "").strip()
        if endpoint:
            _store = CosmosStore(endpoint, os.getenv("COSMOS_DATABASE", "everyfan"),
                                 os.getenv("COSMOS_KEY") or None)
            log.info("Cosmos DB persistence on: %s / %s (%s)", endpoint, _store.database,
                     "key" if _store.key else "Entra ID")
    return _store
