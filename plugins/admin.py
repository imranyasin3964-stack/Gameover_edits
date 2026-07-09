"""
👑 GAMEOVER EDITS — Advanced Admin Panel
Owner-only commands and interactive inline panels for:
  - Live system stats (CPU, RAM, Disk, Bandwidth speed)
  - Custom credits search & management
  - Premium (VIP) user management
"""

import os
import sys
import shutil
import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from config import Config
from core.db import (
    add_premium, remove_premium, list_premium_users,
    get_total_edits_today, get_all_time_total,
    add_credits, get_credits, get_today_count
)
from core.queue import render_queue
from core.states import set_state, get_state, clear_state
import psutil


def _is_owner(user_id: int) -> bool:
    return user_id == Config.OWNER_ID


# ── System Stats Utility ───────────────────────────────────────────────────────

async def get_live_system_stats():
    """Retrieve non-blocking live CPU, RAM, and network speeds."""
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory().percent
    net_1 = psutil.net_io_counters()
    
    await asyncio.sleep(1.0)
    
    net_2 = psutil.net_io_counters()
    sent_speed_kb = (net_2.bytes_sent - net_1.bytes_sent) / 1024.0
    recv_speed_kb = (net_2.bytes_recv - net_1.bytes_recv) / 1024.0
    
    return cpu, mem, sent_speed_kb, recv_speed_kb


def _get_disk_str() -> str:
    try:
        disk = shutil.disk_usage("downloads")
        disk_used_mb = (disk.total - disk.free) / (1024 ** 2)
        disk_total_mb = disk.total / (1024 ** 2)
        return f"{disk_used_mb:.1f} MB / {disk_total_mb:.1f} MB"
    except Exception:
        return "N/A"


# ── Admin Keyboard Menu ────────────────────────────────────────────────────────

def _admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🖥️ Refresh Stats", callback_data="admin_stats_refresh"),
            InlineKeyboardButton("🔍 Search User ID", callback_data="admin_search_user"),
        ],
        [
            InlineKeyboardButton("💳 Add Credits", callback_data="admin_manage_credits"),
            InlineKeyboardButton("💎 List VIPs", callback_data="admin_list_vips"),
        ],
        [
            InlineKeyboardButton("❌ Close Panel", callback_data="admin_close_panel"),
        ]
    ])


async def build_stats_caption(loop_idx: int = 0) -> str:
    """Build the statistics text screen."""
    today_total   = get_total_edits_today()
    alltime_total = get_all_time_total()
    premium_count = len(list_premium_users())
    queue_size    = render_queue.queue_size()
    is_rendering  = render_queue.is_busy()
    curr_user     = render_queue.current_user()

    cpu, mem, up_kb, down_kb = await get_live_system_stats()
    disk_str = _get_disk_str()
    queue_user_str = f" (User: <code>{curr_user}</code>)" if curr_user else ""

    refresh_indicator = (
        f"<i>⏱️ Auto-refreshing live (Update {loop_idx}/20)...</i>"
        if loop_idx > 0 else
        "<i>🟢 Interactive Panel | Refresh below</i>"
    )

    return (
        f"📊 <b>GAMEOVER EDITS — Live Server Panel</b>\n"
        f"{refresh_indicator}\n\n"
        f"📈 <b>Renders Today:</b> <code>{today_total}</code>\n"
        f"🎬 <b>All-Time Renders:</b> <code>{alltime_total}</code>\n"
        f"💎 <b>Premium Users:</b> <code>{premium_count}</code>\n\n"
        f"🖥️ <b>CPU Usage:</b> <code>{cpu}%</code>\n"
        f"💾 <b>RAM Usage:</b> <code>{mem}%</code>\n"
        f"📊 <b>Disk Space:</b> <code>{disk_str}</code>\n\n"
        f"🚀 <b>Network Upload:</b> <code>{up_kb:.1f} KB/s</code>\n"
        f"📥 <b>Network Download:</b> <code>{down_kb:.1f} KB/s</code>\n\n"
        f"⚙️ <b>Queue Status:</b> <code>{'🟢 Rendering' if is_rendering else '⚪ Idle'}</code>{queue_user_str}\n"
        f"📋 <b>Jobs Waiting:</b> <code>{queue_size}</code>"
    )


