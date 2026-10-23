"""Loads backend/analytics/config.yaml (override the path with ANALYTICS_CONFIG)."""

from __future__ import annotations

import copy
import os
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).with_name("config.yaml")


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_config(path: str | Path | None = None) -> dict:
    """A private copy of the analytics config, so callers can tweak it in tests."""
    return copy.deepcopy(_load(str(path or os.getenv("ANALYTICS_CONFIG") or DEFAULT_PATH)))
