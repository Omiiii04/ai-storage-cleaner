from pathlib import Path
from typing import Optional

from loguru import logger

from config import get_config
from storage.base import StorageScanner
from utils.hasher import is_supported_image, get_phash
from utils.metadata import get_photo_metadata
from utils.models import PhotoRecord


class LocalScanner(StorageScanner):
    """Scans the configured PC photos directory recursively."""

    def __init__(self, root_dir: Optional[Path] = None, source: str = "pc"):
        cfg = get_config()
        self.root_dir = root_dir or cfg.pc_photos_dir
        self._source = source

    @property
    def source_name(self) -> str:
        return self._source

    def is_available(self) -> bool:
        return self.root_dir.exists() and self.root_dir.is_dir()

    def scan(self) -> list[PhotoRecord]:
        if not self.is_available():
            logger.error(f"Directory not found: {self.root_dir}")
            return []

        records: list[PhotoRecord] = []
        logger.info(f"Scanning [{self._source}] {self.root_dir}")

        for path in self.root_dir.rglob("*"):
            if not path.is_file():
                continue
            if not is_supported_image(path):
                continue

            try:
                meta = get_photo_metadata(path)
                record = PhotoRecord(
                    source=self._source,           # type: ignore[arg-type]
                    path_or_url=str(path),
                    filename=path.name,
                    size_bytes=meta["size_bytes"],
                    width=meta["width"],
                    height=meta["height"],
                    created_at=meta["created_at"],
                    # phash computed later in extract node (batch, with progress)
                )
                records.append(record)
            except Exception as e:
                logger.warning(f"Skipping {path}: {e}")

        logger.info(f"[{self._source}] Found {len(records)} supported images in {self.root_dir}")
        return records
