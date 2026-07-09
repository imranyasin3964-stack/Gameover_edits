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

            -- Tracks custom credits given to standard users
            CREATE TABLE IF NOT EXISTS user_credits (
                user_id     INTEGER PRIMARY KEY,
                credits     INTEGER NOT NULL DEFAULT 0,
                updated_at  TEXT NOT NULL
            );

            -- Tracks all registered users
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                first_name  TEXT,
                last_name   TEXT,
                joined_at   TEXT NOT NULL
            );

            -- Tracks dynamic bot settings
            CREATE TABLE IF NOT EXISTS settings (
                key         TEXT PRIMARY KEY,
                value       TEXT
            );
        """)
        conn.commit()

    print(f"[DB] ✅ Database initialized: {db_path}")


# ── Premium Management ─────────────────────────────────────────────────────────

def is_premium(user_id: int) -> bool:
    """Check if a user has premium (unlimited) access. Owner is always premium."""
    from config import Config
    if user_id == Config.OWNER_ID:
        return True
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


# ── Custom Credits Management ──────────────────────────────────────────────────

def get_credits(user_id: int) -> int:
    """Return custom credits of a user. Default is 0."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT credits FROM user_credits WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["credits"] if row else 0


def add_credits(user_id: int, amount: int) -> int:
    """
    Add or set custom credits for a user. Returns new total.
    """
    current = get_credits(user_id)
    new_total = max(0, current + amount)
    with _connect() as conn:
        conn.execute("""
            INSERT INTO user_credits (user_id, credits, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET credits = ?, updated_at = ?
        """, (user_id, new_total, datetime.now(timezone.utc).isoformat(), new_total, datetime.now(timezone.utc).isoformat()))
        conn.commit()
    return new_total


def use_credit(user_id: int) -> bool:
    """
    Decrement a user's custom credits by 1. Returns True if successful.
    """
    current = get_credits(user_id)
    if current <= 0:
        return False
    with _connect() as conn:
        conn.execute(
            "UPDATE user_credits SET credits = credits - 1, updated_at = ? WHERE user_id = ?",
            (datetime.now(timezone.utc).isoformat(), user_id)
        )
        conn.commit()
    return True


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
    Premium users always return True.
    If the user has custom credits > 0, returns True.
    Otherwise, checks daily free limit.
    """
    if is_premium(user_id):
        return True
    if get_credits(user_id) > 0:
        return True
    return get_today_count(user_id) < daily_limit


def record_edit(user_id: int):
    """
    Increment today's edit count by 1.
    If user has custom credits > 0, decrement that instead.
    """
    if is_premium(user_id):
        return
    if get_credits(user_id) > 0:
        use_credit(user_id)
        return
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
    Return how many more edits the user has.
    Returns -1 for premium users (unlimited).
    Returns custom credits if user has custom credits.
    Otherwise returns remaining free daily edits.
    """
    if is_premium(user_id):
        return -1  # -1 = unlimited
    credits = get_credits(user_id)
    if credits > 0:
        return credits
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


# ── Settings & User Management ──────────────────────────────────────────────────

def add_user(user_id: int, username: str, first_name: str, last_name: str) -> bool:
    """
    Add a user to the database. Returns True if newly added, False if already exists.
    """
    joined_at = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET username = ?, first_name = ?, last_name = ? WHERE user_id = ?",
                (username or "", first_name or "", last_name or "", user_id)
            )
            conn.commit()
            return False

        conn.execute(
            "INSERT INTO users (user_id, username, first_name, last_name, joined_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, username or "", first_name or "", last_name or "", joined_at)
        )
        conn.commit()
        return True


def get_setting(key: str, default: str = "") -> str:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = ?",
            (key, value, value)
        )
        conn.commit()