# ── Register Code ──────────────────────────────────────────────────────────────

def register(app: Client):

    # ── /stats or /admin Command ───────────────────────────────────────────────
    @app.on_message(filters.command(["stats", "admin"]))
    async def admin_panel_cmd(client: Client, message: Message):
        if not message.from_user or not _is_owner(message.from_user.id):
            await message.reply_text("❌ <b>Owner only command!</b>", parse_mode=enums.ParseMode.HTML)
            return

        status_msg = await message.reply_text(
            "📊 <b>Loading system statistics...</b>",
            parse_mode=enums.ParseMode.HTML
        )
        
        caption = await build_stats_caption()
        await status_msg.edit_text(
            caption,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=_admin_keyboard()
        )

    # ── Admin Command Actions (Traditional Commands) ───────────────────────────
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

        add_premium(target_id, added_by=message.from_user.id)
        await message.reply_text(f"✅ User <code>{target_id}</code> is now VIP Premium.", parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.command("removepremium"))
    async def remove_premium_cmd(client: Client, message: Message):
        if not message.from_user or not _is_owner(message.from_user.id):
            await message.reply_text("❌ <b>Owner only command!</b>", parse_mode=enums.ParseMode.HTML)
            return

        if len(message.command) < 2:
            await message.reply_text("⚠️ <b>Usage:</b> <code>/removepremium &lt;user_id&gt;</code>", parse_mode=enums.ParseMode.HTML)
            return

        try:
            target_id = int(message.command[1])
        except ValueError:
            await message.reply_text("❌ <b>Invalid user ID.</b>", parse_mode=enums.ParseMode.HTML)
            return

        remove_premium(target_id)
        await message.reply_text(f"✅ Premium VIP access removed from <code>{target_id}</code>.", parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.command("addcredits"))
    async def add_credits_command(client: Client, message: Message):
        if not message.from_user or not _is_owner(message.from_user.id):
            await message.reply_text("❌ <b>Owner only command!</b>", parse_mode=enums.ParseMode.HTML)
            return

        if len(message.command) < 3:
            await message.reply_text("⚠️ <b>Usage:</b> <code>/addcredits &lt;user_id&gt; &lt;amount&gt;</code>", parse_mode=enums.ParseMode.HTML)
            return

        try:
            target_id = int(message.command[1])
            amount = int(message.command[2])
        except ValueError:
            await message.reply_text("❌ <b>Invalid ID or amount.</b>", parse_mode=enums.ParseMode.HTML)
            return

        new_total = add_credits(target_id, amount)
        await message.reply_text(
            f"✅ User <code>{target_id}</code> balance updated. New total: <code>{new_total} credits</code>.",
            parse_mode=enums.ParseMode.HTML
        )

    # ── Interactive Callback Query Handlers ────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^admin_"))
    async def admin_callback_handler(client: Client, query: CallbackQuery):
        owner_id = query.from_user.id
        if not _is_owner(owner_id):
            await query.answer("❌ You are not the Owner!", show_alert=True)
            return

        data    = query.data
        chat_id = query.message.chat.id

        # 1. Close Panel
        if data == "admin_close_panel":
            clear_state(owner_id)
            await query.answer("Panel Closed!")
            await query.message.delete()
            return

        # 2. Main Menu Back
        elif data == "admin_back_main":
            clear_state(owner_id)
            await query.answer("Returned to Menu")
            caption = await build_stats_caption()
            await query.message.edit_text(
                caption,
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_admin_keyboard()
            )

        # 3. Refresh Stats
        elif data == "admin_stats_refresh":
            await query.answer("🔄 Refreshing stats...")
            caption = await build_stats_caption()
            try:
                await query.message.edit_text(
                    caption,
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=_admin_keyboard()
                )
            except Exception:
                pass

        # 4. Search User ID
        elif data == "admin_search_user":
            await query.answer()
            set_state(owner_id, "waiting_search_id", chat_id)
            await query.message.edit_text(
                "🔍 <b>Send the Numeric User ID to check status:</b>\n\n"
                "<i>Please type or paste the User ID below:</i>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="admin_back_main")]
                ])
            )

        # 5. Manage Credits (custom amount input)
        elif data == "admin_manage_credits":
            await query.answer()
            set_state(owner_id, "waiting_credit_amount", chat_id)
            await query.message.edit_text(
                "💳 <b>Add Custom Credits</b>\n\n"
                "Send the <b>User ID</b> and <b>Amount</b> separated by space:\n"
                "Format: <code>[User_ID] [Amount]</code>\n"
                "Example: <code>12345678 10</code>\n\n"
                "<i>(Send negative value to subtract)</i>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="admin_back_main")]
                ])
            )

        # 6. List VIPs
        elif data == "admin_list_vips":
            await query.answer()
            vips = list_premium_users()
            if not vips:
                vips_str = "No VIP premium users registered."
            else:
                vips_str = "\n".join(f"• <code>{uid}</code>" for uid in vips)
            await query.message.edit_text(
                f"💎 <b>VIP Premium Users:</b>\n\n{vips_str}",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="admin_back_main")]
                ])
            )

        # 7. Action callbacks from User search status
        elif data.startswith("admin_act|"):
            parts = data.split("|")
            action = parts[1]
            target_id = int(parts[2])

            if action == "addcr":
                amount = int(parts[3])
                new_total = add_credits(target_id, amount)
                await query.answer(f"Added {amount} credits!")
            elif action == "clearcr":
                current = get_credits(target_id)
                new_total = add_credits(target_id, -current)
                await query.answer("Credits cleared!")
            elif action == "makevip":
                add_premium(target_id, added_by=owner_id)
                await query.answer("User upgraded to Premium VIP!")
            elif action == "remvip":
                remove_premium(target_id)
                await query.answer("Premium VIP revoked!")

            # Redraw status
            vip = is_premium(target_id)
            credits = get_credits(target_id)
            used_today = get_today_count(target_id)

            vip_str = "💎 <b>Premium (VIP):</b> <code>Yes (Unlimited) 🔓</code>" if vip else "🆓 <b>Premium (VIP):</b> <code>No (Free limits apply)</code>"
            credits_str = f"💳 <b>Custom Credits:</b> <code>{credits}</code>"
            used_str = f"🎬 <b>Edits Used Today:</b> <code>{used_today} / {Config.DAILY_FREE_LIMIT}</code>"

            try:
                tgt_user = await client.get_users(target_id)
                name_line = f"👤 <b>Name:</b> <a href='tg://user?id={target_id}'>{tgt_user.first_name} {tgt_user.last_name or ''}</a>\n"
                mention_line = f"🔗 <b>Username:</b> @{tgt_user.username}\n" if tgt_user.username else ""
            except Exception:
                name_line = f"👤 <b>Name:</b> <a href='tg://user?id={target_id}'>Unknown</a> (Never started bot)\n"
                mention_line = ""

            await query.message.edit_text(
                f"👤 <b>GAMEOVER EDITS — User Status</b>\n\n"
                f"🆔 <b>User ID:</b> <code>{target_id}</code>\n"
                f"{name_line}"
                f"{mention_line}"
                f"{vip_str}\n"
                f"{credits_str}\n"
                f"{used_str}",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("➕ Add 5 Credits", callback_data=f"admin_act|addcr|{target_id}|5"),
                        InlineKeyboardButton("➕ Add 10 Credits", callback_data=f"admin_act|addcr|{target_id}|10"),
                    ],
                    [
                        InlineKeyboardButton("💎 Make Premium", callback_data=f"admin_act|makevip|{target_id}"),
                        InlineKeyboardButton("❌ Revoke Premium", callback_data=f"admin_act|remvip|{target_id}"),
                    ],
                    [
                        InlineKeyboardButton("🧹 Clear Custom Credits", callback_data=f"admin_act|clearcr|{target_id}"),
                    ],
                    [
                        InlineKeyboardButton("🔙 Back to Main Menu", callback_data="admin_back_main"),
                    ]
                ])
            )

    # ── Message Input Handler (Catches text inputs for user search & credits) ──
    @app.on_message(filters.chat(Config.OWNER_ID) & filters.text & ~filters.command(["admin", "stats", "start", "help", "premium", "edit"]))
    async def admin_input_handler(client: Client, message: Message):
        owner_id = message.from_user.id
        state = get_state(owner_id)
        if not state:
            return

        chat_id = message.chat.id
        step = state["quality"]

        # A. User ID Search
        if step == "waiting_search_id":
            clear_state(owner_id)
            try:
                target_id = int(message.text.strip())
            except ValueError:
                await message.reply_text("❌ <b>Numeric User ID only!</b>", parse_mode=enums.ParseMode.HTML)
                return

            vip = is_premium(target_id)
            credits = get_credits(target_id)
            used_today = get_today_count(target_id)

            vip_str = "💎 <b>Premium (VIP):</b> <code>Yes (Unlimited) 🔓</code>" if vip else "🆓 <b>Premium (VIP):</b> <code>No (Free limits)</code>"
            credits_str = f"💳 <b>Custom Credits:</b> <code>{credits}</code>"
            used_str = f"🎬 <b>Edits Used Today:</b> <code>{used_today} / {Config.DAILY_FREE_LIMIT}</code>"

            try:
                tgt_user = await client.get_users(target_id)
                name_line = f"👤 <b>Name:</b> <a href='tg://user?id={target_id}'>{tgt_user.first_name} {tgt_user.last_name or ''}</a>\n"
                mention_line = f"🔗 <b>Username:</b> @{tgt_user.username}\n" if tgt_user.username else ""
            except Exception:
                name_line = f"👤 <b>Name:</b> <a href='tg://user?id={target_id}'>Unknown</a> (Never started bot)\n"
                mention_line = ""

            await message.reply_text(
                f"👤 <b>GAMEOVER EDITS — User Status</b>\n\n"
                f"🆔 <b>User ID:</b> <code>{target_id}</code>\n"
                f"{name_line}"
                f"{mention_line}"
                f"{vip_str}\n"
                f"{credits_str}\n"
                f"{used_str}",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("➕ Add 5 Credits", callback_data=f"admin_act|addcr|{target_id}|5"),
                        InlineKeyboardButton("➕ Add 10 Credits", callback_data=f"admin_act|addcr|{target_id}|10"),
                    ],
                    [
                        InlineKeyboardButton("💎 Make Premium", callback_data=f"admin_act|makevip|{target_id}"),
                        InlineKeyboardButton("❌ Revoke Premium", callback_data=f"admin_act|remvip|{target_id}"),
                    ],
                    [
                        InlineKeyboardButton("🧹 Clear Custom Credits", callback_data=f"admin_act|clearcr|{target_id}"),
                    ],
                    [
                        InlineKeyboardButton("🔙 Back to Main Menu", callback_data="admin_back_main"),
                    ]
                ])
            )

        # B. Custom Credit Add
        elif step == "waiting_credit_amount":
            clear_state(owner_id)
            parts = message.text.strip().split()
            if len(parts) < 2:
                await message.reply_text(
                    "❌ <b>Format must be:</b> <code>[User_ID] [Amount]</code>\n"
                    "Example: <code>12345678 15</code>",
                    parse_mode=enums.ParseMode.HTML
                )
                return

            try:
                target_id = int(parts[0])
                amount = int(parts[1])
            except ValueError:
                await message.reply_text("❌ <b>Values must be integers!</b>", parse_mode=enums.ParseMode.HTML)
                return

            new_total = add_credits(target_id, amount)
            await message.reply_text(
                f"✅ <b>Credits balance updated!</b>\n\n"
                f"🆔 <b>User ID:</b> <code>{target_id}</code>\n"
                f"📊 <b>Change:</b> <code>{'+' if amount >= 0 else ''}{amount} credits</code>\n"
                f"💰 <b>New Balance:</b> <code>{new_total} credits</code>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Main Menu", callback_data="admin_back_main")]
                ])
            )
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
