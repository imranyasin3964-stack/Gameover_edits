"""
🎬 GAMEOVER EDITS — Core Edit Plugin (Phase 3: Hybrid Cloud Architecture)

Rendering Modes:
  DRIVE MODE (default when credentials.json + folder IDs are configured):
    1. Download video from Telegram → VPS local disk
    2. Upload to Google Drive INPUT_VIDEOS/{quality}_{job_id}.mp4
    3. Async-poll OUTPUT_VIDEOS every 15s for up to 45 min
    4. Download finished GPU-rendered file from Drive
    5. Send to Telegram user as Document
    6. Cleanup Drive (delete both input & output files)

  LOCAL FALLBACK MODE (auto-activates when Drive is NOT configured):
    Uses the original local FFmpeg CPU render pipeline via core/renderer.py
    Identical user experience, just slower.

User flow (both modes):
  /edit → Quality buttons → User sends video → Download → [Hybrid OR Local] → Upload to TG
"""

import os
import sys
import time
import uuid
import asyncio
import traceback

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
from core.db import can_edit, record_edit, get_remaining_edits, is_premium, has_watermark_disabled
from core.states import set_state, get_state, clear_state
from core.queue import render_queue
from core.renderer import render_video, QUALITY_PROFILES, INPUT_DIR, RENDER_DIR


# ── Progress bar helper ────────────────────────────────────────────────────────

def _bar(pct: float, length: int = 10) -> str:
    filled = int(round(pct / 100 * length))
    empty  = length - filled
    return f"{'▰' * filled}{'▱' * empty}"


# ── Reply Keyboard: Quality Selection ─────────────────────────────────────────

def _quality_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([
        ["🎬 1080p (Fast & Free)"],
        ["🎥 2K (Balance Mode)"],
        ["💎 4K Beast Mode (VIP)"],
        ["❌ Cancel"]
    ], resize_keyboard=True)


# ── Quality key map ────────────────────────────────────────────────────────────

MAP_TEXT_TO_QUALITY = {
    "🎬 1080p (Fast & Free)": "edit60",
    "🎥 2K (Balance Mode)":   "edit90",
    "💎 4K Beast Mode (VIP)": "edit120",
}


# ── register() ────────────────────────────────────────────────────────────────

