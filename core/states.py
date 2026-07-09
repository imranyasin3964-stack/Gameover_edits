"""
🧠 GAMEOVER EDITS — User State Manager
Keeps track of what each user is currently doing (which quality they picked,
whether we are waiting for their video, etc.).

Uses a simple in-memory dict — no database needed for transient state.
State is automatically cleared after a render completes or is cancelled.
"""

import time
from typing import Optional


# ── State Schema ───────────────────────────────────────────────────────────────
# user_states[user_id] = {
#     "quality":    "1080p60" | "2k60" | "4k120",
#     "chat_id":    int,
#     "waiting":    True,      # True = bot is waiting for user to send video
#     "created_at": float,     # Unix timestamp — for auto-expiry
# }

_user_states: dict[int, dict] = {}

# State auto-expires after 10 minutes of inactivity
STATE_TTL_SECONDS = 600


def set_state(user_id: int, quality: str, chat_id: int):
    """Save that a user selected a quality and is now expected to send a video."""
    _user_states[user_id] = {
        "quality":    quality,
        "chat_id":    chat_id,
        "waiting":    True,
        "created_at": time.time(),
    }


def get_state(user_id: int) -> Optional[dict]:
    """
    Return the user's current state, or None if they have no active state
    or if the state has expired (TTL exceeded).
    """
    state = _user_states.get(user_id)
    if not state:
        return None

    # Auto-expire stale states
    if time.time() - state["created_at"] > STATE_TTL_SECONDS:
        clear_state(user_id)
        return None

    return state


def clear_state(user_id: int):
    """Remove user's state once their render is complete or cancelled."""
    _user_states.pop(user_id, None)


def is_waiting(user_id: int) -> bool:
    """Returns True if bot is waiting for this user to send a video."""
    state = get_state(user_id)
    return state is not None and state.get("waiting", False)
