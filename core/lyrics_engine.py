"""
🎵 core/lyrics_engine.py
Automated Lyrical Status Generator Engine
Handles:
1. Slowed & Reverb audio rendering.
2. Whisper AI transcription & SRT generation.
3. Dark gradient/vignette canvas video rendering with subtitles & watermark.
"""

import os
import sys
import time
import json
import asyncio
import whisper
from typing import Optional, Callable, Awaitable


def _escape_srt_path(srt_path: str) -> str:
    """
    Safely escape the SRT path for use inside FFmpeg subtitles filter.
    Converts to absolute path and escapes special characters.
    On Linux, colons and backslashes are the main concerns.
    """
    abs_path = os.path.abspath(srt_path)
    # On Linux/Mac, escape colons and backslashes for FFmpeg filter chain
    if sys.platform.startswith("win"):
        # Windows: replace drive-letter colon and use forward slashes
        abs_path = abs_path.replace("\\", "/")
        if len(abs_path) >= 2 and abs_path[1] == ":":
            abs_path = abs_path[0] + "\\:" + abs_path[2:]
    else:
        # Linux/Mac: escape colons
        abs_path = abs_path.replace(":", "\\:")
    return abs_path


def _format_srt_time(seconds: float) -> str:
    """Format seconds into standard SRT timestamp: HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        millis = 999
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


async def get_audio_duration(input_path: str) -> float:
    """Get the duration of the audio using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        input_path
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )
        stdout, _ = await proc.communicate()
        data = json.loads(stdout.decode())
        return float(data["format"]["duration"])
    except Exception as e:
        print(f"[Lyrics Engine] ffprobe error: {e}")
        return 0.0


