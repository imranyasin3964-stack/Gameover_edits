"""
⚡ GAMEOVER EDITS — Master FFmpeg Render Engine v2.0
=====================================================
Three truly distinct render tiers, each with its own filter chain:

  /edit60  → 1080p 60fps  | preset=fast     | CRF 18 | ~5 min
             Standard bicubic scale, basic color grade. Fast & free.

  /edit90  → 2K 60fps     | preset=medium   | CRF 16 | ~10 min
             Stronger Lanczos scale, deeper S-curves, medium unsharp.

  /edit120 → 4K 60fps     | preset=veryslow | CRF 14 | ~25-30 min
             hqdn3d denoiser → spline36 upscale → extreme S-curve
             color grading → heavy unsharp. Near-lossless. Max CPU.

Rules:
  - NO minterpolate (causes access violations / crashes).
  - stdout=DEVNULL to prevent asyncio subprocess deadlock.
  - Live output file size + ETA + premium progress bars.
"""

import os
import re
import sys
import json
import time
import asyncio
import uuid
from typing import Optional, Callable, Awaitable

# ── Output folders ─────────────────────────────────────────────────────────────
RENDER_DIR = os.path.join("downloads", "renders")
os.makedirs(RENDER_DIR, exist_ok=True)

INPUT_DIR = os.path.join("downloads", "input")
os.makedirs(INPUT_DIR, exist_ok=True)


# ── Quality Profiles ───────────────────────────────────────────────────────────
# These are the source-of-truth configs.  The filter chain for each profile
# is built separately in _build_filter_chain_* below.

