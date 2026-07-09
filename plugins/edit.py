"""
🎬 GAMEOVER EDITS — Core Edit Plugin
Handles the complete user flow:
  /edit → Show quality buttons
  → User picks quality (state saved)
  → User sends video
  → Download → Render → Upload as Document
"""

import os
import time
import uuid
import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from config import Config
from core.db import can_edit, record_edit, get_remaining_edits, is_premium
from core.states import set_state, get_state, clear_state, is_waiting
from core.queue import render_queue
from core.renderer import render_video, QUALITY_PROFILES, INPUT_DIR


# ── Inline Keyboard: Quality Selection ────────────────────────────────────────

def _quality_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🎬 /edit60 — 1080p 60fps  (Fast & Free)",
            callback_data="ge_quality|edit60",
            style="primary"
        )],
        [InlineKeyboardButton(
            "🎥 /edit90 — 2K 60fps  (Balance Mode)",
            callback_data="ge_quality|edit90",
            style="primary"
        )],
        [InlineKeyboardButton(
            "💎 /edit120 — 4K Beast Mode  (VIP 🔒)",
            callback_data="ge_quality|edit120",
            style="success"
        )],
        [InlineKeyboardButton("❌ Cancel", callback_data="ge_cancel", style="danger")],
    ])


# ── /edit Command ──────────────────────────────────────────────────────────────

