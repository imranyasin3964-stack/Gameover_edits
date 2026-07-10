"""
🎵 plugins/lyrical.py
Lyrical status command and flow handler
"""

import os
import time
import uuid
import asyncio
import traceback
from pyrogram import Client, filters, enums
from pyrogram.types import Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

from config import Config
from core.db import get_credits, add_credits, is_premium
from core.states import set_state, get_state, clear_state
from core.lyrics_engine import (
    get_audio_duration,
    process_lofi_audio,
    transcribe_audio_to_srt,
    render_lyrical_video,
    extract_audio_from_video
)

INPUT_DIR = os.path.join("downloads", "input")
RENDER_DIR = os.path.join("downloads", "renders")


def _make_progress_bar_chars(pct: float, length: int = 10) -> str:
    filled = int(round(pct / 100 * length))
    empty  = length - filled
    return f"{'▰' * filled}{'▱' * empty}"


def register(app: Client):

    @app.on_message(filters.command(["lyrics", "lyrical"]) & filters.private)
    async def lyrics_cmd_handler(client: Client, message: Message):
        user_id = message.from_user.id
        credits = get_credits(user_id)
        is_vip = is_premium(user_id)

        if not is_vip and credits <= 0:
            await message.reply_text(
                "⚠️ <b>Out of credits!</b>\n\n"
                "Free users need 1 credit to generate a Lyrical Status.\n"
                "To get credits:\n"
                "👉 Invite friends with your referral link to earn credits.\n"
                "👉 Buy a Premium subscription for unlimited edits!",
                parse_mode=enums.ParseMode.HTML
            )
            return

        set_state(user_id, "waiting_lyrical_audio", message.chat.id)
        await message.reply_text(
            "🎵 <b>Automated Lyrical Status Generator</b>\n\n"
            "Please send or forward the <b>Audio file (.mp3, .m4a, .wav)</b>, "
            "<b>Video</b>, or <b>Voice Note</b> you want to use.\n\n"
            "⚡ <i>The bot will:\n"
            "1. Process it into Slowed &amp; Reverb lofi.\n"
            "2. Generate timed lyrics with Whisper AI.\n"
            "3. Render a stunning cinematic status video!</i>\n\n"
            "💰 Cost: <code>1 Credit</code> (Free for Premium)",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)
        )

    # ── Custom filter: only fire when user is in lyrical waiting state ──────────
    def is_waiting_lyrical_audio(_, __, message: Message) -> bool:
        if not message.from_user:
            return False
        state = get_state(message.from_user.id)
        return state and state.get("quality") == "waiting_lyrical_audio"

    @app.on_message(
        filters.private
        & filters.create(is_waiting_lyrical_audio)
    )
    async def lyrical_input_handler(client: Client, message: Message):
        user     = message.from_user
        owner_id = user.id
        chat_id  = message.chat.id

        # ── Cancel ────────────────────────────────────────────────────────────
        if message.text and message.text.strip() == "❌ Cancel":
            clear_state(owner_id)
            await message.reply_text(
                "❌ <b>Operation cancelled.</b>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=ReplyKeyboardRemove()
            )
            return

        # ── Validate media type ───────────────────────────────────────────────
        is_media_ok = False
        is_video    = False

        if message.audio or message.voice or message.video:
            is_media_ok = True
            if message.video:
                is_video = True
        elif message.document and message.document.mime_type:
            mime = message.document.mime_type
            if mime.startswith("audio/"):
                is_media_ok = True
            elif mime.startswith("video/"):
                is_media_ok = True
                is_video = True

        if not is_media_ok:
            await message.reply_text(
                "❌ <b>Please send a valid Audio, Video, or Voice note!</b>",
                parse_mode=enums.ParseMode.HTML
            )
            return

        # ── Credit check ─────────────────────────────────────────────────────
        credits = get_credits(user.id)
        is_vip  = is_premium(user.id)
        if not is_vip and credits <= 0:
            clear_state(owner_id)
            await message.reply_text(
                "⚠️ <b>Out of credits!</b> Operation cancelled.",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=ReplyKeyboardRemove()
            )
            return

        # Deduct credit immediately (refunded on fail)
        has_deducted = False
        if not is_vip:
            add_credits(user.id, -1)
            has_deducted = True

        # Clear state so the user cannot trigger double processes
        clear_state(owner_id)

        # ── Send initial status message ───────────────────────────────────────
        job_id     = uuid.uuid4().hex[:8]
        status_msg = await message.reply_text(
            "⏳ <b>Initializing Lyrical Engine...</b>",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove()
        )
        status_chat_id = status_msg.chat.id
        status_msg_id  = status_msg.id

        # Bound edit helper to bypass peer-lookup issues by using status_msg.edit_text directly
        async def _edit(text: str) -> None:
            try:
                await status_msg.edit_text(text, parse_mode=enums.ParseMode.HTML)
            except Exception as exc:
                import sys
                err = str(exc)
                if "MESSAGE_NOT_MODIFIED" not in err:
                    print(
                        f"[Lyrical Edit] ⚠ edit failed "
                        f"(chat={status_chat_id} msg={status_msg_id}): {exc}",
                        file=sys.stderr
                    )

        raw_video_path  = None
        input_audio_path = None
        lofi_audio_path  = None
        srt_path         = None
        output_video_path = None

        try:
            # ── Step 1: Download Media ────────────────────────────────────────
            ext = ".mp4" if is_video else ".mp3"
            target_media = message.audio or message.voice or message.video or message.document
            if target_media and hasattr(target_media, "file_name") and target_media.file_name:
                _, fext = os.path.splitext(target_media.file_name)
                if fext:
                    ext = fext

            download_target_path = os.path.join(INPUT_DIR, f"ly_dl_{job_id}{ext}")
            input_audio_path     = os.path.join(INPUT_DIR, f"ly_in_{job_id}.mp3")
            lofi_audio_path      = os.path.join(INPUT_DIR, f"ly_lofi_{job_id}.wav")
            srt_path             = os.path.join(INPUT_DIR, f"ly_subs_{job_id}.srt")
            output_video_path    = os.path.join(RENDER_DIR, f"ly_out_{job_id}.mp4")

            last_edit_time = [time.time()]

            async def dl_progress(current, total):
                now = time.time()
                if now - last_edit_time[0] < 3.0:
                    return
                last_edit_time[0] = now
                cur_mb = current / (1024 * 1024)
                tot_mb = total / (1024 * 1024)
                pct    = (current / total) * 100 if total > 0 else 0
                bar    = _make_progress_bar_chars(pct, 10)
                label  = "VIDEO" if is_video else "AUDIO"
                await _edit(
                    f"📥 <b>DOWNLOADING {label} TRACK...</b>\n\n"
                    f"Progress: {bar} {pct:.0f}%\n"
                    f"📦 Size: <code>{cur_mb:.1f} MB / {tot_mb:.1f} MB</code>"
                )

            await client.download_media(message, file_name=download_target_path, progress=dl_progress)

            if not os.path.exists(download_target_path) or os.path.getsize(download_target_path) < 500:
                raise ValueError("Downloaded file is empty or corrupted.")

            # ── Step 2: Extract audio if video was sent ───────────────────────
            if is_video:
                raw_video_path = download_target_path
                await _edit("🔊 <b>EXTRACTING AUDIO STREAM FROM VIDEO...</b>\n\n<i>Please wait...</i>")
                extract_ok = await extract_audio_from_video(raw_video_path, input_audio_path)
                if not extract_ok:
                    raise ValueError("Could not extract audio track from video.")
            else:
                input_audio_path = download_target_path

            duration = await get_audio_duration(input_audio_path)
            if duration <= 0:
                raise ValueError("Could not determine audio duration.")

            # ── Step 3: Lofi Reverb Filtering ─────────────────────────────────
            await _edit(
                "🎸 <b>APPLYING SLOWED &amp; REVERB FILTERS...</b>\n\n"
                "<i>This lowers pitch and adds depth. Please wait...</i>"
            )
            lofi_ok = await process_lofi_audio(input_audio_path, lofi_audio_path)
            if not lofi_ok:
                raise ValueError("Failed to apply lofi filter.")

            # asetrate=44100*0.85 lengthens audio by factor of 1/0.85 ≈ 1.176
            video_duration = duration / 0.85

            # ── Step 4: Whisper AI Transcription ──────────────────────────────
            await _edit(
                "🤖 <b>WHISPER AI GENERATING LYRICS...</b>\n\n"
                "<i>Transcribing timestamps. This takes a few moments...</i>"
            )
            loop = asyncio.get_event_loop()
            trans_ok = await loop.run_in_executor(
                None, transcribe_audio_to_srt, lofi_audio_path, srt_path
            )
            if not trans_ok:
                raise ValueError("Whisper transcription failed.")

            # ── Step 5: Render Subtitled Video ────────────────────────────────
            await _edit(
                f"⚙️ <b>GAMEOVER ENGINE RENDER...</b>\n\n"
                f"Progress: {_make_progress_bar_chars(0, 10)} 0%\n"
                f"⏱ Elapsed: <code>0s</code>\n"
                f"⏳ ETA: <code>Calculating...</code>"
            )

            async def render_progress(info: dict):
                now = time.time()
                if now - last_edit_time[0] < 3.0:
                    return
                last_edit_time[0] = now
                pct  = info["pct"]
                bar  = _make_progress_bar_chars(pct, 10)
                await _edit(
                    f"⚙️ <b>GAMEOVER ENGINE RENDER...</b>\n\n"
                    f"Progress: {bar} {pct:.0f}%\n"
                    f"⏱ Elapsed: <code>{info['elapsed']}</code>\n"
                    f"⏳ ETA: <code>{info['eta']}</code>"
                )

            render_ok = await render_lyrical_video(
                audio_path=lofi_audio_path,
                srt_path=srt_path,
                output_path=output_video_path,
                duration=video_duration,
                watermark_text=Config.WATERMARK_TEXT,
                progress_callback=render_progress
            )
            if not render_ok:
                raise ValueError("FFmpeg rendering failed. Check terminal for detailed FFmpeg error log.")

            # ── Step 6: Upload Lyrical Video ──────────────────────────────────
            async def ul_progress(current, total):
                now = time.time()
                if now - last_edit_time[0] < 3.0:
                    return
                last_edit_time[0] = now
                cur_mb = current / (1024 * 1024)
                tot_mb = total / (1024 * 1024)
                pct    = (current / total) * 100 if total > 0 else 0
                bar    = _make_progress_bar_chars(pct, 10)
                await _edit(
                    f"📤 <b>UPLOADING LYRICAL VIDEO...</b>\n\n"
                    f"Progress: {bar} {pct:.0f}%\n"
                    f"📦 Size: <code>{cur_mb:.1f} MB / {tot_mb:.1f} MB</code>"
                )

            out_size = os.path.getsize(output_video_path) / (1024 * 1024)
            caption  = (
                f"🎬 <b>GAMEOVER LYRICAL STATUS</b>\n\n"
                f"✅ <b>Slowed &amp; Reverb:</b> Yes 🎸\n"
                f"📝 <b>Whisper Timed Subtitles:</b> Yes 🤖\n"
                f"📦 <b>Size:</b> <code>{out_size:.1f} MB</code>\n"
                f"🆔 <b>Job ID:</b> <code>{job_id}</code>\n\n"
                f"<i>Timed lyrics burned into a premium dark aesthetic canvas.</i>"
            )

            await client.send_document(
                chat_id=chat_id,
                document=output_video_path,
                caption=caption,
                parse_mode=enums.ParseMode.HTML,
                force_document=True,
                progress=ul_progress
            )

            # Delete the status message after upload
            try:
                await client.delete_messages(chat_id=status_chat_id, message_ids=status_msg_id)
            except Exception:
                pass

            remaining_credits = get_credits(user.id)
            remaining_str = "💎 Unlimited (Premium)" if is_vip else f"{remaining_credits} credits"

            await client.send_message(
                chat_id=chat_id,
                text=(
                    f"✅ <b>Lyrical Status Render Complete!</b>\n\n"
                    f"Your video has been sent above! ☝️\n"
                    f"💰 <b>Credits:</b> <code>{remaining_str}</code>\n\n"
                    f"Type /lyrics to make another one!"
                ),
                parse_mode=enums.ParseMode.HTML
            )

        except Exception as e:
            traceback.print_exc()
            print(f"[Lyrical Plugin] ❌ Error processing job {job_id}: {e}")

            # Refund credit if deducted
            if has_deducted:
                add_credits(user.id, 1)

            await _edit(
                f"❌ <b>Process Failed!</b>\n\n"
                f"Reason: <code>{str(e)}</code>\n\n"
                f"<i>Your credit has been refunded. Please try with another file.</i>"
            )

        finally:
            # Clean up all temp files
            for p in [raw_video_path, input_audio_path, lofi_audio_path, srt_path, output_video_path]:
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
