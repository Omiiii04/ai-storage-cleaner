"""
PC local file scanner.
Now accepts a list of root directories so the user can scan
multiple named folders (familyPhotos, groupPhotos, etc.)
without touching .env — paths are passed via CLI or interactive mode.
"""
from pathlib import Path
from typing import Optional

from loguru import logger

from storage.base import StorageScanner
from utils.hasher import is_supported_image
from utils.metadata import get_photo_metadata
from utils.models import PhotoRecord


class LocalScanner(StorageScanner):
    """
    Scans one or more local directories recursively.

    Args:
        root_dirs: list of Path objects to scan (CLI --pc-dir values, or .env default)
        source:    "pc" or "mobile" (used as the PhotoRecord.source tag)
    """

    def __init__(self, root_dirs: list[Path], source: str = "pc"):
        self.root_dirs = [Path(d) for d in root_dirs]
        self._source = source

    @property
    def source_name(self) -> str:
        return self._source

    def is_available(self) -> bool:
        return any(d.exists() and d.is_dir() for d in self.root_dirs)

    def scan(self) -> list[PhotoRecord]:
        if not self.root_dirs:
            logger.error(
                f"[{self._source}] No directories specified. "
                "Pass --pc-dir or set PC_PHOTOS_DIR in .env"
            )
            return []

        records: list[PhotoRecord] = []

        for root in self.root_dirs:
            if not root.exists() or not root.is_dir():
                logger.warning(f"[{self._source}] Skipping — directory not found: {root}")
                continue

            logger.info(f"Scanning [{self._source}] {root}")
            folder_count = 0

            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if not is_supported_image(path):
                    continue
                try:
                    meta = get_photo_metadata(path)
                    records.append(PhotoRecord(
                        source=self._source,        # type: ignore[arg-type]
                        path_or_url=str(path),
                        filename=path.name,
                        size_bytes=meta["size_bytes"],
                        width=meta["width"],
                        height=meta["height"],
                        created_at=meta["created_at"],
                    ))
                    folder_count += 1
                except Exception as e:
                    logger.warning(f"Skipping {path}: {e}")

            logger.info(f"  └─ {root.name}: {folder_count} images")

        logger.info(
            f"[{self._source}] Total: {len(records)} images "
            f"across {len(self.root_dirs)} folder(s)"
        )
        return records
