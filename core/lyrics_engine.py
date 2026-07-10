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


def _get_font_file() -> str:
    """Return a valid font path depending on the operating system."""
    if sys.platform.startswith("win"):
        font_path = "C:/Windows/Fonts/arial.ttf"
        if os.path.exists(font_path):
            return font_path.replace(":", "\\:")
    else:
        for path in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]:
            if os.path.exists(path):
                return path
    return ""


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
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
        return os.path.exists(output_path) and os.path.getsize(output_path) > 1000
    except Exception as e:
        print(f"[Lyrics Engine] Lofi conversion failed: {e}")
        return False


async def extract_audio_from_video(video_path: str, audio_path: str) -> bool:
    """Extract audio stream from a video file using FFmpeg."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-ac", "2", "-ar", "44100", "-ab", "192k",
        audio_path
    ]
    print(f"[Lyrics Engine] Extracting audio from video: {' '.join(cmd)}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
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
    """Render 1080p aesthetic dark background video, burning subtitles and watermark."""
    escaped_srt = srt_path.replace(":", "\\:").replace("\\", "/")
    font_file = _get_font_file()
    font_opt = f":fontfile='{font_file}'" if font_file else ""
    
    # Subtitles and watermark drawing configurations
    # Using 'DejaVu Sans Bold' (or default Arial fallback), size 30, white color, thick black outline, drop shadow
    subtitles_filter = (
        f"subtitles={escaped_srt}:force_style='Fontname=DejaVu Sans Bold,Fontsize=30,"
        f"PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=1,Alignment=2'"
    )
    
    watermark_filter = (
        f"drawtext=text='{watermark_text}':fontsize=40:fontcolor=white@0.65"
        f":x=w-tw-20:y=h-th-20:shadowx=2:shadowy=2:shadowcolor=black@0.9"
    )

    # 1. Color canvas (dark blue/grey Spotify-like gradient look)
    # 2. Vignette filter for dark cinematic edges
    # 3. Burn subtitles
    # 4. Burn watermark
    filter_chain = f"color=c=0x0a0f18:s=1920x1080:d={duration},vignette=0.5,{subtitles_filter},{watermark_filter}"

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", filter_chain,
        "-i", audio_path,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path
    ]

    print(f"[Lyrics Engine] Rendering video: {' '.join(cmd)}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Monitor FFmpeg progress asynchronously
        start_time = time.time()
        while True:
            # Let's read from stderr where FFmpeg writes progress info
            line_bytes = await proc.stderr.readline()
            if not line_bytes:
                break
            line = line_bytes.decode(errors="ignore").strip()
            
            # Simple progress parser based on time duration elapsed
            if "time=" in line:
                try:
                    # Extract time=00:00:00.00
                    time_part = line.split("time=")[1].split()[0]
                    h, m, s = time_part.split(":")
                    elapsed_seconds = int(h)*3600 + int(m)*60 + float(s)
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
        return os.path.exists(output_path) and os.path.getsize(output_path) > 1000
    except Exception as e:
        print(f"[Lyrics Engine] Video rendering failed: {e}")
        return False
