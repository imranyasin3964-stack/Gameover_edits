"""
⚡ colab_worker.py
GAMEOVER EDITS — High-Performance Google Colab GPU Worker (Phase 2)

Description:
  This script runs in a Google Colab GPU environment (Tesla T4, L4, A100).
  It mounts your Google Drive, listens for new incoming videos in INPUT_VIDEOS/,
  enhances them using Colab's hardware-accelerated NVIDIA GPU (NVENC), and
  saves the output in OUTPUT_VIDEOS/ before deleting the input to complete the job.

Usage:
  1. Open a new Google Colab notebook (https://colab.research.google.com).
  2. Change runtime type to GPU: "Runtime" -> "Change runtime type" -> Select "T4 GPU".
  3. Paste this entire script into a cell.
  4. Run the cell and click the Google Drive authentication link to authorize access.
  5. The loop will run indefinitely, processing any videos sent by your Telegram bot.
"""

import os
import re
import sys
import time
import subprocess
import shutil

# ── Configuration ─────────────────────────────────────────────────────────────
# Adjust these folder names if your Google Drive directories are named differently
DRIVE_MOUNT_POINT = "/content/drive"
INPUT_DIR = "/content/drive/MyDrive/INPUT_VIDEOS"
OUTPUT_DIR = "/content/drive/MyDrive/OUTPUT_VIDEOS"

# Local fast working directories inside the Colab virtual machine
LOCAL_IN_DIR = "/content/local_input"
LOCAL_OUT_DIR = "/content/local_output"

# ── Quality Profile Filters (GPU NVENC Optimized) ──────────────────────────────
# We use standard FFmpeg filters but replace libx264 software encoding with
# h264_nvenc (NVIDIA hardware acceleration) for ultra-fast renders.
QUALITY_PROFILES = {
    # ── Tier 1: 1080p 60fps (Fast Mode) ──
    "edit60": {
        "filters": (
            "mpdecimate,yadif=mode=1,"
            "scale=1920:1080:flags=lanczos,"
            "minterpolate=fps=60:mi_mode=mci,"
            "curves=preset=strong_contrast,"
            "eq=contrast=1.12:saturation=1.35:gamma=0.96,"
            "unsharp=lx=3:ly=3:la=0.4:cx=3:cy=3:ca=0.15,"
            "format=yuv420p"
        ),
        "encoder": "-c:v h264_nvenc -preset slow -rc constqp -qp 18"
    },
    # ── Tier 2: 2K 90fps (Pro Mode) ──
    "edit90": {
        "filters": (
            "mpdecimate,yadif=mode=1,"
            "scale=2560:1440:flags=spline,"
            "eq=contrast=1.1:saturation=1.4:gamma=0.95,"
            "unsharp=lx=3:ly=3:la=0.5:cx=3:cy=3:ca=0.1,"
            "minterpolate=fps=90:mi_mode=mci:mc_mode=aobmc:scd=fdiff,"
            "format=yuv420p"
        ),
        "encoder": "-c:v h264_nvenc -preset slow -rc constqp -qp 16"
    },
    # ── Tier 3: 4K 120fps (TRUE Beast Mode) ──
    "edit120": {
        "filters": (
            "mpdecimate,yadif=mode=1,"
            "hqdn3d=3:3:4:4,"
            "scale=3840:2160:flags=spline,"
            "eq=contrast=1.15:saturation=1.60:gamma=0.95:brightness=-0.01,"
            "unsharp=lx=3:ly=3:la=0.7:cx=3:cy=3:ca=0.2,"
            "minterpolate=fps=120:mi_mode=mci:mc_mode=aobmc:vsbmc=1:scd=fdiff,"
            "format=yuv420p"
        ),
        "encoder": "-c:v h264_nvenc -preset slow -rc constqp -qp 14"
    }
}