QUALITY_PROFILES: dict[str, dict] = {

    # ── Tier 1: FAST MODE ──────────────────────────────────────────────────────
    "edit60": {
        "label":    "🎬 1080p — 60 FPS (Fast Mode)",
        "width":    1920,
        "height":   1080,
        "fps":      60,
        "crf":      18,
        "preset":   "fast",
        "est_min":  "~5 min",
        "tier":     1,
    },

    # ── Tier 2: BALANCE MODE ───────────────────────────────────────────────────
    "edit90": {
        "label":    "🎥 2K — 60 FPS (Balance Mode)",
        "width":    2560,
        "height":   1440,
        "fps":      60,
        "crf":      16,
        "preset":   "medium",
        "est_min":  "~10 min",
        "tier":     2,
    },

    # ── Tier 3: TRUE BEAST MODE ────────────────────────────────────────────────
    "edit120": {
        "label":    "💎 4K — 60 FPS (TRUE Beast Mode 🔒)",
        "width":    3840,
        "height":   2160,
        "fps":      60,
        "crf":      14,
        "preset":   "veryslow",
        "est_min":  "25-30 min",
        "tier":     3,
    },
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_time_to_secs(time_str: str) -> Optional[float]:
    """Parse 'HH:MM:SS.xx' or 'HH:MM:SS' from FFmpeg stderr into total seconds."""
    m = re.search(r"time=(\d+):(\d+):(\d+)(?:\.(\d+))?", time_str)
    if m:
        h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if m.group(4):
            val_str = m.group(4)
            cs = int(val_str) / (10 ** len(val_str))
        else:
            cs = 0.0
        return h * 3600 + mi * 60 + s + cs
    return None


def _format_duration(secs: float) -> str:
    """Format seconds into human-readable 'Xm Ys' or 'Ys' string."""
    secs = max(0.0, secs)
    m = int(secs // 60)
    s = int(secs % 60)
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def _make_progress_bar(pct: float, length: int = 12) -> str:
    """Build a premium progress bar: ▰▰▰▰▰▰▰▱▱▱ 70%"""
    filled = int(round(pct / 100 * length))
    empty  = length - filled
    return f"{'▰' * filled}{'▱' * empty} {pct:.0f}%"


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
            stderr=asyncio.subprocess.DEVNULL
        )
        stdout, _ = await proc.communicate()
        data = json.loads(stdout.decode())
        return float(data["format"]["duration"])
    except Exception as e:
        print(f"[Renderer] ffprobe error: {e}")
        return 0.0


def _get_font_file() -> str:
    """Return a valid font path depending on the operating system."""
    from config import Config
    if Config.WATERMARK_FONT and os.path.exists(Config.WATERMARK_FONT):
        return Config.WATERMARK_FONT

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


# ── Per-Tier Filter Chain Builders ─────────────────────────────────────────────

def _escape_wm(text: str) -> str:
    """Escape watermark text for FFmpeg drawtext."""
    return (text
            .replace("\\", "\\\\")
            .replace("'",  "\\'")
            .replace(":",  "\\:"))


def _drawtext(wm: str, font_opt: str) -> str:
    return (
        f"drawtext=text='{wm}':fontsize=32:fontcolor=white@0.5{font_opt}"
        f":x=w-tw-24:y=h-th-24:shadowx=2:shadowy=2:shadowcolor=black@0.6"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TIER 1 — 1080p FAST MODE
# Goal: ~5 minutes. Standard bicubic upscale, basic color grade.
# ─────────────────────────────────────────────────────────────────────────────
def _build_chain_tier1(profile: dict, watermark_text: str) -> str:
    """
    Fast chain for 1080p:
      mpdecimate → yadif=1 → zscale bicubic → fps=60
      → curves medium → eq(sat/bright/contrast) → unsharp(light)
      → drawtext → format=yuv420p
    """
    w, h, fps = profile["width"], profile["height"], profile["fps"]
    wm = _escape_wm(watermark_text)
    font_opt = f":fontfile='{_get_font_file()}'" if _get_font_file() else ""

    filters = [
        # Dedup frames before upscale
        "mpdecimate",
        # Clean deinterlace
        "yadif=mode=1",
        # Bicubic scale — fast, sharp, great quality for 1080p
        f"zscale=w={w}:h={h}:filter=bicubic:dither=random",
        # Lock to 60fps
        f"fps={fps}",
        # Standard S-curve: medium contrast punch
        "curves=preset=medium_contrast",
        # Saturation + slight brightness lift
        "eq=saturation=1.25:brightness=0.02:contrast=1.04:gamma=1.03",
        # Light unsharp — restore detail lost in upscale
        "unsharp=lx=3:ly=3:la=0.4:cx=3:cy=3:ca=0.15",
        # Watermark
        _drawtext(wm, font_opt),
        # Output colorspace
        "format=yuv420p",
    ]
    return ",".join(filters)


# ─────────────────────────────────────────────────────────────────────────────
# TIER 2 — 2K BALANCE MODE
# Goal: ~10 minutes. Lanczos scale, deeper curves, medium unsharp.
# ─────────────────────────────────────────────────────────────────────────────
def _build_chain_tier2(profile: dict, watermark_text: str) -> str:
    """
    Balance chain for 2K:
      mpdecimate → yadif=1 → zscale lanczos → fps=60
      → curves(stronger S) → eq(deeper sat) → unsharp(medium)
      → drawtext → format=yuv420p
    """
    w, h, fps = profile["width"], profile["height"], profile["fps"]
    wm = _escape_wm(watermark_text)
    font_opt = f":fontfile='{_get_font_file()}'" if _get_font_file() else ""

    filters = [
        "mpdecimate",
        "yadif=mode=1",
        # Lanczos — higher quality, slower than bicubic
        f"zscale=w={w}:h={h}:filter=lanczos:dither=random",
        f"fps={fps}",
        # Deeper S-curve for cinematic feel — raises shadows, controls highlights
        "curves=r='0/0 0.05/0.02 0.5/0.55 0.95/0.98 1/1'"
        ":g='0/0 0.05/0.02 0.5/0.53 0.95/0.97 1/1'"
        ":b='0/0 0.05/0.03 0.5/0.51 0.95/0.96 1/1'",
        # Stronger saturation — makes colours pop on OLED / high-contrast screens
        "eq=saturation=1.35:brightness=0.025:contrast=1.06:gamma=1.04",
        # Medium unsharp — sharpens edges and fine textures at 2K resolution
        "unsharp=lx=5:ly=5:la=0.6:cx=5:cy=5:ca=0.25",
        _drawtext(wm, font_opt),
        "format=yuv420p",
    ]
    return ",".join(filters)


# ─────────────────────────────────────────────────────────────────────────────
# TIER 3 — 4K TRUE BEAST MODE
# Goal: 25-30 minutes. Max CPU. Near-lossless. Cinematic.
#
# Chain (order matters):
#   1. mpdecimate          — drop duplicate / near-duplicate frames
#   2. yadif=mode=1        — clean deinterlace (bob, preserves motion)
#   3. hqdn3d              — high-quality 3D denoise BEFORE upscale
#                            (removes source noise so spline36 upscales
#                             clean pixels, not noise)
#   4. zscale spline36     — the BEST scaler FFmpeg has; slower than
#                            lanczos but mathematically superior for 4K
#   5. fps=60              — lock output frame rate
#   6. Custom RGB curves   — cinema-grade S-curve:
#                            deep shadows (lifted black floor),
#                            rich mids, rolled-off highlights
#   7. eq                  — saturation / contrast / gamma fine-tune
#   8. unsharp (heavy)     — extreme edge + chroma sharpening for
#                            razor-sharp 4K pixel detail
#   9. drawtext watermark
#  10. format=yuv420p
# ─────────────────────────────────────────────────────────────────────────────
def _build_chain_tier3(profile: dict, watermark_text: str) -> str:
    """
    True Beast Mode chain for 4K / veryslow / CRF 14.
    Every filter is tuned to squeeze the maximum cinematic quality
    out of a raw mobile / camera video clip.
    """
    w, h, fps = profile["width"], profile["height"], profile["fps"]
    wm = _escape_wm(watermark_text)
    font_opt = f":fontfile='{_get_font_file()}'" if _get_font_file() else ""

    # ── hqdn3d parameters ─────────────────────────────────────────────────────
    # luma_spatial=4, luma_tmp=3, chroma_spatial=3, chroma_tmp=2.5
    # Aggressive enough to kill sensor noise without smearing real edges.
    hqdn3d = "hqdn3d=luma_spatial=4:luma_tmp=3:chroma_spatial=3:chroma_tmp=2.5"

    # ── spline36 upscale ─────────────────────────────────────────────────────
    # spline36 is the gold standard for quality upscaling: no ringing,
    # no aliasing, maximum sharpness retention.
    zscale = (
        f"zscale=w={w}:h={h}"
        ":filter=spline36"
        ":dither=random"
        ":primaries=709"
        ":transfer=709"
        ":matrix=709"
    )

    # ── Cinema S-curve (per-channel RGB) ─────────────────────────────────────
    # Lifted black floor (0.02 at input-0 and 0.04 at input-0.05) gives the
    # classic cinematic "fade to grey" shadow look used in Hollywood grades.
    # Rolled highlights (0.97 at input-0.95) prevent blown-out whites.
    # Green channel is slightly more aggressive mid-boost for warmth.
    curves = (
        "curves="
        "r='0/0.02 0.05/0.06 0.30/0.32 0.50/0.56 0.75/0.78 0.95/0.96 1/0.98'"
        ":g='0/0.02 0.05/0.07 0.30/0.33 0.50/0.58 0.75/0.79 0.95/0.97 1/0.99'"
        ":b='0/0.02 0.05/0.05 0.30/0.30 0.50/0.52 0.75/0.76 0.95/0.95 1/0.97'"
    )

    # ── eq fine-tune ─────────────────────────────────────────────────────────
    # After curves, we dial in saturation for vivid colours without
    # over-saturation. contrast=1.08 adds the final punch.
    eq = "eq=saturation=1.45:brightness=0.03:contrast=1.08:gamma=1.05"

    # ── Heavy unsharp mask ────────────────────────────────────────────────────
    # At 4K, edges are naturally larger in pixels. A stronger luma kernel
    # (lx=7:ly=7) sharpens full pixel-level detail across hair, text,
    # skin texture.  Chroma sharpening (cx=5:cy=5) ensures colours don't
    # bleed across edges.
    unsharp = "unsharp=lx=7:ly=7:la=0.8:cx=5:cy=5:ca=0.35"

    filters = [
        "mpdecimate",
        "yadif=mode=1",
        hqdn3d,       # Step 3: Denoise BEFORE upscale (critical order)
        zscale,       # Step 4: spline36 upscale to 4K
        f"fps={fps}", # Step 5: Lock to 60fps
        curves,       # Step 6: Cinema S-curve grade
        eq,           # Step 7: Saturation / contrast fine-tune
        unsharp,      # Step 8: Extreme edge sharpening
        _drawtext(wm, font_opt),
        "format=yuv420p",
    ]
    return ",".join(filters)


# ── Dispatch filter chain by tier ──────────────────────────────────────────────

def _build_filter_chain(profile: dict, watermark_text: str) -> str:
    """Route to the correct tier-specific filter chain builder."""
    tier = profile.get("tier", 1)
    if tier == 1:
        return _build_chain_tier1(profile, watermark_text)
    elif tier == 2:
        return _build_chain_tier2(profile, watermark_text)
    else:
        return _build_chain_tier3(profile, watermark_text)


# ── FFmpeg Command Builder ──────────────────────────────────────────────────────

def _build_ffmpeg_cmd(
    input_path: str,
    output_path: str,
    profile: dict,
    filter_chain: str
) -> list[str]:
    """Assemble the final FFmpeg command list."""
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,

        # ── Video ──────────────────────────────────────────────────────────────
        "-vf", filter_chain,
        "-c:v",   "libx264",
        "-preset", profile["preset"],
        "-crf",    str(profile["crf"]),

        # Force all CPU threads (no limit) — critical for veryslow to be fast
        "-threads", "0",
    ]

    # Tier 3 gets extra x264 tuning params for maximum quality
    if profile.get("tier") == 3:
        cmd += [
            # Tune for film-like content: slower but better motion compensation
            "-tune", "film",
            # Max analysis depth — reference frames, subpixel motion
            "-x264-params",
            (
                "ref=6"
                ":bframes=8"
                ":b-adapt=2"
                ":direct=auto"
                ":me=umh"
                ":subme=10"
                ":merange=24"
                ":trellis=2"
                ":rc-lookahead=60"
                ":deblock=-1,-1"
                ":psy-rd=1.0:0.15"
                ":aq-mode=3"
                ":aq-strength=0.8"
            ),
        ]

    cmd += [
        # ── Colorspace metadata ─────────────────────────────────────────────
        "-colorspace",      "bt709",
        "-color_primaries", "bt709",
        "-color_trc",       "bt709",

        # ── Audio: AAC 192k ─────────────────────────────────────────────────
        "-c:a", "aac",
        "-b:a", "192k",

        # ── Fast web playback ───────────────────────────────────────────────
        "-movflags", "+faststart",

        output_path,
    ]
    return cmd


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
        input_path:        Path to the raw input video.
        quality_key:       One of 'edit60', 'edit90', 'edit120'.
        watermark_text:    Text to burn into the bottom-right corner.
        progress_callback: Async callable that receives a progress dict.

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

    total_duration = await _get_video_duration(input_path)
    print(f"[Renderer] Input duration: {total_duration:.2f}s")

    start_time   = time.time()
    last_cb_time = 0.0

    try:
        # stdout=DEVNULL: prevents OS stdout buffer from filling → deadlock
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

        # ── Parse FFmpeg stderr for real-time progress ─────────────────────────
        async def _read_stderr():
            nonlocal last_cb_time
            async for raw_line in proc.stderr:
                line = raw_line.decode("utf-8", errors="ignore").strip()

                rendered_secs = _parse_time_to_secs(line)
                if rendered_secs is None:
                    continue

                now     = time.time()
                elapsed = now - start_time

                if total_duration > 0:
                    pct = min(99.0, (rendered_secs / total_duration) * 100)
                else:
                    pct = 0.0

                if elapsed > 1 and pct > 0:
                    total_est = elapsed / (pct / 100)
                    eta_secs  = max(0, total_est - elapsed)
                    eta_str   = _format_duration(eta_secs)
                else:
                    eta_str = "calculating..."

                bar = _make_progress_bar(pct)

                # Live output file size
                out_size_mb = 0.0
                if os.path.exists(output_path):
                    out_size_mb = os.path.getsize(output_path) / (1024 * 1024)

                print(
                    f"[Renderer {job_id}] {bar} | "
                    f"size: {out_size_mb:.1f}MB | "
                    f"elapsed: {_format_duration(elapsed)} | "
                    f"ETA: {eta_str}"
                )

                if progress_callback and (now - last_cb_time) >= 3.0:
                    last_cb_time = now
                    await progress_callback({
                        "step":    "⚙️ Rendering...",
                        "pct":     pct,
                        "bar":     bar,
                        "elapsed": _format_duration(elapsed),
                        "eta":     eta_str,
                        "quality": profile["label"],
                        "size_mb": out_size_mb,
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

        if progress_callback:
            await progress_callback({
                "step":    "📤 Uploading...",
                "pct":     100.0,
                "bar":     _make_progress_bar(100),
                "elapsed": _format_duration(elapsed_total),
                "eta":     "Done!",
                "quality": profile["label"],
                "size_mb": size_mb,
            })

        return output_path

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[Renderer] ❌ Exception in job {job_id}: {e}")
        return None
