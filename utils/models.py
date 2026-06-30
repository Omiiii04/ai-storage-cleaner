"""
Core data models shared across all modules.
Build this first — every other module depends on it.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


# ── Photo record ──────────────────────────────────────────────

@dataclass
class PhotoRecord:
    """Represents a single photo from any storage source."""

    source: Literal["pc", "google_photos", "mobile"]
    path_or_url: str          # local path for pc/mobile, API base URL for google_photos
    filename: str
    size_bytes: int = 0
    width: int = 0
    height: int = 0
    created_at: Optional[datetime] = None
    phash: Optional[str] = None  # 64-bit hex string from imagehash.phash()

    @property
    def pixels(self) -> int:
        return self.width * self.height

    @property
    def is_local(self) -> bool:
        return self.source in ("pc", "mobile")

    def __repr__(self) -> str:
        return f"PhotoRecord({self.source}:{self.filename} {self.width}x{self.height})"


# ── Duplicate group ───────────────────────────────────────────

@dataclass
class DuplicateGroup:
    """A group of photos that are perceptual duplicates of each other."""

    group_id: str                                         # representative phash
    all_photos: list[PhotoRecord] = field(default_factory=list)

    # ── Derived properties ────────────────────────────────────

    @property
    def sources(self) -> set[str]:
        return {p.source for p in self.all_photos}

    @property
    def local_photos(self) -> list[PhotoRecord]:
        return [p for p in self.all_photos if p.is_local]

    @property
    def cloud_photo(self) -> Optional[PhotoRecord]:
        cloud = [p for p in self.all_photos if p.source == "google_photos"]
        return cloud[0] if cloud else None

    @property
    def cloud_phash_confirmed(self) -> bool:
        """True if a local photo has a confirmed phash match with the cloud copy."""
        cloud = self.cloud_photo
        if not cloud or not cloud.phash:
            return False
        from utils.hasher import hamming_distance
        from config import get_config
        threshold = get_config().hamming_threshold
        return any(
            p.phash and hamming_distance(p.phash, cloud.phash) <= threshold
            for p in self.local_photos
        )

    def get_by_source(self, source: str) -> Optional[PhotoRecord]:
        matches = [p for p in self.all_photos if p.source == source]
        return matches[0] if matches else None

    def get_best_local(self) -> Optional[PhotoRecord]:
        """Return the highest-resolution local photo."""
        return max(self.local_photos, key=lambda p: p.pixels, default=None)

    @property
    def primary(self) -> PhotoRecord:
        """Best photo in the group: cloud if available, else highest-res local."""
        return self.cloud_photo or self.get_best_local() or self.all_photos[0]


# ── Actions ───────────────────────────────────────────────────

ActionType = Literal["DELETE", "MOVE_TO_HRP", "SKIP"]
OutcomeType = Literal["SUCCESS", "FAILED", "SKIPPED", "DRY_RUN"]


@dataclass
class Action:
    """A planned action for a single photo, produced by the rule engine."""

    type: ActionType
    photo: PhotoRecord
    reason: str
    confidence: float = 1.0   # 0.0–1.0


@dataclass
class ActionResult:
    """Result of executing (or dry-running) a single Action."""

    action: Action
    outcome: OutcomeType
    timestamp: datetime = field(default_factory=datetime.now)
    error_msg: Optional[str] = None
    dest_path: Optional[str] = None   # where the file was moved
