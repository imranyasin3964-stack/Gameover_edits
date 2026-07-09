"""
🗄️ GAMEOVER EDITS — Database Layer (SQLite)
Handles:
  - Daily edit quota tracking per user (free = 1 edit/day)
  - Premium user registry (admin-managed, unlimited edits)
  - Auto-resets daily count on a new calendar day (UTC)
"""

import sqlite3
import asyncio
from datetime import date, datetime, timezone
from typing import Optional


DB_PATH = "gameedit.db"


def _get_today() -> str:
    """Return today's date as 'YYYY-MM-DD' string (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DB_PATH):
    """
    Create the database tables if they don't exist.
    Called once on bot startup.
    """
    global DB_PATH
    DB_PATH = db_path

    with _connect() as conn:
        conn.executescript("""
            -- Tracks how many free edits each user has used today
            CREATE TABLE IF NOT EXISTS daily_usage (
                user_id     INTEGER NOT NULL,
                date        TEXT    NOT NULL,
                edit_count  INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, date)
            );

            -- Registry of all premium (unlimited) users
            CREATE TABLE IF NOT EXISTS premium_users (
                user_id     INTEGER PRIMARY KEY,
                added_by    INTEGER,            -- Admin who added this user
                added_at    TEXT NOT NULL        -- ISO timestamp
            );
        """)
        conn.commit()

    print(f"[DB] ✅ Database initialized: {db_path}")


# ── Premium Management ─────────────────────────────────────────────────────────

def is_premium(user_id: int) -> bool:
    """Check if a user has premium (unlimited) access."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM premium_users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row is not None


def add_premium(user_id: int, added_by: int) -> bool:
    """
    Grant premium to a user. Returns True if newly added, False if already premium.
    """
    if is_premium(user_id):
        return False
    with _connect() as conn:
        conn.execute(
            "INSERT INTO premium_users (user_id, added_by, added_at) VALUES (?, ?, ?)",
            (user_id, added_by, datetime.now(timezone.utc).isoformat())
        )
        conn.commit()
    return True


def remove_premium(user_id: int) -> bool:
    """
    Revoke premium from a user. Returns True if removed, False if wasn't premium.
    """
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM premium_users WHERE user_id = ?", (user_id,)
        )
        conn.commit()
        return cursor.rowcount > 0


def list_premium_users() -> list[int]:
    """Return a list of all premium user IDs."""
    with _connect() as conn:
        rows = conn.execute("SELECT user_id FROM premium_users").fetchall()
        return [row["user_id"] for row in rows]


# ── Daily Quota ────────────────────────────────────────────────────────────────

def get_today_count(user_id: int) -> int:
    """Return how many edits this user has used today (resets each UTC day)."""
    today = _get_today()
    with _connect() as conn:
        row = conn.execute(
            "SELECT edit_count FROM daily_usage WHERE user_id = ? AND date = ?",
            (user_id, today)
        ).fetchone()
        return row["edit_count"] if row else 0


def can_edit(user_id: int, daily_limit: int) -> bool:
    """
    Returns True if the user is allowed to start a new render.
    Premium users always return True. Free users check daily quota.
    """
    if is_premium(user_id):
        return True
    return get_today_count(user_id) < daily_limit


def record_edit(user_id: int):
    """
    Increment today's edit count by 1.
    Uses INSERT OR REPLACE to create the row if it doesn't exist yet.
    """
    today = _get_today()
    with _connect() as conn:
        conn.execute("""
            INSERT INTO daily_usage (user_id, date, edit_count)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, date) DO UPDATE SET edit_count = edit_count + 1
        """, (user_id, today))
        conn.commit()


def get_remaining_edits(user_id: int, daily_limit: int) -> int:
    """
    Return how many more free edits the user has today.
    Returns -1 for premium users (unlimited).
    """
    if is_premium(user_id):
        return -1  # -1 = unlimited
    used = get_today_count(user_id)
    return max(0, daily_limit - used)


# ── Stats ──────────────────────────────────────────────────────────────────────

def get_total_edits_today() -> int:
    """Return total number of renders done today across all users."""
    today = _get_today()
    with _connect() as conn:
        row = conn.execute(
            "SELECT SUM(edit_count) as total FROM daily_usage WHERE date = ?",
            (today,)
        ).fetchone()
        return row["total"] if row["total"] else 0


def get_all_time_total() -> int:
    """Return total renders ever done through this bot."""
    with _connect() as conn:
        row = conn.execute("SELECT SUM(edit_count) as total FROM daily_usage").fetchone()
        return row["total"] if row["total"] else 0
