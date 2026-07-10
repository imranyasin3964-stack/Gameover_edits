"""
🗄️ GAMEOVER EDITS — Database Layer (SQLite)
Handles:
  - Daily edit quota tracking per user (free = 1 edit/day)
  - Time-limited Premium user subscriptions (expiry_date stored as ISO-8601 UTC)
  - Auto-resets daily count on a new calendar day (UTC)
  - Custom credits management
  - User registration
  - Dynamic bot settings (key/value store)

Schema notes:
  premium_users.expiry_date — ISO-8601 UTC string, e.g. "2026-08-08T14:05:32+00:00"
  is_premium() compares expiry_date > utcnow() so access expires automatically.
  Owner (Config.OWNER_ID) is always premium regardless of the table.
"""

import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional


import time

DB_PATH = "gameedit.db"


# ── Internal helpers ────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    """Return current UTC time as an aware datetime."""
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat()


def _get_today() -> str:
    """Return today's date as 'YYYY-MM-DD' string (UTC)."""
    return _now_utc().strftime("%Y-%m-%d")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Initialisation ──────────────────────────────────────────────────────────────

def init_db(db_path: str = DB_PATH):
    """
    Create / migrate database tables.
    Called once on bot startup.
    Safe to call on an existing database — uses ALTER TABLE to add the
    expiry_date column if it is missing (forward-migration for old DBs).
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

            -- Time-limited premium (VIP) subscriptions
            CREATE TABLE IF NOT EXISTS premium_users (
                user_id     INTEGER PRIMARY KEY,
                added_by    INTEGER,
                added_at    TEXT NOT NULL,
                expiry_date TEXT NOT NULL        -- ISO-8601 UTC; access valid while now < expiry_date
            );

            -- Tracks custom render credits given to standard users
            CREATE TABLE IF NOT EXISTS user_credits (
                user_id     INTEGER PRIMARY KEY,
                credits     INTEGER NOT NULL DEFAULT 0,
                updated_at  TEXT NOT NULL
            );

            -- Tracks all registered users
            CREATE TABLE IF NOT EXISTS users (
                user_id         INTEGER PRIMARY KEY,
                username        TEXT,
                first_name      TEXT,
                last_name       TEXT,
                joined_at       TEXT NOT NULL,
                last_used_time  REAL DEFAULT 0,
                referred_by     INTEGER
            );

            -- Dynamic bot settings (key/value store)
            CREATE TABLE IF NOT EXISTS settings (
                key         TEXT PRIMARY KEY,
                value       TEXT
            );

            -- Users with watermark disabled
            CREATE TABLE IF NOT EXISTS no_watermark_users (
                user_id     INTEGER PRIMARY KEY
            );
        """)
        conn.commit()

        # ── Forward-migration: add columns if upgrading from an old DB ────
        try:
            conn.execute("ALTER TABLE premium_users ADD COLUMN expiry_date TEXT NOT NULL DEFAULT ''")
            conn.commit()
            far_future = (_now_utc() + timedelta(days=3650)).isoformat()
            conn.execute(
                "UPDATE premium_users SET expiry_date = ? WHERE expiry_date = ''",
                (far_future,)
            )
            conn.commit()
            print("[DB] ⬆️  Migrated premium_users table: added expiry_date column.")
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("ALTER TABLE users ADD COLUMN last_used_time REAL DEFAULT 0")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    print(f"[DB] ✅ Database initialized: {db_path}")


# ── Premium Management ──────────────────────────────────────────────────────────

