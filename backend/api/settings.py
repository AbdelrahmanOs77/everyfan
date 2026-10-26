"""All runtime configuration comes from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _list(name: str, default: str) -> list[str]:
    return [v.strip() for v in os.getenv(name, default).split(",") if v.strip()]


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


@dataclass
class Settings:
    transport: str = field(default_factory=lambda: os.getenv("STREAM_TRANSPORT", "local").lower())
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", ROOT / "data")))
    demo_dir: Path = field(default_factory=lambda: Path(os.getenv("DEMO_DIR", ROOT / "demo")))
    frontend_origins: list[str] = field(default_factory=lambda: _list("FRONTEND_ORIGIN", "http://localhost:5173"))
    broadcast_delay_s: float = field(default_factory=lambda: _float("BROADCAST_DELAY_S", 6.0))
    allowed_speeds: list[float] = field(default_factory=lambda: [float(v) for v in _list("ALLOWED_SPEEDS", "1,5,10,20")])
    admin_token: str | None = field(default_factory=lambda: os.getenv("ADMIN_TOKEN") or None)
    # Abuse and cost protection
    start_per_minute: float = field(default_factory=lambda: _float("RATE_LIMIT_START_PER_MIN", 3))
    control_per_minute: float = field(default_factory=lambda: _float("RATE_LIMIT_CONTROL_PER_MIN", 30))
    read_per_minute: float = field(default_factory=lambda: _float("RATE_LIMIT_READ_PER_MIN", 240))
    max_ws_per_client: int = field(default_factory=lambda: _int("MAX_WS_PER_CLIENT", 6))
    max_ws_total: int = field(default_factory=lambda: _int("MAX_WS_TOTAL", 200))
    max_active_live: int = field(default_factory=lambda: _int("MAX_ACTIVE_LIVE_REPLAYS", 2))
    idle_stop_s: float = field(default_factory=lambda: _float("IDLE_STOP_S", 300))
    daily_token_cap: int = field(default_factory=lambda: _int("LIVE_MODE_DAILY_TOKEN_CAP", 200_000))
    budget_file: Path = field(default_factory=lambda: Path(os.getenv("BUDGET_FILE", "/tmp/everyfan_budget.json")))
    # Analytics (Owner B) publishes moments; agents (Owner C) turn them into verified overlays.
    # backend.api.template_plugin:register is Owner A's original goal/red-card stand-in: do not load it
    # together with the agents plugin, or goals are shown twice.
    plugins: list[str] = field(default_factory=lambda: _list(
        "PIPELINE_PLUGINS", "backend.analytics.plugin:register,backend.agents.plugin:register"))
    preload: list[str] = field(default_factory=lambda: _list("PRELOAD_MATCHES", "match_001"))
    max_loaded_matches: int = field(default_factory=lambda: _int("MAX_LOADED_MATCHES", 2))
    version: str = field(default_factory=lambda: os.getenv("APP_VERSION", "dev"))
