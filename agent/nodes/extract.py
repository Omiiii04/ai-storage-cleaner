"""
Node 2 — Metadata + pHash extraction.

KEY FIX (re-hashing bug):
    scan_node creates fresh PhotoRecord objects with phash=None every run.
    Without a cache check, every run re-pulls every mobile photo and
    re-hashes every PC file from scratch.

    Fix: before hashing anything, load existing hashes from the SQLite
    index by (source, path). Records whose path is already indexed with
    a hash are populated instantly from cache; only genuinely new or
    changed files are hashed.

    Result: second run and beyond skip adb pulls entirely for unchanged
    mobile photos — the hash is read from photo_index.db in milliseconds.
"""
from loguru import logger
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from agent.state import AgentState
from db.store import PhotoStore
from utils.hasher import get_phash, is_supported_image
from utils.metadata import get_image_dimensions


def extract_metadata_node(state: AgentState) -> AgentState:
    logger.info("━━━ NODE: extract ━━━")
    store = PhotoStore()
    scan_results = state.get("scan_results", {})

    for source, records in scan_results.items():

        if source == "google_photos":
            # pHash already computed during scan via thumbnail download
            store.upsert_many(records)
            logger.info(f"[google_photos] {len(records)} records indexed (hashes pre-computed)")
            continue

        # ── Load SQLite cache for this source ──────────────────
        # Keys: path_or_url → phash (only records that already have a hash)
        cached: dict[str, str] = {
            r.path_or_url: r.phash
            for r in store.get_by_source(source)
            if r.phash
        }

        # Apply cached hashes to scan results — O(n) dict lookup
        cache_hits = 0
        for record in records:
            if record.phash is None and record.path_or_url in cached:
                record.phash = cached[record.path_or_url]
                cache_hits += 1

        # Only records still without a hash need work
        needs_hash = [r for r in records if not r.phash]

        logger.info(
            f"[{source}] {len(records)} records — "
            f"{cache_hits} from SQLite cache, "
            f"{len(needs_hash)} need hashing"
        )

        if source == "mobile":
            _extract_mobile(records, needs_hash, store)
            continue

        # ── PC: hash in-place (file is readable directly) ──────
        if needs_hash:
            supported = [r for r in needs_hash if is_supported_image(r.path_or_url)]
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                transient=True,
            ) as progress:
                task = progress.add_task(f"Hashing [{source}]…", total=len(supported))
                for record in supported:
                    record.phash = get_phash(record.path_or_url)
                    progress.advance(task)

        store.upsert_many(records)
        logger.info(f"[{source}] {len(records)} records upserted to index")

    return {**state}


def _extract_mobile(
    records: list,
    needs_hash: list,
    store: PhotoStore,
) -> None:
    """
    Pull and hash only mobile files NOT already in the SQLite cache.
    On first run: pulls and hashes every file (slow — expected).
    On subsequent runs: needs_hash is empty → no adb pulls, instant.
    """
    if not needs_hash:
        logger.info(
            "[mobile] All records already hashed in SQLite cache — "
            "skipping adb pulls entirely ✓"
        )
        store.upsert_many(records)
        return

    from storage.mobile import MobileScanner
    scanner = MobileScanner()

    if not scanner.is_available():
        logger.warning(
            "[mobile] Device not available for hashing — "
            f"{len(needs_hash)} records kept unhashed"
        )
        store.upsert_many(records)
        return

    logger.info(
        f"[mobile] Pulling + hashing {len(needs_hash)} new files via adb "
        f"({len(records) - len(needs_hash)} served from cache)"
    )

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
    logger.info(
        f"[mobile] {len(records)} records upserted "
        f"({len(needs_hash)} newly hashed)"
    )
