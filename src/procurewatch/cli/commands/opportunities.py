"""
Opportunities viewing and export commands.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    help="View and export opportunities",
    no_args_is_help=True,
)


@app.command("list")
def list_opportunities(
    portal: Optional[str] = typer.Option(
        None,
        "--portal",
        "-p",
        help="Filter by portal name",
    ),
    status: Optional[str] = typer.Option(
        None,
        "--status",
        "-s",
        help="Filter by status (OPEN, CLOSED, AWARDED, etc.)",
    ),
    closing_within: Optional[int] = typer.Option(
        None,
        "--closing-within",
        "-c",
        help="Filter by closing within N days",
    ),
    limit: int = typer.Option(
        20,
        "--limit",
        "-n",
        help="Maximum results to show",
    ),
    format: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format (table, json, csv)",
    ),
) -> None:
    """List opportunities with filters.
    
    Examples:
        procurewatch opportunities list --status OPEN --closing-within 7
        procurewatch opportunities list --portal nevadaepro --format json
    """
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence.repo import OpportunityRepository, PortalRepository
    
    with get_session() as session:
        opp_repo = OpportunityRepository(session)
        portal_repo = PortalRepository(session)
        
        # Resolve portal ID if name provided
        portal_id = None
        if portal:
            p = portal_repo.get_by_name(portal)
            if not p:
                err_console.print(f"[red]Portal not found:[/red] {portal}")
                raise typer.Exit(1)
            portal_id = p.id
        
        opportunities = opp_repo.list_opportunities(
            portal_id=portal_id,
            status=status.upper() if status else None,
            closing_within_days=closing_within,
            limit=limit,
        )
        
        if not opportunities:
            console.print("[dim]No opportunities found matching criteria.[/dim]")
            return
        
        if format == "json":
            import json
            data = [
                {
                    "id": o.id,
                    "external_id": o.external_id,
                    "title": o.title,
                    "status": o.status,
                    "agency": o.agency,
                    "closing_at": o.closing_at.isoformat() if o.closing_at else None,
                    "posted_at": o.posted_at.isoformat() if o.posted_at else None,
                    "estimated_value": o.estimated_value,
                    "source_url": o.source_url,
                }
                for o in opportunities
            ]
            console.print_json(json.dumps(data))
            return
        
        if format == "csv":
            import csv
            import sys
            writer = csv.writer(sys.stdout)
            writer.writerow(["id", "external_id", "title", "status", "agency", "closing_at", "estimated_value"])
            for o in opportunities:
                writer.writerow([
                    o.id,
                    o.external_id,
                    o.title[:80] if o.title else "",
                    o.status,
                    o.agency or "",
                    o.closing_at.isoformat() if o.closing_at else "",
                    o.estimated_value or "",
                ])
            return
        
        # Table format
        table = Table(title=f"Opportunities ({len(opportunities)} shown)", show_header=True, header_style="bold magenta")
        table.add_column("ID", style="dim", no_wrap=True)
        table.add_column("Title", max_width=50)
        table.add_column("Status", justify="center")
        table.add_column("Agency", max_width=30)
        table.add_column("Closing", justify="right")
        table.add_column("Value", justify="right")
        
        for opp in opportunities:
            # Status styling
            status_style = {
                "OPEN": "green",
                "CLOSED": "dim",
                "AWARDED": "blue",
                "EXPIRED": "red",
            }.get(opp.status, "yellow")
            
            # Closing date with urgency
            closing_str = "[dim]-[/dim]"
            if opp.closing_at:
                days_until = (opp.closing_at - datetime.utcnow()).days
                if days_until < 0:
                    closing_str = "[dim]Past[/dim]"
                elif days_until <= 3:
                    closing_str = f"[red bold]{days_until}d[/red bold]"
                elif days_until <= 7:
                    closing_str = f"[yellow]{days_until}d[/yellow]"
                else:
                    closing_str = opp.closing_at.strftime("%Y-%m-%d")
            
            # Value formatting
            value_str = "[dim]-[/dim]"
            if opp.estimated_value:
                if opp.estimated_value >= 1_000_000:
                    value_str = f"${opp.estimated_value/1_000_000:.1f}M"
                elif opp.estimated_value >= 1_000:
                    value_str = f"${opp.estimated_value/1_000:.0f}K"
                else:
                    value_str = f"${opp.estimated_value:.0f}"
            
            table.add_row(
                str(opp.id),
                (opp.title[:47] + "...") if opp.title and len(opp.title) > 50 else (opp.title or "[dim]-[/dim]"),
                f"[{status_style}]{opp.status}[/{status_style}]",
                (opp.agency[:27] + "...") if opp.agency and len(opp.agency) > 30 else (opp.agency or "[dim]-[/dim]"),
                closing_str,
                value_str,
            )
        
        console.print(table)


@app.command("show")
def show_opportunity(
    id: int = typer.Argument(..., help="Opportunity ID"),
    show_events: bool = typer.Option(
        False,
        "--events",
        "-e",
        help="Show change history",
    ),
) -> None:
    """Show detailed information about an opportunity."""
    from rich.panel import Panel
    
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence.repo import OpportunityRepository
    
    with get_session() as session:
        repo = OpportunityRepository(session)
        opp = repo.get_by_id(id)
        
        if not opp:
            err_console.print(f"[red]Opportunity not found:[/red] {id}")
            raise typer.Exit(1)
        
        # Main details
        details = f"""[bold]Title:[/bold] {opp.title or '-'}
