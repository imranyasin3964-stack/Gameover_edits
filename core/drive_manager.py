"""
☁️ core/drive_manager.py
GAMEOVER EDITS — Google Drive Bridge Layer (Phase 1)

Architecture Role:
  This is a PURE UTILITY MODULE. It has zero Telegram / Pyrogram logic.
  All functions are synchronous. Call them from async handlers using:
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, some_drive_function, arg1, arg2)

Authentication:
  Uses a Google Service Account JSON file (credentials.json).
  No browser, no OAuth pop-up — fully headless VPS compatible.

Folder convention:
  INPUT_VIDEOS/   ← VPS uploads raw user videos here (filename = {job_id}.mp4)
  OUTPUT_VIDEOS/  ← Colab GPU worker drops finished videos here (same filename)

Functions:
  authenticate_drive()              → returns Drive API service resource
  upload_to_input(path, filename)   → uploads file, returns Drive file_id (str)
  check_output_ready(filename)      → returns file_id if found, else None
  download_from_output(id, path)    → downloads file to local path
  cleanup_drive(input_id, output_id)→ permanently deletes both Drive files
"""

import os
import sys
import time
import io
import logging

# ── Google API imports ─────────────────────────────────────────────────────────
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
    from googleapiclient.errors import HttpError
except ImportError:
    print(
        "[DriveManager] ❌ Google API libraries not installed!\n"
        "Run: pip install google-api-python-client google-auth",
        file=sys.stderr
    )
    raise

# ── Logger ─────────────────────────────────────────────────────────────────────
logger = logging.getLogger("DriveManager")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("[DriveManager] %(levelname)s — %(message)s"))
    logger.addHandler(_handler)

# ── Required API Scope ─────────────────────────────────────────────────────────
_SCOPES = ["https://www.googleapis.com/auth/drive"]

# ── Module-level service cache (created once, reused) ─────────────────────────
_drive_service = None


# ──────────────────────────────────────────────────────────────────────────────
# 1. AUTHENTICATE
# ──────────────────────────────────────────────────────────────────────────────

def authenticate_drive():
    """
    Initialize (or return cached) Google Drive API service using a Service Account.

    Reads the path to credentials.json from the environment variable
    DRIVE_CREDENTIALS_PATH (default: 'credentials.json').

    Returns:
        googleapiclient.discovery.Resource — authenticated Drive v3 service object

    Raises:
        FileNotFoundError  — if credentials.json doesn't exist at the configured path
        Exception          — if Google auth fails for any other reason
    """
    global _drive_service

    # Return cached service to avoid rebuilding on every call
    if _drive_service is not None:
        return _drive_service

    # Import here to avoid circular import if config is not yet loaded
    from config import Config

    creds_path = Config.DRIVE_CREDENTIALS_PATH

    if not os.path.isfile(creds_path):
        raise FileNotFoundError(
            f"[DriveManager] credentials.json not found at: '{creds_path}'\n"
            f"Please download your Service Account JSON from Google Cloud Console\n"
            f"and place it at the path specified by DRIVE_CREDENTIALS_PATH in .env"
        )

    try:
        credentials = service_account.Credentials.from_service_account_file(
            creds_path, scopes=_SCOPES
        )
        service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        _drive_service = service
        logger.info("✅ Authenticated successfully with Google Drive API.")
        return _drive_service

    except Exception as exc:
        logger.error(f"❌ Authentication failed: {exc}")
        raise


# ──────────────────────────────────────────────────────────────────────────────
# 2. UPLOAD TO INPUT FOLDER
# ──────────────────────────────────────────────────────────────────────────────

