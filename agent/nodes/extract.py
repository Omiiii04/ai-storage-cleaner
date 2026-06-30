from loguru import logger
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from agent.state import AgentState
from db.store import PhotoStore
from utils.hasher import get_phash, is_supported_image


def extract_metadata_node(state: AgentState) -> AgentState:
    """
    Node 2 — compute pHash for local photos, then upsert everything into SQLite.
    Google Photos records already have phash from scan (thumbnail download).
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

        # Compute phash for local files with a progress bar
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

    return state
