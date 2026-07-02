# Photo Management Agent — Full Implementation Prompt

Use this prompt with Claude Code, Cursor, GitHub Copilot, or any AI coding assistant
to implement, extend, or debug this project.

---

## Project overview

Build a Python-based AI agent that deduplicates and organises photos across three storage sources:
- **Google Photos** (cloud, via REST API + OAuth 2.0)
- **PC local storage** (configurable path)
- **Mobile storage** (USB-C mount, optional)

The agent scans all three sources, detects duplicate photos using perceptual hashing,
applies priority-ordered rules to decide what to do with each photo, and executes or previews
the resulting actions. Default mode is always dry-run. Changes are never permanent on first pass.

---

## Tech stack (exact versions)

```
langgraph>=0.2            # agent pipeline (StateGraph)
langchain-core>=0.3
google-api-python-client>=2.100  # Google Photos REST API
google-auth-oauthlib>=1.0        # OAuth 2.0 Desktop flow
imagehash>=4.3            # pHash perceptual hashing
Pillow>=10.0              # image open, resize, EXIF
piexif>=1.1               # EXIF DateTimeOriginal extraction
pillow-heif>=0.13         # HEIC/HEIF support
chromadb>=0.4             # vector store (optional for V2 semantic search)
typer[all]>=0.12          # CLI
rich>=13.0                # terminal UI (tables, progress, prompts)
pydantic-settings>=2.0    # .env config
python-dotenv>=1.0
loguru>=0.7               # logging
jinja2>=3.1               # HTML report template
aiofiles>=23.0            # async I/O
requests>=2.31            # Google Photos API calls
```

Python version: **3.11+**

---

## Directory structure

```
photo-agent/
├── main.py                    # Typer CLI (commands: scan, run, report, purge-trash, clear-cache)
├── config.py                  # pydantic-settings Config class, get_config() singleton
├── requirements.txt
├── .env                       # PC_PHOTOS_DIR, HRP_FOLDER, ANDROID_*, etc.
├── .env.example
├── .gitignore
├── README.md
│
├── agent/
│   ├── __init__.py
│   ├── graph.py               # LangGraph StateGraph (build_graph() → compiled graph)
│   ├── state.py               # AgentState TypedDict
│   └── nodes/
│       ├── __init__.py
│       ├── scan.py            # scan_node — runs StorageManager.scan_all()
│       ├── extract.py         # extract_metadata_node — computes pHash, upserts to SQLite
│       ├── detect.py          # detect_duplicates_node — union-find grouping
│       ├── plan.py            # apply_rules_node — rule engine → action plan
│       ├── confirm.py         # confirm_with_user_node — Rich prompt, dry-run gate
│       ├── execute.py         # execute_actions_node — delegates to core/executor
│       └── report.py          # generate_report_node — HTML + JSON report
│
├── storage/
│   ├── __init__.py
│   ├── base.py                # StorageScanner ABC (scan, is_available, source_name)
│   ├── local.py               # LocalScanner — os.walk, filters by extension
│   ├── google_photos.py       # GooglePhotosScanner — OAuth + paginated /v1/mediaItems
│   ├── mobile.py              # MobileScanner — checks DCIM/ on mount path
│   └── manager.py             # StorageManager — runs all scanners, returns dict
│
├── core/
│   ├── __init__.py
│   ├── duplicate_detector.py  # detect_duplicates() — union-find on pHash
│   ├── rule_engine.py         # apply_rules() — priority-ordered rules → list[Action]
│   └── executor.py            # execute_actions() — dry-run preview + real execution
│
├── utils/
│   ├── __init__.py
│   ├── models.py              # PhotoRecord, DuplicateGroup, Action, ActionResult
│   ├── hasher.py              # get_phash(), get_phash_from_bytes(), hamming_distance()
│   └── metadata.py            # get_image_dimensions(), get_exif_date(), get_photo_metadata()
│
├── db/
│   ├── __init__.py
│   └── store.py               # PhotoStore — SQLite index (upsert, get_all, get_phash_index)
│
└── reports/
    ├── .gitkeep
    └── template.html          # (optional separate Jinja2 template — can be inline in report.py)
```