def upload_to_input(local_file_path: str, filename: str) -> str:
    """
    Upload a local video file to the Google Drive INPUT_VIDEOS folder.

    Uses resumable chunked upload (safe for large files up to several GB).

    Args:
        local_file_path (str): Absolute or relative path to the local file to upload.
        filename        (str): The exact filename to use on Drive (e.g. '{job_id}.mp4').

    Returns:
        str — the Google Drive file ID of the uploaded file.

    Raises:
        FileNotFoundError — if local_file_path does not exist.
        HttpError         — if the Drive API returns an error.
        Exception         — for any other upload failure.
    """
    from config import Config

    if not os.path.isfile(local_file_path):
        raise FileNotFoundError(
            f"[DriveManager] Local file not found for upload: '{local_file_path}'"
        )

    file_size_mb = os.path.getsize(local_file_path) / (1024 * 1024)
    logger.info(f"📤 Uploading '{filename}' ({file_size_mb:.1f} MB) to INPUT_VIDEOS folder...")

    service = authenticate_drive()
    folder_id = Config.DRIVE_INPUT_FOLDER_ID

    file_metadata = {
        "name": filename,
        "parents": [folder_id],
    }

    # Resumable upload — handles large video files without timeout issues
    media = MediaFileUpload(
        local_file_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10 MB chunks
    )

    try:
        request = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, name, size",
        )

        response = None
        last_log_pct = -1
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                # Log every 10% to avoid flooding terminal
                if pct - last_log_pct >= 10:
                    logger.info(f"   ↑ Upload progress: {pct}%")
                    last_log_pct = pct

        file_id = response.get("id")
        logger.info(f"✅ Upload complete. Drive file_id: {file_id}")
        return file_id

    except HttpError as exc:
        logger.error(f"❌ Drive HTTP error during upload: {exc}")
        raise
    except Exception as exc:
        logger.error(f"❌ Upload failed: {exc}")
        raise


# ──────────────────────────────────────────────────────────────────────────────
# 3. CHECK IF OUTPUT IS READY
# ──────────────────────────────────────────────────────────────────────────────

def check_output_ready(expected_filename: str):
    """
    Check whether the Colab GPU worker has placed a finished file in OUTPUT_VIDEOS.

    Searches the OUTPUT_VIDEOS folder by exact filename match.
    This function is designed to be called repeatedly in a polling loop.

    Args:
        expected_filename (str): The filename to look for (e.g. '{job_id}.mp4').

    Returns:
        str  — Drive file_id of the output file if found.
        None — if the file is not yet present in the folder.

    Raises:
        HttpError — if the Drive API returns an unexpected error.
    """
    from config import Config

    service = authenticate_drive()
    folder_id = Config.DRIVE_OUTPUT_FOLDER_ID

    # Escape single quotes in filename to prevent query injection
    safe_filename = expected_filename.replace("'", "\\'")

    query = (
        f"name = '{safe_filename}' "
        f"and '{folder_id}' in parents "
        f"and trashed = false"
    )

    try:
        result = service.files().list(
            q=query,
            fields="files(id, name, size, modifiedTime)",
            pageSize=1,
        ).execute()

        files = result.get("files", [])
        if files:
            file_id = files[0]["id"]
            size_mb = int(files[0].get("size", 0)) / (1024 * 1024)
            logger.info(
                f"✅ Output ready: '{expected_filename}' "
                f"(file_id={file_id}, size={size_mb:.1f} MB)"
            )
            return file_id

        # Not found yet — caller should retry after polling interval
        return None

    except HttpError as exc:
        logger.error(f"❌ Drive HTTP error checking output: {exc}")
        raise
    except Exception as exc:
        logger.error(f"❌ check_output_ready failed: {exc}")
        raise


# ──────────────────────────────────────────────────────────────────────────────
# 4. DOWNLOAD FROM OUTPUT FOLDER
# ──────────────────────────────────────────────────────────────────────────────

def download_from_output(file_id: str, save_path: str) -> bool:
    """
    Download a finished video file from Google Drive OUTPUT_VIDEOS to the VPS disk.

    Uses chunked streaming download — safe for large files without memory issues.

    Args:
        file_id   (str): The Drive file ID returned by check_output_ready().
        save_path (str): Local filesystem path where the file should be saved.

    Returns:
        True  — on successful download and write.
        False — if download fails for any reason (error is logged).

    Raises:
        Does NOT raise — returns False on failure so the caller can handle gracefully.
    """
    service = authenticate_drive()

    logger.info(f"📥 Downloading file_id='{file_id}' → '{save_path}'...")

    # Ensure parent directory exists
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)

    try:
        request = service.files().get_media(fileId=file_id)

        with io.FileIO(save_path, mode="wb") as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=10 * 1024 * 1024)
            done = False
            last_log_pct = -1
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    if pct - last_log_pct >= 10:
                        logger.info(f"   ↓ Download progress: {pct}%")
                        last_log_pct = pct

        final_size_mb = os.path.getsize(save_path) / (1024 * 1024)
        logger.info(f"✅ Download complete: '{save_path}' ({final_size_mb:.1f} MB)")
        return True

    except HttpError as exc:
        logger.error(f"❌ Drive HTTP error during download: {exc}")
        # Clean up partial file if it exists
        if os.path.exists(save_path):
            try:
                os.remove(save_path)
            except Exception:
                pass
        return False

    except Exception as exc:
        logger.error(f"❌ Download failed: {exc}")
        if os.path.exists(save_path):
            try:
                os.remove(save_path)
            except Exception:
                pass
        return False


