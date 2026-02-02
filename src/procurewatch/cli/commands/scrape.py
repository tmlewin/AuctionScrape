"""
Scrape commands for running portal scrapes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    help="Run scrape jobs",
    no_args_is_help=True,
)


def _load_portal_config(portal_name: str):
    """Load portal configuration by name."""
    from procurewatch.core.config.loader import load_portal_config, ConfigError
    
    # Try to find the config file
    portals_dir = Path("configs/portals")
    
    # Try exact match first
    for ext in [".yaml", ".yml"]:
        config_path = portals_dir / f"{portal_name}{ext}"
        if config_path.exists():
            try:
                return load_portal_config(config_path)
            except ConfigError as e:
                err_console.print(f"[red]Error loading portal config:[/red] {e}")
                raise typer.Exit(1)
    
    err_console.print(f"[red]Portal config not found:[/red] {portal_name}")
    err_console.print(f"[dim]Looked in: {portals_dir}[/dim]")
    
    available = _list_available_portals()
    if available:
        err_console.print(f"[dim]Available: {', '.join(available)}[/dim]")
    
    raise typer.Exit(1)


def _list_available_portals() -> list[str]:
    """List available portal configuration files."""
    portals_dir = Path("configs/portals")
    if not portals_dir.exists():
        return []
    
    return [
        f.stem for f in portals_dir.glob("*.yaml")
        if not f.name.startswith("_")
    ]


@app.command("run")
def run_scrape(
    portal: Optional[str] = typer.Option(
        None,
        "--portal",
        "-p",
        help="Portal name to scrape",
    ),
    all_portals: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Scrape all enabled portals",
    ),
    max_pages: int = typer.Option(
        50,
        "--max-pages",
        "-n",
        help="Maximum pages to scrape per portal",
    ),
    follow_details: bool = typer.Option(
        True,
        "--follow-details/--no-follow-details",
        help="Follow detail page links",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Don't save results to database",
    ),
) -> None:
    """Run a scrape job for one or more portals.
    
    Examples:
        procurewatch scrape run --portal clarkcounty_nv
        procurewatch scrape run --all --max-pages 10
        procurewatch scrape run -p nevadaepro --dry-run
    """
    if not portal and not all_portals:
        err_console.print("[red]Specify --portal <name> or --all[/red]")
        available = _list_available_portals()
        if available:
            err_console.print(f"[dim]Available portals: {', '.join(available)}[/dim]")
        raise typer.Exit(1)
    
    if portal and all_portals:
        err_console.print("[red]Cannot specify both --portal and --all[/red]")
        raise typer.Exit(1)
    
    # Determine which portals to scrape
    if all_portals:
        portals_to_scrape = _list_available_portals()
        if not portals_to_scrape:
            err_console.print("[red]No portal configurations found[/red]")
            raise typer.Exit(1)
    else:
        portals_to_scrape = [portal]
    
    console.print()
    
    if len(portals_to_scrape) == 1:
        console.print(f"[bold]Starting scrape for portal:[/bold] {portals_to_scrape[0]}")
    else:
        console.print(f"[bold]Starting scrape for {len(portals_to_scrape)} portals[/bold]")
    
    if dry_run:
        console.print("[yellow]Dry run mode - results will not be saved[/yellow]")
    
    console.print()
    
    # Run scrapes
    all_stats = []
    
    for portal_name in portals_to_scrape:
        stats = _run_single_portal(
            portal_name,
            max_pages=max_pages,
            follow_details=follow_details,
            dry_run=dry_run,
        )
        all_stats.append((portal_name, stats))
    
    # Show summary
    console.print()
    _show_summary(all_stats)


def _run_single_portal(
    portal_name: str,
    max_pages: int,
    follow_details: bool,
    dry_run: bool,
):
    """Run scrape for a single portal."""
    from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
    from procurewatch.core.orchestrator import ScrapeRunner
    
    config = _load_portal_config(portal_name)
    
    runner = ScrapeRunner(config, dry_run=dry_run)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"[cyan]Scraping {portal_name}...[/cyan]",
            total=None,
        )
        
        try:
            stats = asyncio.run(runner.run(
                max_pages=max_pages,
                follow_details=follow_details,
            ))
            
            if stats.errors_count > 0:
                progress.update(
                    task,
                    description=f"[yellow]{portal_name}: completed with {stats.errors_count} errors[/yellow]"
                )
            else:
                progress.update(
                    task,
                    description=f"[green]{portal_name}: completed successfully[/green]"
                )
            
            return stats
            
        except Exception as e:
            progress.update(
                task,
                description=f"[red]{portal_name}: failed - {e}[/red]"
            )
            
            # Return empty stats on failure
            from procurewatch.core.orchestrator.runner import RunStats
            stats = RunStats()
            stats.errors.append(str(e))
            stats.errors_count = 1
            return stats


def _show_summary(all_stats: list):
    """Show summary table of scrape results."""
    from procurewatch.core.orchestrator.runner import RunStats
    
    table = Table(title="Scrape Summary")
    
    table.add_column("Portal", style="cyan")
    table.add_column("Pages", justify="right")
    table.add_column("Found", justify="right")
    table.add_column("New", justify="right", style="green")
    table.add_column("Updated", justify="right", style="yellow")
    table.add_column("Errors", justify="right", style="red")
    table.add_column("Duration", justify="right")
    
    total_pages = 0
    total_found = 0
    total_new = 0
    total_updated = 0
    total_errors = 0
    
    for portal_name, stats in all_stats:
        duration = f"{stats.duration_seconds:.1f}s" if stats.duration_seconds else "-"
        
        table.add_row(
            portal_name,
            str(stats.pages_scraped),
            str(stats.opportunities_found),
            str(stats.opportunities_new),
            str(stats.opportunities_updated),
            str(stats.errors_count),
            duration,
        )
        
        total_pages += stats.pages_scraped
        total_found += stats.opportunities_found
        total_new += stats.opportunities_new
        total_updated += stats.opportunities_updated
        total_errors += stats.errors_count
    
    if len(all_stats) > 1:
        table.add_section()
        table.add_row(
            "[bold]Total[/bold]",
            str(total_pages),
            str(total_found),
            str(total_new),
            str(total_updated),
            str(total_errors),
            "",
        )
    
    console.print(table)
    
    # Show errors if any
    for portal_name, stats in all_stats:
        if stats.errors:
            console.print()
            console.print(f"[red]Errors from {portal_name}:[/red]")
            for error in stats.errors[:5]:  # Show first 5 errors
                console.print(f"  • {error}")
            if len(stats.errors) > 5:
                console.print(f"  [dim]... and {len(stats.errors) - 5} more[/dim]")


@app.command("test")
def test_scrape(
    portal: str = typer.Argument(..., help="Portal name to test"),
    pages: int = typer.Option(
        1,
        "--pages",
        "-n",
        help="Number of pages to scrape",
    ),
) -> None:
    """Test scraping a portal without saving results.
    
    Useful for debugging portal configurations.
    
    Examples:
        procurewatch scrape test clarkcounty_nv
        procurewatch scrape test nevadaepro --pages 2
    """
    console.print(f"[bold]Testing scrape for:[/bold] {portal}")
    console.print(f"[dim]Pages: {pages}, Dry run: True[/dim]")
    console.print()
    
    stats = _run_single_portal(
        portal,
        max_pages=pages,
        follow_details=False,  # Faster for testing
        dry_run=True,
    )
    
    console.print()
    
    # Show detailed stats
    console.print("[bold]Results:[/bold]")
    console.print(f"  Pages scraped: {stats.pages_scraped}")
    console.print(f"  Opportunities found: {stats.opportunities_found}")
    console.print(f"  Errors: {stats.errors_count}")
    
    if stats.duration_seconds:
        console.print(f"  Duration: {stats.duration_seconds:.2f}s")
    
    if stats.errors:
        console.print()
        console.print("[red]Errors:[/red]")
        for error in stats.errors:
            console.print(f"  • {error}")
    
    if stats.warnings:
        console.print()
        console.print("[yellow]Warnings:[/yellow]")
        for warning in stats.warnings[:10]:
            console.print(f"  • {warning}")


@app.command("resume")
def resume_scrape(
    run_id: int = typer.Argument(..., help="Run ID to resume"),
) -> None:
    """Resume an interrupted scrape run.
    
    Continues from the last checkpoint saved during the run.
    """
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence.models import ScrapeRun
    
    with get_session() as session:
        run = session.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
        
        if not run:
            err_console.print(f"[red]Run not found:[/red] {run_id}")
            raise typer.Exit(1)
        
        if run.status not in ("RUNNING", "PARTIAL", "FAILED"):
            err_console.print(f"[red]Run cannot be resumed (status: {run.status})[/red]")
            raise typer.Exit(1)
        
        if not run.checkpoint:
            err_console.print("[red]No checkpoint found for this run[/red]")
            raise typer.Exit(1)
        
        portal_name = run.portal.name if run.portal else "unknown"
    
    console.print(f"[bold]Resuming run:[/bold] {run_id}")
    console.print(f"[dim]Portal:[/dim] {portal_name}")
    console.print()
    
    # TODO: Implement resume logic with checkpoint
    console.print("[yellow]Resume from checkpoint not yet implemented[/yellow]")
    console.print("[dim]Use 'scrape run' to start a fresh scrape[/dim]")


@app.command("list-runs")
def list_runs(
    portal: Optional[str] = typer.Option(
        None,
        "--portal",
        "-p",
        help="Filter by portal name",
    ),
    limit: int = typer.Option(
        10,
        "--limit",
        "-n",
        help="Number of runs to show",
    ),
) -> None:
    """List recent scrape runs."""
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence.models import ScrapeRun, Portal
    
    with get_session() as session:
        query = session.query(ScrapeRun).order_by(ScrapeRun.started_at.desc())
        
        if portal:
            query = query.join(Portal).filter(Portal.name == portal)
        
        runs = query.limit(limit).all()
        
        if not runs:
            console.print("[dim]No scrape runs found[/dim]")
            return
        
        table = Table(title="Recent Scrape Runs")
        
        table.add_column("ID", justify="right")
        table.add_column("Portal")
        table.add_column("Status")
        table.add_column("Started")
        table.add_column("Pages")
        table.add_column("New")
        table.add_column("Updated")
        table.add_column("Errors")
        
        for run in runs:
            status_style = {
                "COMPLETED": "green",
                "RUNNING": "yellow",
                "FAILED": "red",
            }.get(run.status, "dim")
            
            portal_name = run.portal.name if run.portal else "?"
            started = run.started_at.strftime("%Y-%m-%d %H:%M") if run.started_at else "-"
            
            table.add_row(
                str(run.id),
                portal_name,
                f"[{status_style}]{run.status}[/{status_style}]",
                started,
                str(run.pages_scraped),
                str(run.opportunities_new),
                str(run.opportunities_updated),
                str(run.errors_count),
            )
        
        console.print(table)
