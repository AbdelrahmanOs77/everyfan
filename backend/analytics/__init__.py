"""EveryFan match intelligence (Owner B): metrics, indices, moments, evidence and persistence.

    from backend.analytics import MatchAnalytics, MomentDetector
    PIPELINE_PLUGINS=backend.analytics.plugin:register

Everything here is deterministic Python: the same events give byte-identical stats and moments.
"""

from .config import load_config
from .engine import MatchAnalytics, PlayerTracker
from .moments import MomentDetector

__all__ = ["load_config", "MatchAnalytics", "PlayerTracker", "MomentDetector"]
