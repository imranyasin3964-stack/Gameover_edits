"""
👑 GAMEOVER EDITS — Advanced Admin Panel
Owner-only commands and interactive inline panels for:
  - Live system stats (CPU, RAM, Disk, Bandwidth speed)
  - Time-based Premium subscription management (/give <id> <days>)
  - Custom credits search & management
  - Dynamic welcome video changer
"""

import os
import shutil
import asyncio
from datetime import datetime, timezone, timedelta
from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)

from config import Config
from core.db import (
    grant_premium, add_premium, remove_premium, list_premium_users,
    get_premium_expiry, count_active_premium,
    get_total_edits_today, get_all_time_total,
    add_credits, get_credits, get_today_count,
    is_premium,
)
from core.queue import render_queue
from core.states import set_state, get_state, clear_state
import psutil


def _is_owner(user_id: int) -> bool:
    return user_id == Config.OWNER_ID


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ── Expiry helpers ──────────────────────────────────────────────────────────────

def _format_expiry(expiry_dt: datetime) -> str:
    """Return a clean, human-readable expiry string in UTC."""
    return expiry_dt.strftime("%Y-%m-%d %H:%M UTC")


def _time_remaining(expiry_dt: datetime) -> str:
    """Return a compact 'Xd Yh Zm' remaining string, or 'Expired'."""
    diff = expiry_dt - _now_utc()
    total_secs = int(diff.total_seconds())
    if total_secs <= 0:
        return "Expired"
    days    = total_secs // 86400
    hours   = (total_secs % 86400) // 3600
    minutes = (total_secs % 3600) // 60
    parts   = []
    if days:    parts.append(f"{days}d")
    if hours:   parts.append(f"{hours}h")
    if minutes: parts.append(f"{minutes}m")
    return " ".join(parts) if parts else "< 1m"


# ── System Stats Utility ────────────────────────────────────────────────────────

async def get_live_system_stats():
    """Retrieve non-blocking live CPU, RAM, and network speeds."""
    psutil.cpu_percent(interval=None)  # Flush CPU counter
    net_1 = psutil.net_io_counters()
    await asyncio.sleep(1.0)
    cpu   = psutil.cpu_percent(interval=None)  # Measure CPU usage over the 1s interval
    mem   = psutil.virtual_memory().percent
    net_2 = psutil.net_io_counters()
    sent_speed_kb = (net_2.bytes_sent - net_1.bytes_sent) / 1024.0
    recv_speed_kb = (net_2.bytes_recv - net_1.bytes_recv) / 1024.0
    return cpu, mem, sent_speed_kb, recv_speed_kb


def _get_disk_str() -> str:
    try:
        disk = shutil.disk_usage("downloads")
        disk_used_mb  = (disk.total - disk.free) / (1024 ** 2)
        disk_total_mb = disk.total / (1024 ** 2)
        return f"{disk_used_mb:.1f} MB / {disk_total_mb:.1f} MB"
    except Exception:
        return "N/A"


# ── Admin Keyboard Menu ─────────────────────────────────────────────────────────

def _admin_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([
        ["🖥️ Refresh Stats", "🔍 Search User ID"],
        ["💳 Add Credits", "📹 Change Start Video"],
        ["👥 List Users", "🚫 Watermark Toggle"],
        ["👥 List Active VIPs", "📢 Global Broadcast"],
        ["❌ Close Panel"]
    ], resize_keyboard=True)