---

## Data models (utils/models.py)

```python
@dataclass
class PhotoRecord:
    source: Literal["pc", "google_photos", "mobile"]
    path_or_url: str      # local path for pc/mobile, API base URL for google_photos
    filename: str
    size_bytes: int = 0
    width: int = 0        # original resolution (from EXIF or API metadata)
    height: int = 0
    created_at: Optional[datetime] = None
    phash: Optional[str] = None   # 64-bit hex string from imagehash.phash()

@dataclass
class DuplicateGroup:
    group_id: str                  # representative phash of the group
    all_photos: list[PhotoRecord]
    # Properties: sources, local_photos, cloud_photo, cloud_phash_confirmed,
    #             get_by_source(), get_best_local(), primary

@dataclass
class Action:
    type: Literal["DELETE", "MOVE_TO_HRP", "SKIP"]
    photo: PhotoRecord
    reason: str
    confidence: float = 1.0

@dataclass
class ActionResult:
    action: Action
    outcome: Literal["SUCCESS", "FAILED", "SKIPPED", "DRY_RUN"]
    timestamp: datetime
    error_msg: Optional[str] = None
    dest_path: Optional[str] = None
```

---

## LangGraph pipeline (agent/graph.py)

```
scan → extract → detect → plan → confirm ──(user_confirmed=True)──→ execute → report
                                         ──(user_confirmed=False)──→ END
```

Node responsibilities:
- **scan**: StorageManager.scan_all() → scan_results
- **extract**: compute pHash for local files, upsert all to SQLite
- **detect**: detect_duplicates(scan_results, threshold) → duplicate_groups
- **plan**: apply_rules(duplicate_groups) → action_plan
- **confirm**: show Rich table, ask confirmation (always False in dry-run)
- **execute**: execute_actions(action_plan, dry_run, max_deletes) → execution_results
- **report**: render HTML report, append JSON log → report

AgentState TypedDict keys:
  dry_run, skip_mobile, skip_google, hamming_threshold, max_deletes,
  scan_results, duplicate_groups, action_plan, user_confirmed,
  execution_results, report

---

## Config (.env variables)

```
# Required
PC_PHOTOS_DIR=/path/to/your/photos
HRP_FOLDER=/path/to/HRP

# Optional
HAMMING_THRESHOLD=10                   # 0-64, default 10
HRP_RATIO=1.2                          # local/cloud pixel ratio, default 1.2
DRY_RUN=true                           # always default to dry-run
MAX_DELETES=                           # leave empty for no cap
LOG_LEVEL=INFO

# Mobile (Android via ADB — see storage/mobile.py for full setup steps)
ANDROID_REMOTE_DIR=/sdcard/DCIM
ANDROID_DEVICE_SERIAL=                 # only needed with multiple devices connected
ANDROID_TRASH_DIR=/sdcard/.photo_agent_trash
ENABLE_MOBILE_DELETE=false             # off by default — soft-delete via adb shell mv when true

# Google Photos
GOOGLE_CREDENTIALS_PATH=client_secret.json
```

---

## Duplicate detection algorithm (core/duplicate_detector.py)

1. Flatten all PhotoRecords from scan_results into one list
2. Filter to only photos that have a phash (unhashed photos become solo groups)
3. Run union-find clustering:
   - For each pair (i, j): if hamming_distance(phash_i, phash_j) <= threshold → union(i, j)
   - Path compression in find()
