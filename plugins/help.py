"""
📖 GAMEOVER EDITS — /start, /help, /premium commands
"""

from pyrogram import Client, filters, enums
from pyrogram.types import Message

from config import Config
from core.db import get_remaining_edits, is_premium, get_premium_expiry


HELP_TEXT = """
<b>🎬 GAMEOVER EDITS — Help Menu</b>

━━━━━━━━━━━━━━━━━━━━━━━━━
<b>HOW TO USE:</b>

<b>Step 1:</b> Type <code>/edit</code> in any chat.
<b>Step 2:</b> Choose your render quality from the buttons.
<b>Step 3:</b> Send or forward the video you want to edit.
<b>Step 4:</b> Sit back! Bot renders and sends back the file.

━━━━━━━━━━━━━━━━━━━━━━━━━
<b>QUALITY OPTIONS:</b>

🎬 <b>1080p — 60 FPS</b> (Free)
   → Full HD, smooth 60fps, ~1-2 min render
   → Great for daily sharing

🎥 <b>2K — 60 FPS</b> (Free)
   → 2560×1440 resolution, crisp detail
   → Perfect for TikTok & Reels creators

💎 <b>4K — 120 FPS</b> (Premium Only)
   → Ultra HD 3840×2160, buttery 120fps
   → Professional-grade Beast Mode render

━━━━━━━━━━━━━━━━━━━━━━━━━
<b>COMMANDS:</b>

/edit — Open quality selection menu
/help — Show this help message
/premium — View premium info & pricing

━━━━━━━━━━━━━━━━━━━━━━━━━
<b>LIMITS:</b>
• <b>Free Users:</b> 1 render per day
• <b>Premium Users:</b> Unlimited renders, Beast Mode unlocked 🔓

For premium access, contact: {owner}
""".strip()


PREMIUM_TEXT = """
<b>💎 GAMEOVER EDITS — Premium Plans</b>

━━━━━━━━━━━━━━━━━━━━━━━━━
<b>FREE PLAN:</b>
✅ 1080p & 2K quality
✅ 1 edit per day
✅ Color Grading + Watermark
❌ 4K 120fps Beast Mode locked

<b>PREMIUM PLAN:</b>
✅ ALL quality modes (1080p, 2K, 4K)
✅ 💎 4K 120 FPS Beast Mode unlocked
✅ Unlimited daily edits
✅ Priority rendering (jump the queue)

━━━━━━━━━━━━━━━━━━━━━━━━━
To get Premium access, contact the Admin directly:

👑 <b>Admin:</b> {owner_mention}

<i>Mention you want GAMEOVER EDITS Premium!</i>
""".strip()


