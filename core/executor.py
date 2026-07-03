"""
Action executor.
DRY RUN (default): prints a compact action preview, touches nothing.
EXECUTE: moves files to trash or HRP folder; never calls os.remove().
"""
import json
import shutil
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

from config import get_config
from utils.models import Action, ActionResult

console = Console()


# ── Formatting helpers ─────────────────────────────────────────

def _fmt_bytes(n: int) -> str:
    if n == 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


_TYPE_COLOUR = {"DELETE": "red", "MOVE_TO_HRP": "green", "SKIP": "dim"}


# ── Preview table ──────────────────────────────────────────────

def print_action_table(actions: list[Action]) -> None:
    """
    Print a Rich summary of planned actions.

    KEY FIX: previous version printed every individual SKIP as its own table row.
    With 2,000+ photos all returning SKIP (common when --skip-google is used),
    this floods the terminal with thousands of identical lines and is unreadable.

    New behaviour:
    - DELETE and MOVE_TO_HRP → shown individually in a table (you want to review these)
    - SKIP                   → collapsed into a grouped count summary
    """
    non_skips = [a for a in actions if a.type != "SKIP"]
    skips     = [a for a in actions if a.type == "SKIP"]
    deletes   = [a for a in actions if a.type == "DELETE"]
    hrp       = [a for a in actions if a.type == "MOVE_TO_HRP"]
    freed     = sum(a.photo.size_bytes for a in deletes)

    # ── Summary line (always shown first) ─────────────────────
    console.print(
        f"\n[bold]Summary:[/bold]  "
        f"[red]{len(deletes)} delete[/red] ({_fmt_bytes(freed)} freed)  ·  "
        f"[green]{len(hrp)} → HRP[/green]  ·  "
        f"[dim]{len(skips)} skip[/dim]"
    )

    # ── Actionable items table ─────────────────────────────────
    if non_skips:
        table = Table(
            title="Actions to execute", show_header=True,
            header_style="bold", min_width=80,
        )
        table.add_column("Type",     min_width=14, style="bold")
        table.add_column("Filename", min_width=36)
        table.add_column("Source",   min_width=14)
        table.add_column("Reason")

        for action in non_skips:
            colour = _TYPE_COLOUR.get(action.type, "white")
            table.add_row(
                f"[{colour}]{action.type}[/{colour}]",
                action.photo.filename,
                action.photo.source,
                action.reason,
            )
        console.print(table)
    else:
        console.print("[dim]  No delete or HRP actions planned.[/dim]")

    # ── Skip summary (grouped, not individual rows) ────────────
    if skips:
        console.print(f"\n[dim]Skipped {len(skips)} photos:[/dim]")
        # Group by (source, reason) → count
        groups = Counter((a.photo.source, a.reason) for a in skips)
        for (source, reason), count in sorted(groups.items()):
            console.print(f"  [dim]{count:>5}  {source:<16}  {reason}[/dim]")


# ── File operations ────────────────────────────────────────────

def _do_delete(action: Action, trash_dir: Path) -> ActionResult:
    if action.photo.source == "mobile":
        return _do_mobile_delete(action)

    src = Path(action.photo.path_or_url)
    if not src.exists():
        return ActionResult(action=action, outcome="FAILED", error_msg="Source not found")
    try:
        dest_name = f"{uuid.uuid4().hex[:8]}_{src.name}"
        dest = trash_dir / dest_name
        shutil.move(str(src), str(dest))
        logger.info(f"[DELETE] {src.name} → trash/{dest_name}")
        return ActionResult(action=action, outcome="SUCCESS", dest_path=str(dest))
    except Exception as e:
        logger.error(f"[DELETE FAILED] {src}: {e}")
        return ActionResult(action=action, outcome="FAILED", error_msg=str(e))


def _do_mobile_delete(action: Action) -> ActionResult:
    from storage.mobile import MobileScanner
    scanner = MobileScanner()
    ok, result = scanner.move_to_trash(action.photo.path_or_url, action.photo.filename)
    if ok:
        logger.info(f"[DELETE mobile] {action.photo.filename} → {result}")
        return ActionResult(action=action, outcome="SUCCESS", dest_path=result)
    logger.error(f"[DELETE mobile FAILED] {action.photo.filename}: {result}")
    return ActionResult(action=action, outcome="FAILED", error_msg=result)


