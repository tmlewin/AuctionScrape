"""
Schedule management commands.
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    help="Manage scheduled scrape jobs",
    no_args_is_help=True,
)


@app.command("list")
def list_schedules() -> None:
    """List all configured schedules."""
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence.models import ScheduledJob
    from sqlalchemy import select
    
    with get_session() as session:
        stmt = select(ScheduledJob).order_by(ScheduledJob.name)
        jobs = session.execute(stmt).scalars().all()
        
        if not jobs:
            console.print("[dim]No schedules configured.[/dim]")
            console.print("Add one with: [yellow]procurewatch schedule add[/yellow]")
            return
        
        table = Table(title="Scheduled Jobs", show_header=True, header_style="bold magenta")
        table.add_column("Name", style="cyan")
        table.add_column("Status", justify="center")
        table.add_column("Schedule")
        table.add_column("Portals")
        table.add_column("Last Run")
        table.add_column("Next Run")
        
        for job in jobs:
            status = "[green]OK Enabled[/green]" if job.enabled else "[red]x Disabled[/red]"
            
            schedule_desc = f"{job.schedule_type}"
            if job.time_of_day:
                schedule_desc += f" @ {job.time_of_day}"
            if job.cron_expression:
                schedule_desc = f"cron: {job.cron_expression}"
            
            portals = job.portals_json or []
            portals_str = ", ".join(portals[:3])
            if len(portals) > 3:
                portals_str += f" (+{len(portals) - 3})"
            if not portals:
                portals_str = "[dim]all[/dim]"
            
            last_run = job.last_run_at.strftime("%Y-%m-%d %H:%M") if job.last_run_at else "[dim]Never[/dim]"
            next_run = job.next_run_at.strftime("%Y-%m-%d %H:%M") if job.next_run_at else "[dim]-[/dim]"
            
            table.add_row(
                job.name,
                status,
                schedule_desc,
                portals_str,
                last_run,
                next_run,
            )
        
        console.print(table)


@app.command("add")
def add_schedule(
    name: str = typer.Argument(..., help="Schedule name"),
    portals: Optional[str] = typer.Option(
        None,
        "--portals",
        "-p",
        help="Comma-separated portal names (default: all)",
    ),
    daily: Optional[str] = typer.Option(
        None,
        "--daily",
        help="Run daily at HH:MM (e.g., '06:15')",
    ),
    weekday: Optional[str] = typer.Option(
        None,
        "--weekday",
        help="Run weekdays at HH:MM",
    ),
    hourly: bool = typer.Option(
        False,
        "--hourly",
        help="Run every hour",
    ),
    cron: Optional[str] = typer.Option(
        None,
        "--cron",
        help="Cron expression",
    ),
    jitter: int = typer.Option(
        5,
        "--jitter",
        help="Jitter window in minutes",
    ),
    timezone: str = typer.Option(
        "UTC",
        "--timezone",
        "-tz",
        help="Timezone for schedule",
    ),
) -> None:
    """Add a new scheduled scrape job.
    
    Examples:
        procurewatch schedule add daily_nv --portals nevadaepro,clarkcounty --daily 06:15
        procurewatch schedule add hourly_all --hourly --jitter 10
    """
    from datetime import datetime
    
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence.models import ScheduledJob
    
    # Validate schedule type
    schedule_types = [daily, weekday, hourly, cron]
    if sum(1 for s in schedule_types if s or (isinstance(s, bool) and s)) != 1:
        err_console.print("[red]Specify exactly one of: --daily, --weekday, --hourly, --cron[/red]")
        raise typer.Exit(1)
    
    # Determine schedule type and time
    if daily:
        schedule_type = "daily"
        time_of_day = daily
    elif weekday:
        schedule_type = "weekday"
        time_of_day = weekday
    elif hourly:
        schedule_type = "hourly"
        time_of_day = None
    else:
        schedule_type = "cron"
        time_of_day = None
    
    # Parse portals
    portal_list = [p.strip() for p in portals.split(",")] if portals else []
    
    with get_session() as session:
        # Check for existing
        from sqlalchemy import select
        stmt = select(ScheduledJob).where(ScheduledJob.name == name)
        existing = session.execute(stmt).scalar_one_or_none()
        
        if existing:
            err_console.print(f"[red]Schedule already exists:[/red] {name}")
            raise typer.Exit(1)
        
        job = ScheduledJob(
            name=name,
            enabled=True,
            portals_json=portal_list if portal_list else None,
            schedule_type=schedule_type,
            time_of_day=time_of_day,
            cron_expression=cron,
            timezone=timezone,
            jitter_minutes=jitter,
            created_at=datetime.utcnow(),
        )
        session.add(job)
    
    console.print(f"[green]OK[/green] Created schedule: {name}")
    console.print(f"[dim]Type:[/dim] {schedule_type}")
    if time_of_day:
        console.print(f"[dim]Time:[/dim] {time_of_day} ({timezone})")
    console.print(f"[dim]Jitter:[/dim] ±{jitter} minutes")
    console.print(f"[dim]Portals:[/dim] {', '.join(portal_list) if portal_list else 'all'}")


@app.command("pause")
def pause_schedule(
    name: str = typer.Argument(..., help="Schedule name"),
) -> None:
    """Pause a schedule."""
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence.models import ScheduledJob
    from sqlalchemy import select
    
    with get_session() as session:
        stmt = select(ScheduledJob).where(ScheduledJob.name == name)
        job = session.execute(stmt).scalar_one_or_none()
        
        if not job:
            err_console.print(f"[red]Schedule not found:[/red] {name}")
            raise typer.Exit(1)
        
        job.enabled = False
    
    console.print(f"[yellow]||[/yellow] Paused schedule: {name}")


@app.command("resume")
def resume_schedule(
    name: str = typer.Argument(..., help="Schedule name"),
) -> None:
    """Resume a paused schedule."""
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence.models import ScheduledJob
    from sqlalchemy import select
    
    with get_session() as session:
        stmt = select(ScheduledJob).where(ScheduledJob.name == name)
        job = session.execute(stmt).scalar_one_or_none()
        
        if not job:
            err_console.print(f"[red]Schedule not found:[/red] {name}")
            raise typer.Exit(1)
        
        job.enabled = True
    
    console.print(f"[green]>[/green] Resumed schedule: {name}")


@app.command("run-now")
def run_schedule_now(
    name: str = typer.Argument(..., help="Schedule name"),
) -> None:
    """Trigger a scheduled job to run immediately."""
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence.models import ScheduledJob
    from sqlalchemy import select
    
    with get_session() as session:
        stmt = select(ScheduledJob).where(ScheduledJob.name == name)
        job = session.execute(stmt).scalar_one_or_none()
        
        if not job:
            err_console.print(f"[red]Schedule not found:[/red] {name}")
            raise typer.Exit(1)
        
        portals = job.portals_json or []
    
    console.print(f"[bold]Triggering schedule:[/bold] {name}")
    
    # TODO: Implement actual trigger in M3
    console.print("[yellow]Immediate trigger will be implemented in Milestone 3 (M3)[/yellow]")


@app.command("delete")
def delete_schedule(
    name: str = typer.Argument(..., help="Schedule name"),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation",
    ),
) -> None:
    """Delete a schedule."""
    if not force:
        if not typer.confirm(f"Delete schedule '{name}'?"):
            raise typer.Abort()
    
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence.models import ScheduledJob
    from sqlalchemy import select
    
    with get_session() as session:
        stmt = select(ScheduledJob).where(ScheduledJob.name == name)
        job = session.execute(stmt).scalar_one_or_none()
        
        if not job:
            err_console.print(f"[red]Schedule not found:[/red] {name}")
            raise typer.Exit(1)
        
        session.delete(job)
    
    console.print(f"[red]x[/red] Deleted schedule: {name}")


@app.command("start")
def start_scheduler() -> None:
    """Start the background scheduler service.
    
    Runs as a foreground process. Use Ctrl+C to stop.
    """
    console.print("[bold]Starting scheduler service...[/bold]")
    console.print("[dim]Press Ctrl+C to stop[/dim]")
    console.print()
    
    # TODO: Implement scheduler service in M3
    console.print("[yellow]Scheduler service will be implemented in Milestone 3 (M3)[/yellow]")
