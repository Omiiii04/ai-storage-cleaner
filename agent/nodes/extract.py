from loguru import logger
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from agent.state import AgentState
from db.store import PhotoStore
from utils.hasher import get_phash, is_supported_image
from utils.metadata import get_image_dimensions


def extract_metadata_node(state: AgentState) -> AgentState:
    """
    Node 2 — compute pHash for local + mobile photos, then upsert everything into SQLite.
    Google Photos records already have phash from scan (thumbnail download).
    Mobile records need an `adb pull` before they can be hashed — ADB has no
    direct streaming-read API, so each file is pulled to a local temp cache first.
    """
    logger.info("━━━ NODE: extract ━━━")
    store = PhotoStore()
    scan_results = state.get("scan_results", {})

    for source, records in scan_results.items():

        if source == "google_photos":
            # pHash already computed during scan via thumbnail
            store.upsert_many(records)
            logger.info(f"[{source}] {len(records)} records indexed (hashes pre-computed)")
            continue

        if source == "mobile":
            _extract_mobile(records, store)
            continue

        # ── pc (and any other local, mount-based source) ──────
        needs_hash = [r for r in records if not r.phash and is_supported_image(r.path_or_url)]
        logger.info(f"[{source}] Computing pHash for {len(needs_hash)} files…")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task(f"Hashing [{source}]…", total=len(needs_hash))
            for record in needs_hash:
                record.phash = get_phash(record.path_or_url)
                progress.advance(task)

        store.upsert_many(records)
        logger.info(f"[{source}] {len(records)} records upserted to index")

    return {**state}


def _extract_mobile(records: list, store: PhotoStore) -> None:
    """Pull each phone photo to a local cache, then hash + measure it there."""
    from storage.mobile import MobileScanner

    scanner = MobileScanner()
    if not scanner.is_available():
        logger.warning("[mobile] Device not available for hashing — skipping (records kept unhashed)")
        store.upsert_many(records)
        return

    needs_hash = [r for r in records if not r.phash]
    logger.info(f"[mobile] Pulling + hashing {len(needs_hash)} files via adb…")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        transient=True,
    ) as progress:
        task = progress.add_task("Hashing [mobile]…", total=len(needs_hash))
        for record in needs_hash:
            local_path = scanner.pull_for_hash(record)
            if local_path:
                record.phash = get_phash(local_path)
                record.width, record.height = get_image_dimensions(local_path)
            progress.advance(task)

    store.upsert_many(records)
    logger.info(f"[mobile] {len(records)} records upserted to index")