def register(app: Client):

    @app.on_message(filters.command("start"))
    async def start_command(client: Client, message: Message):
        user = message.from_user
        if not user:
            return
        
        name = user.first_name

        # ── User Registration & Admin Notification ──────────────────────────────────
        from core.db import add_user, get_setting
        is_new = add_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )

        if is_new:
            try:
                username_str = f" (@{user.username})" if user.username else ""
                await client.send_message(
                    Config.OWNER_ID,
                    f"🔔 <b>New User Joined GAMEOVER EDITS!</b>\n\n"
                    f"👤 <b>Name:</b> <a href='tg://user?id={user.id}'>{user.first_name} {user.last_name or ''}</a>{username_str}\n"
                    f"🆔 <b>User ID:</b> <code>{user.id}</code>",
                    parse_mode=enums.ParseMode.HTML
                )
            except Exception as e:
                print(f"[Help Plugin] ⚠️ Failed to notify owner: {e}")

        remaining = get_remaining_edits(user.id, Config.DAILY_FREE_LIMIT)
        is_vip    = is_premium(user.id)

        status_line = (
            "💎 <b>Status:</b> <code>PREMIUM — Unlimited Edits 🔓</code>"
            if is_vip else
            f"🆓 <b>Status:</b> <code>FREE — {remaining} edit(s) remaining today</code>"
        )

        text = (
            f"👋 <b>Welcome, {name}!</b>\n\n"
            f"I'm <b>GAMEOVER EDITS</b> — your professional video rendering bot.\n\n"
            f"I take your raw videos and transform them into:\n"
            f"  🎬 Sharp 1080p 60fps\n"
            f"  🎥 Crisp 2K 60fps\n"
            f"  💎 Beast Mode 4K 120fps\n\n"
            f"All with <b>HDR color grading</b>, <b>pixel sharpening</b>, and a <b>GAMEOVER EDITS</b> watermark.\n\n"
            f"{status_line}\n\n"
            f"Type /edit to begin! 🚀\n"
            f"Type /help for the full guide."
        )

        # Retrieve dynamic welcome media
        db_start_video = get_setting("start_video_file_id", "")
        db_video_type = get_setting("start_video_type", "video")
        
        start_source = db_start_video if db_start_video else Config.START_VIDEO

        if start_source:
            try:
                is_gif = (db_video_type == "animation" or 
                          start_source.endswith(".gif") or 
                          "animation" in db_video_type)
                if is_gif:
                    await message.reply_animation(start_source, caption=text, parse_mode=enums.ParseMode.HTML)
                else:
                    await message.reply_video(start_source, caption=text, parse_mode=enums.ParseMode.HTML)
                return
            except Exception as e:
                print(f"[Help Plugin] ⚠️ Failed to send start welcome video: {e}")

        await message.reply_text(text, parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.command("help"))
    async def help_command(client: Client, message: Message):
        owner_link = f'<a href="tg://user?id={Config.OWNER_ID}">GameOver</a>'
        await message.reply_text(
            HELP_TEXT.format(owner=owner_link),
            parse_mode=enums.ParseMode.HTML,
        )

    @app.on_message(filters.command("premium"))
    async def premium_command(client: Client, message: Message):
        owner_link = f'<a href="tg://user?id={Config.OWNER_ID}">GameOver</a>'
        await message.reply_text(
            PREMIUM_TEXT.format(owner_mention=owner_link),
            parse_mode=enums.ParseMode.HTML,
        )

    @app.on_message(filters.command("myplan"))
    async def myplan_command(client: Client, message: Message):
        """Show the user their current subscription status and exact time remaining."""
        from datetime import datetime, timezone, timedelta

        user = message.from_user
        if not user:
            return

        vip       = is_premium(user.id)
        expiry_dt = get_premium_expiry(user.id)
        remaining = get_remaining_edits(user.id, Config.DAILY_FREE_LIMIT)

        # ── Owner ──────────────────────────────────────────────────────────────
        if user.id == Config.OWNER_ID:
            await message.reply_text(
                f"👑 <b>Your Plan: OWNER</b>\n\n"
                f"You have <b>permanent, unlimited</b> access to all features.\n"
                f"💎 4K Beast Mode unlocked 🔓\n"
                f"♾️ Unlimited daily renders",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        # ── Active Premium ─────────────────────────────────────────────────────
        if vip and expiry_dt:
            now_utc   = datetime.now(timezone.utc)
            diff      = expiry_dt - now_utc
            total_sec = int(diff.total_seconds())

            if total_sec > 0:
                days    = total_sec // 86400
                hours   = (total_sec % 86400) // 3600
                minutes = (total_sec % 3600) // 60

                # Build a clear remaining string
                remaining_parts = []
                if days:    remaining_parts.append(f"{days} day(s)")
                if hours:   remaining_parts.append(f"{hours} hour(s)")
                if minutes: remaining_parts.append(f"{minutes} minute(s)")
                remaining_str = ", ".join(remaining_parts) if remaining_parts else "less than 1 minute"

                expiry_str = expiry_dt.strftime("%Y-%m-%d %H:%M UTC")

                # Urgency hint
                if total_sec < 86400:       # less than 1 day
                    urgency = "\n\n⚠️ <b>Your subscription expires very soon!</b> Contact admin to renew."
                elif total_sec < 86400 * 3: # less than 3 days
                    urgency = "\n\n🔔 <b>Tip:</b> Your plan expires in less than 3 days."
                else:
                    urgency = ""

                await message.reply_text(
                    f"💎 <b>Your Plan: PREMIUM</b>\n\n"
                    f"✅ Status: <code>Active</code>\n"
                    f"⏰ <b>Expires:</b> <code>{expiry_str}</code>\n"
                    f"⌛ <b>Time Remaining:</b> <code>{remaining_str}</code>\n\n"
                    f"<b>Included:</b>\n"
                    f"  ✅ Unlimited daily edits\n"
                    f"  ✅ All quality modes (1080p / 2K / 4K)\n"
                    f"  ✅ 4K Beast Mode unlocked 🔓"
                    f"{urgency}",
                    parse_mode=enums.ParseMode.HTML,
                )
                return

        # ── Free User (or expired premium) ────────────────────────────────────
        edits_left = max(0, remaining) if remaining >= 0 else 0
        expired_note = ""
        if expiry_dt:
            # They had premium but it lapsed
            expired_str  = expiry_dt.strftime("%Y-%m-%d %H:%M UTC")
            expired_note = f"\n\n⚠️ Your last subscription expired on <code>{expired_str}</code>."

        owner_link = f'<a href="tg://user?id={Config.OWNER_ID}">GameOver</a>'

        await message.reply_text(
            f"🆓 <b>Your Plan: FREE</b>\n\n"
            f"🎬 <b>Edits left today:</b> <code>{edits_left} / {Config.DAILY_FREE_LIMIT}</code>\n"
            f"❌ 4K Beast Mode locked\n"
            f"❌ Limited to {Config.DAILY_FREE_LIMIT} render(s) per day"
            f"{expired_note}\n\n"
            f"💎 <b>Upgrade to Premium</b> for unlimited edits + 4K!\n"
            f"Contact: {owner_link}",
            parse_mode=enums.ParseMode.HTML,
        )

