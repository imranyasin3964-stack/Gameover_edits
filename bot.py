"""
🎬 GAMEOVER EDITS — Main Entry Point
Starts the Pyrogram bot, loads all plugins, and initialises the render queue.
"""

import os
import sys
import asyncio
import importlib

from pyrogram import Client
from pyrogram.types import BotCommand
import pyrogram.types
import inspect

# ── Redirect stdout/stderr to bot.log ──────────────────────────────────────────
class Logger(object):
    def __init__(self):
        self.terminal = sys.stdout
        self.log = open("bot.log", "a", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()

    def flush(self):
        self.terminal.flush()
        self.log.flush()

sys.stdout = Logger()
sys.stderr = Logger()

from config import Config
from core.db import init_db
from core.queue import render_queue

# ── Monkeypatch InlineKeyboardButton to support styling ───────────────────────
# Pyrofork and custom versions of Pyrogram support button styles (primary, success, danger)
# to render button colors. We patch the constructor to prevent TypeErrors on standard Pyrogram.
sig = inspect.signature(pyrogram.types.InlineKeyboardButton.__init__)
if "style" not in sig.parameters:
    original_init = pyrogram.types.InlineKeyboardButton.__init__
    def patched_init(self, *args, **kwargs):
        style = kwargs.pop("style", None)
        original_init(self, *args, **kwargs)
        if style is not None:
            self.style = style
    pyrogram.types.InlineKeyboardButton.__init__ = patched_init


# ── Plugins to load (in order) ─────────────────────────────────────────────────
PLUGINS = [
    "plugins.help",
    "plugins.admin",
    "plugins.edit",
    "plugins.lyrical",
]


async def set_bot_commands(app: Client):
    """Register the bot's command menu in Telegram (shown in the / menu)."""
    try:
        await asyncio.wait_for(app.set_bot_commands([
            BotCommand("start",   "🎬 Welcome message & your status"),
            BotCommand("edit",    "🎥 Open quality menu and start editing"),
            BotCommand("lyrics",  "🎵 Generate automated lyrical lofi status"),
            BotCommand("help",    "📖 Show full usage guide"),
            BotCommand("premium", "💎 View premium plans"),
        ]), timeout=10)
        print("[Bot] ✅ Bot commands registered.")
    except Exception as e:
        print(f"[Bot] ⚠️ Could not register bot commands: {e}")


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
    print("[Bot] 🚀 Initializing Pyrogram client...")
    app = Client(
        name="gameover_edits",
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        bot_token=Config.BOT_TOKEN,
    )

    # ── Load all plugins ───────────────────────────────────────────────────────
    print("[Bot] 📦 Loading plugins...")
    for plugin_path in PLUGINS:
        module = importlib.import_module(plugin_path)
        if hasattr(module, "register"):
            module.register(app)
            print(f"[Bot] ✅ Plugin loaded: {plugin_path}")
        else:
            print(f"[Bot] ⚠️  Plugin has no register() function: {plugin_path}")

    # ── Start everything ───────────────────────────────────────────────────────
    print("[Bot] 🌐 Connecting to Telegram...")
    async with app:
        me = await app.get_me()
        print(f"\n{'='*50}")
        print(f"🎬 GAMEOVER EDITS BOT STARTED!")
        print(f"   Username : @{me.username}")
        print(f"   Bot ID   : {me.id}")
        print(f"   Owner ID : {Config.OWNER_ID}")
        print(f"{'='*50}\n")

        # Start render queue worker
        await render_queue.start()

        # Register bot commands asynchronously
        asyncio.create_task(set_bot_commands(app))

        # Keep running
        try:
            await asyncio.Event().wait()
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Bot] 🛑 Bot stopped gracefully.")
