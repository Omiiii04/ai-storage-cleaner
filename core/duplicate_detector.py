"""
Duplicate detection using perceptual hashing + union-find grouping.
Groups photos that are within Hamming distance of each other.
"""
import uuid
from loguru import logger

from utils.hasher import hamming_distance
from utils.models import DuplicateGroup, PhotoRecord


def _union_find_groups(
    all_photos: list[PhotoRecord],
    threshold: int,
) -> list[DuplicateGroup]:
    """
    Cluster photos using union-find.
    Two photos belong to the same group if Hamming(h1, h2) <= threshold.
    Handles transitive duplicates: if A~B and B~C → group {A, B, C}.
    """
    n = len(all_photos)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]  # path compression
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        parent[find(i)] = find(j)

    # O(n²) pairwise comparison — fine for personal libraries up to ~100k photos
    for i in range(n):
        h1 = all_photos[i].phash
        if not h1:
            continue
        for j in range(i + 1, n):
            h2 = all_photos[j].phash
            if h2 and hamming_distance(h1, h2) <= threshold:
                union(i, j)

    # Collect into groups keyed by root index
    group_map: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        group_map.setdefault(root, []).append(i)

    groups: list[DuplicateGroup] = []
    for indices in group_map.values():
        photos = [all_photos[i] for i in indices]
        rep = photos[0].phash or str(uuid.uuid4())
        groups.append(DuplicateGroup(group_id=rep, all_photos=photos))

    return groups


def detect_duplicates(
    scan_results: dict[str, list[PhotoRecord]],
    threshold: int = 10,
) -> list[DuplicateGroup]:
    """
    Main entry point for duplicate detection.

    Args:
        scan_results: {source_name: [PhotoRecord]} from StorageManager
        threshold:    max Hamming distance to consider two photos duplicates

    Returns:
        list[DuplicateGroup] — every photo belongs to exactly one group,
        even if it has no duplicates (single-member groups for unique photos).
    """
    all_photos: list[PhotoRecord] = [
        p for records in scan_results.values() for p in records
    ]
    hashed = [p for p in all_photos if p.phash]
    unhashed = [p for p in all_photos if not p.phash]

    logger.info(
        f"Duplicate detection: {len(all_photos)} total photos "
        f"({len(hashed)} hashed, {len(unhashed)} skipped — no hash)"
    )

    groups = _union_find_groups(hashed, threshold)

    # Wrap unhashed photos in solo groups so they flow through the pipeline
    for photo in unhashed:
        groups.append(DuplicateGroup(group_id=str(uuid.uuid4()), all_photos=[photo]))

    multi = [g for g in groups if len(g.all_photos) > 1]
    logger.info(
        f"Result: {len(groups)} groups — "
        f"{len(multi)} have duplicates, "
        f"{len(groups) - len(multi)} are unique"
    )
    return groups
