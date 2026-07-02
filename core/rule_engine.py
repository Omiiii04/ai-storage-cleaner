"""
Rule engine — converts duplicate groups into a list of Actions.

Priority order (first match wins):
    1. SKIP   — only 1 source (not backed up — never touch)
    2. HRP    — local resolution > cloud × ratio (preserve high-res local)
    3. DELETE — hash-confirmed copy on Google Photos (safe to remove local)
    4. SKIP   — cloud match is filename-only, no phash confirm (not safe enough)
    5. SKIP   — fallback (insufficient backup confidence)
"""
from typing import Optional

from loguru import logger

from config import get_config
from utils.models import Action, DuplicateGroup


def _hrp_check(group: DuplicateGroup, ratio: float) -> Optional[Action]:
    """Return MOVE_TO_HRP Action if local has meaningfully higher resolution than cloud."""
    cloud = group.cloud_photo
    best_local = group.get_best_local()

    if not cloud or not best_local or cloud.pixels == 0:
        return None

    actual_ratio = best_local.pixels / cloud.pixels
    if actual_ratio > ratio:
        return Action(
            type="MOVE_TO_HRP",
            photo=best_local,
            reason=(
                f"Local {best_local.width}×{best_local.height} px "
                f"> Cloud {cloud.width}×{cloud.height} px "
                f"(ratio {actual_ratio:.2f})"
            ),
            confidence=0.95,
        )
    return None


def apply_rules(
    groups: list[DuplicateGroup],
    hrp_ratio: Optional[float] = None,
) -> list[Action]:
    """
    Apply rules to every group and return the full action plan.
    One or more Actions per group (multiple DELETEs if multiple local copies exist).
    """
    cfg = get_config()
    ratio = hrp_ratio or cfg.hrp_ratio
    actions: list[Action] = []

    for group in groups:
        sources = group.sources

        # ── Rule 1: single source — never touch ───────────────
        if len(sources) < 2:
            actions.append(Action(
                type="SKIP",
                photo=group.primary,
                reason="Only 1 source — not backed up",
                confidence=1.0,
            ))
            continue

        # ── Rule 2: HRP — high-res local copy (priority) ──────
        hrp_action = _hrp_check(group, ratio)
        if hrp_action:
            actions.append(hrp_action)
            continue

        # ── Rule 3: hash-confirmed cloud backup → delete local ─
        if "google_photos" in sources and group.cloud_phash_confirmed:
            for photo in group.local_photos:
                if photo.source == "mobile" and not cfg.enable_mobile_delete:
                    actions.append(Action(
                        type="SKIP",
                        photo=photo,
                        reason=(
                            "Mobile delete disabled by default — set "
                            "ENABLE_MOBILE_DELETE=true in .env to allow, or "
                            "delete manually via your phone's gallery app"
                        ),
                        confidence=0.8,
                    ))
                    continue
                actions.append(Action(
                    type="DELETE",
                    photo=photo,
                    reason="Hash-confirmed backup on Google Photos",
                    confidence=0.99,
                ))
            continue

        # ── Rule 4: cloud present but hash not confirmed ───────
        if "google_photos" in sources and not group.cloud_phash_confirmed:
            logger.warning(
                f"Cloud match for '{group.primary.filename}' is filename-only — "
                "skipping (pHash confirmation required to delete)"
            )
            actions.append(Action(
                type="SKIP",
                photo=group.primary,
                reason="Cloud match unconfirmed by phash — skipping (safe default)",
                confidence=0.3,
            ))
            continue

        # ── Rule 5: fallback ───────────────────────────────────
        actions.append(Action(
            type="SKIP",
            photo=group.primary,
            reason="Insufficient backup confidence",
            confidence=0.5,
        ))

    # Summary log
    by_type = {t: sum(1 for a in actions if a.type == t) for t in ("DELETE", "MOVE_TO_HRP", "SKIP")}
    logger.info(
        f"Rule engine: {by_type['DELETE']} DELETE  |  "
        f"{by_type['MOVE_TO_HRP']} MOVE_TO_HRP  |  "
        f"{by_type['SKIP']} SKIP"
    )
    return actions
