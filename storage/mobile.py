"""
Android storage connector via ADB (Android Debug Bridge).

WHY ADB INSTEAD OF A MOUNTED PATH
──────────────────────────────────
Android phones connected via USB use MTP (Media Transfer Protocol) —
not a real block-level filesystem mount. os.walk() / pathlib.rglob()
cannot reliably read it on any OS. ADB talks to the phone over a stable
protocol that works identically on macOS / Windows / Linux.

DYNAMIC FOLDER SELECTION
─────────────────────────
MobileScanner now accepts a list of remote_dirs so the user can target
specific folders (DCIM/Camera, Pictures/WhatsApp, etc.) instead of
scanning the entire DCIM tree. Paths are supplied via:
    CLI         --mobile-dir /sdcard/DCIM/Camera --mobile-dir /sdcard/Pictures/WhatsApp
    Interactive python main.py scan --interactive   (shows a picker built from adb ls)
    Default     android_remote_dir in .env (fallback when no CLI dirs given)

ONE-TIME SETUP
──────────────
1. Settings → About Phone → tap "Build Number" 7× → Developer Options unlocked
2. Settings → Developer Options → enable "USB Debugging"
3. Install adb:
       macOS    brew install android-platform-tools
       Windows  https://developer.android.com/tools/releases/platform-tools  (add to PATH)
       Linux    sudo apt install android-tools-adb
4. Connect phone → run `adb devices` → phone shows "unauthorized"
5. Tap "Allow USB debugging?" on the phone screen → Always allow → Allow
6. Run `python main.py mobile-status` to verify
"""
import hashlib
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from config import get_config
from storage.base import StorageScanner
from utils.hasher import is_supported_image
from utils.models import PhotoRecord


# ── Low-level adb helpers ───────────────────────────────────────

def adb_available() -> bool:
    return shutil.which("adb") is not None


