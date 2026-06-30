from loguru import logger

from config import get_config
from storage.base import StorageScanner
from storage.local import LocalScanner
from utils.models import PhotoRecord


class MobileScanner(StorageScanner):
    """
    Scans mobile storage mounted via USB-C in File Transfer (MTP) mode.

    Setup:
        Android: Enable Developer Options → USB debugging off, select "File Transfer"
        iPhone: Trust the computer when prompted
        Mount path: set MOBILE_MOUNT_PATH in .env
            macOS → /Volumes/YourPhoneName
            Linux → /media/youruser/YourPhoneName
            Windows → D:\\ (drive letter)
    """

    def __init__(self):
        cfg = get_config()
        self.mount_path = cfg.mobile_mount_path

    @property
    def source_name(self) -> str:
        return "mobile"

    def is_available(self) -> bool:
        if not self.mount_path:
            return False
        dcim = self.mount_path / "DCIM"
        return dcim.exists() and dcim.is_dir()

    def scan(self) -> list[PhotoRecord]:
        if not self.mount_path:
            logger.info("MOBILE_MOUNT_PATH not set — skipping mobile scan")
            return []

        if not self.is_available():
            logger.warning(
                f"Mobile not found at {self.mount_path}/DCIM — "
                "make sure the phone is connected in File Transfer mode"
            )
            return []

        dcim = self.mount_path / "DCIM"
        logger.info(f"Scanning [mobile] {dcim}")

        # Delegate to LocalScanner with the DCIM directory
        _scanner = LocalScanner(root_dir=dcim, source="mobile")
        records = _scanner.scan()

        logger.info(f"[mobile] Found {len(records)} images in {dcim}")
        return records
