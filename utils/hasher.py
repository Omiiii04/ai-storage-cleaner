"""
Perceptual hashing utilities.
Uses imagehash.phash() — 64-bit hash robust to resize, minor edits, JPEG compression.
"""
import io
from pathlib import Path
from typing import Optional

from loguru import logger

# HEIC support — register before Pillow imports
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    logger.warning("pillow-heif not installed — .heic/.heif files will be skipped")

from imagehash import phash
from PIL import Image

SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".heic", ".heif",
    ".webp", ".bmp", ".tiff", ".tif",
}


def is_supported_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def get_phash(path: str | Path) -> Optional[str]:
    """
    Compute perceptual hash of a local image file.
    Returns 64-bit hex string, or None on error.
    """
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            return str(phash(img))
    except Exception as e:
        logger.warning(f"Cannot hash {path}: {e}")
        return None


def get_phash_from_bytes(data: bytes) -> Optional[str]:
    """
    Compute pHash from raw image bytes.
    Used for Google Photos thumbnails (downloaded to memory, not disk).
    """
    try:
        with Image.open(io.BytesIO(data)) as img:
            img = img.convert("RGB")
            return str(phash(img))
    except Exception as e:
        logger.warning(f"Cannot hash bytes ({len(data)} bytes): {e}")
        return None


def hamming_distance(h1: str, h2: str) -> int:
    """
    Compute Hamming distance between two hex pHash strings.

    Guide:
        0       → byte-identical
        ≤ 5     → almost certainly the same image
        ≤ 10    → same content, possible minor edit/crop/compression
        > 15    → likely different photos
    """
    if not h1 or not h2 or len(h1) != len(h2):
        return 64  # max distance
    try:
        return bin(int(h1, 16) ^ int(h2, 16)).count("1")
    except ValueError:
        return 64


def are_duplicates(h1: Optional[str], h2: Optional[str], threshold: int = 10) -> bool:
    """Return True if two hashes are within the Hamming distance threshold."""
    if not h1 or not h2:
        return False
    return hamming_distance(h1, h2) <= threshold