async def build_stats_caption(loop_idx: int = 0) -> str:
    """Build the statistics text screen."""
    today_total   = get_total_edits_today()
    alltime_total = get_all_time_total()
    premium_count = count_active_premium()
    queue_size    = render_queue.queue_size()
    is_rendering  = render_queue.is_busy()
    curr_user     = render_queue.current_user()

    cpu, mem, up_kb, down_kb = await get_live_system_stats()
    disk_str      = _get_disk_str()
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
        f"💎 <b>Active Premium Users:</b> <code>{premium_count}</code>\n\n"
        f"🖥️ <b>CPU Usage:</b> <code>{cpu}%</code>\n"
        f"💾 <b>RAM Usage:</b> <code>{mem}%</code>\n"
        f"📊 <b>Disk Space:</b> <code>{disk_str}</code>\n\n"
        f"🚀 <b>Network Upload:</b> <code>{up_kb:.1f} KB/s</code>\n"
        f"📥 <b>Network Download:</b> <code>{down_kb:.1f} KB/s</code>\n\n"
        f"⚙️ <b>Queue Status:</b> <code>{'🟢 Rendering' if is_rendering else '⚪ Idle'}</code>{queue_user_str}\n"
        f"📋 <b>Jobs Waiting:</b> <code>{queue_size}</code>"
    )


# ── User Status Card builder ────────────────────────────────────────────────────

def _build_user_status_card(target_id: int) -> str:
    """Build the text portion of a user-status card (no Telegram API call needed)."""
    vip        = is_premium(target_id)
    credits    = get_credits(target_id)
    used_today = get_today_count(target_id)
    expiry_dt  = get_premium_expiry(target_id)

    from core.db import has_watermark_disabled
    no_wm = has_watermark_disabled(target_id)

    from config import Config as _Config
    if vip and target_id == _Config.OWNER_ID:
        vip_str = "💎 <b>Premium (VIP):</b> <code>OWNER — Permanent 👑</code>"
    elif vip and expiry_dt:
        remaining = _time_remaining(expiry_dt)
        expiry_f  = _format_expiry(expiry_dt)
        vip_str   = (
            f"💎 <b>Premium (VIP):</b> <code>Active ✅</code>\n"
            f"   ⏳ <b>Expires:</b> <code>{expiry_f}</code>\n"
            f"   ⌛ <b>Remaining:</b> <code>{remaining}</code>"
        )
    else:
        vip_str = "🆓 <b>Premium (VIP):</b> <code>No — Free limits apply</code>"

    credits_str  = f"💳 <b>Custom Credits:</b> <code>{credits}</code>"
    used_str     = f"🎬 <b>Edits Used Today:</b> <code>{used_today} / {Config.DAILY_FREE_LIMIT}</code>"
    wm_str       = f"🏷️ <b>Watermark:</b> <code>{'❌ Disabled (No Watermark)' if no_wm else '✅ Enabled'}</code>"

    return f"{vip_str}\n{credits_str}\n{used_str}\n{wm_str}"