def check_gpu():
    """Verify that the NVIDIA GPU is accessible in Colab."""
    print("=" * 65)
    print("🤖 Checking GPU Status...")
    try:
        res = subprocess.run(["nvidia-smi"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0:
            print("✅ NVIDIA GPU is ONLINE. Render speeds will be hardware-accelerated.")
            # Print GPU Name
            for line in res.stdout.split("\n"):
                if "Tesla" in line or "NVIDIA" in line or "L4" in line or "A100" in line:
                    print(f"   GPU Type: {line.strip()}")
        else:
            print("⚠️ WARNING: nvidia-smi failed. FFmpeg might fall back to CPU (slower).")
    except FileNotFoundError:
        print("❌ ERROR: No NVIDIA GPU detected. Go to Runtime -> Change runtime type -> Choose T4 GPU.")
    print("=" * 65)

def setup_environment():
    """Mount Google Drive and create local temp folders."""
    print("\n📦 Setting up environment...")
    
    # 1. Mount Google Drive
    if not os.path.exists("/content/drive/MyDrive"):
        from google.colab import drive
        print("🔗 Mounting Google Drive. Please authorize in the popup window...")
        drive.mount(DRIVE_MOUNT_POINT)
    else:
        print("✅ Google Drive already mounted.")

    # 2. Create Drive Directories if they don't exist
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"📂 INPUT folder:  {INPUT_DIR}")
    print(f"📂 OUTPUT folder: {OUTPUT_DIR}")

    # 3. Create Local Scratch Directories inside Colab VM
    os.makedirs(LOCAL_IN_DIR, exist_ok=True)
    os.makedirs(LOCAL_OUT_DIR, exist_ok=True)
    print("✅ Temporary directories initialized.\n")

def process_video(filename: str):
    """
    Process a single video file using its filename quality prefix.
    Expected filename format: {quality}_{job_id}.mp4
    Example: edit120_8d7a4c1f.mp4
    """
    drive_input_path = os.path.join(INPUT_DIR, filename)
    
    # Parse Quality and Job ID from filename
    match = re.match(r"^(edit60|edit90|edit120)_(.+)\.(mp4|mkv|mov)$", filename, re.IGNORECASE)
    if not match:
        print(f"⚠️ [Skip] Invalid file format '{filename}'. Expected format: 'editXX_jobID.mp4'.")
        # Rename or delete to prevent infinite looping over unprocessable files
        try:
            os.remove(drive_input_path)
            print(f"   Removed invalid file from input folder to clean queue.")
        except Exception as e:
            print(f"   Could not remove invalid file: {e}")
        return

    quality = match.group(1).lower()
    job_id = match.group(2)
    ext = match.group(3)
    
    local_input_path = os.path.join(LOCAL_IN_DIR, f"{job_id}_in.{ext}")
    local_output_path = os.path.join(LOCAL_OUT_DIR, f"{job_id}_out.mp4")
    drive_output_path = os.path.join(OUTPUT_DIR, f"{quality}_{job_id}.mp4")

    print("=" * 65)
    print(f"🚀 [Job {job_id}] Starting Task ({quality.upper()})")
    print(f"   File: {filename}")
    print("=" * 65)

    start_time = time.time()

    # 1. Copy file locally from Drive to Colab VM (much faster for FFmpeg to read)
    print(f"📥 Copying to local workspace...")
    try:
        shutil.copy2(drive_input_path, local_input_path)
        print(f"   Downloaded locally to {local_input_path}")
    except Exception as e:
        print(f"❌ Copy failed: {e}")
        return

    # 2. Build FFmpeg command with NVIDIA NVENC GPU Acceleration
    profile = QUALITY_PROFILES[quality]
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-i", local_input_path,
        "-vf", profile["filters"],
    ]
    # Split the GPU encoder params into list
    ffmpeg_cmd.extend(profile["encoder"].split())
    # Audio params
    ffmpeg_cmd.extend([
        "-c:a", "aac", "-b:a", "192k",
        local_output_path
    ])

    print(f"⚙️ Running FFmpeg GPU Enhancement...")
    print(f"   CMD: {' '.join(ffmpeg_cmd)}")

    try:
        # Run FFmpeg and print status logs
        process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        
        # Monitor progress via stderr output printed to stdout
        for line in process.stdout:
            # Print frame rate & speed logs to show Colab GPU progress
            if "frame=" in line or "time=" in line or "speed=" in line:
                print(f"   ⚡ {line.strip()}", end="\r")
        process.wait()
        print()

        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg failed with exit code {process.returncode}")
        
        print("✅ Enhancement complete!")

        # 3. Copy finished output video back to Google Drive OUTPUT_VIDEOS folder
        print(f"📤 Uploading back to Google Drive...")
        shutil.copy2(local_output_path, drive_output_path)
        print(f"   Successfully uploaded to: {drive_output_path}")

        # 4. Remove original from INPUT_VIDEOS (this marks it done for the VPS bot)
        print("🧹 Cleaning up Drive INPUT file...")
        if os.path.exists(drive_input_path):
            os.remove(drive_input_path)
        print("✅ Drive queue item cleared.")

    except Exception as e:
        print(f"❌ JOB FAILED: {e}")
        # Write a simple text error file to the output folder so the bot knows it failed
        err_file_path = os.path.join(OUTPUT_DIR, f"error_{quality}_{job_id}.txt")
        try:
            with open(err_file_path, "w") as f:
                f.write(f"Enhancement error: {str(e)}")
            # Delete input file to prevent endless crashing loops
            if os.path.exists(drive_input_path):
                os.remove(drive_input_path)
        except Exception as write_err:
            print(f"   Could not write error file or delete input: {write_err}")

    finally:
        # 5. Clean local temporary VM files to save storage space
        for path in [local_input_path, local_output_path]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
        
        elapsed = time.time() - start_time
        print(f"⏱️ Job {job_id} Finished in {elapsed:.1f}s\n")

def main_loop():
    """Main listening loop that polls the Google Drive folder."""
    print("=" * 65)
    print("🛰️ GAMEOVER Colab Worker is listening for new jobs...")
    print("   Press 'Stop' button in Colab to exit.")
    print("=" * 65)

    while True:
        try:
            # List all files in the INPUT folder
            files = [f for f in os.listdir(INPUT_DIR) if os.path.isfile(os.path.join(INPUT_DIR, f))]
            
            # Sort files by oldest modified time to process in order of submission (FIFO)
            if files:
                files.sort(key=lambda x: os.path.getmtime(os.path.join(INPUT_DIR, x)))
                next_file = files[0]
                
                # Check that the file size isn't zero and isn't currently uploading/downloading
                file_path = os.path.join(INPUT_DIR, next_file)
                initial_size = os.path.getsize(file_path)
                time.sleep(1.5)  # Wait briefly to check if file size is still changing (uploading)
                current_size = os.path.getsize(file_path)
                
                if initial_size == current_size and current_size > 0:
                    process_video(next_file)
                else:
                    print(f"⏳ File '{next_file}' is uploading to Drive. Waiting...", end="\r")
            else:
                # No files found, sleep for 2 seconds before checking again
                time.sleep(2.0)
                
        except KeyboardInterrupt:
            print("\n👋 Worker stopped by user.")
            break
        except Exception as e:
            print(f"\n⚠️ Loop warning: {e}")
            time.sleep(5.0)  # Wait before retrying after any unexpected system error

if __name__ == "__main__":
    check_gpu()
    setup_environment()
    main_loop()