[bold]External ID:[/bold] {opp.external_id}
[bold]Status:[/bold] {opp.status}
[bold]Portal:[/bold] {opp.portal.name if opp.portal else '-'}

[bold]Agency:[/bold] {opp.agency or '-'}
[bold]Department:[/bold] {opp.department or '-'}
[bold]Location:[/bold] {opp.location or '-'}
[bold]Category:[/bold] {opp.category or '-'}

[bold]Posted:[/bold] {opp.posted_at or '-'}
[bold]Closing:[/bold] {opp.closing_at or '-'}
[bold]Awarded:[/bold] {opp.awarded_at or '-'}

[bold]Estimated Value:[/bold] {f'${opp.estimated_value:,.2f}' if opp.estimated_value else '-'} {opp.estimated_value_currency}
[bold]Award Amount:[/bold] {f'${opp.award_amount:,.2f}' if opp.award_amount else '-'}
[bold]Awardee:[/bold] {opp.awardee or '-'}

[bold]Contact:[/bold] {opp.contact_name or '-'}
[bold]Email:[/bold] {opp.contact_email or '-'}
[bold]Phone:[/bold] {opp.contact_phone or '-'}

[bold]Source URL:[/bold] {opp.source_url or '-'}
[bold]Detail URL:[/bold] {opp.detail_url or '-'}

