"""
Google Photos storage connector via REST API + OAuth 2.0.

One-time setup:
    1. console.cloud.google.com → create project
    2. APIs & Services → Library → search "Photos Library API" → Enable
    3. Credentials → + Create Credentials → OAuth 2.0 Client ID → Desktop App
    4. Download JSON → save as client_secret.json (or set GOOGLE_CREDENTIALS_PATH)
    5. First run opens a browser tab for Google sign-in. Token is cached afterward.
"""
import time
from datetime import datetime
from typing import Optional

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from loguru import logger

from config import get_config
from storage.base import StorageScanner
from utils.hasher import get_phash_from_bytes
from utils.models import PhotoRecord

SCOPES = ["https://www.googleapis.com/auth/photoslibrary.readonly"]
THUMBNAIL_SUFFIX = "=w400-h400"   # enough resolution for accurate pHash, avoids large downloads
PAGE_SIZE = 100
RATE_LIMIT_DELAY = 0.1             # seconds between API page calls


class GooglePhotosScanner(StorageScanner):
    """Lists all photos in Google Photos and computes pHash from thumbnails."""

    def __init__(self):
        self.cfg = get_config()

    @property
    def source_name(self) -> str:
        return "google_photos"

    def is_available(self) -> bool:
        return self.cfg.google_credentials_path.exists()

    # ── Authentication ─────────────────────────────────────────

    def _authenticate(self) -> Credentials:
        """OAuth 2.0 flow — opens browser on first run, uses cached token afterward."""
        token_path = self.cfg.google_token_path
        creds: Optional[Credentials] = None

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing Google Photos token...")
                creds.refresh(Request())
            else:
                logger.info("Opening browser for Google Photos sign-in...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.cfg.google_credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0)

            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json())
            logger.info(f"Token cached at {token_path}")

        return creds

    # ── API calls ──────────────────────────────────────────────

    def _list_media_items(self, creds: Credentials) -> list[dict]:
        """Page through /v1/mediaItems and return all raw API objects."""
        items: list[dict] = []
        url = "https://photoslibrary.googleapis.com/v1/mediaItems"
        params: dict = {"pageSize": PAGE_SIZE}
        retries = 0

        while True:
            headers = {"Authorization": f"Bearer {creds.token}"}
            response = requests.get(url, headers=headers, params=params, timeout=30)

            if response.status_code == 401 and retries < 3:
                logger.warning("Token expired mid-scan — refreshing...")
                creds.refresh(Request())
                retries += 1
                continue

            response.raise_for_status()
            data = response.json()
            items.extend(data.get("mediaItems", []))

            next_page = data.get("nextPageToken")
            if not next_page:
                break

            params["pageToken"] = next_page
            retries = 0
            time.sleep(RATE_LIMIT_DELAY)

        return items

    def _download_thumbnail_hash(self, base_url: str, creds: Credentials) -> Optional[str]:
        """Download a small thumbnail and compute its pHash."""
        try:
            url = base_url + THUMBNAIL_SUFFIX
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {creds.token}"},
                timeout=15,
            )
            resp.raise_for_status()
            return get_phash_from_bytes(resp.content)
        except Exception as e:
            logger.warning(f"Thumbnail fetch failed: {e}")
            return None

    # ── Main scan ──────────────────────────────────────────────

    def scan(self) -> list[PhotoRecord]:
        if not self.is_available():
            logger.error(
                f"client_secret.json not found at {self.cfg.google_credentials_path}\n"
                "Download it from: Google Cloud Console → Credentials → OAuth 2.0 Client"
            )
            return []

        logger.info("Authenticating with Google Photos...")
        creds = self._authenticate()

        logger.info("Fetching Google Photos media items...")
        raw_items = self._list_media_items(creds)
        logger.info(f"Found {len(raw_items)} items — computing hashes (this may take a while)...")

        records: list[PhotoRecord] = []
        for i, item in enumerate(raw_items):
            mime = item.get("mimeType", "")
            if not mime.startswith("image/"):
                continue   # skip videos

            meta = item.get("mediaMetadata", {})

            created_at = None
            if ct := meta.get("creationTime"):
                try:
                    created_at = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                except ValueError:
                    pass

            phash_val = self._download_thumbnail_hash(item["baseUrl"], creds)

            record = PhotoRecord(
                source="google_photos",
                path_or_url=item["baseUrl"],
                filename=item.get("filename", f"photo_{i:06d}"),
                size_bytes=0,                      # API does not expose file size
                width=int(meta.get("width", 0)),   # original resolution from API
                height=int(meta.get("height", 0)),
                created_at=created_at,
                phash=phash_val,
            )
            records.append(record)

            if (i + 1) % 50 == 0:
                logger.info(f"  Hashed {i + 1}/{len(raw_items)} Google Photos...")

        logger.info(f"[google_photos] {len(records)} images indexed")
        return records
