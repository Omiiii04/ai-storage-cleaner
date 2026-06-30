"""
Image metadata extraction: resolution, EXIF date, file size.
"""
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple

from loguru import logger
from PIL import Image

try:
    import piexif
    _PIEXIF = True
except ImportError:
    _PIEXIF = False
    logger.warning("piexif not installed — EXIF dates will not be extracted from local files")


def get_image_dimensions(path: str | Path) -> Tuple[int, int]:
    """Return (width, height). Returns (0, 0) on error."""
    try:
        with Image.open(path) as img:
            return img.size   # PIL returns (width, height)
    except Exception as e:
        logger.warning(f"Cannot read dimensions from {path}: {e}")
        return 0, 0


def get_exif_date(path: str | Path) -> Optional[datetime]:
    """Extract DateTimeOriginal from EXIF. Returns None if unavailable."""
    if not _PIEXIF:
        return None
    try:
        exif = piexif.load(str(path))
        raw = exif.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
        if raw:
            dt_str = raw.decode() if isinstance(raw, bytes) else raw
            return datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None


def get_file_date(path: str | Path) -> Optional[datetime]:
    """Fallback: return file modification time as creation date."""
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime)
    except Exception:
        return None


def get_photo_metadata(path: str | Path) -> dict[str, Any]:
    """
    Return metadata dict for a local image file.
    Keys: width, height, size_bytes, created_at
    """
    p = Path(path)
    width, height = get_image_dimensions(p)
    size_bytes = p.stat().st_size if p.exists() else 0
    created_at = get_exif_date(p) or get_file_date(p)
    return {
        "width": width,
        "height": height,
        "size_bytes": size_bytes,
        "created_at": created_at,
    }