def is_premium(user_id: int) -> bool:
    """
    Return True if the user currently has an active Premium subscription.

    Rules:
      1. Owner is always premium (never expires).
      2. Otherwise check premium_users: row must exist AND expiry_date > now.
         Expired rows are ignored (they just become free users automatically).
    """
    from config import Config
    if user_id == Config.OWNER_ID:
        return True

    now_str = _now_iso()
    with _connect() as conn:
        row = conn.execute(
            "SELECT expiry_date FROM premium_users WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        if row is None:
            return False
        # ISO-8601 string comparison works correctly for UTC timestamps
        return row["expiry_date"] > now_str


def grant_premium(user_id: int, days: int, added_by: int) -> datetime:
    """
    Grant or extend Premium access for `days` days from NOW.

    If the user already has an active subscription, the new expiry is calculated
    from NOW (not stacked on top of the existing expiry).  This keeps the
    behaviour predictable for the admin.

    Returns the new expiry datetime (UTC, aware).
    """
    expiry_dt  = _now_utc() + timedelta(days=days)
    expiry_iso = expiry_dt.isoformat()
    now_iso    = _now_iso()

    with _connect() as conn:
        conn.execute("""
            INSERT INTO premium_users (user_id, added_by, added_at, expiry_date)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                added_by    = excluded.added_by,
                added_at    = excluded.added_at,
                expiry_date = excluded.expiry_date
        """, (user_id, added_by, now_iso, expiry_iso))
        conn.commit()

    return expiry_dt


# Backward-compatible alias used by existing callback buttons ("makevip")
def add_premium(user_id: int, added_by: int, days: int = 36500) -> bool:
    """
    Legacy wrapper: grants premium for `days` days (default 100 years ≈ permanent).
    Returns True always (consistent with old behaviour).
    """
    grant_premium(user_id, days=days, added_by=added_by)
    return True


def remove_premium(user_id: int) -> bool:
    """
    Immediately revoke Premium by setting expiry_date to the past.
    Returns True if a row was updated, False if user was not in the table.
    """
    past_iso = (_now_utc() - timedelta(seconds=1)).isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE premium_users SET expiry_date = ? WHERE user_id = ?",
            (past_iso, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def get_premium_expiry(user_id: int) -> Optional[datetime]:
    """
    Return the expiry datetime (UTC, aware) for a user, or None if not premium.
    For the Owner, returns None (owner is unconditionally premium — no expiry concept).
    """
    from config import Config
    if user_id == Config.OWNER_ID:
        return None  # Owner has no expiry

    with _connect() as conn:
        row = conn.execute(
            "SELECT expiry_date FROM premium_users WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        if row is None or not row["expiry_date"]:
            return None
        try:
            return datetime.fromisoformat(row["expiry_date"])
        except ValueError:
            return None


def list_premium_users() -> list[dict]:
    """
    Return a list of dicts for all users that currently have active subscriptions.
    Each dict: {"user_id": int, "expiry_date": str}
    Expired entries are excluded.
    """
    now_str = _now_iso()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT user_id, expiry_date FROM premium_users WHERE expiry_date > ?",
            (now_str,)
        ).fetchall()
        return [{"user_id": row["user_id"], "expiry_date": row["expiry_date"]} for row in rows]


# ── Custom Credits Management ───────────────────────────────────────────────────

def get_credits(user_id: int) -> int:
    """Return custom render credits for a user. Default 0."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT credits FROM user_credits WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["credits"] if row else 0


def add_credits(user_id: int, amount: int) -> int:
    """Add (or subtract) custom credits. Returns new total."""
    current   = get_credits(user_id)
    new_total = max(0, current + amount)
    now_iso   = _now_iso()
    with _connect() as conn:
        conn.execute("""
            INSERT INTO user_credits (user_id, credits, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET credits = ?, updated_at = ?
        """, (user_id, new_total, now_iso, new_total, now_iso))
        conn.commit()
    return new_total


def use_credit(user_id: int) -> bool:
    """Decrement a user's custom credits by 1. Returns True on success."""
    if get_credits(user_id) <= 0:
        return False
    with _connect() as conn:
        conn.execute(
            "UPDATE user_credits SET credits = credits - 1, updated_at = ? WHERE user_id = ?",
            (_now_iso(), user_id)
        )
        conn.commit()
    return True


# ── Daily Quota ─────────────────────────────────────────────────────────────────

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
    Returns True if the user may start a new render.
      • Premium users → always True
      • Users with custom credits → True (credits deducted on record_edit)
      • Free users → True if daily count < daily_limit
    """
    if is_premium(user_id):
        return True
    if get_credits(user_id) > 0:
        return True
    return get_today_count(user_id) < daily_limit


def record_edit(user_id: int):
    """
    Record one render for quota and statistics purposes.
      • Users with credits → decrement one credit
      • Increment daily counter in daily_usage for all users (including premium)
    """
    if not is_premium(user_id) and get_credits(user_id) > 0:
        use_credit(user_id)
        # Continue to record in daily_usage for stats
    
    # Update last used time for anti-spam cooldown
    set_last_used_time(user_id, time.time())
    
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
    Return remaining edits for display purposes.
      • -1 = unlimited (premium)
      • ≥0 = exact count remaining
    """
    if is_premium(user_id):
        return -1
    credits = get_credits(user_id)
    if credits > 0:
        return credits
    used = get_today_count(user_id)
    return max(0, daily_limit - used)


# ── Stats ───────────────────────────────────────────────────────────────────────

def get_total_edits_today() -> int:
    """Total renders done today across all users."""
    today = _get_today()
    with _connect() as conn:
        row = conn.execute(
            "SELECT SUM(edit_count) as total FROM daily_usage WHERE date = ?",
            (today,)
        ).fetchone()
        return row["total"] if row["total"] else 0


def get_all_time_total() -> int:
    """Total renders ever processed by this bot."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT SUM(edit_count) as total FROM daily_usage"
        ).fetchone()
        return row["total"] if row["total"] else 0


# ── User Registration ───────────────────────────────────────────────────────────

def add_user(
    user_id: int,
    username: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
    referred_by: Optional[int] = None
) -> bool:
    """
    Register or update a user.
    Returns True if this is a brand-new user, False if they already existed.
    """
    joined_at = _now_iso()
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET username = ?, first_name = ?, last_name = ? WHERE user_id = ?",
                (username or "", first_name or "", last_name or "", user_id)
            )
            conn.commit()
            return False
        conn.execute(
            "INSERT INTO users (user_id, username, first_name, last_name, joined_at, referred_by, last_used_time) "
            "VALUES (?, ?, ?, ?, ?, ?, 0)",
            (user_id, username or "", first_name or "", last_name or "", joined_at, referred_by)
        )
        conn.commit()
        return True


def get_last_used_time(user_id: int) -> float:
    with _connect() as conn:
        row = conn.execute("SELECT last_used_time FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return row["last_used_time"] if row and row["last_used_time"] else 0.0


def set_last_used_time(user_id: int, timestamp: float):
    with _connect() as conn:
        conn.execute("UPDATE users SET last_used_time = ? WHERE user_id = ?", (timestamp, user_id))
        conn.commit()


def get_cooldown_remaining(user_id: int) -> float:
    """Return remaining cooldown seconds. Premium users have 0 cooldown."""
    if is_premium(user_id):
        return 0.0
    last_used = get_last_used_time(user_id)
    if not last_used:
        return 0.0
    elapsed = time.time() - last_used
    remaining = 1800.0 - elapsed  # 30 minutes = 1800 seconds
    return max(0.0, remaining)


# ── Settings ────────────────────────────────────────────────────────────────────

def get_setting(key: str, default: str = "") -> str:
    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = ?",
            (key, value, value)
        )
        conn.commit()


# ── Internal: count active premium users (for stats panel) ─────────────────────

def count_active_premium() -> int:
    """Number of users with a currently-active subscription (owner excluded)."""
    return len(list_premium_users())


# ── Watermark Remover Toggles ───────────────────────────────────────────────────

def has_watermark_disabled(user_id: int) -> bool:
    """Check if a user has their watermark disabled."""
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM no_watermark_users WHERE user_id = ?", (user_id,)).fetchone()
        return row is not None


def toggle_watermark(user_id: int) -> bool:
    """Toggle watermark status. Returns True if watermark is now disabled, False if enabled."""
    current = has_watermark_disabled(user_id)
    with _connect() as conn:
        if current:
            conn.execute("DELETE FROM no_watermark_users WHERE user_id = ?", (user_id,))
            conn.commit()
            return False
        else:
            conn.execute("INSERT OR IGNORE INTO no_watermark_users (user_id) VALUES (?)", (user_id,))
            conn.commit()
            return True


# ── List Users Directory ─────────────────────────────────────────────────────────

def list_all_users() -> list[dict]:
    """Retrieve all registered users ordered by joined date."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT user_id, username, first_name, last_name, joined_at "
            "FROM users ORDER BY joined_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]