def run_adb(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    r"""
    Run 'adb <args>' and return a CompletedProcess (never raises).

    IMPORTANT — shell quoting:
    When a command contains shell operators like ( ) | ; >, do NOT split
    them into separate argv tokens. Instead pass the whole command as a
    single string in the args list AFTER 'shell', e.g.:
        run_adb(["shell", "find /sdcard -type f \( -iname '*.jpg' \) -exec dirname {} +"])
    Splitting breaks them: Android sh would receive literal \( as a file.
    """
    try:
        return subprocess.run(
            ["adb", *args], capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(
            args, returncode=127, stdout="", stderr="adb binary not found on PATH"
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            args, returncode=124, stdout="", stderr=f"adb timed out after {timeout}s"
        )


# ── Scanner ──────────────────────────────────────────────────────

class MobileScanner(StorageScanner):
    """
    Scans one or more directories on an Android phone over ADB.

    Args:
        remote_dirs: list of on-device paths to scan, e.g.
                     ["/sdcard/DCIM/Camera", "/sdcard/Pictures/WhatsApp"]
                     Defaults to [config.android_remote_dir] if not provided.
    """

    def __init__(self, remote_dirs: Optional[list[str]] = None):
        cfg = get_config()
        self.remote_dirs: list[str] = remote_dirs or [cfg.android_remote_dir]
        self.device_serial: Optional[str] = cfg.android_device_serial
        self._cache_dir = Path(tempfile.gettempdir()) / "photo_agent_adb_cache"

    @property
    def source_name(self) -> str:
        return "mobile"

    def _device_args(self) -> list[str]:
        return ["-s", self.device_serial] if self.device_serial else []

    # ── Availability / diagnostics ─────────────────────────────

    def is_available(self) -> bool:
        if not adb_available():
            return False
        result = run_adb(["devices"], timeout=10)
        if result.returncode != 0:
            return False
        lines = [l for l in result.stdout.splitlines()[1:] if l.strip()]
        ready = [l.split("\t")[0] for l in lines if l.endswith("\tdevice")]
        unauthorized = [l for l in lines if "unauthorized" in l]
        if unauthorized and not ready:
            logger.warning(
                "Phone detected but unauthorized — check the phone screen for "
                "'Allow USB debugging?' and tap Allow."
            )
            return False
        if not ready:
            return False
        if self.device_serial:
            return self.device_serial in ready
        if len(ready) > 1:
            logger.warning(
                f"Multiple ADB devices connected ({', '.join(ready)}) — "
                "set ANDROID_DEVICE_SERIAL in .env or pass the serial to pick one."
            )
            return False
        return True

    # ── Interactive: list folders on device ────────────────────

    def list_scannable_dirs(self, parent: str = "/sdcard") -> list[str]:
        """
        Return directories on the device that actually contain photos.
        Used by the interactive folder picker in main.py.

        Passes the entire find expression as a SINGLE shell string so that
        shell operators ( ) are interpreted by sh, not passed as literals.
        """
        logger.info(f"Listing photo-containing folders under {parent} on device…")
        # Single shell string — sh parses ( ) and -exec correctly
        cmd = (
            f"find '{parent}' -maxdepth 5 -type f "
            r"\( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' "
            r"-o -iname '*.heic' -o -iname '*.heif' -o -iname '*.webp' \) "
            "-exec dirname '{}' + 2>/dev/null"
        )
        result = run_adb(
            self._device_args() + ["shell", cmd],
            timeout=60,
        )
        seen: set[str] = set()
        dirs: list[str] = []
        for line in result.stdout.splitlines():
            d = line.strip()
            if d and d not in seen:
                seen.add(d)
                dirs.append(d)
        return sorted(dirs)

    # ── Scanning ───────────────────────────────────────────────

    def _list_files_in_dir(self, remote_dir: str) -> list[dict]:
        """
        Single round-trip: find all image files + stat them in one call.
        Passes command as a single shell string so the pipe delimiter in
        the stat format string isn't mistaken for a shell pipe operator.
        """
        cmd = (
            f"find '{remote_dir}' -type f "
            r"\( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' "
            r"-o -iname '*.heic' -o -iname '*.heif' -o -iname '*.webp' \) "
            "-exec stat -c '%n|%s|%Y' '{}' + 2>/dev/null"
        )
        result = run_adb(
            self._device_args() + ["shell", cmd],
            timeout=300,
        )
        entries: list[dict] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = line.rsplit("|", 2)
            if len(parts) != 3:
                continue
            path, size, mtime = parts
            if is_supported_image(path):
                entries.append({
                    "path": path,
                    "size": int(size) if size.isdigit() else 0,
                    "mtime": int(mtime) if mtime.isdigit() else 0,
                })
        return entries

    def scan(self) -> list[PhotoRecord]:
        if not self.is_available():
            logger.warning(
                "No ADB device available. Run `python main.py mobile-status` to diagnose."
            )
            return []

        records: list[PhotoRecord] = []

        for remote_dir in self.remote_dirs:
            logger.info(f"Scanning [mobile] {remote_dir}")
            entries = self._list_files_in_dir(remote_dir)
            logger.info(f"  └─ {remote_dir.split('/')[-1]}: {len(entries)} images")

            for entry in entries:
                created_at = datetime.fromtimestamp(entry["mtime"]) if entry["mtime"] else None
                records.append(PhotoRecord(
                    source="mobile",
                    path_or_url=entry["path"],
                    filename=Path(entry["path"]).name,
                    size_bytes=entry["size"],
                    width=0,
                    height=0,
                    created_at=created_at,
                ))

        logger.info(
            f"[mobile] Total: {len(records)} images "
            f"across {len(self.remote_dirs)} folder(s)"
        )
        return records

    # ── Pull (read) ────────────────────────────────────────────

    def pull_to(self, remote_path: str, local_dest: Path) -> tuple[bool, Optional[str]]:
        local_dest.parent.mkdir(parents=True, exist_ok=True)
        result = run_adb(
            self._device_args() + ["pull", remote_path, str(local_dest)], timeout=120
        )
        if result.returncode == 0 and local_dest.exists():
            return True, None
        return False, result.stderr.strip() or "Unknown adb pull error"

    def pull_for_hash(self, record: PhotoRecord) -> Optional[Path]:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        stem = hashlib.sha1(record.path_or_url.encode()).hexdigest()[:16]
        local_path = self._cache_dir / f"{stem}{Path(record.path_or_url).suffix}"
        if local_path.exists():
            return local_path
        ok, err = self.pull_to(record.path_or_url, local_path)
        if not ok:
            logger.warning(f"Could not pull {record.path_or_url}: {err}")
            return None
        return local_path

    def cleanup_cache(self) -> None:
        if self._cache_dir.exists():
            try:
                shutil.rmtree(self._cache_dir)
                logger.debug(f"Cleared ADB pull cache: {self._cache_dir}")
            except Exception as e:
                logger.warning(f"Could not clear ADB cache: {e}")

    # ── Write (delete) ─────────────────────────────────────────

    def move_to_trash(self, remote_path: str, filename: str) -> tuple[bool, Optional[str]]:
        cfg = get_config()
        trash_dir = cfg.android_trash_dir
        run_adb(self._device_args() + ["shell", "mkdir", "-p", trash_dir], timeout=15)
        dest_name = f"{uuid.uuid4().hex[:8]}_{filename}"
        dest_path = f"{trash_dir}/{dest_name}"
        result = run_adb(
            self._device_args() + ["shell", "mv", remote_path, dest_path], timeout=30
        )
        if result.returncode == 0 and not result.stderr.strip():
            return True, dest_path
        return False, result.stderr.strip() or "Unknown adb mv error"
