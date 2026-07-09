"""
⚡ GAMEOVER EDITS — Flawless FFmpeg Render Engine
This is the heart of the bot. Fixes every problem the old renderer had:

OLD PROBLEMS:                     NEW FIX:
─────────────────────────────────────────────────────────────────────────────
minterpolate (MCI mode)    →   minterpolate mi_mode=blend (10x faster, clean)
preset slow + CRF 8        →   preset fast + smart CRF per quality
No colorspace tags         →   Explicit bt709 colorspace metadata
Missing yuv420p            →   format=yuv420p (fixes color banding on all TVs)
Washed-out colors          →   curves S-curve + eq saturation/gamma boost
Soft/blurry upscale        →   Lanczos scaling + unsharp after scale
No watermark               →   Semi-transparent drawtext bottom-right
"""

import os
import re
import json
import time
import asyncio
import uuid
from typing import Optional, Callable, Awaitable

# ── Output folder ──────────────────────────────────────────────────────────────
RENDER_DIR = os.path.join("downloads", "renders")
os.makedirs(RENDER_DIR, exist_ok=True)

INPUT_DIR = os.path.join("downloads", "input")
os.makedirs(INPUT_DIR, exist_ok=True)


# ── Quality Profiles ───────────────────────────────────────────────────────────

QUALITY_PROFILES: dict[str, dict] = {
    "1080p60": {
        "label":   "🎬 1080p — 60 FPS",
        "width":   1920,
        "height":  1080,
        "fps":     60,
        "crf":     18,
        "preset":  "fast",
        "est_min": "1-2 min",
    },
    "2k60": {
        "label":   "🎥 2K — 60 FPS",
        "width":   2560,
        "height":  1440,
        "fps":     60,
        "crf":     16,
        "preset":  "fast",
        "est_min": "2-4 min",
    },
    "4k120": {
        "label":   "💎 4K — 120 FPS (Beast Mode)",
        "width":   3840,
        "height":  2160,
        "fps":     120,
        "crf":     14,
        "preset":  "fast",
        "est_min": "5-12 min",
    },
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_time_to_secs(time_str: str) -> Optional[float]:
    """Parse 'HH:MM:SS.xx' from FFmpeg stderr into total seconds."""
    m = re.search(r"time=(\d+):(\d+):(\d+)\.(\d+)", time_str)
    if m:
        h, mi, s, cs = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        return h * 3600 + mi * 60 + s + cs / 100.0
    return None


def _format_duration(secs: float) -> str:
    """Format seconds into human-readable 'Xm Ys' string."""
    secs = max(0.0, secs)
    m = int(secs // 60)
    s = int(secs % 60)
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def _make_progress_bar(pct: float, length: int = 10) -> str:
    """Build a visual progress bar like [████████░░] 80%"""
    filled = int(round(pct / 100 * length))
    empty  = length - filled
    return f"[{'█' * filled}{'░' * empty}] {pct:.0f}%"


async def _get_video_duration(input_path: str) -> float:
    """Use ffprobe to get the exact video duration in seconds."""
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
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        data = json.loads(stdout.decode())
        return float(data["format"]["duration"])
    except Exception as e:
        print(f"[Renderer] ffprobe error: {e}")
        return 0.0


# ── Filter Chain Builder ───────────────────────────────────────────────────────

def _build_filter_chain(profile: dict, watermark_text: str) -> str:
    """
    Build the complete FFmpeg video filter chain for a given quality profile.

    Filter Order (order MATTERS in FFmpeg):
    1. scale   — Lanczos upscale to target resolution
    2. minterpolate (blend) — Fast, clean FPS boost (no MCI = no artifacts)
    3. curves  — S-curve contrast: makes darks darker, lights brighter = HDR punch
    4. eq      — Boost saturation + subtle brightness/gamma for vivid colors
    5. unsharp — Crisp pixel edges after upscale (mild strength = no halos)
    6. drawtext — Watermark: semi-transparent, bottom-right
    7. format  — Force yuv420p: CRITICAL — fixes color banding on all devices
    """
    w   = profile["width"]
    h   = profile["height"]
    fps = profile["fps"]

    # Escape watermark text for FFmpeg drawtext filter
    wm = (watermark_text
          .replace("\\", "\\\\")
          .replace("'",  "\\'")
          .replace(":",  "\\:"))

    filters = [
        # 1. High-quality Lanczos upscale to target resolution
        f"scale={w}:{h}:flags=lanczos+accurate_rnd",

        # 2. Frame rate boost — blend mode is 10x faster than MCI, no pixelation
        f"minterpolate=fps={fps}:mi_mode=blend",

        # 3. S-curve contrast: HDR-like punch without blowing highlights
        "curves=preset=medium_contrast",

        # 4. Saturation + brightness boost for vivid, vibrant colors
        "eq=saturation=1.3:brightness=0.025:contrast=1.05:gamma=1.04",

        # 5. Unsharp mask: restores crispness lost during upscale
        #    luma  kernel 3x3, strength 0.5 — sharp but no halos
        #    chroma kernel 3x3, strength 0.2 — subtle chroma sharpening
        "unsharp=lx=3:ly=3:la=0.5:cx=3:cy=3:ca=0.2",

        # 6. Watermark — white, 45% opacity, 20px from bottom-right corner
        f"drawtext=text='{wm}':fontsize=28:fontcolor=white@0.45"
        f":x=w-tw-20:y=h-th-20:shadowx=1:shadowy=1:shadowcolor=black@0.5",

        # 7. CRITICAL: Force yuv420p — prevents color banding on TVs/mobile
        "format=yuv420p",
    ]

    return ",".join(filters)


def _build_ffmpeg_cmd(
    input_path: str,
    output_path: str,
    profile: dict,
    filter_chain: str
) -> list[str]:
    """Assemble the final FFmpeg command list."""
    return [
        "ffmpeg", "-y",
        "-i", input_path,

        # ── Video ──
        "-vf", filter_chain,
        "-c:v",    "libx264",
        "-preset",  profile["preset"],
        "-crf",     str(profile["crf"]),

        # ── Colorspace metadata (fixes display on Apple/Samsung/web players) ──
        "-colorspace",      "bt709",
        "-color_primaries", "bt709",
        "-color_trc",       "bt709",

        # ── Audio: re-encode to AAC 192k for universal compatibility ──
        "-c:a",  "aac",
        "-b:a",  "192k",

        # ── Output container optimizations ──
        "-movflags", "+faststart",  # Fast web playback (moov atom at start)

        output_path,
    ]


# ── Main Renderer ──────────────────────────────────────────────────────────────

async def render_video(
    input_path: str,
    quality_key: str,
    watermark_text: str,
    progress_callback: Optional[Callable[[dict], Awaitable[None]]] = None,
) -> Optional[str]:
    """
    Render a video using the GAMEOVER EDITS FFmpeg engine.

    Args:
        input_path:       Local path to the downloaded input video.
        quality_key:      One of: '1080p60', '2k60', '4k120'.
        watermark_text:   Text for the bottom-right watermark.
        progress_callback: Async function called with a progress dict every ~2 seconds.
                          Dict keys: step, pct, elapsed, eta, bar

    Returns:
        Path to the rendered output file, or None on failure.
    """
    profile = QUALITY_PROFILES.get(quality_key)
    if not profile:
        print(f"[Renderer] ❌ Unknown quality key: {quality_key}")
        return None

    job_id      = uuid.uuid4().hex[:8]
    output_path = os.path.join(RENDER_DIR, f"ge_{job_id}_{quality_key}.mp4")

    filter_chain = _build_filter_chain(profile, watermark_text)
    cmd          = _build_ffmpeg_cmd(input_path, output_path, profile, filter_chain)

    print(f"[Renderer] 🚀 Starting job {job_id} | Quality: {profile['label']}")
    print(f"[Renderer] CMD: {' '.join(cmd)}")

    # Get input duration for accurate progress calculation
    total_duration = await _get_video_duration(input_path)
    print(f"[Renderer] Input duration: {total_duration:.2f}s")

    start_time = time.time()
    last_cb_time = 0.0

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # ── Parse FFmpeg stderr for progress ──────────────────────────────────
        async def _read_stderr():
            nonlocal last_cb_time
            async for raw_line in proc.stderr:
                line = raw_line.decode("utf-8", errors="ignore").strip()

                rendered_secs = _parse_time_to_secs(line)
                if rendered_secs is None:
                    continue

                now     = time.time()
                elapsed = now - start_time

                # Calculate progress percentage
                if total_duration > 0:
                    pct = min(99.0, (rendered_secs / total_duration) * 100)
                else:
                    pct = 0.0

                # Estimate ETA
                if elapsed > 1 and pct > 0:
                    total_est   = elapsed / (pct / 100)
                    eta_secs    = max(0, total_est - elapsed)
                    eta_str     = _format_duration(eta_secs)
                else:
                    eta_str = "calculating..."

                bar = _make_progress_bar(pct)

                # Console log every 5%
                print(f"[Renderer {job_id}] {bar} | elapsed: {_format_duration(elapsed)} | ETA: {eta_str}")

                # Fire callback every 2 seconds (don't spam Telegram API)
                if progress_callback and (now - last_cb_time) >= 2.0:
                    last_cb_time = now
                    await progress_callback({
                        "step":    "⚙️ Rendering...",
                        "pct":     pct,
                        "bar":     bar,
                        "elapsed": _format_duration(elapsed),
                        "eta":     eta_str,
                        "quality": profile["label"],
                    })

        await _read_stderr()
        await proc.wait()

        if proc.returncode != 0:
            print(f"[Renderer] ❌ FFmpeg exited with code {proc.returncode} for job {job_id}")
            return None

        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
            print(f"[Renderer] ❌ Output file missing or too small: {output_path}")
            return None

        elapsed_total = time.time() - start_time
        size_mb       = os.path.getsize(output_path) / (1024 * 1024)
        print(f"[Renderer] ✅ Job {job_id} done in {_format_duration(elapsed_total)} | Size: {size_mb:.1f} MB")

        # Fire final 100% callback
        if progress_callback:
            await progress_callback({
                "step":    "📤 Uploading...",
                "pct":     100.0,
                "bar":     _make_progress_bar(100),
                "elapsed": _format_duration(elapsed_total),
                "eta":     "Done!",
                "quality": profile["label"],
            })

        return output_path

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[Renderer] ❌ Exception in job {job_id}: {e}")
        return None