[bold]Last Seen:[/bold] {opp.last_seen_at}
[bold]Confidence:[/bold] {f'{opp.extraction_confidence:.1%}' if opp.extraction_confidence else '-'}"""
        
        console.print()
        console.print(Panel.fit(details, title=f"[bold cyan]Opportunity #{opp.id}[/bold cyan]", border_style="cyan"))
        
        # Description
        if opp.description:
            console.print()
            console.print(Panel(
                opp.description[:2000] + ("..." if len(opp.description) > 2000 else ""),
                title="[bold]Description[/bold]",
                border_style="dim",
            ))
        
        # Events history
        if show_events:
            events = repo.get_events(opportunity_id=opp.id, limit=20)
            
            if events:
                console.print()
                event_table = Table(title="Change History", show_header=True, header_style="bold magenta")
                event_table.add_column("Date", style="dim")
                event_table.add_column("Event", style="cyan")
                event_table.add_column("Details")
                
                for event in events:
                    details_str = event.message or ""
                    if event.diff:
                        changed_fields = list(event.diff.keys())
                        details_str = f"Changed: {', '.join(changed_fields[:3])}"
                        if len(changed_fields) > 3:
                            details_str += f" (+{len(changed_fields) - 3})"
                    
                    event_table.add_row(
                        event.created_at.strftime("%Y-%m-%d %H:%M"),
                        event.event_type,
                        details_str,
                    )
                
                console.print(event_table)


@app.command("export")
def export_opportunities(
    output: Path = typer.Argument(..., help="Output file path"),
    format: str = typer.Option(
        None,
        "--format",
        "-f",
        help="Output format (inferred from extension if not specified)",
    ),
    portal: Optional[str] = typer.Option(
        None,
        "--portal",
        "-p",
        help="Filter by portal",
    ),
    status: Optional[str] = typer.Option(
        None,
        "--status",
        "-s",
        help="Filter by status",
    ),
    limit: int = typer.Option(
        10000,
        "--limit",
        "-n",
        help="Maximum records to export",
    ),
) -> None:
    """Export opportunities to a file.
    
    Supported formats: csv, json, jsonl
    
    Examples:
        procurewatch opportunities export data/export.csv --status OPEN
        procurewatch opportunities export data/all.json --format json
    """
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence.repo import OpportunityRepository, PortalRepository
    
    # Determine format
    if not format:
        format = output.suffix.lstrip(".").lower()
    
    if format not in ("csv", "json", "jsonl"):
        err_console.print(f"[red]Unsupported format:[/red] {format}")
        err_console.print("[dim]Supported: csv, json, jsonl[/dim]")
        raise typer.Exit(1)
    
    with get_session() as session:
        opp_repo = OpportunityRepository(session)
        portal_repo = PortalRepository(session)
        
        portal_id = None
        if portal:
            p = portal_repo.get_by_name(portal)
            if not p:
                err_console.print(f"[red]Portal not found:[/red] {portal}")
                raise typer.Exit(1)
            portal_id = p.id
        
        opportunities = opp_repo.list_opportunities(
            portal_id=portal_id,
            status=status.upper() if status else None,
            limit=limit,
        )
        
        if not opportunities:
            console.print("[yellow]No opportunities to export.[/yellow]")
            return
        
        # Export based on format
        output.parent.mkdir(parents=True, exist_ok=True)
        
        if format == "csv":
            import csv
            with open(output, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "id", "external_id", "title", "status", "agency",
                    "closing_at", "posted_at", "estimated_value", "source_url",
                ])
                for o in opportunities:
                    writer.writerow([
                        o.id,
                        o.external_id,
                        o.title,
                        o.status,
                        o.agency,
                        o.closing_at.isoformat() if o.closing_at else "",
                        o.posted_at.isoformat() if o.posted_at else "",
                        o.estimated_value or "",
                        o.source_url or "",
                    ])
        
        elif format == "json":
            import json
            data = [
                {
                    "id": o.id,
                    "external_id": o.external_id,
                    "title": o.title,
                    "description": o.description,
                    "status": o.status,
                    "agency": o.agency,
                    "closing_at": o.closing_at.isoformat() if o.closing_at else None,
                    "posted_at": o.posted_at.isoformat() if o.posted_at else None,
                    "estimated_value": o.estimated_value,
                    "source_url": o.source_url,
                    "detail_url": o.detail_url,
                }
                for o in opportunities
            ]
            with open(output, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        
        elif format == "jsonl":
            import json
            with open(output, "w", encoding="utf-8") as f:
                for o in opportunities:
                    data = {
                        "id": o.id,
                        "external_id": o.external_id,
                        "title": o.title,
                        "status": o.status,
                        "agency": o.agency,
                        "closing_at": o.closing_at.isoformat() if o.closing_at else None,
                        "posted_at": o.posted_at.isoformat() if o.posted_at else None,
                        "estimated_value": o.estimated_value,
                    }
                    f.write(json.dumps(data) + "\n")
    
    console.print(f"[green]OK[/green] Exported {len(opportunities)} opportunities to {output}")


@app.command("stats")
def show_stats(
    portal: Optional[str] = typer.Option(
        None,
        "--portal",
        "-p",
        help="Filter by portal",
    ),
) -> None:
    """Show opportunity statistics."""
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence.repo import OpportunityRepository, PortalRepository
    
    with get_session() as session:
        opp_repo = OpportunityRepository(session)
        portal_repo = PortalRepository(session)
        
        portal_id = None
        if portal:
            p = portal_repo.get_by_name(portal)
            if not p:
                err_console.print(f"[red]Portal not found:[/red] {portal}")
                raise typer.Exit(1)
            portal_id = p.id
        
        counts = opp_repo.count_by_status(portal_id=portal_id)
        
        if not counts:
            console.print("[dim]No opportunities found.[/dim]")
            return
        
        table = Table(title="Opportunity Statistics", show_header=True, header_style="bold magenta")
        table.add_column("Status", style="cyan")
        table.add_column("Count", justify="right")
        table.add_column("Percentage", justify="right")
        
        total = sum(counts.values())
        
        for status in ["OPEN", "CLOSED", "AWARDED", "EXPIRED", "CANCELLED", "UNKNOWN"]:
            count = counts.get(status, 0)
            if count > 0:
                pct = count / total * 100
                table.add_row(status, str(count), f"{pct:.1f}%")
        
        table.add_section()
        table.add_row("[bold]Total[/bold]", f"[bold]{total}[/bold]", "[bold]100%[/bold]")
        
        console.print(table)
