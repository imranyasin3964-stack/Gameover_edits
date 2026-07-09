"""
⚙️ GAMEOVER EDITS — Configuration
Load all credentials and settings from the .env file.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── Bot Credentials ────────────────────────────────────────────────────────
    API_ID: int    = int(os.getenv("API_ID", 0))
    API_HASH: str  = os.getenv("API_HASH", "")
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

    # ── Bot Identity ───────────────────────────────────────────────────────────
    BOT_NAME: str     = "🎬 GAMEOVER EDITS"
    BOT_USERNAME: str = os.getenv("BOT_USERNAME", "")

    # ── Owner / Admin ──────────────────────────────────────────────────────────
    # Your personal Telegram User ID. Get it from @userinfobot
    OWNER_ID: int = int(os.getenv("OWNER_ID", 0))

    # Optional welcoming video/GIF file path or URL for /start command
    START_VIDEO: str = os.getenv("START_VIDEO", "")

    # ── Limits ─────────────────────────────────────────────────────────────────
    # How many free renders a normal user gets per day
    DAILY_FREE_LIMIT: int = 1

    # Max video file size the bot will accept for editing (in MB)
    MAX_VIDEO_SIZE_MB: int = 500

    # ── File Paths ─────────────────────────────────────────────────────────────
    DOWNLOADS_DIR: str = os.getenv("DOWNLOADS_DIR", "downloads")
    DB_PATH: str       = os.getenv("DB_PATH", "gameedit.db")

    # ── Watermark ─────────────────────────────────────────────────────────────
    WATERMARK_TEXT: str = "GAMEOVER EDITS"
    # Font file for watermark. If None, FFmpeg default font is used.
    WATERMARK_FONT: str = os.getenv("WATERMARK_FONT", "")

    @staticmethod
    def validate():
        """Check that all required env vars are set before bot starts."""
        missing = []
        if not Config.API_ID:
            missing.append("API_ID")
        if not Config.API_HASH:
            missing.append("API_HASH")
        if not Config.BOT_TOKEN:
            missing.append("BOT_TOKEN")
        if not Config.OWNER_ID:
            missing.append("OWNER_ID")

        if missing:
            raise ValueError(
                f"\n\n❌ .env mein ye fields missing hain:\n"
                + "\n".join(f"  - {m}" for m in missing)
                + "\n\nPehle .env fill karo phir bot chalao!\n"
            )