def register(app: Client):

    # ── /edit Command ──────────────────────────────────────────────────────────

    @app.on_message(filters.command("edit"))
    async def edit_command(client: Client, message: Message):
        user = message.from_user
        if not user:
            return

        remaining = get_remaining_edits(user.id, Config.DAILY_FREE_LIMIT)
        is_vip    = is_premium(user.id)

        drive_mode = Config.drive_configured()
        mode_badge = "☁️ <b>Mode:</b> <code>Colab GPU Cloud</code>" if drive_mode else "⚙️ <b>Mode:</b> <code>Local CPU Render</code>"

        if is_vip:
            quota_line = "💎 <b>Status:</b> <code>PREMIUM — Unlimited 🔓</code>"
        elif remaining > 0:
            quota_line = f"🆓 <b>Status:</b> <code>FREE — {remaining} edit(s) left today</code>"
        else:
            quota_line = "❌ <b>Daily limit reached!</b> Get Premium for unlimited edits."

        await message.reply_text(
            f"<b>🎬 GAMEOVER EDITS — Select Quality</b>\n\n"
            f"{mode_badge}\n"
            f"{quota_line}\n\n"
            f"Choose the render quality:\n\n"
            f"🎬 <b>/edit60</b>  — 1080p 60fps | ~5 min\n"
            f"🎥 <b>/edit90</b>  — 2K 90fps | ~10 min\n"
            f"💎 <b>/edit120</b> — 4K 120fps | 25-30 min | VIP\n\n"
            f"<i>After selecting, send the video you want to edit.</i>",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=_quality_reply_keyboard(),
        )

    # ── Quality Button Handler ─────────────────────────────────────────────────

    def is_quality_btn(_, __, message: Message) -> bool:
        if not message.text:
            return False
        return message.text.strip() in MAP_TEXT_TO_QUALITY

    @app.on_message(
        filters.create(is_quality_btn)
        & filters.incoming
        & filters.private
    )
    async def quality_selection_message_handler(client: Client, message: Message):
        user = message.from_user
        if not user:
            return

        text    = message.text.strip()
        quality = MAP_TEXT_TO_QUALITY[text]
        profile = QUALITY_PROFILES.get(quality)
        if not profile:
            return

        # 4K = VIP only
        if quality == "edit120" and not is_premium(user.id):
            await message.reply_text(
                "🔒 <b>4K Beast Mode is a VIP Premium feature!</b>\n\n"
                "Contact the admin to unlock!",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_quality_reply_keyboard()
            )
            return

        if not can_edit(user.id, Config.DAILY_FREE_LIMIT):
            bot_me = await client.get_me()
            invite_link = f"https://t.me/{bot_me.username}?start={user.id}"
            await message.reply_text(
                "❌ <b>Out of Free Edits!</b>\n"
                "🎁 Invite friends to earn more, or buy Premium for UNLIMITED edits.",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎁 Invite & Earn Free Edits", url=invite_link)]
                ])
            )
            return

        set_state(user.id, quality, message.chat.id)
        await message.reply_text(
            f"✅ <b>Quality Selected:</b> {profile['label']}\n"
            f"⏱️ <b>Est. Render Time:</b> <code>{profile['est_min']}</code>\n\n"
            f"📹 <b>Now send me the video you want to edit!</b>\n\n"
            f"<i>• Max size: {Config.MAX_VIDEO_SIZE_MB} MB\n"
            f"• State expires in 10 minutes</i>",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("❌ Cancel")]], resize_keyboard=True
            )
        )

    # ── Cancel Handlers ────────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex(r"^ge_cancel$"))
    async def cancel_callback(client: Client, query: CallbackQuery):
        clear_state(query.from_user.id)
        await query.answer("❌ Cancelled!")
        try:
            await query.message.delete()
        except Exception:
            pass
        await client.send_message(
            chat_id=query.message.chat.id,
            text="❌ <b>Cancelled.</b> Send /edit to start again.",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove()
        )

    def is_cancel_for_video_edit(_, __, message: Message) -> bool:
        if not message.from_user or not message.text:
            return False
        if message.text.strip() != "❌ Cancel":
            return False
        state = get_state(message.from_user.id)
        return bool(state and state.get("quality") in QUALITY_PROFILES)

    @app.on_message(filters.create(is_cancel_for_video_edit) & filters.private)
    async def cancel_message_handler(client: Client, message: Message):
        if not message.from_user:
            return
        clear_state(message.from_user.id)
        await message.reply_text(
            "❌ <b>Cancelled.</b> Send /edit to start again.",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove()
        )

    # ── Video Handler ──────────────────────────────────────────────────────────

    def is_waiting_for_video_edit(_, __, message: Message) -> bool:
        if not message.from_user:
            return False
        state = get_state(message.from_user.id)
        return bool(state and state.get("quality") in QUALITY_PROFILES)

    @app.on_message(
        (filters.video | filters.document)
        & filters.create(is_waiting_for_video_edit)
    )
    async def video_handler(client: Client, message: Message):
        user = message.from_user
        if not user:
            return

        state = get_state(user.id)
        quality = state["quality"]
        profile = QUALITY_PROFILES.get(quality)
        if not profile:
            clear_state(user.id)
            return

        media = message.video or message.document
        if not media:
            return

        # Size check
        file_size_mb = (media.file_size or 0) / (1024 * 1024)
        if file_size_mb > Config.MAX_VIDEO_SIZE_MB:
            await message.reply_text(
                f"❌ <b>File too large!</b>\n"
                f"Max: <code>{Config.MAX_VIDEO_SIZE_MB} MB</code>\n"
                f"Your file: <code>{file_size_mb:.1f} MB</code>",
                parse_mode=enums.ParseMode.HTML
            )
            return

        # Only accept video mime types for documents
        if message.document:
            mime = message.document.mime_type or ""
            if not mime.startswith("video/"):
                return

        # Cooldown check
        from core.db import get_cooldown_remaining
        cooldown = get_cooldown_remaining(user.id)
        if cooldown > 0:
            clear_state(user.id)
            minutes = int(cooldown // 60) + (1 if cooldown % 60 > 0 else 0)
            await message.reply_text(
                f"⏳ <b>Cooldown Active!</b>\n"
                f"Time remaining: <code>{minutes} minutes</code>\n"
                f"💎 <i>Upgrade to Premium to bypass!</i>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=ReplyKeyboardRemove()
            )
            return

        # Final quota check (race condition protection)
        if not can_edit(user.id, Config.DAILY_FREE_LIMIT):
            clear_state(user.id)
            bot_me = await client.get_me()
            invite_link = f"https://t.me/{bot_me.username}?start={user.id}"
            await message.reply_text(
                "❌ <b>Out of Free Edits!</b>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎁 Invite & Earn Free Edits", url=invite_link)]
                ])
            )
            return

        clear_state(user.id)

        # Detect which rendering mode to use
        use_drive = Config.drive_configured()
        mode_label = "☁️ Colab GPU Cloud" if use_drive else "⚙️ Local CPU"

        # Send initial status message
        status_msg = await message.reply_text(
            f"📥 <b>Downloading your video...</b>\n\n"
            f"<b>Quality:</b> {profile['label']}\n"
            f"<b>Mode:</b> <code>{mode_label}</code>\n"
            f"<b>Est. Time:</b> <code>{profile['est_min']}</code>\n"
            f"<b>File Size:</b> <code>{file_size_mb:.1f} MB</code>",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove(),
        )

        # ── Lock IDs and bind edit function ───────────────────────────────────
        status_chat_id = status_msg.chat.id  # immutable integer
        status_msg_id  = status_msg.id        # immutable integer
        print(
            f"[Edit] 📌 STATUS MSG LOCKED — "
            f"chat_id={status_chat_id}  msg_id={status_msg_id}  "
            f"mode={'DRIVE' if use_drive else 'LOCAL'}"
        )

        async def _edit(text: str) -> None:
            """Bound edit: uses status_msg.edit_text() to bypass peer cache."""
            # Print a clean, plain-text log to the VPS console for easy monitoring
            clean_log = text.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "").replace("<i>", "").replace("</i>", "")
            # Replace multiple newlines with a single space/newline for log readability
            clean_log = " | ".join(line.strip() for line in clean_log.split("\n") if line.strip())
            print(f"[Progress Log] ⚡ {clean_log}")

            try:
                await status_msg.edit_text(text, parse_mode=enums.ParseMode.HTML)
            except Exception as exc:
                err = str(exc)
                if "MESSAGE_ID_INVALID" in err:
                    try:
                        # Refresh peer cache in Pyrogram SQLite session database
                        await client.get_chat(status_chat_id)
                        await status_msg.edit_text(text, parse_mode=enums.ParseMode.HTML)
                        return
                    except Exception as retry_exc:
                        exc = retry_exc
                
                err = str(exc)
                if "MESSAGE_NOT_MODIFIED" not in err:
                    print(f"[Edit] ⚠ edit_text failed: {exc}", file=sys.stderr)

        job_id  = uuid.uuid4().hex[:8]
        chat_id = status_chat_id

        # ──────────────────────────────────────────────────────────────────────
        # do_render() — the main async task
        # ──────────────────────────────────────────────────────────────────────
        async def do_render():
            input_path        = None
            output_path       = None
            drive_input_id    = None
            drive_output_id   = None

            last_edit_time = [time.time()]

            try:
                # ── Step 1: Download from Telegram ─────────────────────────────
                input_path = os.path.join(INPUT_DIR, f"ge_in_{job_id}.mp4")

                async def dl_progress(current, total):
                    now = time.time()
                    if now - last_edit_time[0] < 3.0:
                        return
                    last_edit_time[0] = now
                    cur_mb = current / (1024 * 1024)
                    tot_mb = total   / (1024 * 1024)
                    pct    = (current / total) * 100 if total > 0 else 0
                    await _edit(
                        f"📥 <b>DOWNLOADING YOUR VIDEO...</b>\n\n"
                        f"Progress: {_bar(pct)} {pct:.0f}%\n"
                        f"📦 Size: <code>{cur_mb:.1f} MB / {tot_mb:.1f} MB</code>"
                    )

                await client.download_media(message, file_name=input_path, progress=dl_progress)

                if not os.path.exists(input_path) or os.path.getsize(input_path) < 1000:
                    await _edit("❌ <b>Download failed. Please try again.</b>")
                    return

                # ── ROUTE: Drive (Colab GPU) or Local CPU ─────────────────────
                if use_drive:
                    output_path = await _render_via_drive(
                        input_path=input_path,
                        quality=quality,
                        profile=profile,
                        job_id=job_id,
                        _edit=_edit,
                        last_edit_time=last_edit_time,
                    )
                    # Retrieve the stored Drive IDs for cleanup later
                    drive_input_id  = getattr(_render_via_drive, "_last_input_id",  None)
                    drive_output_id = getattr(_render_via_drive, "_last_output_id", None)
                else:
                    output_path = await _render_via_local(
                        input_path=input_path,
                        quality=quality,
                        profile=profile,
                        user_id=user.id,
                        job_id=job_id,
                        _edit=_edit,
                        last_edit_time=last_edit_time,
                    )

                if not output_path or not os.path.exists(output_path):
                    await _edit(
                        "❌ <b>Render failed!</b>\n"
                        "The processing step encountered an error. Please try again."
                    )
                    return

                out_size = os.path.getsize(output_path) / (1024 * 1024)

                # ── Step 3: Upload finished video to Telegram ──────────────────
                async def ul_progress(current, total):
                    now = time.time()
                    if now - last_edit_time[0] < 3.0:
                        return
                    last_edit_time[0] = now
                    cur_mb = current / (1024 * 1024)
                    tot_mb = total   / (1024 * 1024)
                    pct    = (current / total) * 100 if total > 0 else 0
                    await _edit(
                        f"📤 <b>UPLOADING YOUR VIDEO...</b>\n\n"
                        f"Progress: {_bar(pct)} {pct:.0f}%\n"
                        f"📦 Size: <code>{cur_mb:.1f} MB / {tot_mb:.1f} MB</code>"
                    )

                caption = (
                    f"🎬 <b>GAMEOVER EDITS</b>\n\n"
                    f"✅ <b>Quality:</b> {profile['label']}\n"
                    f"🖥️ <b>Rendered by:</b> <code>{'Colab GPU ☁️' if use_drive else 'Local CPU ⚙️'}</code>\n"
                    f"📦 <b>Size:</b> <code>{out_size:.1f} MB</code>\n"
                    f"🆔 <b>Job ID:</b> <code>{job_id}</code>\n\n"
                    f"<i>Sent as Document — full quality, no Telegram compression!</i>"
                )

                await client.send_document(
                    chat_id=chat_id,
                    document=output_path,
                    caption=caption,
                    parse_mode=enums.ParseMode.HTML,
                    force_document=True,
                    progress=ul_progress,
                )

                record_edit(user.id)

                remaining_after = get_remaining_edits(user.id, Config.DAILY_FREE_LIMIT)
                remaining_str = (
                    "💎 Unlimited (Premium)"
                    if (is_premium(user.id) or remaining_after < 0)
                    else f"{remaining_after} edit(s) left today"
                )

                # Delete progress message, send clean done message
                try:
                    await client.delete_messages(
                        chat_id=status_chat_id, message_ids=status_msg_id
                    )
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
                traceback.print_exc()
                print(f"[Edit Plugin] ❌ Job {job_id} error: {e}")
                await _edit(f"❌ <b>An unexpected error occurred:</b>\n<code>{e}</code>")

            finally:
                # Always clean up local temp files
                for path in [input_path, output_path]:
                    if path and os.path.exists(path):
                        try:
                            os.remove(path)
                        except Exception:
                            pass

                # Clean up Drive files if Drive mode was used
                if use_drive and (drive_input_id or drive_output_id):
                    loop = asyncio.get_event_loop()
                    try:
                        from core.drive_manager import cleanup_drive
                        await loop.run_in_executor(
                            None, cleanup_drive, drive_input_id, drive_output_id
                        )
                    except Exception as exc:
                        print(f"[Edit Plugin] ⚠ Drive cleanup warning: {exc}", file=sys.stderr)

        # ── Submit to render queue ─────────────────────────────────────────────
        pos = await render_queue.submit(
            job_id=job_id,
            user_id=user.id,
            callback=do_render,
        )

        if pos > 1:
            await _edit(
                f"📋 <b>Added to queue!</b>\n\n"
                f"🆔 <b>Job ID:</b> <code>{job_id}</code>\n"
                f"🎬 <b>Quality:</b> {profile['label']}\n"
                f"📍 <b>Your position:</b> <code>#{pos}</code>\n\n"
                f"<i>You will be notified when your render starts.</i>"
            )


