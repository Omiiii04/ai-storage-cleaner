"""
Google Photos storage connector via REST API + OAuth 2.0 (Picker API).

One-time setup:
    1. console.cloud.google.com → create project
    2. APIs & Services → Library → search "Photos Picker API" → Enable
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

# Using the new Picker API scope required as of March 2025
SCOPES = ["https://www.googleapis.com/auth/photospicker.mediaitems.readonly"]
THUMBNAIL_SUFFIX = "=w400-h400"   # enough resolution for accurate pHash, avoids large downloads
PAGE_SIZE = 100
RATE_LIMIT_DELAY = 0.1             # seconds between API page calls


class GooglePhotosScanner(StorageScanner):
    """Lists photos selected by the user via the Google Photos Picker API and computes pHash."""

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

    # ── Picker API calls ───────────────────────────────────────
    
    def _create_picker_session(self, creds: Credentials) -> str:
        url = "https://photospicker.googleapis.com/v1/sessions"
        headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}
        
        # We don't need to refresh manually inside here for the single POST unless it fails 401
        response = requests.post(url, headers=headers, json={})
        if response.status_code == 401:
            creds.refresh(Request())
            headers["Authorization"] = f"Bearer {creds.token}"
            response = requests.post(url, headers=headers, json={})
            
        if response.status_code == 403:
            logger.error("403 Forbidden. Ensure the 'Google Photos Picker API' is enabled in your Google Cloud Project.")
            
        response.raise_for_status()
        data = response.json()
        
        session_id = data.get("id")
        picker_uri = data.get("pickerUri")
        
        logger.info(f"\n"
                    f"===============================================================\n"
                    f" ACTION REQUIRED: Select photos to scan\n"
                    f"===============================================================\n"
                    f" Google no longer allows silent background scanning.\n"
                    f" Please open this URL in your browser:\n\n"
                    f" {picker_uri}\n\n"
                    f" Select the photos you want to scan, click 'Done', then return here.\n"
                    f"===============================================================\n")
        
        # Poll until the user completes the selection
        poll_url = f"https://photospicker.googleapis.com/v1/sessions/{session_id}"
        while True:
            poll_resp = requests.get(poll_url, headers=headers)
            poll_resp.raise_for_status()
            poll_data = poll_resp.json()
            
            # The exact response field indicating completion might vary (e.g. mediaItemsSet). 
            # We check if mediaItemsSet is true.
            if poll_data.get("mediaItemsSet"):
                logger.info("Selection complete detected!")
                break
                
            time.sleep(3)
            
        return session_id

    def _list_media_items(self, creds: Credentials, session_id: str) -> list[dict]:
        """Page through /v1/mediaItems?sessionId=... and return all raw API objects."""
        items: list[dict] = []
        url = "https://photospicker.googleapis.com/v1/mediaItems"
        params: dict = {"sessionId": session_id, "pageSize": PAGE_SIZE}
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

        logger.info("Creating a Picker session...")
        session_id = self._create_picker_session(creds)

        logger.info("Fetching selected Google Photos media items...")
        raw_items = self._list_media_items(creds, session_id)
        
        if not raw_items:
            logger.info("No items were selected in the Picker UI.")
            return []
            
        logger.info(f"Found {len(raw_items)} items — computing hashes (this may take a while)...")

        records: list[PhotoRecord] = []
        for i, item in enumerate(raw_items):
            # Picker API items might have a nested mediaFile structure depending on version,
            # but usually it's just flattened or contains a mediaFile object.
            # Let's try to extract standard fields.
            
            # Extract nested mediaFile if present, else use item itself
            media_file = item.get("mediaFile", item)
            
            mime = media_file.get("mimeType", "")
            if not mime.startswith("image/"):
                continue   # skip videos

            meta = media_file.get("mediaMetadata", {})

            created_at = None
            if ct := meta.get("creationTime"):
                try:
                    created_at = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                except ValueError:
                    pass

            base_url = media_file.get("baseUrl")
            if not base_url:
                continue

            phash_val = self._download_thumbnail_hash(base_url, creds)

            record = PhotoRecord(
                source="google_photos",
                path_or_url=base_url,
                filename=media_file.get("filename", f"photo_{i:06d}"),
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

