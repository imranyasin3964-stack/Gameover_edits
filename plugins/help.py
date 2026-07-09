"""
📖 GAMEOVER EDITS — /start, /help, /premium commands
"""

from pyrogram import Client, filters, enums
from pyrogram.types import Message

from config import Config
from core.db import get_remaining_edits, is_premium


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

For premium access, contact: @{owner}
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

👑 <b>Admin:</b> @{owner_mention}

<i>Mention you want GAMEOVER EDITS Premium!</i>
""".strip()


def register(app: Client):

    @app.on_message(filters.command("start"))
    async def start_command(client: Client, message: Message):
        user = message.from_user
        name = user.first_name if user else "Friend"

        remaining = get_remaining_edits(user.id, Config.DAILY_FREE_LIMIT) if user else 1
        is_vip    = is_premium(user.id) if user else False

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

        if Config.START_VIDEO:
            try:
                if Config.START_VIDEO.endswith(".gif"):
                    await message.reply_animation(Config.START_VIDEO, caption=text, parse_mode=enums.ParseMode.HTML)
                else:
                    await message.reply_video(Config.START_VIDEO, caption=text, parse_mode=enums.ParseMode.HTML)
                return
            except Exception as e:
                print(f"[Help Plugin] ⚠️ Failed to send start video: {e}")

        await message.reply_text(text, parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.command("help"))
    async def help_command(client: Client, message: Message):
        # Get owner's username for contact info
        try:
            owner = await client.get_users(Config.OWNER_ID)
            owner_mention = f"@{owner.username}" if owner.username else str(Config.OWNER_ID)
        except Exception:
            owner_mention = str(Config.OWNER_ID)

        await message.reply_text(
            HELP_TEXT.format(owner=owner_mention),
            parse_mode=enums.ParseMode.HTML,
        )

    @app.on_message(filters.command("premium"))
    async def premium_command(client: Client, message: Message):
        try:
            owner = await client.get_users(Config.OWNER_ID)
            owner_mention = f"@{owner.username}" if owner.username else str(Config.OWNER_ID)
        except Exception:
            owner_mention = str(Config.OWNER_ID)

        await message.reply_text(
            PREMIUM_TEXT.format(owner_mention=owner_mention),
            parse_mode=enums.ParseMode.HTML,
        )
