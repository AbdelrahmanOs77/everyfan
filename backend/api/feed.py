"""Builds viewer messages (see hub.py) from consumer callbacks. Shared by live and demo modes.

Tracking is sent in a compact form to keep WebSocket traffic small:
    {"frame": 1527, "period": 1, "ball": [52.1, 31.0], "players": [["nil_07", 40.2, 26.5], ...]}
"""

from __future__ import annotations

from shared.schemas import ControlMessage, SyntheticEvent, TrackingFrame

from backend.services.consumer import MatchState

from .hub import message


def reset_msg(state: MatchState) -> dict:
    return message("reset", state.match_id, state.run_id, 0.0, {"reason": "new_run"})


def metadata_msg(state: MatchState) -> dict:
    return message("metadata", state.match_id, state.run_id, 0.0, state.metadata.model_dump(exclude_none=True))


def state_msg(state: MatchState) -> dict:
    return message("state", state.match_id, state.run_id, state.game_time_s, state.to_dict())


def event_msg(e: SyntheticEvent, state: MatchState) -> dict:
    return message("event", state.match_id, state.run_id, e.game_time_s, e.model_dump(exclude_none=True))


def tracking_msg(f: TrackingFrame, state: MatchState) -> dict:
    return message("tracking", state.match_id, state.run_id, f.game_clock_s, {
        "frame": f.frame,
        "period": f.period,
        "ball": [f.ball.x_m, f.ball.y_m],
        "players": [[p.player_id, p.x_m, p.y_m] for p in f.players],
    })


def control_msg(c: ControlMessage, state: MatchState) -> dict:
    return message("control", state.match_id, state.run_id, state.game_time_s, c.model_dump(exclude_none=True))


def replay_msg(match_id: str, status: dict, mode: str) -> dict:
    return message("replay", match_id, status.get("run_id"), status.get("game_time_s", 0.0), {**status, "mode": mode})
