"""
photo-agent CLI
───────────────
Commands:
    scan          Scan all storages (read-only)
    run           Full pipeline: scan → detect → plan → confirm → execute
    report        Open the most recent HTML report in your browser
    purge-trash   Permanently delete files in ~/.photo_agent_trash/
    clear-cache   Wipe the SQLite index (forces full re-scan next run)
"""
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from loguru import logger
from rich.console import Console

app = typer.Typer(
    name="photo-agent",
    help="Deduplicate photos across Google Photos, PC, and mobile.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


# ── Logging ────────────────────────────────────────────────────

def _setup_logging() -> None:
    from config import get_config
    cfg = get_config()
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(
        sys.stderr,
        level=cfg.log_level,
        colorize=True,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
    )
    logger.add(
        cfg.log_dir / "agent.log",
        rotation="1 day",
        retention="14 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )


# ── Default initial state ──────────────────────────────────────

def _base_state(
    dry_run: bool,
    skip_mobile: bool,
    skip_google: bool,
    threshold: Optional[int],
    max_deletes: Optional[int],
) -> dict:
    from config import get_config
    cfg = get_config()
    return {
        "dry_run":           dry_run,
        "skip_mobile":       skip_mobile,
        "skip_google":       skip_google,
        "user_confirmed":    False,
        "hamming_threshold": threshold or cfg.hamming_threshold,
        "max_deletes":       max_deletes,
        "scan_results":      {},
        "duplicate_groups":  [],
        "action_plan":       [],
        "execution_results": [],
        "report":            {},
    }


# ── Commands ───────────────────────────────────────────────────

@app.command()
def scan(
    skip_mobile: bool = typer.Option(False, "--skip-mobile", help="Skip mobile storage"),
    skip_google:  bool = typer.Option(False, "--skip-google",  help="Skip Google Photos"),
) -> None:
    """Scan all storages and index photos. Completely read-only — no files changed."""
    _setup_logging()
    from agent.graph import graph

    console.print("[bold]Scanning storage sources…[/bold]\n")
    state = _base_state(True, skip_mobile, skip_google, None, None)
    # Only run the scan + extract nodes, stop before detect
    result = graph.invoke(state)

    scan_results = result.get("scan_results", {})
    total = sum(len(v) for v in scan_results.values())
    for source, records in scan_results.items():
        console.print(f"  [green]{source:<16}[/green] {len(records)} photos")
    console.print(f"\n[bold green]Done.[/bold green] {total} photos indexed.")


@app.command()
def run(
    execute:      bool         = typer.Option(False, "--execute",      help="Apply changes (default: dry-run)"),
    skip_mobile:  bool         = typer.Option(False, "--skip-mobile"),
    skip_google:  bool         = typer.Option(False, "--skip-google"),
    threshold:    Optional[int]= typer.Option(None,  "--threshold", "-t", help="Hamming threshold (default from .env)"),
    max_deletes:  Optional[int]= typer.Option(None,  "--max-deletes",  help="Cap number of delete actions"),
) -> None:
    """
    Full pipeline: scan → detect duplicates → plan → (confirm) → execute.

    Default is DRY RUN — use --execute to apply changes.
    Files are moved to ~/.photo_agent_trash/, never permanently deleted here.
    """
    _setup_logging()
    from agent.graph import graph

    if execute:
        console.print("[bold red]EXECUTE MODE[/bold red] — files will be moved to trash\n")
    else:
        console.print("[bold yellow]DRY RUN[/bold yellow] — no files will be changed\n")

    state = _base_state(not execute, skip_mobile, skip_google, threshold, max_deletes)
    result = graph.invoke(state)

    report_data = result.get("report", {})
    if path := report_data.get("report_path"):
        console.print(f"\n[bold]Report saved:[/bold] {path}")
        console.print("Run [bold]python main.py report[/bold] to open it in your browser.")


@app.command()
def report() -> None:
    """Open the most recent HTML report in your browser."""
    report_dir = Path("reports")
    files = sorted(report_dir.glob("report_*.html"), reverse=True)
    if not files:
        console.print("[red]No reports found. Run [bold]python main.py run[/bold] first.[/red]")
        raise typer.Exit(1)
    latest = files[0]
    console.print(f"Opening [bold]{latest}[/bold]")
    opener = "open" if sys.platform == "darwin" else ("start" if sys.platform == "win32" else "xdg-open")
    subprocess.run([opener, str(latest)])


@app.command("purge-trash")
def purge_trash() -> None:
    """Permanently delete all files in the trash folder. Requires typed confirmation."""
    from config import get_config
    trash = get_config().trash_dir

    if not trash.exists() or not any(trash.iterdir()):
        console.print("[green]Trash folder is empty.[/green]")
        return

    files = list(trash.rglob("*"))
    console.print(f"[red bold]{len(files)} file(s) in {trash} will be permanently deleted.[/red bold]")
    confirm = typer.prompt("Type  yes I reviewed the trash  to confirm", default="")

    if confirm.strip() == "yes I reviewed the trash":
        import shutil
        shutil.rmtree(trash)
        trash.mkdir(parents=True)
        console.print("[green]Trash purged.[/green]")
    else:
        console.print("[yellow]Aborted.[/yellow]")


@app.command("clear-cache")
def clear_cache() -> None:
    """Clear the SQLite photo index. Next run will re-scan everything from scratch."""
    from db.store import PhotoStore
    PhotoStore().clear()
    console.print("[green]Photo index cleared.[/green]")


if __name__ == "__main__":
    app()
