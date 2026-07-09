"""
👑 GAMEOVER EDITS — Admin Commands
Owner-only commands for managing premium users and viewing bot stats.
"""

import os
import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import Message

from config import Config
from core.db import (
    add_premium, remove_premium, list_premium_users,
    get_total_edits_today, get_all_time_total,
    add_credits, get_credits
)
from core.queue import render_queue
import psutil


def _is_owner(user_id: int) -> bool:
    return user_id == Config.OWNER_ID


async def get_live_system_stats():
    """Retrieve non-blocking live CPU, RAM, and network speeds."""
    # Get initial values
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory().percent
    net_1 = psutil.net_io_counters()
    
    # Wait 1 second asynchronously
    await asyncio.sleep(1.0)
    
    net_2 = psutil.net_io_counters()
    sent_speed_kb = (net_2.bytes_sent - net_1.bytes_sent) / 1024.0
    recv_speed_kb = (net_2.bytes_recv - net_1.bytes_recv) / 1024.0
    
    return cpu, mem, sent_speed_kb, recv_speed_kb


def register(app: Client):

    # ── /addpremium <user_id> ──────────────────────────────────────────────────
    @app.on_message(filters.command("addpremium"))
    async def add_premium_cmd(client: Client, message: Message):
        if not message.from_user or not _is_owner(message.from_user.id):
            await message.reply_text("❌ <b>Owner only command!</b>", parse_mode=enums.ParseMode.HTML)
            return

        if len(message.command) < 2:
            await message.reply_text(
                "⚠️ <b>Usage:</b> <code>/addpremium &lt;user_id&gt;</code>",
                parse_mode=enums.ParseMode.HTML
            )
            return

        try:
            target_id = int(message.command[1])
        except ValueError:
            await message.reply_text("❌ <b>Invalid user ID.</b>", parse_mode=enums.ParseMode.HTML)
            return

        added = add_premium(target_id, added_by=message.from_user.id)

        if added:
            await message.reply_text(
                f"✅ <b>User <code>{target_id}</code> has been granted Premium!</b>\n"
                f"💎 They now have unlimited renders and Beast Mode access.",
                parse_mode=enums.ParseMode.HTML
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
                    parse_mode=enums.ParseMode.HTML
                )
            except Exception:
                pass  # User may have not started the bot
        else:
            await message.reply_text(
                f"⚠️ <b>User <code>{target_id}</code> is already Premium.</b>",
                parse_mode=enums.ParseMode.HTML
            )

    # ── /removepremium <user_id> ───────────────────────────────────────────────
    @app.on_message(filters.command("removepremium"))
    async def remove_premium_cmd(client: Client, message: Message):
        if not message.from_user or not _is_owner(message.from_user.id):
            await message.reply_text("❌ <b>Owner only command!</b>", parse_mode=enums.ParseMode.HTML)
            return

        if len(message.command) < 2:
            await message.reply_text(
                "⚠️ <b>Usage:</b> <code>/removepremium &lt;user_id&gt;</code>",
                parse_mode=enums.ParseMode.HTML
            )
            return

        try:
            target_id = int(message.command[1])
        except ValueError:
            await message.reply_text("❌ <b>Invalid user ID.</b>", parse_mode=enums.ParseMode.HTML)
            return

        removed = remove_premium(target_id)

        if removed:
            await message.reply_text(
                f"✅ <b>Premium revoked from <code>{target_id}</code>.</b>\n"
                f"They are now on the free plan (1 edit/day).",
                parse_mode=enums.ParseMode.HTML
            )
        else:
            await message.reply_text(
                f"⚠️ <b>User <code>{target_id}</code> was not a Premium user.</b>",
                parse_mode=enums.ParseMode.HTML
            )

    # ── /listpremium ───────────────────────────────────────────────────────────
    @app.on_message(filters.command("listpremium"))
    async def list_premium_cmd(client: Client, message: Message):
        if not message.from_user or not _is_owner(message.from_user.id):
            await message.reply_text("❌ <b>Owner only command!</b>", parse_mode=enums.ParseMode.HTML)
            return

        users = list_premium_users()
        if not users:
            await message.reply_text(
                "📋 <b>No premium users yet.</b>\n"
                "Use <code>/addpremium &lt;user_id&gt;</code> to add one.",
                parse_mode=enums.ParseMode.HTML
            )
            return

        lines = [f"  • <code>{uid}</code>" for uid in users]
        await message.reply_text(
            f"💎 <b>Premium Users ({len(users)} total):</b>\n\n"
            + "\n".join(lines),
            parse_mode=enums.ParseMode.HTML
        )

    # ── /addcredits <user_id> <amount> ──────────────────────────────────────────
    @app.on_message(filters.command("addcredits"))
    async def add_credits_cmd(client: Client, message: Message):
        if not message.from_user or not _is_owner(message.from_user.id):
            await message.reply_text("❌ <b>Owner only command!</b>", parse_mode=enums.ParseMode.HTML)
            return

        if len(message.command) < 3:
            await message.reply_text(
                "⚠️ <b>Usage:</b> <code>/addcredits &lt;user_id&gt; &lt;amount&gt;</code>\n"
                "Example: <code>/addcredits 12345678 5</code>",
                parse_mode=enums.ParseMode.HTML
            )
            return

        try:
            target_id = int(message.command[1])
            amount = int(message.command[2])
        except ValueError:
            await message.reply_text("❌ <b>Invalid user ID or amount.</b>", parse_mode=enums.ParseMode.HTML)
            return

        new_total = add_credits(target_id, amount)
        await message.reply_text(
            f"✅ <b>Successfully updated credits for <code>{target_id}</code>!</b>\n"
            f"📊 <b>Change:</b> <code>{'+' if amount >= 0 else ''}{amount} credits</code>\n"
            f"💰 <b>New Balance:</b> <code>{new_total} credits</code>",
            parse_mode=enums.ParseMode.HTML
        )
        # Notify the user
        try:
            await client.send_message(
                target_id,
                f"🎁 <b>You have received {amount} custom render credits from the Admin!</b>\n"
                f"💰 <b>Current Balance:</b> <code>{new_total} credits</code>\n\n"
                f"Type /edit to use your credits!",
                parse_mode=enums.ParseMode.HTML
            )
        except Exception:
            pass

    # ── /stats or /admin ───────────────────────────────────────────────────────
    @app.on_message(filters.command(["stats", "admin"]))
    async def stats_cmd(client: Client, message: Message):
        if not message.from_user or not _is_owner(message.from_user.id):
            await message.reply_text("❌ <b>Owner only command!</b>", parse_mode=enums.ParseMode.HTML)
            return

        status_msg = await message.reply_text(
            "📊 <b>Fetching live system statistics...</b>",
            parse_mode=enums.ParseMode.HTML
        )

        # Run live update loop for 60 seconds (20 iterations of 3 seconds each)
        for i in range(20):
            try:
                today_total   = get_total_edits_today()
                alltime_total = get_all_time_total()
                premium_count = len(list_premium_users())
                queue_size    = render_queue.queue_size()
                is_rendering  = render_queue.is_busy()
                curr_user     = render_queue.current_user()

                # Get Live CPU, Memory, and Network Speeds (takes 1 second)
                cpu, mem, up_kb, down_kb = await get_live_system_stats()

                # Disk usage
                try:
                    import shutil
                    disk = shutil.disk_usage("downloads")
                    disk_used_mb = (disk.total - disk.free) / (1024 ** 2)
                    disk_total_mb = disk.total / (1024 ** 2)
                    disk_str = f"<code>{disk_used_mb:.1f} MB / {disk_total_mb:.1f} MB</code>"
                except Exception:
                    disk_str = "N/A"

                queue_user_str = f" (User: <code>{curr_user}</code>)" if curr_user else ""

                caption = (
                    f"📊 <b>GAMEOVER EDITS — Live Server Panel</b>\n"
                    f"<i>⏱️ Auto-refreshing live (Update {i+1}/20)...</i>\n\n"
                    f"📈 <b>Renders Today:</b> <code>{today_total}</code>\n"
                    f"🎬 <b>All-Time Renders:</b> <code>{alltime_total}</code>\n"
                    f"💎 <b>Premium Users:</b> <code>{premium_count}</code>\n\n"
                    f"🖥️ <b>CPU Usage:</b> <code>{cpu}%</code>\n"
                    f"💾 <b>RAM Usage:</b> <code>{mem}%</code>\n"
                    f"📊 <b>Disk Space:</b> {disk_str}\n\n"
                    f"🚀 <b>Network Upload:</b> <code>{up_kb:.1f} KB/s</code>\n"
                    f"📥 <b>Network Download:</b> <code>{down_kb:.1f} KB/s</code>\n\n"
                    f"⚙️ <b>Queue Status:</b> <code>{'🟢 Rendering' if is_rendering else '⚪ Idle'}</code>{queue_user_str}\n"
                    f"📋 <b>Jobs Waiting:</b> <code>{queue_size}</code>"
                )

                await status_msg.edit_text(caption, parse_mode=enums.ParseMode.HTML)
                await asyncio.sleep(2.0)  # Wait 2 seconds before next poll (total loop time = 3 seconds)
            except Exception as loop_err:
                print(f"[Admin Loop Stats Error] {loop_err}")
                break

        # Final update to show loop ended
        try:
            await status_msg.edit_text(
                status_msg.text.replace("Auto-refreshing live", "Live refresh paused (Type /admin to refresh again)"),
                parse_mode=enums.ParseMode.HTML
            )
        except Exception:
            pass