def _do_hrp_move(action: Action, hrp_folder: Path) -> ActionResult:
    if action.photo.source == "mobile":
        return _do_mobile_hrp_pull(action, hrp_folder)

    src = Path(action.photo.path_or_url)
    if not src.exists():
        return ActionResult(action=action, outcome="FAILED", error_msg="Source not found")
    try:
        hrp_folder.mkdir(parents=True, exist_ok=True)
        dest = hrp_folder / src.name
        if dest.exists():
            dest = hrp_folder / f"{uuid.uuid4().hex[:6]}_{src.name}"
        shutil.move(str(src), str(dest))
        logger.info(f"[HRP] {src.name} → {dest}")
        return ActionResult(action=action, outcome="SUCCESS", dest_path=str(dest))
    except Exception as e:
        logger.error(f"[HRP FAILED] {src}: {e}")
        return ActionResult(action=action, outcome="FAILED", error_msg=str(e))


def _do_mobile_hrp_pull(action: Action, hrp_folder: Path) -> ActionResult:
    from storage.mobile import MobileScanner
    scanner = MobileScanner()
    hrp_folder.mkdir(parents=True, exist_ok=True)

    dest = hrp_folder / action.photo.filename
    if dest.exists():
        dest = hrp_folder / f"{uuid.uuid4().hex[:6]}_{action.photo.filename}"

    ok, err = scanner.pull_to(action.photo.path_or_url, dest)
    if ok:
        logger.info(f"[HRP mobile] {action.photo.filename} → {dest} (phone copy untouched)")
        return ActionResult(action=action, outcome="SUCCESS", dest_path=str(dest))
    logger.error(f"[HRP mobile FAILED] {action.photo.filename}: {err}")
    return ActionResult(action=action, outcome="FAILED", error_msg=err)


def _append_log(results: list[ActionResult], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    existing: list = []
    if log_path.exists():
        try:
            existing = json.loads(log_path.read_text())
        except json.JSONDecodeError:
            pass
    existing.append({
        "timestamp": datetime.now().isoformat(),
        "results": [
            {
                "action":  r.action.type,
                "file":    r.action.photo.filename,
                "source":  r.action.photo.source,
                "reason":  r.action.reason,
                "outcome": r.outcome,
                "error":   r.error_msg,
                "dest":    r.dest_path,
            }
            for r in results
        ],
    })
    log_path.write_text(json.dumps(existing, indent=2))


# ── Main entry point ───────────────────────────────────────────

def execute_actions(
    actions: list[Action],
    dry_run: bool = True,
    max_deletes: Optional[int] = None,
) -> list[ActionResult]:
    cfg = get_config()

    if dry_run:
        console.print("\n[yellow bold]DRY RUN[/yellow bold] — no files will be changed\n")
        print_action_table(actions)
        return [ActionResult(action=a, outcome="DRY_RUN") for a in actions]

    cfg.trash_dir.mkdir(parents=True, exist_ok=True)
    cap = max_deletes or cfg.max_deletes
    delete_count = 0
    results: list[ActionResult] = []

    executable = [a for a in actions if a.type != "SKIP"]
    skipped    = [a for a in actions if a.type == "SKIP"]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Executing actions…", total=len(executable))

        for action in executable:
            progress.advance(task)

            if action.type == "DELETE":
                if cap is not None and delete_count >= cap:
                    logger.warning(f"max-deletes cap ({cap}) reached — skipping {action.photo.filename}")
                    results.append(ActionResult(action=action, outcome="SKIPPED"))
                    continue
                result = _do_delete(action, cfg.trash_dir)
                if result.outcome == "SUCCESS":
                    delete_count += 1

            elif action.type == "MOVE_TO_HRP":
                result = _do_hrp_move(action, cfg.hrp_folder)

            else:
                result = ActionResult(action=action, outcome="SKIPPED")

            results.append(result)

    for action in skipped:
        results.append(ActionResult(action=action, outcome="SKIPPED"))

    _append_log(results, cfg.actions_log_path)
    return results
