"""
StorageManager — orchestrates all three scanners.

Accepts explicit pc_dirs and mobile_dirs (from CLI or interactive mode)
which override the .env defaults. This is the key to dynamic multi-folder
scanning without touching config files.

Resolution order for directories:
    1. Explicit list passed to __init__  (CLI --pc-dir / --mobile-dir values)
    2. .env default                      (PC_PHOTOS_DIR / ANDROID_REMOTE_DIR)
    3. Error logged + scanner skipped    (neither set)
"""
from pathlib import Path
from typing import Optional

from loguru import logger

from config import get_config
from storage.base import StorageScanner
from storage.google_photos import GooglePhotosScanner
from storage.local import LocalScanner
from storage.mobile import MobileScanner
from utils.models import PhotoRecord


class StorageManager:
    def __init__(
        self,
        skip_google: bool = False,
        skip_mobile: bool = False,
        pc_dirs: Optional[list[Path]] = None,
        mobile_dirs: Optional[list[str]] = None,
    ):
        cfg = get_config()
        self.scanners: list[StorageScanner] = []

        # ── PC ────────────────────────────────────────────────
        resolved_pc = pc_dirs or ([cfg.pc_photos_dir] if cfg.pc_photos_dir else [])
        if not resolved_pc:
            logger.error(
                "No PC folders specified. "
                "Use --pc-dir <path> or set PC_PHOTOS_DIR in .env"
            )
        else:
            self.scanners.append(LocalScanner(root_dirs=resolved_pc, source="pc"))

        # ── Google Photos ─────────────────────────────────────
        if not skip_google:
            self.scanners.append(GooglePhotosScanner())

        # ── Mobile ────────────────────────────────────────────
        if not skip_mobile:
            resolved_mobile = mobile_dirs or [cfg.android_remote_dir]
            self.scanners.append(MobileScanner(remote_dirs=resolved_mobile))

    def scan_all(self) -> dict[str, list[PhotoRecord]]:
        """
        Run all available scanners.
        Returns {source_name: [PhotoRecord]}.
        """
        results: dict[str, list[PhotoRecord]] = {}

        for scanner in self.scanners:
            if not scanner.is_available():
                logger.info(f"Scanner '{scanner.source_name}' unavailable — skipping")
                continue
            try:
                records = scanner.scan()
                results[scanner.source_name] = records
            except Exception as e:
                logger.error(f"Scanner '{scanner.source_name}' failed: {e}")
                results[scanner.source_name] = []

        total = sum(len(v) for v in results.values())
        logger.info(f"All scans complete: {total} photos across {list(results.keys())}")
        return results