def register(app: Client):

    @app.on_message(filters.command("edit"))
    async def edit_command(client: Client, message: Message):
        user = message.from_user
        if not user:
            return

        remaining = get_remaining_edits(user.id, Config.DAILY_FREE_LIMIT)
        is_vip    = is_premium(user.id)

        # Status line
        if is_vip:
            quota_line = "💎 <b>Status:</b> <code>PREMIUM — Unlimited 🔓</code>"
        elif remaining > 0:
            quota_line = f"🆓 <b>Status:</b> <code>FREE — {remaining} edit(s) left today</code>"
        else:
            quota_line = "❌ <b>Daily limit reached!</b> Get Premium for unlimited edits."

        # If free user has no edits left, still show keyboard but they'll be blocked on video send
        await message.reply_text(
            f"<b>🎬 GAMEOVER EDITS — Select Quality</b>\n\n"
            f"{quota_line}\n\n"
            f"Choose the render quality for your video:\n\n"
            f"🎬 <b>/edit60</b>  — 1080p 60fps, ~5 min, Fast &amp; Free\n"
            f"🎥 <b>/edit90</b>  — 2K 60fps, ~10 min, Balance Mode\n"
            f"💎 <b>/edit120</b> — 4K Beast Mode, 25-30 min, VIP Only\n\n"
            f"<i>After selecting, send the video you want to edit.</i>",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=_quality_keyboard(),
        )

    # ── Quality Button Callback ────────────────────────────────────────────────

    @app.on_callback_query(filters.regex(r"^ge_quality\|"))
    async def quality_callback(client: Client, query: CallbackQuery):
        user     = query.from_user
        quality  = query.data.split("|")[1]
        profile  = QUALITY_PROFILES.get(quality)

        if not profile:
            await query.answer("❌ Unknown quality!", show_alert=True)
            return

        # 4K Beast Mode: premium check
        if quality == "edit120" and not is_premium(user.id):
            await query.answer(
                "🔒 4K Beast Mode is a VIP Premium feature!\n"
                "It uses veryslow + spline36 + cinema colour grading (25-30 min).\n"
                "Contact the admin to unlock!",
                show_alert=True
            )
            return

        # Check daily quota for free users
        if not can_edit(user.id, Config.DAILY_FREE_LIMIT):
            await query.answer(
                "❌ You've used your free edit for today.\n"
                "Come back tomorrow or get Premium for unlimited!",
                show_alert=True
            )
            return

        # Save user's quality choice in state
        chat_id = query.message.chat.id
        set_state(user.id, quality, chat_id)

        await query.answer(f"✅ {profile['label']} selected!")

        await query.message.edit_text(
            f"✅ <b>Quality Selected:</b> {profile['label']}\n"
            f"⏱️ <b>Est. Render Time:</b> <code>{profile['est_min']}</code>\n\n"
            f"📹 <b>Now send me the video you want to edit!</b>\n\n"
            f"<i>• Send a normal video (not a document)\n"
            f"• Max size: {Config.MAX_VIDEO_SIZE_MB} MB\n"
            f"• Your state expires in 10 minutes</i>",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="ge_cancel")]
            ]),
        )

    # ── Cancel Button ──────────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex(r"^ge_cancel$"))
    async def cancel_callback(client: Client, query: CallbackQuery):
        user = query.from_user
        clear_state(user.id)
        await query.answer("Cancelled!")
        await query.message.edit_text(
            "❌ <b>Cancelled.</b> Type /edit to start again.",
            parse_mode=enums.ParseMode.HTML
        )

    # ── Video Message Handler ──────────────────────────────────────────────────

    @app.on_message(filters.video | filters.document)
    async def video_handler(client: Client, message: Message):
        user = message.from_user
        if not user:
            return

        # Only handle if user has an active quality-selection state
        state = get_state(user.id)
        if not state:
            return  # Ignore — user hasn't typed /edit yet

        quality = state["quality"]
        if quality not in QUALITY_PROFILES:
            return  # Ignore admin/broadcast inputs

        profile = QUALITY_PROFILES.get(quality)
        if not profile:
            clear_state(user.id)
            return

        # ── Validate the file ──────────────────────────────────────────────────
        media = message.video or message.document
        if not media:
            return

        # Check file size
        file_size_mb = (media.file_size or 0) / (1024 * 1024)
        if file_size_mb > Config.MAX_VIDEO_SIZE_MB:
            await message.reply_text(
                f"❌ <b>File too large!</b>\n"
                f"Max allowed: <code>{Config.MAX_VIDEO_SIZE_MB} MB</code>\n"
                f"Your file: <code>{file_size_mb:.1f} MB</code>",
                parse_mode=enums.ParseMode.HTML
            )
            return

        # For documents: only accept video mime types
        if message.document:
            mime = message.document.mime_type or ""
            if not mime.startswith("video/"):
                return  # Not a video document, ignore

        # ── Check daily quota again (race condition protection) ───────────────
        if not can_edit(user.id, Config.DAILY_FREE_LIMIT):
            clear_state(user.id)
            await message.reply_text(
                "❌ <b>Daily limit reached!</b> You've used your free edit for today.\n"
                "Type /premium to learn about unlimited access.",
                parse_mode=enums.ParseMode.HTML
            )
            return

        # Clear the state immediately — they can't submit twice now
        clear_state(user.id)

        # ── Show queue position if busy ────────────────────────────────────────
        queue_pos = render_queue.queue_size() + (1 if render_queue.is_busy() else 0)
        wait_note = (
            f"\n\n📋 <b>Queue position:</b> <code>#{queue_pos + 1}</code>\n"
            f"<i>Please wait for the current render to finish...</i>"
            if queue_pos > 0 else ""
        )

        # ── Status message ─────────────────────────────────────────────────────
        status_msg = await message.reply_text(
            f"📥 <b>Downloading your video...</b>\n\n"
            f"<b>Quality:</b> {profile['label']}\n"
            f"<b>Est. Time:</b> <code>{profile['est_min']}</code>\n"
            f"<b>File Size:</b> <code>{file_size_mb:.1f} MB</code>"
            f"{wait_note}",
            parse_mode=enums.ParseMode.HTML,
        )

        job_id = uuid.uuid4().hex[:8]
        chat_id = message.chat.id

        async def do_render():
            input_path  = None
            output_path = None

            def _make_progress_bar_chars(pct: float, length: int = 15) -> str:
                filled = int(round(pct / 100 * length))
                empty  = length - filled
                return f"{'▰' * filled}{'▱' * empty}"

            # Terminal variables
            dl_status     = "Waiting..."
            render_status = "Waiting..."
            ul_status     = "Waiting..."

            def build_terminal_text():
                return (
                    f"🖥️ <b>GAMEOVER EDITS TERMINAL</b>\n\n"
                    f"<code>"
                    f"📥 Downloading: {dl_status}\n"
                    f"⚙️ Rendering:   {render_status}\n"
                    f"📤 Uploading:   {ul_status}"
                    f"</code>"
                )

            try:
                # ── Step 1: Download ───────────────────────────────────────────
                dl_status = "0.0 MB / 0.0 MB (0%)\n[▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱]"
                await _safe_edit(status_msg, build_terminal_text())

                ext         = ".mp4"
                input_path  = os.path.join(INPUT_DIR, f"ge_in_{job_id}{ext}")
                dl_start    = time.time()
                last_edit_time = [time.time()]

                async def dl_progress(current, total):
                    nonlocal dl_status
                    now = time.time()
                    if now - last_edit_time[0] < 3.0:
                        return
                    last_edit_time[0] = now

                    cur_mb = current / (1024 * 1024)
                    tot_mb = total / (1024 * 1024)
                    pct = (current / total) * 100 if total > 0 else 0
                    bar = _make_progress_bar_chars(pct, 15)
                    dl_status = f"{cur_mb:.1f} MB / {tot_mb:.1f} MB ({pct:.1f}%)\n[{bar}]"
                    await _safe_edit(status_msg, build_terminal_text())

                await client.download_media(message, file_name=input_path, progress=dl_progress)

                if not os.path.exists(input_path) or os.path.getsize(input_path) < 1000:
                    await _safe_edit(status_msg, "❌ <b>Download failed. Please try again.</b>")
                    return

                dl_time = time.time() - dl_start
                in_size = os.path.getsize(input_path) / (1024 * 1024)
                dl_status = f"Done! [{in_size:.1f} MB in {dl_time:.0f}s]"
                await _safe_edit(status_msg, build_terminal_text())

                # ── Step 2: Render ─────────────────────────────────────────────
                render_start = time.time()
                render_status = "Starting..."
                await _safe_edit(status_msg, build_terminal_text())

                async def progress_cb(info: dict):
                    nonlocal render_status
                    now = time.time()
                    if now - last_edit_time[0] < 3.0:
                        return
                    last_edit_time[0] = now

                    pct   = info["pct"]
                    speed = info.get("speed", "1.0x")
                    eta   = info["eta"]
                    bar   = _make_progress_bar_chars(pct, 15)
                    render_status = f"{pct:.1f}% | Speed: {speed} | ETA: {eta}\n[{bar}]"
                    await _safe_edit(status_msg, build_terminal_text())

                output_path = await render_video(
                    input_path=input_path,
                    quality_key=quality,
                    watermark_text=Config.WATERMARK_TEXT,
                    progress_callback=progress_cb,
                )

                if not output_path:
                    await _safe_edit(status_msg,
                        "❌ <b>Render failed!</b>\n"
                        "FFmpeg encountered an error. Please try again."
                    )
                    return

                render_time = time.time() - render_start
                out_size = os.path.getsize(output_path) / (1024 * 1024)
                render_status = f"Done! [{out_size:.1f} MB in {render_time:.0f}s]"
                await _safe_edit(status_msg, build_terminal_text())

                # ── Step 3: Upload as Document ─────────────────────────────────
                ul_status = "0.0 MB / 0.0 MB (0%)\n[▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱]"
                await _safe_edit(status_msg, build_terminal_text())

                async def ul_progress(current, total):
                    nonlocal ul_status
                    now = time.time()
                    if now - last_edit_time[0] < 3.0:
                        return
                    last_edit_time[0] = now

                    cur_mb = current / (1024 * 1024)
                    tot_mb = total / (1024 * 1024)
                    pct = (current / total) * 100 if total > 0 else 0
                    bar = _make_progress_bar_chars(pct, 15)
                    ul_status = f"{cur_mb:.1f} MB / {tot_mb:.1f} MB ({pct:.1f}%)\n[{bar}]"
                    await _safe_edit(status_msg, build_terminal_text())

                caption = (
                    f"🎬 <b>GAMEOVER EDITS</b>\n\n"
                    f"✅ <b>Quality:</b> {profile['label']}\n"
                    f"📦 <b>Size:</b> <code>{out_size:.1f} MB</code>\n"
                    f"🆔 <b>Job ID:</b> <code>{job_id}</code>\n\n"
                    f"<i>Sent as Document — full quality preserved, no Telegram compression!</i>"
                )

                await client.send_document(
                    chat_id=chat_id,
                    document=output_path,
                    caption=caption,
                    parse_mode=enums.ParseMode.HTML,
                    force_document=True,  # Never compress as video
                    progress=ul_progress,
                )

                ul_status = "Done!"
                await _safe_edit(status_msg, build_terminal_text())

                # Record the edit in DB
                record_edit(user.id)

                remaining_after = get_remaining_edits(user.id, Config.DAILY_FREE_LIMIT)
                if is_premium(user.id):
                    remaining_str = "💎 Unlimited (Premium)"
                elif remaining_after < 0:
                    remaining_str = "💎 Unlimited (Premium)"
                else:
                    remaining_str = f"{remaining_after} edit(s) left today"

                # Delete the status message and send a clean done message
                try:
                    await status_msg.delete()
                except Exception:
                    pass

                await client.send_message(
                    chat_id=chat_id,
                    text=(
                        f"✅ <b>Render Complete!</b>\n\n"
                        f"Your file has been sent above ☝️\n"
                        f"📊 <b>Credits:</b> <code>{remaining_str}</code>\n\n"
                        f"Type /edit to make another render!"
                    ),
                    parse_mode=enums.ParseMode.HTML,
                )

            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"[Edit Plugin] ❌ Job {job_id} error: {e}")
                await _safe_edit(status_msg, f"❌ <b>An unexpected error occurred:</b>\n<code>{e}</code>")

            finally:
                # Always clean up temp files
                for path in [input_path, output_path]:
                    if path and os.path.exists(path):
                        try:
                            os.remove(path)
                        except Exception:
                            pass

        # Submit to the render queue
        pos = await render_queue.submit(
            job_id=job_id,
            user_id=user.id,
            callback=do_render,
        )

        if pos > 1:
            await _safe_edit(status_msg,
                f"📋 <b>Added to queue!</b>\n\n"
                f"🆔 <b>Job ID:</b> <code>{job_id}</code>\n"
                f"🎬 <b>Quality:</b> {profile['label']}\n"
                f"📍 <b>Your position:</b> <code>#{pos}</code>\n\n"
                f"<i>You will be notified when your render starts.</i>"
            )


# ── Helper ─────────────────────────────────────────────────────────────────────

async def _safe_edit(message: Message, text: str):
    """Edit a message safely, ignoring any Telegram API errors."""
    try:
        await message.edit_text(text, parse_mode=enums.ParseMode.HTML)
    except Exception:
        pass
