from loguru import logger

from storage.base import StorageScanner
from storage.google_photos import GooglePhotosScanner
from storage.local import LocalScanner
from storage.mobile import MobileScanner
from utils.models import PhotoRecord


class StorageManager:
    """Orchestrates all storage scanners and returns consolidated results."""

    def __init__(self, skip_google: bool = False, skip_mobile: bool = False):
        self.scanners: list[StorageScanner] = [LocalScanner()]

        if not skip_google:
            self.scanners.append(GooglePhotosScanner())

        if not skip_mobile:
            self.scanners.append(MobileScanner())

    def scan_all(self) -> dict[str, list[PhotoRecord]]:
        """
        Run all available scanners sequentially.
        Returns {source_name: [PhotoRecord]}.
        Unavailable scanners are skipped (not an error).
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
