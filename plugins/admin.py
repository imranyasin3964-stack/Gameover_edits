"""
👑 GAMEOVER EDITS — Admin Commands
Owner-only commands for managing premium users and viewing bot stats.
"""

import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message

from config import Config
from core.db import (
    add_premium, remove_premium, list_premium_users,
    get_total_edits_today, get_all_time_total
)
from core.queue import render_queue


def _is_owner(user_id: int) -> bool:
    return user_id == Config.OWNER_ID


def register(app: Client):

    # ── /addpremium <user_id> ──────────────────────────────────────────────────
    @app.on_message(filters.command("addpremium"))
    async def add_premium_cmd(client: Client, message: Message):
        if not message.from_user or not _is_owner(message.from_user.id):
            await message.reply_text("❌ <b>Owner only command!</b>", parse_mode="html")
            return

        if len(message.command) < 2:
            await message.reply_text(
                "⚠️ <b>Usage:</b> <code>/addpremium &lt;user_id&gt;</code>",
                parse_mode="html"
            )
            return

        try:
            target_id = int(message.command[1])
        except ValueError:
            await message.reply_text("❌ <b>Invalid user ID.</b>", parse_mode="html")
            return

        added = add_premium(target_id, added_by=message.from_user.id)

        if added:
            await message.reply_text(
                f"✅ <b>User <code>{target_id}</code> has been granted Premium!</b>\n"
                f"💎 They now have unlimited renders and Beast Mode access.",
                parse_mode="html"
            )
            # Notify the user if possible
            try:
                await client.send_message(
                    target_id,
                    "🎉 <b>Congratulations! Your GAMEOVER EDITS account has been upgraded to Premium!</b>\n\n"
                    "💎 You now have:\n"
                    "  ✅ Unlimited daily renders\n"
                    "  ✅ 4K 120 FPS Beast Mode unlocked 🔓\n\n"
                    "Type /edit to start your first premium render!",
                    parse_mode="html"
                )
            except Exception:
                pass  # User may have not started the bot
        else:
            await message.reply_text(
                f"⚠️ <b>User <code>{target_id}</code> is already Premium.</b>",
                parse_mode="html"
            )

    # ── /removepremium <user_id> ───────────────────────────────────────────────
    @app.on_message(filters.command("removepremium"))
    async def remove_premium_cmd(client: Client, message: Message):
        if not message.from_user or not _is_owner(message.from_user.id):
            await message.reply_text("❌ <b>Owner only command!</b>", parse_mode="html")
            return

        if len(message.command) < 2:
            await message.reply_text(
                "⚠️ <b>Usage:</b> <code>/removepremium &lt;user_id&gt;</code>",
                parse_mode="html"
            )
            return

        try:
            target_id = int(message.command[1])
        except ValueError:
            await message.reply_text("❌ <b>Invalid user ID.</b>", parse_mode="html")
            return

        removed = remove_premium(target_id)

        if removed:
            await message.reply_text(
                f"✅ <b>Premium revoked from <code>{target_id}</code>.</b>\n"
                f"They are now on the free plan (1 edit/day).",
                parse_mode="html"
            )
        else:
            await message.reply_text(
                f"⚠️ <b>User <code>{target_id}</code> was not a Premium user.</b>",
                parse_mode="html"
            )

    # ── /listpremium ───────────────────────────────────────────────────────────
    @app.on_message(filters.command("listpremium"))
    async def list_premium_cmd(client: Client, message: Message):
        if not message.from_user or not _is_owner(message.from_user.id):
            await message.reply_text("❌ <b>Owner only command!</b>", parse_mode="html")
            return

        users = list_premium_users()
        if not users:
            await message.reply_text(
                "📋 <b>No premium users yet.</b>\n"
                "Use <code>/addpremium &lt;user_id&gt;</code> to add one.",
                parse_mode="html"
            )
            return

        lines = [f"  • <code>{uid}</code>" for uid in users]
        await message.reply_text(
            f"💎 <b>Premium Users ({len(users)} total):</b>\n\n"
            + "\n".join(lines),
            parse_mode="html"
        )

    # ── /stats ─────────────────────────────────────────────────────────────────
    @app.on_message(filters.command("stats"))
    async def stats_cmd(client: Client, message: Message):
        if not message.from_user or not _is_owner(message.from_user.id):
            await message.reply_text("❌ <b>Owner only command!</b>", parse_mode="html")
            return

        today_total   = get_total_edits_today()
        alltime_total = get_all_time_total()
        premium_count = len(list_premium_users())
        queue_size    = render_queue.queue_size()
        is_rendering  = render_queue.is_busy()

        # Get CPU and disk stats if available
        try:
            import shutil
            disk  = shutil.disk_usage("downloads")
            disk_used_mb  = (disk.total - disk.free) / (1024 ** 2)
            disk_total_mb = disk.total / (1024 ** 2)
            disk_line = f"💾 <b>Disk:</b> <code>{disk_used_mb:.0f} MB / {disk_total_mb:.0f} MB used</code>"
        except Exception:
            disk_line = ""

        await message.reply_text(
            f"📊 <b>GAMEOVER EDITS — Bot Stats</b>\n\n"
            f"🎬 <b>Renders Today:</b> <code>{today_total}</code>\n"
            f"📈 <b>All-Time Renders:</b> <code>{alltime_total}</code>\n"
            f"💎 <b>Premium Users:</b> <code>{premium_count}</code>\n\n"
            f"⚙️ <b>Queue Status:</b> <code>{'🟢 Rendering now' if is_rendering else '⚪ Idle'}</code>\n"
            f"📋 <b>Jobs Waiting:</b> <code>{queue_size}</code>\n"
            f"{disk_line}",
            parse_mode="html"
        )