def _user_action_keyboard(target_id: int) -> InlineKeyboardMarkup:
    """Action buttons shown on a user status card."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ 5 Credits",  callback_data=f"admin_act|addcr|{target_id}|5", style="primary"),
            InlineKeyboardButton("➕ 10 Credits", callback_data=f"admin_act|addcr|{target_id}|10", style="primary"),
        ],
        [
            InlineKeyboardButton("💎 Give 30d Premium",  callback_data=f"admin_act|give30|{target_id}", style="success"),
            InlineKeyboardButton("💎 Give 7d Premium",   callback_data=f"admin_act|give7|{target_id}", style="success"),
        ],
        [
            InlineKeyboardButton("💎 Give 1d Premium",   callback_data=f"admin_act|give1|{target_id}", style="success"),
            InlineKeyboardButton("❌ Revoke Premium",     callback_data=f"admin_act|remvip|{target_id}", style="danger"),
        ],
        [
            InlineKeyboardButton("🧹 Clear Credits",     callback_data=f"admin_act|clearcr|{target_id}", style="danger"),
            InlineKeyboardButton("🏷️ Toggle Watermark",  callback_data=f"admin_act|togwm|{target_id}", style="primary"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Main Menu", callback_data="admin_back_main", style="primary"),
        ]
    ])


async def _show_users_list_page(client: Client, chat_id: int, page: int, message_to_edit=None):
    from core.db import list_all_users
    users = list_all_users()
    if not users:
        text = "❌ <b>No registered users found!</b>"
        if message_to_edit:
            await message_to_edit.edit_text(text, parse_mode=enums.ParseMode.HTML)
        else:
            await client.send_message(chat_id, text, parse_mode=enums.ParseMode.HTML)
        return

    # Pagination calculation
    per_page = 8
    total_pages = (len(users) + per_page - 1) // per_page
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_users = users[start_idx:end_idx]

    buttons = []
    for u in page_users:
        uid = u["user_id"]
        fname = u["first_name"] or "User"
        lname = u["last_name"] or ""
        name = f"{fname} {lname}".strip()
        uname = f" (@{u['username']})" if u["username"] else f" ({uid})"
        button_text = f"👤 {name}{uname}"
        if len(button_text) > 35:
            button_text = button_text[:32] + "..."
        buttons.append([InlineKeyboardButton(button_text, callback_data=f"admin_user_view|{uid}")])

    # Navigation buttons
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"admin_users_page|{page - 1}"))
    nav_row.append(InlineKeyboardButton(f"Page {page}/{total_pages}", callback_data="admin_noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"admin_users_page|{page + 1}"))
    buttons.append(nav_row)

    buttons.append([InlineKeyboardButton("🔙 Main Menu", callback_data="admin_back_main", style="primary")])

    text = (
        f"👥 <b>GAMEOVER EDITS — Registered Users List</b>\n\n"
        f"Total Registered Users: <code>{len(users)}</code>\n"
        f"<i>Click a user below to view status and manage them:</i>"
    )

    if message_to_edit:
        await message_to_edit.edit_text(text, parse_mode=enums.ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await client.send_message(chat_id, text, parse_mode=enums.ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


# ── Register ────────────────────────────────────────────────────────────────────

def register(app: Client):

    # ── /admin or /stats ───────────────────────────────────────────────────────
    @app.on_message(filters.command(["stats", "admin"]))
    async def admin_panel_cmd(client: Client, message: Message):
        if not message.from_user or not _is_owner(message.from_user.id):
            await message.reply_text("❌ <b>Owner only command!</b>", parse_mode=enums.ParseMode.HTML)
            return

        caption = await build_stats_caption()
        await message.reply_text(
            caption,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=_admin_reply_keyboard()
        )

    # ── /give <user_id> [days]  (/addpremium alias) ────────────────────────────
    @app.on_message(filters.command(["give", "addpremium"]))
    async def give_premium_cmd(client: Client, message: Message):
        if not message.from_user or not _is_owner(message.from_user.id):
            await message.reply_text("❌ <b>Owner only command!</b>", parse_mode=enums.ParseMode.HTML)
            return

        args = message.command[1:]  # everything after the command word

        if not args:
            await message.reply_text(
                "⚠️ <b>Usage:</b> <code>/give &lt;user_id&gt; [days]</code>\n\n"
                "Examples:\n"
                "  <code>/give 123456789 7</code> — 7 days\n"
                "  <code>/give 123456789 30</code> — 30 days\n"
                "  <code>/give 123456789</code>    — defaults to 30 days",
                parse_mode=enums.ParseMode.HTML
            )
            return

        try:
            target_id = int(args[0])
        except ValueError:
            await message.reply_text("❌ <b>Invalid user ID.</b>", parse_mode=enums.ParseMode.HTML)
            return

        days = 30  # default
        if len(args) >= 2:
            try:
                days = int(args[1])
                if days <= 0:
                    raise ValueError
            except ValueError:
                await message.reply_text(
                    "❌ <b>Days must be a positive integer.</b>\n"
                    "Example: <code>/give 123456789 14</code>",
                    parse_mode=enums.ParseMode.HTML
                )
                return

        expiry_dt  = grant_premium(target_id, days=days, added_by=message.from_user.id)
        expiry_str = _format_expiry(expiry_dt)

        await message.reply_text(
            f"✅ <b>Premium Granted!</b>\n\n"
            f"🆔 <b>User ID:</b> <code>{target_id}</code>\n"
            f"📅 <b>Duration:</b> <code>{days} day(s)</code>\n"
            f"⏰ <b>Expiry:</b> <code>{expiry_str}</code>",
            parse_mode=enums.ParseMode.HTML
        )

        # Notify the user
        try:
            await client.send_message(
                target_id,
                f"🎉 <b>Congratulations! You've been upgraded to GAMEOVER EDITS Premium!</b>\n\n"
                f"💎 <b>Duration:</b> <code>{days} day(s)</code>\n"
                f"⏰ <b>Access until:</b> <code>{expiry_str}</code>\n\n"
                f"✅ You now have:\n"
                f"  • Unlimited daily edits\n"
                f"  • 4K Beast Mode unlocked 🔓\n\n"
                f"Type /edit to start rendering! 🚀",
                parse_mode=enums.ParseMode.HTML
            )
        except Exception:
            pass  # User may not have started the bot yet

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
                f"✅ Premium access for <code>{target_id}</code> has been <b>revoked</b>.",
                parse_mode=enums.ParseMode.HTML
            )
            try:
                await client.send_message(
                    target_id,
                    "⚠️ <b>Your GAMEOVER EDITS Premium subscription has been removed.</b>\n"
                    "You have been reverted to the Free plan.\n\n"
                    "Contact the admin to renew.",
                    parse_mode=enums.ParseMode.HTML
                )
            except Exception:
                pass
        else:
            await message.reply_text(
                f"ℹ️ <code>{target_id}</code> was not in the premium list.",
                parse_mode=enums.ParseMode.HTML
            )

    # ── /addcredits <user_id> <amount> ─────────────────────────────────────────
    @app.on_message(filters.command("addcredits"))
    async def add_credits_command(client: Client, message: Message):
        if not message.from_user or not _is_owner(message.from_user.id):
            await message.reply_text("❌ <b>Owner only command!</b>", parse_mode=enums.ParseMode.HTML)
            return

        if len(message.command) < 3:
            await message.reply_text(
                "⚠️ <b>Usage:</b> <code>/addcredits &lt;user_id&gt; &lt;amount&gt;</code>",
                parse_mode=enums.ParseMode.HTML
            )
            return

        try:
            target_id = int(message.command[1])
            amount    = int(message.command[2])
        except ValueError:
            await message.reply_text("❌ <b>Invalid ID or amount.</b>", parse_mode=enums.ParseMode.HTML)
            return

        new_total = add_credits(target_id, amount)
        await message.reply_text(
            f"✅ User <code>{target_id}</code> balance updated. "
            f"New total: <code>{new_total} credits</code>.",
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

        # 2. Back to Main Menu
        if data == "admin_back_main":
            clear_state(owner_id)
            await query.answer("Returned to Menu")
            try:
                await query.message.delete()
            except Exception:
                pass
            caption = await build_stats_caption()
            await client.send_message(
                chat_id=chat_id,
                text=caption,
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_admin_reply_keyboard()
            )

        elif data.startswith("admin_users_page|"):
            page = int(data.split("|")[1])
            await _show_users_list_page(client, chat_id, page, query.message)

        elif data.startswith("admin_user_view|"):
            target_id = int(data.split("|")[1])
            status_body = _build_user_status_card(target_id)
            try:
                tgt_user   = await client.get_users(target_id)
                name_line  = (
                    f"👤 <b>Name:</b> "
                    f"<a href='tg://user?id={target_id}'>"
                    f"{tgt_user.first_name} {tgt_user.last_name or ''}</a>\n"
                )
                mention_line = (
                    f"🔗 <b>Username:</b> @{tgt_user.username}\n"
                    if tgt_user.username else ""
                )
            except Exception:
                name_line    = f"👤 <b>Name:</b> <a href='tg://user?id={target_id}'>Unknown</a>\n"
                mention_line = ""

            await query.message.edit_text(
                f"👤 <b>GAMEOVER EDITS — User Status</b>\n\n"
                f"🆔 <b>User ID:</b> <code>{target_id}</code>\n"
                f"{name_line}"
                f"{mention_line}"
                f"{status_body}",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_user_action_keyboard(target_id)
            )

        elif data == "admin_noop":
            await query.answer()

        # 7. Action buttons on User Status card
        elif data.startswith("admin_act|"):
            parts  = data.split("|")
            action = parts[1]
            target_id = int(parts[2])

            if action == "addcr":
                amount    = int(parts[3])
                add_credits(target_id, amount)
                await query.answer(f"✅ Added {amount} credits!")

            elif action == "clearcr":
                current = get_credits(target_id)
                add_credits(target_id, -current)
                await query.answer("Credits cleared!")

            elif action == "togwm":
                from core.db import toggle_watermark
                disabled = toggle_watermark(target_id)
                status_str = "Watermark disabled!" if disabled else "Watermark enabled!"
                await query.answer(f"🏷️ {status_str}", show_alert=True)

            elif action.startswith("give"):
                # give30 / give7 / give1
                days_map = {"give30": 30, "give7": 7, "give1": 1}
                days     = days_map.get(action, 30)
                expiry_dt = grant_premium(target_id, days=days, added_by=owner_id)
                await query.answer(f"✅ {days}d Premium granted!")
                # Notify the user silently
                try:
                    expiry_str = _format_expiry(expiry_dt)
                    await client.send_message(
                        target_id,
                        f"🎉 <b>You've been upgraded to GAMEOVER EDITS Premium!</b>\n\n"
                        f"💎 <b>Duration:</b> <code>{days} day(s)</code>\n"
                        f"⏰ <b>Access until:</b> <code>{expiry_str}</code>\n\n"
                        f"Unlimited edits + 4K Beast Mode unlocked 🔓\n"
                        f"Type /edit to start! 🚀",
                        parse_mode=enums.ParseMode.HTML
                    )
                except Exception:
                    pass

            elif action == "makevip":
                # Legacy button: 30-day grant
                expiry_dt = grant_premium(target_id, days=30, added_by=owner_id)
                await query.answer("✅ 30-day Premium granted!")

            elif action == "remvip":
                remove_premium(target_id)
                await query.answer("❌ Premium revoked!")
                try:
                    await client.send_message(
                        target_id,
                        "⚠️ <b>Your GAMEOVER EDITS Premium has been removed.</b>\n"
                        "You are now on the Free plan. Contact admin to renew.",
                        parse_mode=enums.ParseMode.HTML
                    )
                except Exception:
                    pass

            # Redraw the status card
            status_body = _build_user_status_card(target_id)
            try:
                tgt_user   = await client.get_users(target_id)
                name_line  = (
                    f"👤 <b>Name:</b> "
                    f"<a href='tg://user?id={target_id}'>"
                    f"{tgt_user.first_name} {tgt_user.last_name or ''}</a>\n"
                )
                mention_line = (
                    f"🔗 <b>Username:</b> @{tgt_user.username}\n"
                    if tgt_user.username else ""
                )
            except Exception:
                name_line    = f"👤 <b>Name:</b> <a href='tg://user?id={target_id}'>Unknown</a>\n"
                mention_line = ""

            await query.message.edit_text(
                f"👤 <b>GAMEOVER EDITS — User Status</b>\n\n"
                f"🆔 <b>User ID:</b> <code>{target_id}</code>\n"
                f"{name_line}"
                f"{mention_line}"
                f"{status_body}",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_user_action_keyboard(target_id)
            )

    # ── Reply Keyboard Buttons Handler ──────────────────────────────────────────
    ADMIN_BUTTONS = [
        "🖥️ Refresh Stats",
        "🔍 Search User ID",
        "💳 Add Credits",
        "📹 Change Start Video",
        "👥 List Users",
        "🚫 Watermark Toggle",
        "👥 List Active VIPs",
        "📢 Global Broadcast",
        "❌ Close Panel"
    ]

    def is_admin_button(_, __, message: Message) -> bool:
        if not message.text:
            return False
        return message.text.strip() in ADMIN_BUTTONS

    @app.on_message(
        filters.chat(Config.OWNER_ID)
        & filters.create(is_admin_button)
    )
    async def admin_buttons_handler(client: Client, message: Message):
        text = message.text.strip()

        owner_id = message.from_user.id
        chat_id  = message.chat.id

        if text == "🖥️ Refresh Stats":
            caption = await build_stats_caption()
            await message.reply_text(
                caption,
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_admin_reply_keyboard()
            )

        elif text == "❌ Close Panel":
            clear_state(owner_id)
            await message.reply_text(
                "❌ <b>Admin panel closed.</b> Keyboard removed.",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=ReplyKeyboardRemove()
            )

        elif text == "🔍 Search User ID":
            set_state(owner_id, "waiting_search_id", chat_id)
            await message.reply_text(
                "🔍 <b>Send the Numeric User ID to check status:</b>\n\n"
                "<i>Please type or paste the User ID below:</i>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)
            )

        elif text == "💳 Add Credits":
            set_state(owner_id, "waiting_credit_amount", chat_id)
            await message.reply_text(
                "💳 <b>Add Custom Credits</b>\n\n"
                "Send the <b>User ID</b> and <b>Amount</b> separated by space:\n"
                "Format: <code>[User_ID] [Amount]</code>\n"
                "Example: <code>12345678 10</code>\n\n"
                "<i>(Send a negative value to subtract credits)</i>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)
            )

        elif text == "📹 Change Start Video":
            set_state(owner_id, "waiting_start_video", chat_id)
            await message.reply_text(
                "📹 <b>Change Welcome /start Video</b>\n\n"
                "Send or forward the video or GIF you want new users to see on /start.\n\n"
                "<i>(The bot stores its Telegram File ID — loads instantly for all users.)</i>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)
            )

        elif text == "👥 List Users":
            await _show_users_list_page(client, message.chat.id, 1)

        elif text == "🚫 Watermark Toggle":
            set_state(owner_id, "waiting_watermark_toggle", chat_id)
            await message.reply_text(
                "🚫 <b>Toggle Watermark for User</b>\n\n"
                "Please send the numeric <b>User ID</b> of the target user:\n"
                "Format: <code>[User_ID]</code>\n"
                "Example: <code>12345678</code>\n\n"
                "<i>(If currently enabled, it will be disabled. If disabled, it will be enabled.)</i>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)
            )

        elif text == "📢 Global Broadcast":
            set_state(owner_id, "waiting_broadcast_msg", chat_id)
            await message.reply_text(
                "📢 <b>Global Broadcast to Users</b>\n\n"
                "Please send or forward the message you want to broadcast to all users.\n"
                "You can send text, photo, video, document, or audio. The bot will copy it to everyone.",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)
            )

        elif text == "👥 List Active VIPs":
            vips = list_premium_users()
            if not vips:
                vips_str = "<i>No active Premium subscribers.</i>"
            else:
                lines = []
                for v in vips:
                    uid = v["user_id"]
                    try:
                        expiry_dt = datetime.fromisoformat(v["expiry_date"])
                        remaining = _time_remaining(expiry_dt)
                        expiry_f  = _format_expiry(expiry_dt)
                        lines.append(
                            f"• <code>{uid}</code> — ⏳ <code>{remaining}</code> "
                            f"<i>(until {expiry_f})</i>"
                        )
                    except Exception:
                        lines.append(f"• <code>{uid}</code>")
                vips_str = "\n".join(lines)

            await message.reply_text(
                f"💎 <b>Active Premium Subscribers ({len(vips)}):</b>\n\n{vips_str}",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_admin_reply_keyboard()
            )

    # Filter to detect if the user has an active waiting state
    def is_admin_waiting_state(_, __, message: Message) -> bool:
        if not message.from_user:
            return False
        state = get_state(message.from_user.id)
        if state and state.get("quality", "").startswith("waiting_"):
            return True
        return False

    # ── Message Input Handler (Handles all owner states: Search, Credits, Start Video, Broadcast) ──
    @app.on_message(
        filters.chat(Config.OWNER_ID)
        & filters.create(is_admin_waiting_state)
        & ~filters.command(["admin", "stats", "start", "help", "premium",
                             "edit", "give", "addpremium", "removepremium",
                             "addcredits", "myplan"])
    )
    async def admin_input_handler(client: Client, message: Message):
        owner_id = message.from_user.id
        state    = get_state(owner_id)
        if not state:
            return

        # Handle cancel request
        if message.text and message.text.strip() == "❌ Cancel":
            clear_state(owner_id)
            caption = await build_stats_caption()
            await message.reply_text(
                "❌ <b>Operation cancelled.</b>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_admin_reply_keyboard()
            )
            return

        step = state["quality"]

        # A. User ID Search
        if step == "waiting_search_id":
            if not message.text:
                await message.reply_text("❌ <b>Please send a numeric User ID in text format!</b>", parse_mode=enums.ParseMode.HTML)
                return

            clear_state(owner_id)
            try:
                target_id = int(message.text.strip())
            except ValueError:
                await message.reply_text("❌ <b>Numeric User ID only!</b>", parse_mode=enums.ParseMode.HTML)
                return

            status_body = _build_user_status_card(target_id)
            try:
                tgt_user   = await client.get_users(target_id)
                name_line  = (
                    f"👤 <b>Name:</b> "
                    f"<a href='tg://user?id={target_id}'>"
                    f"{tgt_user.first_name} {tgt_user.last_name or ''}</a>\n"
                )
                mention_line = (
                    f"🔗 <b>Username:</b> @{tgt_user.username}\n"
                    if tgt_user.username else ""
                )
            except Exception:
                name_line    = (
                    f"👤 <b>Name:</b> "
                    f"<a href='tg://user?id={target_id}'>Unknown</a> "
                    f"(Never started bot)\n"
                )
                mention_line = ""

            await message.reply_text(
                f"👤 <b>GAMEOVER EDITS — User Status</b>\n\n"
                f"🆔 <b>User ID:</b> <code>{target_id}</code>\n"
                f"{name_line}"
                f"{mention_line}"
                f"{status_body}",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_user_action_keyboard(target_id)
            )

        # Watermark Remover Toggle State
        elif step == "waiting_watermark_toggle":
            if not message.text:
                await message.reply_text("❌ <b>Please send a numeric User ID in text format!</b>", parse_mode=enums.ParseMode.HTML)
                return

            clear_state(owner_id)
            try:
                target_id = int(message.text.strip())
            except ValueError:
                await message.reply_text("❌ <b>Numeric User ID only!</b>", parse_mode=enums.ParseMode.HTML)
                return

            from core.db import toggle_watermark
            disabled = toggle_watermark(target_id)
            status_str = "❌ Disabled (No Watermark on outputs)" if disabled else "✅ Enabled (Outputs will have watermark)"

            await message.reply_text(
                f"✅ <b>Watermark settings updated!</b>\n\n"
                f"🆔 <b>User ID:</b> <code>{target_id}</code>\n"
                f"🏷️ <b>Watermark Status:</b> <code>{status_str}</code>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_admin_reply_keyboard()
            )

        # B. Custom Credits Add
        elif step == "waiting_credit_amount":
            if not message.text:
                await message.reply_text("❌ <b>Format:</b> <code>[User_ID] [Amount]</code> in text format!", parse_mode=enums.ParseMode.HTML)
                return

            clear_state(owner_id)
            parts = message.text.strip().split()
            if len(parts) < 2:
                await message.reply_text(
                    "❌ <b>Format:</b> <code>[User_ID] [Amount]</code>\n"
                    "Example: <code>12345678 15</code>",
                    parse_mode=enums.ParseMode.HTML
                )
                return

            try:
                target_id = int(parts[0])
                amount    = int(parts[1])
            except ValueError:
                await message.reply_text("❌ <b>Values must be integers!</b>", parse_mode=enums.ParseMode.HTML)
                return

            new_total = add_credits(target_id, amount)
            await message.reply_text(
                f"✅ <b>Credits updated!</b>\n\n"
                f"🆔 <b>User ID:</b> <code>{target_id}</code>\n"
                f"📊 <b>Change:</b> <code>{'+' if amount >= 0 else ''}{amount} credits</code>\n"
                f"💰 <b>New Balance:</b> <code>{new_total} credits</code>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Main Menu", callback_data="admin_back_main", style="primary")]
                ])
            )
            try:
                await client.send_message(
                    target_id,
                    f"🎁 <b>You received {amount} render credits from the Admin!</b>\n"
                    f"💰 <b>Current Balance:</b> <code>{new_total} credits</code>\n\n"
                    f"Type /edit to use them!",
                    parse_mode=enums.ParseMode.HTML
                )
            except Exception:
                pass

        # C. Global Broadcast (Supports all media: text, photo, video, document, audio, etc.)
        elif step == "waiting_broadcast_msg":
            clear_state(owner_id)
            status_msg = await message.reply_text("⏳ <b>Starting global broadcast...</b>", parse_mode=enums.ParseMode.HTML)

            from core.db import _connect
            with _connect() as conn:
                rows = conn.execute("SELECT user_id FROM users").fetchall()
                user_ids = [row["user_id"] for row in rows]

            if not user_ids:
                await status_msg.edit_text("❌ <b>No registered users found in the database!</b>", parse_mode=enums.ParseMode.HTML)
                return

            success_count = 0
            fail_count = 0

            for uid in user_ids:
                # Avoid rate limit, but broadcast to everyone
                try:
                    await message.copy(chat_id=uid)
                    success_count += 1
                except Exception:
                    fail_count += 1
                await asyncio.sleep(0.05)

            await status_msg.edit_text(
                f"📢 <b>Global Broadcast Completed!</b>\n\n"
                f"✅ <b>Successful:</b> <code>{success_count} users</code>\n"
                f"❌ <b>Failed:</b> <code>{fail_count} users</code>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Main Menu", callback_data="admin_back_main", style="primary")]
                ])
            )

        # D. Change Start Video
        elif step == "waiting_start_video":
            file_id   = None
            file_type = "video"

            if message.video:
                file_id   = message.video.file_id
                file_type = "video"
            elif message.animation:
                file_id   = message.animation.file_id
                file_type = "animation"
            elif (
                message.document
                and message.document.mime_type
                and message.document.mime_type.startswith(("video/", "image/gif"))
            ):
                file_id   = message.document.file_id
                file_type = "document"

            if not file_id:
                await message.reply_text(
                    "❌ <b>Unsupported file! Please upload a valid video or GIF.</b>",
                    parse_mode=enums.ParseMode.HTML
                )
                return

            clear_state(owner_id)
            from core.db import set_setting
            set_setting("start_video_file_id", file_id)
            set_setting("start_video_type", file_type)

            await message.reply_text(
                f"✅ <b>Welcome {file_type} updated successfully!</b>\n\n"
                f"🔑 <b>File ID:</b> <code>{file_id[:25]}...{file_id[-10:]}</code>\n"
                f"All new users will now see this on /start.",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Main Menu", callback_data="admin_back_main", style="primary")]
                ])
            )

    @app.on_message(filters.command("logs") & filters.private)
    async def logs_command(client: Client, message: Message):
        if not message.from_user or not _is_owner(message.from_user.id):
            await message.reply_text("❌ <b>Owner only command!</b>", parse_mode=enums.ParseMode.HTML)
            return

        log_file = "bot.log"
        if not os.path.exists(log_file) or os.path.getsize(log_file) == 0:
            await message.reply_text("ℹ️ <b>Log file is empty or does not exist.</b>", parse_mode=enums.ParseMode.HTML)
            return

        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            preview = "".join(lines[-50:])

        caption = "📋 <b>Recent Bot Logs (Last 50 lines):</b>"
        if len(preview) > 4000:
            preview = preview[-4000:]

        await message.reply_text(
            f"{preview}",
            parse_mode=enums.ParseMode.HTML
        )

        try:
            await message.reply_document(
                document=log_file,
                caption="📁 <b>Full System Log File (bot.log)</b>",
                parse_mode=enums.ParseMode.HTML
            )
        except Exception as e:
            print(f"[Admin Plugin] Failed to send log file: {e}")
