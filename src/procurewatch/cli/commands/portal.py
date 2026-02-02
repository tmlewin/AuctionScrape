"""
Portal management commands.

Commands for adding, testing, listing, and managing portal configurations.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Windows-safe console
console = Console(force_terminal=True, legacy_windows=False)
err_console = Console(stderr=True, force_terminal=True, legacy_windows=False)

app = typer.Typer(
    help="Manage portal configurations",
    no_args_is_help=True,
)


@app.command("list")
def list_portals(
    enabled_only: bool = typer.Option(
        False,
        "--enabled",
        "-e",
        help="Show only enabled portals",
    ),
    format: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format (table, json)",
    ),
) -> None:
    """List all configured portals."""
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence.repo import PortalRepository
    
    with get_session() as session:
        repo = PortalRepository(session)
        portals = repo.get_all(enabled_only=enabled_only)
        
        if not portals:
            console.print("[dim]No portals configured.[/dim]")
            console.print("Add one with: [yellow]procurewatch portal add[/yellow]")
            return
        
        if format == "json":
            import json
            data = [
                {
                    "name": p.name,
                    "display_name": p.display_name,
                    "base_url": p.base_url,
                    "enabled": p.enabled,
                    "total_opportunities": p.total_opportunities,
                    "last_scraped": p.last_scraped_at.isoformat() if p.last_scraped_at else None,
                }
                for p in portals
            ]
            console.print_json(json.dumps(data))
            return
        
        table = Table(title="Configured Portals", show_header=True, header_style="bold magenta")
        table.add_column("Name", style="cyan", no_wrap=True)
        table.add_column("Display Name")
        table.add_column("Type")
        table.add_column("Status", justify="center")
        table.add_column("Opportunities", justify="right")
        table.add_column("Last Scraped")
        
        for portal in portals:
            status = "[green]+ Enabled[/green]" if portal.enabled else "[red]x Disabled[/red]"
            last_scraped = portal.last_scraped_at.strftime("%Y-%m-%d %H:%M") if portal.last_scraped_at else "[dim]Never[/dim]"
            
            table.add_row(
                portal.name,
                portal.display_name or "[dim]-[/dim]",
                portal.portal_type,
                status,
                str(portal.total_opportunities),
                last_scraped,
            )
        
        console.print(table)


@app.command("show")
def show_portal(
    name: str = typer.Argument(..., help="Portal name"),
) -> None:
    """Show detailed portal configuration."""
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence.repo import PortalRepository
    
    with get_session() as session:
        repo = PortalRepository(session)
        portal = repo.get_by_name(name)
        
        if not portal:
            err_console.print(f"[red]Portal not found:[/red] {name}")
            raise typer.Exit(1)
        
        console.print()
        console.print(Panel.fit(
            f"[bold]Name:[/bold] {portal.name}\n"
            f"[bold]Display Name:[/bold] {portal.display_name or '-'}\n"
            f"[bold]Base URL:[/bold] {portal.base_url}\n"
            f"[bold]Type:[/bold] {portal.portal_type}\n"
            f"[bold]Enabled:[/bold] {'Yes' if portal.enabled else 'No'}\n"
            f"[bold]Total Opportunities:[/bold] {portal.total_opportunities}\n"
            f"[bold]Total Runs:[/bold] {portal.total_runs}\n"
            f"[bold]Last Scraped:[/bold] {portal.last_scraped_at or 'Never'}\n"
            f"[bold]Last Success:[/bold] {portal.last_success_at or 'Never'}\n"
            f"[bold]Created:[/bold] {portal.created_at}\n"
            f"[bold]Config Hash:[/bold] {portal.config_hash or '-'}",
            title=f"[bold cyan]Portal: {portal.name}[/bold cyan]",
            border_style="cyan",
        ))


@app.command("add")
def add_portal(
    config_file: Path = typer.Argument(
        ...,
        help="Path to portal YAML configuration file",
        exists=True,
        readable=True,
    ),
    sync_db: bool = typer.Option(
        True,
        "--sync-db/--no-sync-db",
        help="Sync configuration to database",
    ),
) -> None:
    """Add a portal from a YAML configuration file.
    
    The configuration file will be copied to configs/portals/
    and optionally synced to the database.
    """
    import shutil
    import hashlib
    
    from procurewatch.core.config.loader import load_portal_config, ConfigError
    
    # Validate configuration
    try:
        config = load_portal_config(config_file)
    except ConfigError as e:
        err_console.print(f"[red]Invalid configuration:[/red] {e}")
        if e.details:
            err_console.print(f"[dim]{e.details}[/dim]")
        raise typer.Exit(1)
    
    # Copy to portals directory
    dest_path = Path(f"configs/portals/{config.name}.yaml")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    
    if dest_path.exists():
        if not typer.confirm(f"Portal config '{config.name}' already exists. Overwrite?"):
            raise typer.Abort()
    
    shutil.copy(config_file, dest_path)
    console.print(f"[green]OK[/green] Copied configuration to {dest_path}")
    
    # Sync to database
    if sync_db:
        from procurewatch.persistence.db import get_session
        from procurewatch.persistence.repo import PortalRepository
        
        # Compute config hash
        config_hash = hashlib.sha256(dest_path.read_bytes()).hexdigest()[:16]
        
        with get_session() as session:
            repo = PortalRepository(session)
            portal, created = repo.upsert(
                name=config.name,
                base_url=str(config.base_url),
                portal_type=config.portal_type.value,
                display_name=config.display_name,
                config_hash=config_hash,
            )
        
        action = "Created" if created else "Updated"
        console.print(f"[green]OK[/green] {action} portal in database: {config.name}")
    
    console.print()
    console.print(f"Test the portal: [yellow]procurewatch portal test {config.name}[/yellow]")


@app.command("test")
def test_portal(
    name: str = typer.Argument(..., help="Portal name to test"),
    max_pages: int = typer.Option(
        1,
        "--max-pages",
        "-n",
        help="Maximum pages to scrape",
    ),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="Don't save results to database",
    ),
) -> None:
    """Test portal connectivity and extraction.
    
    Performs a test scrape to validate:
    - Connectivity to the portal
    - Page structure parsing
    - Extraction confidence
    """
    from rich.progress import Progress, SpinnerColumn, TextColumn
    
    from procurewatch.core.config.loader import load_portal_config, ConfigError
    
    config_path = Path(f"configs/portals/{name}.yaml")
    
    if not config_path.exists():
        err_console.print(f"[red]Portal configuration not found:[/red] {config_path}")
        raise typer.Exit(1)
    
    try:
        config = load_portal_config(config_path)
    except ConfigError as e:
        err_console.print(f"[red]Invalid configuration:[/red] {e}")
        raise typer.Exit(1)
    
    console.print()
    console.print(f"[bold]Testing portal:[/bold] {config.name}")
    console.print(f"[dim]Base URL:[/dim] {config.base_url}")
    console.print(f"[dim]Seed URLs:[/dim] {len(config.seed_urls)}")
    console.print()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Connecting to portal...", total=None)
        
        # TODO: Implement actual test logic in M1
        # For now, just validate config and connectivity
        
        import httpx
        
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                for seed_url in config.seed_urls[:1]:
                    progress.update(task, description=f"Fetching {seed_url[:50]}...")
                    response = client.get(seed_url)
                    
                    progress.update(task, description="Analyzing response...")
                    
        except httpx.RequestError as e:
            progress.stop()
            err_console.print(f"[red]Connection failed:[/red] {e}")
            raise typer.Exit(1)
    
    # Summary
    console.print()
    console.print(Panel.fit(
        f"[green]OK Connectivity:[/green] OK (HTTP {response.status_code})\n"
        f"[green]OK Response size:[/green] {len(response.content):,} bytes\n"
        f"[yellow]! Extraction:[/yellow] Not yet implemented (M1)\n"
        f"[dim]Dry run:[/dim] {dry_run}",
        title="[bold]Test Results[/bold]",
        border_style="green" if response.status_code == 200 else "yellow",
    ))


@app.command("enable")
def enable_portal(
    name: str = typer.Argument(..., help="Portal name"),
) -> None:
    """Enable a portal."""
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence.repo import PortalRepository
    
    with get_session() as session:
        repo = PortalRepository(session)
        portal = repo.get_by_name(name)
        
        if not portal:
            err_console.print(f"[red]Portal not found:[/red] {name}")
            raise typer.Exit(1)
        
        portal.enabled = True
    
    console.print(f"[green]OK[/green] Enabled portal: {name}")


@app.command("disable")
def disable_portal(
    name: str = typer.Argument(..., help="Portal name"),
) -> None:
    """Disable a portal."""
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence.repo import PortalRepository
    
    with get_session() as session:
        repo = PortalRepository(session)
        portal = repo.get_by_name(name)
        
        if not portal:
            err_console.print(f"[red]Portal not found:[/red] {name}")
            raise typer.Exit(1)
        
        portal.enabled = False
    
    console.print(f"[yellow]OK[/yellow] Disabled portal: {name}")


@app.command("sync")
def sync_portals() -> None:
    """Sync all portal YAML configs to database.
    
    Scans configs/portals/ and updates the database to match.
    """
    import hashlib
    
    from procurewatch.core.config.loader import load_all_portal_configs
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence.repo import PortalRepository
    
    portal_dir = Path("configs/portals")
    
    if not portal_dir.exists():
        err_console.print("[red]Portal config directory not found.[/red]")
        raise typer.Exit(1)
    
    configs = load_all_portal_configs(portal_dir)
    
    if not configs:
        console.print("[dim]No portal configurations found.[/dim]")
        return
    
    with get_session() as session:
        repo = PortalRepository(session)
        
        created = 0
        updated = 0
        
        for name, config in configs.items():
            config_path = portal_dir / f"{name}.yaml"
            config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()[:16]
            
            portal, is_new = repo.upsert(
                name=config.name,
                base_url=str(config.base_url),
                portal_type=config.portal_type.value,
                display_name=config.display_name,
                config_hash=config_hash,
            )
            
            if is_new:
                created += 1
                console.print(f"[green]+ Created:[/green] {name}")
            else:
                updated += 1
                console.print(f"[blue]~ Updated:[/blue] {name}")
    
    console.print()
    console.print(f"[bold]Sync complete:[/bold] {created} created, {updated} updated")
