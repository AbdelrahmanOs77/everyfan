"""Small model interface; deterministic offline implementation for CI."""

import json
from typing import Protocol


class ModelClient(Protocol):
    async def complete(self, system: str, user: str, json_schema: dict | None = None) -> tuple[str, int]: ...


class StubModel:
    """Return caller-provided grounded fixtures, never invent text or contact a service.

    User payload: {"task": "writer", "template": {"headline": ..., "body": ..., "fields": ...}}
    or {"task": "analyst", "brief": <Contract D>}.
    Zero tokens means zero model usage, rather than a fabricated token count.
    """

    name = "stub"

    async def complete(self, system: str, user: str, json_schema: dict | None = None) -> tuple[str, int]:
        payload = json.loads(user)
        task = payload.get("task")
        if task == "writer":
            template = payload["template"]
            result = {key: template[key] for key in ("headline", "body", "fields")}
        elif task == "analyst":
            result = payload["brief"]
        else:
            raise ValueError(f"Unsupported stub task: {task!r}")
        return json.dumps(result, ensure_ascii=False), 0
