"""
SQLite-backed photo index.
Caches scan results and phash values — so re-runs skip already-indexed files.
"""
import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from utils.models import PhotoRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    path        TEXT NOT NULL,
    filename    TEXT NOT NULL,
    phash       TEXT,
    width       INTEGER DEFAULT 0,
    height      INTEGER DEFAULT 0,
    size_bytes  INTEGER DEFAULT 0,
    created_at  TEXT,
    indexed_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_phash  ON photos(phash);
CREATE INDEX IF NOT EXISTS idx_source ON photos(source);
CREATE INDEX IF NOT EXISTS idx_path   ON photos(path);
"""


def _record_id(record: PhotoRecord) -> str:
    """Stable SHA-1 ID derived from source + path."""
    key = f"{record.source}:{record.path_or_url}"
    return hashlib.sha1(key.encode()).hexdigest()


class PhotoStore:
    """SQLite-backed photo index for fast phash lookup and scan caching."""

    def __init__(self, db_path: str | Path = "db/photo_index.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # ── Write ──────────────────────────────────────────────────

    def upsert(self, record: PhotoRecord) -> None:
        """Insert or replace a single PhotoRecord."""
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO photos
                   (id, source, path, filename, phash, width, height,
                    size_bytes, created_at, indexed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    _record_id(record),
                    record.source,
                    record.path_or_url,
                    record.filename,
                    record.phash,
                    record.width,
                    record.height,
                    record.size_bytes,
                    record.created_at.isoformat() if record.created_at else None,
                    datetime.now().isoformat(),
                ),
            )

    def upsert_many(self, records: list[PhotoRecord]) -> None:
        for r in records:
            self.upsert(r)
        logger.debug(f"Upserted {len(records)} records")

    def clear(self) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM photos")
        logger.info("Photo index cleared")

    # ── Read ───────────────────────────────────────────────────

    def get_all(self) -> list[PhotoRecord]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM photos").fetchall()
        return [self._to_record(r) for r in rows]

    def get_by_source(self, source: str) -> list[PhotoRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM photos WHERE source = ?", (source,)
            ).fetchall()
        return [self._to_record(r) for r in rows]

    def get_phash_index(self) -> dict[str, list[PhotoRecord]]:
        """
        Return inverted index: {phash_hex: [PhotoRecord]}.
        Only includes records that have a phash (nulls excluded).
        """
        index: dict[str, list[PhotoRecord]] = {}
        for record in self.get_all():
            if record.phash:
                index.setdefault(record.phash, []).append(record)
        return index

    def count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]

    def stats(self) -> dict:
        """
        Return a summary dict used by the CLI footprint panel.
        Tells the user exactly how much storage the index uses and what is stored.
        """
        with self._conn() as conn:
            by_source: dict[str, dict] = {}
            for row in conn.execute(
                "SELECT source, COUNT(*), COUNT(phash), COALESCE(SUM(size_bytes), 0) "
                "FROM photos GROUP BY source"
            ).fetchall():
                by_source[row[0]] = {
                    "total":      row[1],
                    "hashed":     row[2],
                    "size_bytes": row[3],   # sum of original photo sizes (not index size)
                }

            total             = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
            total_hashed      = conn.execute("SELECT COUNT(phash) FROM photos").fetchone()[0]
            total_photo_bytes = conn.execute(
                "SELECT COALESCE(SUM(size_bytes), 0) FROM photos"
            ).fetchone()[0]
            last_indexed      = conn.execute("SELECT MAX(indexed_at) FROM photos").fetchone()[0]

        db_size_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0

        return {
            "by_source":         by_source,
            "total":             total,
            "total_hashed":      total_hashed,
            "total_photo_bytes": total_photo_bytes,   # your actual library size
            "db_size_bytes":     db_size_bytes,        # size of photo_index.db only
            "db_path":           str(self.db_path.resolve()),
            "last_indexed":      last_indexed,
        }

    # ── Internal ───────────────────────────────────────────────

    @staticmethod
    def _to_record(row: sqlite3.Row) -> PhotoRecord:
        created_at: Optional[datetime] = None
        if row["created_at"]:
            try:
                created_at = datetime.fromisoformat(row["created_at"])
            except ValueError:
                pass
        return PhotoRecord(
            source=row["source"],
            path_or_url=row["path"],
            filename=row["filename"],
            size_bytes=row["size_bytes"] or 0,
            width=row["width"] or 0,
            height=row["height"] or 0,
            created_at=created_at,
            phash=row["phash"],
        )
