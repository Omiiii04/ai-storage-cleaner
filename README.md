# Photo Management Agent

A LangGraph-based AI agent that deduplicates and organises photos across **Google Photos**, **PC local storage**, and **mobile storage**.

---

## What it does

| Condition | Action |
|-----------|--------|
| Photo exists in only 1 source | **SKIP** — not backed up, never touch |
| Local resolution > Cloud × 1.2 | **MOVE TO HRP** — preserve high-res local copy |
| Hash-confirmed copy on Google Photos | **DELETE** local — move to trash |
| Cloud match is filename-only | **SKIP + WARN** — not safe enough |

All deletions go to `~/.photo_agent_trash/` — never `os.remove()`.  
Default mode is **dry-run**. Pass `--execute` to apply changes.

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/yourusername/photo-agent.git
cd photo-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure `.env`

```bash
cp .env.example .env
# Edit .env — set PC_PHOTOS_DIR and HRP_FOLDER (mobile config is optional, see below)
```

### 3. Set up Google Photos API

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project → **APIs & Services → Library** → search `Photos Library API` → **Enable**
3. **Credentials → + Create Credentials → OAuth 2.0 Client ID → Desktop App**
4. Download JSON → save as `client_secret.json` in the project root
5. First run opens a browser for Google sign-in. Token is cached at `~/.photo_agent_token.json`

### 4. Mobile (optional — Android via ADB)

Android phones connect over USB using **MTP**, which is not a real filesystem mount — `os.walk`/`pathlib` can't read it reliably on any OS (no native support on macOS, no real drive letter on Windows, flaky gvfs mounts on Linux). This project talks to the phone over **ADB (Android Debug Bridge)** instead, which works identically across all three OSes.

1. On the phone: **Settings → About Phone → tap "Build Number" 7×** to unlock Developer Options
2. **Settings → Developer Options → enable "USB Debugging"**
3. Install the `adb` binary:
   - macOS: `brew install android-platform-tools`
   - Windows: [platform-tools](https://developer.android.com/tools/releases/platform-tools) (add to PATH)
   - Linux: `sudo apt install android-tools-adb`
4. Connect via USB-C, then run `adb devices` — the phone will show **unauthorized** the first time
5. A prompt appears **on the phone**: "Allow USB debugging?" → check "Always allow" → tap **Allow**
6. Verify from inside this project:
   ```bash
   python main.py mobile-status
   ```

No `.env` changes needed for default setup — only set `ANDROID_DEVICE_SERIAL` if you have multiple devices connected at once.

---

## Usage

```bash
# Scan all storages (read-only, safe to run anytime)
python main.py scan

# Preview what would be deleted/moved (dry-run — default)
python main.py run --dry-run

# Apply changes (moves to trash, not hard delete)
python main.py run --execute

# Open HTML report in browser
python main.py report

# Check ADB connection to your phone (run this first if mobile scanning fails)
python main.py mobile-status

# Permanently delete trash after reviewing it
python main.py purge-trash

# Permanently delete the on-device mobile trash folder after reviewing it
python main.py purge-mobile-trash

# Options
python main.py run --skip-mobile --dry-run     # exclude mobile
python main.py run --threshold 5 --dry-run     # stricter matching
python main.py run --max-deletes 50 --execute  # cap actions
```

---

## Architecture

```
User → CLI (main.py)
         ↓
    LangGraph Agent
         ↓
    scan → extract → detect → plan → confirm → execute → report
         ↓                              ↓
  StorageManager               Rule Engine (priority)
  ├── LocalScanner              1. SKIP  — 1 source only
  ├── GooglePhotosScanner       2. HRP   — higher local res
  └── MobileScanner             3. DELETE — cloud confirmed
         ↓
  pHash (imagehash)
  SQLite index (db/)
```

---

## Project structure

```
photo-agent/
├── main.py                # CLI entrypoint (Typer)
├── config.py              # pydantic-settings Config
├── agent/
│   ├── graph.py           # LangGraph StateGraph
│   ├── state.py           # AgentState TypedDict
│   └── nodes/             # One file per pipeline node
├── storage/               # Google Photos, PC, Mobile scanners
├── core/                  # Detector, rule engine, executor
├── utils/                 # Hasher, metadata, data models
├── db/                    # SQLite photo index
└── reports/               # Generated HTML reports
```

---

## Safety guarantees

- `--execute` flag is required to make any changes — dry-run is the default
- PC deletions go to `~/.photo_agent_trash/` — review before running `purge-trash`
- Mobile deletions are **off by default** (`ENABLE_MOBILE_DELETE=false`) — when enabled, they're soft-deleted to an on-device trash folder via `adb shell mv`, never hard-deleted
- Cloud confirmation requires **pHash match**, not just filename
- HRP always overrides DELETE — high-res copies are preserved first (mobile HRP photos are *copied* to the PC; the phone original is never touched)
- `--max-deletes` caps destructive actions per run

---

## Tech stack

`Python 3.11` · `LangGraph` · `imagehash` · `ChromaDB` · `SQLite` · `Typer + Rich` · `Pillow` · `Google Photos API`