# ──────────────────────────────────────────────────────────────────────────────
# 5. CLEANUP — DELETE BOTH DRIVE FILES
# ──────────────────────────────────────────────────────────────────────────────

def cleanup_drive(input_file_id: str = None, output_file_id: str = None) -> None:
    """
    Permanently delete the input and/or output files from Google Drive.

    Called after the finished video has been successfully delivered to the Telegram user.
    Each file_id is deleted independently — if one deletion fails, it logs and continues.

    Args:
        input_file_id  (str | None): Drive file ID of the INPUT_VIDEOS file to delete.
        output_file_id (str | None): Drive file ID of the OUTPUT_VIDEOS file to delete.

    Returns:
        None — errors are logged but never raised, so bot flow is never interrupted.
    """
    service = authenticate_drive()

    def _delete_one(file_id: str, label: str) -> None:
        """Permanently delete a single Drive file by ID. Logs success/failure."""
        if not file_id:
            return
        try:
            service.files().delete(fileId=file_id).execute()
            logger.info(f"🗑 Deleted Drive {label} file: {file_id}")
        except HttpError as exc:
            # 404 means already deleted — log as warning, not error
            if exc.status_code == 404:
                logger.warning(f"⚠ {label} file {file_id} already gone (404). Skipping.")
            else:
                logger.error(f"❌ Failed to delete {label} file {file_id}: {exc}")
        except Exception as exc:
            logger.error(f"❌ Unexpected error deleting {label} file {file_id}: {exc}")

    _delete_one(input_file_id,  "INPUT")
    _delete_one(output_file_id, "OUTPUT")
    logger.info("🧹 Drive cleanup complete.")


# ──────────────────────────────────────────────────────────────────────────────
# QUICK CONNECTIVITY TEST (run directly: python core/drive_manager.py)
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    """
    Self-test: Authenticates and lists the contents of the INPUT_VIDEOS folder.
    Run from the bot root:
        python core/drive_manager.py
    """
    print("=" * 60)
    print("  GAMEOVER EDITS — Drive Manager Self-Test")
    print("=" * 60)

    try:
        svc = authenticate_drive()
        print("✅ Authentication: PASSED")
    except Exception as e:
        print(f"❌ Authentication FAILED: {e}")
        sys.exit(1)

    # Import after auth to ensure dotenv is loaded
    try:
        from config import Config
        print(f"   INPUT  folder ID : {Config.DRIVE_INPUT_FOLDER_ID}")
        print(f"   OUTPUT folder ID : {Config.DRIVE_OUTPUT_FOLDER_ID}")
        print(f"   Poll interval    : {Config.DRIVE_POLL_INTERVAL_SEC}s")
        print(f"   Poll timeout     : {Config.DRIVE_POLL_TIMEOUT_SEC}s")
    except Exception as e:
        print(f"⚠ Config read warning: {e}")

    # List up to 5 files in INPUT folder to confirm folder access
    try:
        from config import Config
        result = svc.files().list(
            q=f"'{Config.DRIVE_INPUT_FOLDER_ID}' in parents and trashed = false",
            fields="files(id, name, size)",
            pageSize=5,
        ).execute()
        files = result.get("files", [])
        if files:
            print(f"\n📁 INPUT_VIDEOS folder contents ({len(files)} file(s)):")
            for f in files:
                sz = int(f.get("size", 0)) / (1024 * 1024)
                print(f"   - {f['name']}  ({sz:.1f} MB)  id={f['id']}")
        else:
            print("\n📁 INPUT_VIDEOS folder: empty (that's fine!)")
        print("\n✅ Folder access: PASSED")
    except Exception as e:
        print(f"❌ Folder access FAILED: {e}")
        sys.exit(1)

    print("\n🎉 ALL TESTS PASSED — Drive Manager is ready!\n")