async def process_lofi_audio(input_path: str, output_path: str) -> bool:
    """Process audio with slowed & reverb filter."""
    # asetrate slows down playback rate (e.g. 0.85x), aresample returns it to normal rate (pitch lowered)
    # aecho adds depth and reverb characteristics
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-filter_complex", "asetrate=44100*0.85,aresample=44100,aecho=0.8:0.9:1000:0.3",
        output_path
    ]
    print(f"[Lyrics Engine] Processing lofi audio: {' '.join(cmd)}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            print(f"[Lyrics Engine] Lofi FFmpeg stderr:\n{stderr.decode(errors='ignore')}")
        return os.path.exists(output_path) and os.path.getsize(output_path) > 1000
    except Exception as e:
        print(f"[Lyrics Engine] Lofi conversion failed: {e}")
        return False


async def extract_audio_from_video(video_path: str, audio_path: str) -> bool:
    """Extract audio stream from a video file using FFmpeg."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-ac", "2", "-ar", "44100", "-b:a", "192k",
        audio_path
    ]
    print(f"[Lyrics Engine] Extracting audio from video: {' '.join(cmd)}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            print(f"[Lyrics Engine] Extract FFmpeg stderr:\n{stderr.decode(errors='ignore')}")
        return os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000
    except Exception as e:
        print(f"[Lyrics Engine] Audio extraction failed: {e}")
        return False


def transcribe_audio_to_srt(audio_path: str, srt_path: str) -> bool:
    """Load Whisper 'base' model and transcribe audio, saving as SRT."""
    print(f"[Lyrics Engine] Transcribing audio with Whisper base model...")
    try:
        # Load the base model (high accuracy, safe for 4-core servers)
        model = whisper.load_model("base")
        result = model.transcribe(audio_path)

        with open(srt_path, "w", encoding="utf-8") as f:
            for idx, seg in enumerate(result.get("segments", []), start=1):
                start_str = _format_srt_time(seg["start"])
                end_str = _format_srt_time(seg["end"])
                text = seg["text"].strip()
                f.write(f"{idx}\n{start_str} --> {end_str}\n{text}\n\n")

        return os.path.exists(srt_path) and os.path.getsize(srt_path) > 0
    except Exception as e:
        print(f"[Lyrics Engine] Whisper transcription failed: {e}")
        return False


async def render_lyrical_video(
    audio_path: str,
    srt_path: str,
    output_path: str,
    duration: float,
    watermark_text: str,
    progress_callback: Optional[Callable[[dict], Awaitable[None]]] = None
) -> bool:
    """
    Render 1080p premium aesthetic video, burning centered subtitles and watermark.

    Command structure (safe & portable):
      ffmpeg -y
        -f lavfi -i "color=c=0x0a192f:s=1920x1080:d={duration},
                     geq=r='...':g='...':b='...'"   (premium dark gradient canvas)
        -i {audio_path}                              (lofi audio track)
        -vf "subtitles=...:Alignment=5, drawtext=..." (centered subtitles + watermark)
        -c:v libx264 -preset medium -crf 18
        -c:a aac -b:a 192k -shortest
        output.mp4

    Background: dark navy → teal gradient via geq (Spotify/CapCut aesthetic).
    Subtitles:  dead-center screen (ASS Alignment=5 = MiddleCenter), Arial 34pt.
    """
    escaped_srt = _escape_srt_path(srt_path)

    # ── Subtitles: dead-center (Alignment=5 = ASS Middle-Center) ─────────────
    # Fontsize 34, thick outline, drop shadow, white text — premium Spotify look
    subtitles_filter = (
        f"subtitles='{escaped_srt}':force_style='"
        f"Fontname=Arial,Fontsize=34,PrimaryColour=&H00FFFFFF,"
        f"OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=2,Alignment=5'"
    )

    # ── Watermark: bottom-right corner ───────────────────────────────────────
    watermark_filter = (
        f"drawtext=text='{watermark_text}':fontsize=40:fontcolor=white@0.65"
        f":x=w-tw-20:y=h-th-20:shadowx=2:shadowy=2:shadowcolor=black@0.9"
    )

    # ── Background canvas: dark blue/teal premium gradient via geq ───────────
    # geq shifts each pixel's RGB based on its X/Y position to produce a
    # subtle horizontal/vertical gradient (dark navy → deep teal undertone).
    # The result looks like a Spotify / CapCut aesthetic background.
    canvas_input = (
        f"color=c=0x0a192f:s=1920x1080:d={duration},"
        f"geq=r='clip(10+X/W*15\,0\,255)':g='clip(25+Y/H*25\,0\,255)':b='clip(47+X/W*20\,0\,255)'"
    )

    # ── Full video filter chain via -vf ──────────────────────────────────────
    # Note: vignette removed — the gradient provides sufficient depth/darkness
    vf_chain = f"{subtitles_filter},{watermark_filter}"

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", canvas_input,   # Input 0: dark canvas
        "-i", audio_path,                     # Input 1: lofi audio
        "-vf", vf_chain,                      # Video filters (subtitle + vignette + watermark)
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path
    ]

    print(f"[Lyrics Engine] Rendering video:\n  {' '.join(cmd)}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Monitor FFmpeg progress from stderr asynchronously
        start_time = time.time()
        stderr_lines = []

        while True:
            line_bytes = await proc.stderr.readline()
            if not line_bytes:
                break
            line = line_bytes.decode(errors="ignore").strip()
            stderr_lines.append(line)

            # Parse FFmpeg progress line
            if "time=" in line:
                try:
                    time_part = line.split("time=")[1].split()[0]
                    h, m, s = time_part.split(":")
                    elapsed_seconds = int(h) * 3600 + int(m) * 60 + float(s)
                    pct = min(100.0, (elapsed_seconds / duration) * 100)

                    if progress_callback:
                        elapsed_str = f"{int(time.time() - start_time)}s"
                        speed = "1.0x"
                        if "speed=" in line:
                            speed = line.split("speed=")[1].split()[0]
                        eta_val = "Calculating..."
                        if elapsed_seconds > 0:
                            total_est = (time.time() - start_time) * (duration / elapsed_seconds)
                            eta_val = f"{int(max(0.0, total_est - (time.time() - start_time)))}s"

                        await progress_callback({
                            "pct": pct,
                            "speed": speed,
                            "eta": eta_val,
                            "elapsed": elapsed_str,
                            "size_mb": os.path.getsize(output_path) / (1024 * 1024) if os.path.exists(output_path) else 0.0
                        })
                except Exception:
                    pass

        await proc.wait()

        # Print full stderr if FFmpeg failed
        if proc.returncode != 0:
            print("[Lyrics Engine] ❌ FFmpeg render FAILED. Full stderr:")
            print("\n".join(stderr_lines[-60:]))  # Last 60 lines
            return False

        return os.path.exists(output_path) and os.path.getsize(output_path) > 1000

    except Exception as e:
        print(f"[Lyrics Engine] Video rendering exception: {e}")
        return False
