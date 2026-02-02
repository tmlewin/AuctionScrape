"""
Database management commands.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    help="Database operations",
    no_args_is_help=True,
)


@app.command("init")
def init_database(
    drop_existing: bool = typer.Option(
        False,
        "--drop",
        help="Drop existing tables before creating",
    ),
) -> None:
    """Initialize the database schema.
    
    Creates all tables. Use --drop to reset the database.
    """
    from procurewatch.persistence.db import get_engine, init_db, drop_db
    from procurewatch.core.config.loader import load_app_config
    
    config = load_app_config()
    
    if drop_existing:
        if not typer.confirm("This will DELETE ALL DATA. Continue?", default=False):
            raise typer.Abort()
        
        console.print("[yellow]Dropping existing tables...[/yellow]")
        drop_db(config.database.url)
    
    console.print("Creating database schema...")
    init_db(config.database.url)
    
    console.print("[green]OK[/green] Database initialized")


@app.command("migrate")
def run_migrations(
    revision: str = typer.Option(
        "head",
        "--revision",
        "-r",
        help="Target revision (default: head)",
    ),
) -> None:
    """Run database migrations."""
    from alembic import command
    from alembic.config import Config
    
    alembic_cfg = Config("alembic.ini")
    
    console.print(f"Running migrations to: {revision}")
    
    try:
        command.upgrade(alembic_cfg, revision)
        console.print("[green]OK[/green] Migrations complete")
    except Exception as e:
        err_console.print(f"[red]Migration failed:[/red] {e}")
        raise typer.Exit(1)


@app.command("downgrade")
def downgrade_database(
    revision: str = typer.Argument(..., help="Target revision"),
) -> None:
    """Downgrade database to a specific revision."""
    from alembic import command
    from alembic.config import Config
    
    if not typer.confirm(f"Downgrade to revision '{revision}'? This may lose data."):
        raise typer.Abort()
    
    alembic_cfg = Config("alembic.ini")
    
    console.print(f"Downgrading to: {revision}")
    
    try:
        command.downgrade(alembic_cfg, revision)
        console.print("[green]OK[/green] Downgrade complete")
    except Exception as e:
        err_console.print(f"[red]Downgrade failed:[/red] {e}")
        raise typer.Exit(1)


@app.command("revision")
def create_revision(
    message: str = typer.Argument(..., help="Revision message"),
    autogenerate: bool = typer.Option(
        True,
        "--autogenerate/--empty",
        help="Autogenerate from model changes",
    ),
) -> None:
    """Create a new migration revision."""
    from alembic import command
    from alembic.config import Config
    
    alembic_cfg = Config("alembic.ini")
    
    console.print(f"Creating revision: {message}")
    
    try:
        command.revision(alembic_cfg, message=message, autogenerate=autogenerate)
        console.print("[green]OK[/green] Revision created")
    except Exception as e:
        err_console.print(f"[red]Failed to create revision:[/red] {e}")
        raise typer.Exit(1)


@app.command("current")
def show_current() -> None:
    """Show current database revision."""
    from alembic import command
    from alembic.config import Config
    
    alembic_cfg = Config("alembic.ini")
    
    console.print("[bold]Current database revision:[/bold]")
    command.current(alembic_cfg, verbose=True)


@app.command("history")
def show_history(
    limit: int = typer.Option(
        10,
        "--limit",
        "-n",
        help="Number of revisions to show",
    ),
) -> None:
    """Show migration history."""
    from alembic import command
    from alembic.config import Config
    
    alembic_cfg = Config("alembic.ini")
    
    console.print("[bold]Migration history:[/bold]")
    command.history(alembic_cfg, indicate_current=True)


@app.command("shell")
def database_shell() -> None:
    """Open an interactive database shell.
    
    Provides a Python REPL with database session and models loaded.
    """
    import code
    
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence import models
    from procurewatch.persistence.repo import (
        OpportunityRepository,
        PortalRepository,
        RunRepository,
    )
    
    console.print("[bold]ProcureWatch Database Shell[/bold]")
    console.print("[dim]Available: session, models, PortalRepository, OpportunityRepository, RunRepository[/dim]")
    console.print()
    
    with get_session() as session:
        local_vars = {
            "session": session,
            "models": models,
            "Portal": models.Portal,
            "Opportunity": models.Opportunity,
            "OpportunityEvent": models.OpportunityEvent,
            "ScrapeRun": models.ScrapeRun,
            "PortalRepository": PortalRepository,
            "OpportunityRepository": OpportunityRepository,
            "RunRepository": RunRepository,
            "portal_repo": PortalRepository(session),
            "opp_repo": OpportunityRepository(session),
            "run_repo": RunRepository(session),
        }
        
        code.interact(local=local_vars)
