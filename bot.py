"""
🎬 GAMEOVER EDITS — Main Entry Point
Starts the Pyrogram bot, loads all plugins, and initialises the render queue.
"""

import os
import asyncio
import importlib

from pyrogram import Client
from pyrogram.types import BotCommand

from config import Config
from core.db import init_db
from core.queue import render_queue


# ── Plugins to load (in order) ─────────────────────────────────────────────────
PLUGINS = [
    "plugins.help",
    "plugins.admin",
    "plugins.edit",
]


async def set_bot_commands(app: Client):
    """Register the bot's command menu in Telegram (shown in the / menu)."""
    await app.set_bot_commands([
        BotCommand("start",   "🎬 Welcome message & your status"),
        BotCommand("edit",    "🎥 Open quality menu and start editing"),
        BotCommand("help",    "📖 Show full usage guide"),
        BotCommand("premium", "💎 View premium plans"),
    ])
    print("[Bot] ✅ Bot commands registered.")


async def main():
    # ── Pre-flight checks ──────────────────────────────────────────────────────
    Config.validate()

    # ── Ensure directories exist ───────────────────────────────────────────────
    os.makedirs(Config.DOWNLOADS_DIR, exist_ok=True)
    os.makedirs(os.path.join("downloads", "renders"), exist_ok=True)
    os.makedirs(os.path.join("downloads", "input"), exist_ok=True)

    # ── Initialise SQLite database ─────────────────────────────────────────────
    init_db(Config.DB_PATH)

    # ── Start Pyrogram client ──────────────────────────────────────────────────
    app = Client(
        name="gameover_edits",
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        bot_token=Config.BOT_TOKEN,
    )

    # ── Load all plugins ───────────────────────────────────────────────────────
    for plugin_path in PLUGINS:
        module = importlib.import_module(plugin_path)
        if hasattr(module, "register"):
            module.register(app)
            print(f"[Bot] ✅ Plugin loaded: {plugin_path}")
        else:
            print(f"[Bot] ⚠️  Plugin has no register() function: {plugin_path}")

    # ── Start everything ───────────────────────────────────────────────────────
    async with app:
        # Register bot commands in Telegram menu
        await set_bot_commands(app)

        # Start render queue worker
        await render_queue.start()

        me = await app.get_me()
        print(f"\n{'='*50}")
        print(f"🎬 GAMEOVER EDITS BOT STARTED!")
        print(f"   Username : @{me.username}")
        print(f"   Bot ID   : {me.id}")
        print(f"   Owner ID : {Config.OWNER_ID}")
        print(f"{'='*50}\n")

        # Keep running
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