# ──────────────────────────────────────────────────────────────────────────────
# RENDER HELPERS (module-level so do_render can reference them cleanly)
# ──────────────────────────────────────────────────────────────────────────────

async def _render_via_drive(
    input_path: str,
    quality: str,
    profile: dict,
    job_id: str,
    _edit,
    last_edit_time: list,
) -> str | None:
    """
    Hybrid Cloud path:
      1. Upload input to Google Drive INPUT_VIDEOS/{quality}_{job_id}.mp4
      2. Async-poll OUTPUT_VIDEOS/{quality}_{job_id}.mp4 every DRIVE_POLL_INTERVAL_SEC
      3. Download finished file to local disk
      4. Return local output path

    Drive file IDs are stashed on the function object so the caller can
    read them for cleanup:
        _render_via_drive._last_input_id
        _render_via_drive._last_output_id
    """
    from core.drive_manager import (
        authenticate_drive,
        upload_to_input,
        check_output_ready,
        download_from_output,
    )

    loop = asyncio.get_event_loop()

    # Filename encodes quality so Colab worker knows which profile to run
    drive_filename = f"{quality}_{job_id}.mp4"
    output_path    = os.path.join(RENDER_DIR, f"ge_out_{job_id}.mp4")

    # ── Upload to Drive INPUT_VIDEOS ──────────────────────────────────────────
    await _edit(
        f"☁️ <b>UPLOADING TO COLAB CLOUD...</b>\n\n"
        f"Quality: {profile['label']}\n"
        f"<i>Sending your video to the GPU server...</i>"
    )
    last_edit_time[0] = time.time()

    try:
        drive_input_id = await loop.run_in_executor(
            None, upload_to_input, input_path, drive_filename
        )
    except Exception as exc:
        print(f"[Edit/Drive] Upload failed: {exc}")
        _render_via_drive._last_input_id  = None
        _render_via_drive._last_output_id = None
        return None

    _render_via_drive._last_input_id  = drive_input_id
    _render_via_drive._last_output_id = None  # will be set once output is found

    print(f"[Edit/Drive] Uploaded. Drive input_id={drive_input_id}. Polling for output...")

    # ── Poll for output ───────────────────────────────────────────────────────
    poll_interval = Config.DRIVE_POLL_INTERVAL_SEC
    poll_timeout  = Config.DRIVE_POLL_TIMEOUT_SEC
    elapsed       = 0
    last_dot      = time.time()

    while elapsed < poll_timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        minutes = elapsed // 60
        seconds = elapsed % 60

        # Update status every full minute, or every 3 dots in between
        now = time.time()
        if now - last_edit_time[0] >= 30:
            last_edit_time[0] = now
            await _edit(
                f"🤖 <b>COLAB GPU RENDERING...</b>\n\n"
                f"Quality: {profile['label']}\n"
                f"⏱ Elapsed: <code>{int(minutes)}m {int(seconds)}s</code>\n"
                f"⏳ Max wait: <code>{poll_timeout // 60} min</code>\n\n"
                f"<i>GPU is processing your video on Google Colab. Hang tight!</i>"
            )

        # Check if Colab has finished the output file
        try:
            output_file_id = await loop.run_in_executor(
                None, check_output_ready, drive_filename
            )
        except Exception as exc:
            print(f"[Edit/Drive] Poll error (will retry): {exc}")
            continue

        if output_file_id:
            _render_via_drive._last_output_id = output_file_id
            print(f"[Edit/Drive] Output ready! file_id={output_file_id}. Downloading...")
            break

    else:
        # Timeout reached
        print(f"[Edit/Drive] Job {job_id} timed out after {poll_timeout}s.")
        return None

    # ── Download finished file from Drive ─────────────────────────────────────
    await _edit(
        f"📥 <b>DOWNLOADING FROM CLOUD...</b>\n\n"
        f"GPU render complete! Fetching your file..."
    )
    last_edit_time[0] = time.time()

    ok = await loop.run_in_executor(
        None, download_from_output, output_file_id, output_path
    )

    if not ok or not os.path.exists(output_path):
        return None

    return output_path