4. Collect connected components into DuplicateGroup objects
5. Wrap unhashed photos in solo groups (they'll be SKIP by rule 1)

Hamming distance guide:
  0       = byte-identical
  ≤ 5     = almost certainly the same image
  ≤ 10    = same content, minor edit/crop/compression (recommended threshold)
  > 15    = different photos

---

## Rule engine (core/rule_engine.py)

Priority order — first match wins for each group:

```
Rule 1: len(group.sources) < 2
        → SKIP (not backed up — never touch)

Rule 2: local_pixels / cloud_pixels > HRP_RATIO
        → MOVE_TO_HRP for get_best_local()

Rule 3: "google_photos" in sources AND group.cloud_phash_confirmed
        → DELETE for each photo in group.local_photos
          (if photo.source == "mobile" and NOT ENABLE_MOBILE_DELETE: SKIP instead — gate, not default)

Rule 4: "google_photos" in sources AND NOT cloud_phash_confirmed
        → SKIP + log WARNING (filename match only — not safe)

Default → SKIP (insufficient backup confidence)
```

`cloud_phash_confirmed` = at least one local photo has hamming_distance(local.phash, cloud.phash) <= threshold

---

## Action executor (core/executor.py)

Dry-run:
- Print Rich table of all planned actions
- Return list[ActionResult] with outcome="DRY_RUN"
- Touch zero files

Execute (branches on photo.source):
- DELETE (pc)     → shutil.move(src, ~/.photo_agent_trash/UUID_filename)  ← NEVER os.remove()
- DELETE (mobile) → adb shell mv into ANDROID_TRASH_DIR (gated by ENABLE_MOBILE_DELETE)
- MOVE_TO_HRP (pc)     → shutil.move(src, HRP_FOLDER/filename)
- MOVE_TO_HRP (mobile) → adb pull (copy) into HRP_FOLDER — phone original untouched
- On failure: log error, mark outcome="FAILED", continue queue — never abort
- Append run log to reports/actions.json

---

## Storage connectors

### LocalScanner (storage/local.py)
- os.walk(PC_PHOTOS_DIR) recursively
- Filter by extension: {.jpg, .jpeg, .png, .heic, .heif, .webp, .bmp, .tiff}
- Build PhotoRecord with metadata from Pillow + piexif
- pHash computed in extract node (not scan — scan is always fast)

### GooglePhotosScanner (storage/google_photos.py)
- OAuth 2.0 Desktop flow via google-auth-oauthlib
- Cache token at ~/.photo_agent_token.json
- Paginate GET /v1/mediaItems (pageSize=100)
- Skip mimeType != image/* (videos)
- Width/height from mediaMetadata (original resolution — no download needed)
- pHash from thumbnail: baseUrl + "=w400-h400" (download ~20KB, not original)
- Handle 401 by refreshing token and retrying (max 3 times)

### MobileScanner (storage/mobile.py)
- Android phones use **MTP** over USB, not a real filesystem mount — `os.walk`/`pathlib` cannot
  reliably read it on any OS (no native macOS support, no real Windows drive letter, flaky Linux gvfs)
- Solution: talk to the phone via **ADB (Android Debug Bridge)** instead — works identically cross-platform
- Setup requires: Developer Options + USB Debugging enabled on phone, `adb` binary on PATH, one-time
  "Allow USB debugging?" authorization tapped on the phone screen
- `scan()`: single `adb shell find <dir> -type f -exec stat -c '%n|%s|%Y' {} +` call — lists files
  AND stats them in one round-trip (critical: one `adb shell stat` call per file is far too slow over USB)
- Hashing requires pulling first: ADB has no direct byte-stream read API, so `pull_for_hash()` does
  `adb pull` to a local temp cache, then the normal `get_phash()` runs on the local copy
- Deletion uses `adb shell mv` into an on-device trash folder (`/sdcard/.photo_agent_trash`) — never
  a hard delete — and is gated behind `ENABLE_MOBILE_DELETE` (off by default) in the rule engine
- HRP for mobile = `adb pull` a copy to the local HRP_FOLDER; the phone original is left untouched
- `cleanup_cache()` clears the temp pull cache — call this at the end of every CLI run

---

## SQLite index (db/store.py)

Table: photos
  id          TEXT PK     -- sha1(source:path)
  source      TEXT
  path        TEXT
  filename    TEXT
  phash       TEXT
  width       INTEGER
  height      INTEGER
  size_bytes  INTEGER
  created_at  TEXT
  indexed_at  TEXT

Key methods:
  upsert(record), upsert_many(records)
  get_all() → list[PhotoRecord]
  get_phash_index() → dict[phash_hex, list[PhotoRecord]]
  clear()

---

## CLI commands (main.py)

```bash
python main.py scan                         # scan only (read-only)
python main.py run                          # dry-run (default)
python main.py run --execute                # apply changes
python main.py run --threshold 5            # stricter matching
python main.py run --skip-mobile            # no mobile scan
python main.py run --skip-google            # no Google Photos
python main.py run --max-deletes 50         # cap deletes
python main.py report                       # open latest HTML report
python main.py mobile-status                # diagnose ADB connection to phone
python main.py purge-trash                  # delete PC trash (requires typed confirm)
python main.py purge-mobile-trash           # delete on-device trash (requires typed confirm)
python main.py clear-cache                  # wipe SQLite index
```

---

## Safety requirements (non-negotiable)

1. NEVER call os.remove(), os.unlink(), or shutil.rmtree() directly on user photos
2. DELETE = shutil.move(src, trash_dir / f"{uuid[:8]}_{filename}")
3. trash_dir = ~/.photo_agent_trash/ — reviewed by user before purge-trash
4. Never delete if photo exists in only 1 source
5. Cloud confirmation requires phash match (not filename match)
6. HRP always overrides DELETE — high-res local copies are preserved
7. --execute is a separate flag — default invocation is always safe
8. --max-deletes caps destructive actions per run
9. Every action logged with: timestamp, file, source, action, reason, outcome

---

## Google Photos API notes

- Base URL: https://photoslibrary.googleapis.com/v1/mediaItems
- Auth scope: https://www.googleapis.com/auth/photoslibrary.readonly
- Rate limit: ~10,000 requests/day on free tier
- baseUrl expires after ~60 minutes — do not cache for reuse across runs
- Thumbnail: baseUrl + "=w400-h400" — sufficient for pHash
- Original resolution: from mediaMetadata.width / mediaMetadata.height (no download needed)
- API does NOT expose file size — size_bytes=0 for Google Photos records

---

## HEIC support

Add at the top of utils/hasher.py before any Pillow import:
```python
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass
```

---

## Extension ideas for V2

- Parallel storage scanning with asyncio.gather()
- CLIP embeddings in ChromaDB for semantic near-duplicate detection
- ADB (adb-shell) support for Android as alternative to USB mount
- Scheduled runs via cron or launchd
- Web UI with FastAPI + HTMX for reviewing duplicates before confirming
- Telegram/email notification after each run
- Smart album grouping in Google Photos using the API

---

## Important implementation notes

1. Build order: utils/models.py → utils/hasher.py → utils/metadata.py → storage/ → db/store.py
   → core/ → agent/state.py → agent/nodes/ → agent/graph.py → main.py
2. get_config() returns a singleton — import it wherever needed
3. Google Photos scan computes pHash during scan (thumbnail download)
   Local scan does NOT compute pHash — that happens in extract_node with a progress bar
4. All nodes return {**state, "new_key": new_value} — never mutate state in-place
5. Loguru is configured in main.py _setup_logging() — do not call logger.add() in modules
6. pillow-heif must be registered BEFORE any Image.open() call — do it at module load time
7. The graph is compiled once as a module-level singleton in agent/graph.py

---

## Testing the setup without Google Photos

```bash
# Set PC_PHOTOS_DIR to any folder with images, use --skip-google below
# Then run:
python main.py scan --skip-google
python main.py run --skip-google --dry-run
```

This tests the full pipeline (scan → detect → plan → preview) without needing OAuth.
