"""
Centralised configuration — reads from .env via pydantic-settings.
All modules import get_config() rather than touching .env directly.
"""
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Storage paths ──────────────────────────────────────────
    pc_photos_dir: Path = Field(..., description="Root of PC photos directory")
    hrp_folder: Path = Field(..., description="Destination for high-resolution local copies")
    mobile_mount_path: Optional[Path] = Field(None, description="USB mount path for mobile device")
    trash_dir: Path = Field(
        default_factory=lambda: Path.home() / ".photo_agent_trash",
        description="Trash folder — files moved here instead of permanently deleted",
    )

    # ── Duplicate detection ────────────────────────────────────
    hamming_threshold: int = Field(10, ge=0, le=64)
    hrp_ratio: float = Field(1.2, gt=1.0, description="local_pixels/cloud_pixels ratio to trigger HRP")

    # ── Execution ─────────────────────────────────────────────
    dry_run: bool = Field(True)
    max_deletes: Optional[int] = Field(None, description="Hard cap on delete actions per run")

    # ── Google Photos OAuth ────────────────────────────────────
    google_credentials_path: Path = Field(
        default=Path("client_secret.json"),
        description="OAuth client_secret.json from Google Cloud Console",
    )
    google_token_path: Path = Field(
        default_factory=lambda: Path.home() / ".photo_agent_token.json",
        description="Cached OAuth token path",
    )

    # ── Logging ───────────────────────────────────────────────
    log_dir: Path = Field(default=Path(".logs"))
    log_level: str = Field("INFO")

    # ── Computed paths ────────────────────────────────────────
    @property
    def db_path(self) -> Path:
        return Path("db") / "photo_index.db"

    @property
    def actions_log_path(self) -> Path:
        return Path("reports") / "actions.json"


_config: Optional[Config] = None


def get_config() -> Config:
    """Return singleton Config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config
