"""
ProcureWatch CLI - Main entry point.

A terminal-first procurement/tender scraper with scheduling,
versioning, and multi-backend support.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from dotenv import load_dotenv
from rich.panel import Panel
from rich.traceback import install as install_rich_traceback

from procurewatch import __app_name__, __version__

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    # Look for .env in current directory and project root
    env_path = Path(".env")
    if not env_path.exists():
        # Try project root (where pyproject.toml is)
        project_root = Path(__file__).parent.parent.parent.parent
        env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv not installed, use system env vars

# Load environment variables from .env (if present)
load_dotenv()

# Install rich traceback for better error display
install_rich_traceback(show_locals=False, width=120)

# Force UTF-8 on Windows to avoid encoding issues
if sys.platform == "win32":
    # Enable UTF-8 mode on Windows
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    # Reconfigure stdout/stderr to use UTF-8 with error replacement
    # This must happen early before any printing
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, OSError):
            pass
    if hasattr(sys.stderr, 'reconfigure'):
        try:
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, OSError):
            pass

# Create console for output with safe encoding
console = Console(force_terminal=True, legacy_windows=False)
err_console = Console(stderr=True, force_terminal=True, legacy_windows=False)

# Create main app
app = typer.Typer(
    name=__app_name__,
    help="Terminal-first procurement/tender scraper and tracker",
    rich_markup_mode="rich",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"[bold cyan]{__app_name__}[/bold cyan] version [green]{__version__}[/green]")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version and exit",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """ProcureWatch - Procurement tender scraper and tracker."""
    pass


# =============================================================================
# Import and register subcommand modules
# =============================================================================

from .commands import db, portal, quick, schedule, scrape, opportunities  # noqa: E402

app.add_typer(portal.app, name="portal", help="Manage portal configurations")
app.add_typer(scrape.app, name="scrape", help="Run scrape jobs")
app.add_typer(schedule.app, name="schedule", help="Manage scheduled jobs")
app.add_typer(opportunities.app, name="opportunities", help="View and export opportunities")
app.add_typer(db.app, name="db", help="Database operations")
app.add_typer(quick.app, name="quick", help="AI-powered scraping (no config needed)")


# =============================================================================
# Init Command
# =============================================================================


@app.command()
def init(
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing configuration",
    ),
) -> None:
    """Initialize ProcureWatch database and configuration.
    
    Creates required directories, default configuration files,
    and initializes the database schema.
    """
    from rich.progress import Progress, SpinnerColumn, TextColumn
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        # Create directories
        task = progress.add_task("Creating directories...", total=None)
        
        dirs_to_create = [
            Path("configs/portals"),
            Path("data"),
            Path("logs"),
            Path("snapshots"),
        ]
        
        for dir_path in dirs_to_create:
            dir_path.mkdir(parents=True, exist_ok=True)
        
        progress.update(task, description="Creating default configuration...")
        
        # Create default app.yaml if not exists
        app_config_path = Path("configs/app.yaml")
        if not app_config_path.exists() or force:
            _create_default_app_config(app_config_path)
        
        progress.update(task, description="Initializing database...")
        
        # Initialize database
        from procurewatch.persistence.db import init_db
        init_db()
        
        progress.update(task, description="Done!")
    
    console.print()
    console.print(Panel.fit(
        "[bold green]OK - ProcureWatch initialized successfully![/bold green]\n\n"
        "Created:\n"
        "  - [cyan]configs/app.yaml[/cyan] - Application configuration\n"
        "  - [cyan]configs/portals/[/cyan] - Portal configuration directory\n"
        "  - [cyan]data/[/cyan] - Database storage\n"
        "  - [cyan]logs/[/cyan] - Log files\n"
        "  - [cyan]snapshots/[/cyan] - HTML snapshots\n\n"
        "Next steps:\n"
        "  1. Add portal configs: [yellow]procurewatch portal add[/yellow]\n"
        "  2. Test a portal: [yellow]procurewatch portal test <name>[/yellow]\n"
        "  3. Run a scrape: [yellow]procurewatch scrape --portal <name>[/yellow]",
        title="[bold]Initialization Complete[/bold]",
        border_style="green",
    ))


def _create_default_app_config(path: Path) -> None:
    """Create default app.yaml configuration."""
    default_config = """\
# ProcureWatch Configuration
# See documentation for all available options

# Directory paths
config_dir: configs
data_dir: data
snapshot_dir: snapshots

# Database settings
database:
  url: sqlite:///data/procurewatch.db
  echo: false

# Logging settings  
logging:
  level: INFO
  file: logs/procurewatch.log
  json_format: true
  rich_console: true

# Scheduler settings
scheduler:
  enabled: true
  max_concurrent_runs: 1
  default_jitter_minutes: 5
  schedules: []

# Default politeness settings for portals
default_politeness:
  concurrency: 2
  min_delay_ms: 500
  max_delay_ms: 2000
  respect_robots_txt: true
  max_retries: 3

# Feature flags
enable_crawl4ai: false
enable_tui: false
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default_config, encoding="utf-8")


# =============================================================================
# Status Command
# =============================================================================


@app.command()
def status() -> None:
    """Show ProcureWatch status and statistics."""
    from rich.table import Table
    
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence.repo import PortalRepository, OpportunityRepository
    
    # Check if initialized
    if not Path("data/procurewatch.db").exists():
        err_console.print("[red]ProcureWatch not initialized. Run:[/red] procurewatch init")
        raise typer.Exit(1)
    
    console.print()
    console.print("[bold]ProcureWatch Status[/bold]")
    console.print()
    
    with get_session() as session:
        portal_repo = PortalRepository(session)
        opp_repo = OpportunityRepository(session)
        
        portals = portal_repo.get_all()
        
        # Portal table
        portal_table = Table(title="Portals", show_header=True, header_style="bold magenta")
        portal_table.add_column("Name", style="cyan")
        portal_table.add_column("Status", justify="center")
        portal_table.add_column("Opportunities", justify="right")
        portal_table.add_column("Last Scraped", justify="right")
        
        for portal in portals:
            status_emoji = "OK" if portal.enabled else "x"
            status_style = "green" if portal.enabled else "red"
            
            last_scraped = portal.last_scraped_at.strftime("%Y-%m-%d %H:%M") if portal.last_scraped_at else "Never"
            
            portal_table.add_row(
                portal.name,
                f"[{status_style}]{status_emoji}[/{status_style}]",
                str(portal.total_opportunities),
                last_scraped,
            )
        
        if portals:
            console.print(portal_table)
        else:
            console.print("[dim]No portals configured. Add one with:[/dim] procurewatch portal add")
        
        console.print()
        
        # Opportunity stats
        status_counts = opp_repo.count_by_status()
        if status_counts:
            stats_table = Table(title="Opportunity Status", show_header=True, header_style="bold magenta")
            stats_table.add_column("Status", style="cyan")
            stats_table.add_column("Count", justify="right")
            
            for status, count in sorted(status_counts.items()):
                stats_table.add_row(status, str(count))
            
            console.print(stats_table)
        else:
            console.print("[dim]No opportunities scraped yet.[/dim]")


# =============================================================================
# Entry Point
# =============================================================================


def run() -> None:
    """Run the CLI application."""
    app()


if __name__ == "__main__":
    run()
