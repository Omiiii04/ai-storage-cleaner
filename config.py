"""
Centralised configuration — reads from .env via pydantic-settings.
All modules import get_config() rather than touching .env directly.

PC_PHOTOS_DIR is now Optional — if not set in .env, the user must pass
--pc-dir via CLI or use --interactive. This enables multi-folder scanning
without editing .env for every new folder.
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

    # ── Storage paths (all optional — CLI args override these) ─
    pc_photos_dir: Optional[Path] = Field(
        None,
        description="Default PC photos folder — used as fallback if no --pc-dir passed via CLI",
    )
    hrp_folder: Path = Field(..., description="Destination for high-resolution local copies")
    trash_dir: Path = Field(
        default_factory=lambda: Path.home() / ".photo_agent_trash",
        description="Trash folder — files moved here instead of permanently deleted",
    )

    # ── Mobile (Android via ADB) ──────────────────────────────
    android_remote_dir: str = Field(
        "/sdcard/DCIM",
        description="Default remote dir on device — used as fallback if no --mobile-dir passed via CLI",
    )
    android_device_serial: Optional[str] = Field(
        None,
        description="adb device serial — only needed if multiple devices connected (`adb devices -l`)",
    )
    android_trash_dir: str = Field(
        "/sdcard/.photo_agent_trash",
        description="On-device folder for soft-deleted mobile photos",
    )
    enable_mobile_delete: bool = Field(
        False,
        description="Allow DELETE actions to modify files on the phone itself (off by default)",
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