async def _render_via_local(
    input_path: str,
    quality: str,
    profile: dict,
    user_id: int,
    job_id: str,
    _edit,
    last_edit_time: list,
) -> str | None:
    """
    Local CPU fallback path: runs the original FFmpeg pipeline via core/renderer.py.
    Identical to the pre-Phase3 behavior.
    """
    initial_bar = _bar(0.0, 10)
    await _edit(
        f"⚙️ <b>GAMEOVER ENGINE RUNNING...</b>\n\n"
        f"Quality: {profile['label']}\n"
        f"Progress: {initial_bar} 0%\n"
        f"📦 Size: <code>0.0 MB</code>\n"
        f"⚡ Speed: <code>0.0x</code>\n"
        f"⏱ Elapsed: <code>0s</code>\n"
        f"⏳ ETA: <code>Calculating...</code>"
    )
    last_edit_time[0] = time.time()

    async def progress_cb(info: dict):
        now = time.time()
        if now - last_edit_time[0] < 3.0:
            return
        last_edit_time[0] = now
        pct     = info["pct"]
        speed   = info.get("speed", "1.0x")
        eta     = info["eta"]
        elapsed = info.get("elapsed", "0s")
        size_mb = info.get("size_mb", 0.0)
        await _edit(
            f"⚙️ <b>GAMEOVER ENGINE RUNNING...</b>\n\n"
            f"Quality: {profile['label']}\n"
            f"Progress: {_bar(pct)} {pct:.0f}%\n"
            f"📦 Size: <code>{size_mb:.1f} MB</code>\n"
            f"⚡ Speed: <code>{speed}</code>\n"
            f"⏱ Elapsed: <code>{elapsed}</code>\n"
            f"⏳ ETA: <code>{eta}</code>"
        )

    show_wm = not has_watermark_disabled(user_id)
    return await render_video(
        input_path=input_path,
        quality_key=quality,
        watermark_text=Config.WATERMARK_TEXT,
        progress_callback=progress_cb,
        show_watermark=show_wm,
    )


# ── Retained for legacy compatibility ─────────────────────────────────────────

async def _safe_edit(client: Client, chat_id: int, message_id: int, text: str):
    """Legacy helper — kept for any plugin that still imports this. Do not use in new code."""
    try:
        await client.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=enums.ParseMode.HTML
        )
    except Exception as e:
        print(f"[SafeEdit] Failed to edit {message_id} in {chat_id}: {e}", file=sys.stderr)
