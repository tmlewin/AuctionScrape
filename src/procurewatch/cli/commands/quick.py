"""
Quick Mode CLI - AI-powered scraping with zero configuration.

Point at any URL -> Get structured procurement data.
No manual CSS selectors, no YAML configuration needed.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

# Force UTF-8 on Windows to avoid encoding issues
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    name="quick",
    help="AI-powered scraping - point at any URL, get structured data",
    no_args_is_help=True,
)


@app.command(name="scrape")
def quick_scrape(
    url: str = typer.Argument(..., help="URL to scrape"),
    max_pages: int = typer.Option(1, "--max-pages", "-p", help="Maximum pages to scrape"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Save results to JSON file"),
    save_db: bool = typer.Option(False, "--save", "-s", help="Save opportunities to database"),
    provider: Optional[str] = typer.Option(
        None, 
        "--provider", 
        help="LLM provider (e.g., openai/gpt-4o-mini, ollama/llama3.3)"
    ),
    headless: bool = typer.Option(True, "--headless/--headed", help="Run browser headless"),
    generate_config: bool = typer.Option(
        False, 
        "--generate-config", 
        "-g", 
        help="Generate portal YAML config from results"
    ),
) -> None:
    """Scrape ANY URL with AI-powered extraction.
    
    No configuration needed - the AI figures out the page structure
    and extracts procurement opportunities automatically.
    
    Examples:
    
        # Quick scrape Alberta portal
        procurewatch quick scrape https://purchasing.alberta.ca/search
        
        # Scrape and save to database
        procurewatch quick scrape https://tenders.gov.au --save
        
        # Export to JSON
        procurewatch quick scrape https://merx.com -o results.json
        
        # Use local Ollama model (free, no API key)
        procurewatch quick scrape https://example.com --provider ollama/llama3.3
        
        # Generate config for future deterministic scraping
        procurewatch quick scrape https://example.com --generate-config
    """
    asyncio.run(_run_quick_scrape(
        url=url,
        max_pages=max_pages,
        output=output,
        save_db=save_db,
        provider=provider,
        headless=headless,
        generate_config=generate_config,
    ))


async def _run_quick_scrape(
    url: str,
    max_pages: int,
    output: Path | None,
    save_db: bool,
    provider: str | None,
    headless: bool,
    generate_config: bool,
) -> None:
    """Run the quick scrape operation."""
    from procurewatch.core.backends.crawl4ai_backend import (
        Crawl4AIBackend,
        LLMConfig,
        generate_portal_config,
    )
    
    console.print()
    
    # Determine effective provider early for display
    import os
    effective_provider = provider or os.getenv("CRAWL4AI_LLM_PROVIDER", "deepseek/deepseek-chat")
    
    console.print(Panel.fit(
        f"[bold cyan]Quick Scrape[/bold cyan]\n\n"
        f"URL: [yellow]{url}[/yellow]\n"
        f"Max Pages: {max_pages}\n"
        f"LLM Provider: {effective_provider}",
        title="[bold]AI-Powered Extraction[/bold]",
        border_style="cyan",
    ))
    console.print()
    
    # Check for API key based on provider
    
    api_key_found = False
    if effective_provider.startswith("deepseek"):
        api_key = os.getenv("DEEPSEEK_API_KEY")
        api_key_found = bool(api_key) and api_key != "your-deepseek-api-key-here"
        if not api_key_found:
            err_console.print(
                "[yellow]DEEPSEEK_API_KEY not set.[/yellow]\n\n"
                "[bold]To get your free DeepSeek API key:[/bold]\n"
                "  1. Go to: [cyan]https://platform.deepseek.com/[/cyan]\n"
                "  2. Sign up (email or Google)\n"
                "  3. Go to 'API Keys' in sidebar\n"
                "  4. Click 'Create new API key'\n"
                "  5. Paste in .env file as DEEPSEEK_API_KEY=sk-...\n\n"
                "[green]DeepSeek is FREE to start with generous limits![/green]\n\n"
                "[dim]Alternative: Use Ollama (free, local):[/dim]\n"
                "  [cyan]--provider ollama/llama3.3[/cyan]"
            )
            raise typer.Exit(1)
    elif effective_provider.startswith("gemini"):
        api_key_found = bool(os.getenv("GEMINI_API_KEY"))
        if not api_key_found:
            err_console.print(
                "[yellow]GEMINI_API_KEY not set.[/yellow]\n\n"
                "[bold]To get your free Gemini API key:[/bold]\n"
                "  1. Go to: [cyan]https://aistudio.google.com[/cyan]\n"
                "  2. Click 'Get API key' then 'Create API key'\n"
                "  3. Copy the key\n\n"
                "[bold]Then set it:[/bold]\n"
                "  Windows: [cyan]set GEMINI_API_KEY=your-key-here[/cyan]\n"
                "  Linux/Mac: [cyan]export GEMINI_API_KEY=your-key-here[/cyan]\n\n"
                "[dim]Alternative: Use DeepSeek (recommended, free):[/dim]\n"
                "  [cyan]--provider deepseek/deepseek-chat[/cyan]"
            )
            raise typer.Exit(1)
    elif effective_provider.startswith("openai"):
        api_key_found = bool(os.getenv("OPENAI_API_KEY"))
        if not api_key_found:
            err_console.print(
                "[yellow]OPENAI_API_KEY not set.[/yellow]\n"
                "Set it with: [cyan]set OPENAI_API_KEY=your-key[/cyan]\n"
                "Or use DeepSeek (free): [cyan]--provider deepseek/deepseek-chat[/cyan]"
            )
            raise typer.Exit(1)
    elif effective_provider.startswith("ollama"):
        api_key_found = True  # Ollama doesn't need a key
    elif effective_provider.startswith("groq"):
        api_key_found = bool(os.getenv("GROQ_API_KEY"))
        if not api_key_found:
            err_console.print(
                "[yellow]GROQ_API_KEY not set.[/yellow]\n"
                "Get free key at: [cyan]https://console.groq.com/[/cyan]\n"
                "Or use DeepSeek (free): [cyan]--provider deepseek/deepseek-chat[/cyan]"
            )
            raise typer.Exit(1)
    
    # Configure LLM
    llm_config = LLMConfig.from_env()
    if provider:
        llm_config.provider = provider
    
    all_opportunities: list[dict] = []
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Initializing AI crawler...", total=None)
        
        try:
            async with Crawl4AIBackend(
                llm_config=llm_config,
                headless=headless,
                timeout=60,
            ) as backend:
                progress.update(task, description=f"[cyan]Extracting from {url}...")
                
                result = await backend.extract_opportunities(url)
                
                if result.error:
                    progress.stop()
                    err_console.print(f"\n[red]Error:[/red] {result.error}")
                    raise typer.Exit(1)
                
                all_opportunities.extend(result.opportunities)
                
                progress.update(
                    task,
                    description=f"[green]Extracted {len(result.opportunities)} opportunities",
                    completed=True,
                )
                
        except Exception as e:
            progress.stop()
            err_console.print(f"\n[red]Error:[/red] {e}")
            raise typer.Exit(1)
    
    console.print()
    
    if not all_opportunities:
        console.print("[yellow]No opportunities found on this page.[/yellow]")
        console.print("\nPossible reasons:")
        console.print("  - The page might not contain procurement data")
        console.print("  - The AI might need a different instruction")
        console.print("  - The page might require authentication")
        raise typer.Exit(0)
    
    # Display results
    _display_opportunities(all_opportunities, result)
    
    # Save to JSON if requested
    if output:
        output.write_text(
            json.dumps(all_opportunities, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        console.print(f"\n[green]Saved {len(all_opportunities)} opportunities to {output}[/green]")
    
    # Save to database if requested
    if save_db:
        count = await _save_to_database(all_opportunities, url)
        console.print(f"\n[green]Saved {count} opportunities to database[/green]")
    
    # Generate config if requested
    if generate_config:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        portal_name = parsed.netloc.replace(".", "_").replace("-", "_")
        
        config_path = Path(f"configs/portals/{portal_name}.yaml")
        yaml_content = await generate_portal_config(url, portal_name, str(config_path))
        
        console.print(f"\n[green]Generated portal config: {config_path}[/green]")
        console.print("[dim]You can now use this for deterministic scraping:[/dim]")
        console.print(f"  [cyan]procurewatch scrape run --portal {portal_name}[/cyan]")


def _display_opportunities(opportunities: list[dict], result) -> None:
    """Display extracted opportunities in a table."""
    from rich.text import Text
    
    # Summary panel
    console.print(Panel.fit(
        f"[bold green]Extracted {len(opportunities)} opportunities[/bold green]\n\n"
        f"Method: [cyan]{result.method}[/cyan]\n"
        f"Confidence: [{'green' if result.confidence > 0.7 else 'yellow'}]{result.confidence:.1%}[/]\n"
        f"Time: {result.elapsed_ms/1000:.1f}s",
        title="[bold]Extraction Results[/bold]",
        border_style="green",
    ))
    console.print()
    
    # Results table
    table = Table(
        title="Opportunities",
        show_header=True,
        header_style="bold magenta",
        show_lines=True,
        expand=True,
    )
    
    table.add_column("#", style="dim", width=3)
    table.add_column("Title", style="cyan", max_width=40, overflow="fold")
    table.add_column("ID", style="yellow", max_width=15)
    table.add_column("Agency", max_width=20, overflow="fold")
    table.add_column("Status", justify="center", max_width=10)
    table.add_column("Closes", justify="right", max_width=12)
    table.add_column("Posted", justify="right", max_width=12)
    
    for i, opp in enumerate(opportunities[:20], 1):  # Show first 20
        title = opp.get("title", "N/A") or "N/A"
        if len(title) > 40:
            title = title[:37] + "..."
        
        # Format status with color
        status = opp.get("status", "") or ""
        if status.lower() in ("open", "active"):
            status = f"[green]{status}[/green]"
        elif status.lower() in ("closed", "expired"):
            status = f"[red]{status}[/red]"
        
        table.add_row(
            str(i),
            title,
            opp.get("external_id", "") or "-",
            opp.get("agency", "") or "-",
            status or "-",
            opp.get("closing_at", "") or "-",
            opp.get("posted_at", "") or "-",
        )
    
    console.print(table)
    
    if len(opportunities) > 20:
        console.print(f"\n[dim]... and {len(opportunities) - 20} more opportunities[/dim]")
    
    # Show sample of first opportunity with all fields
    console.print()
    console.print("[bold]Sample opportunity (all fields):[/bold]")
    sample = opportunities[0]
    for key, value in sample.items():
        if value:
            console.print(f"  [cyan]{key}:[/cyan] {value}")


async def _save_to_database(opportunities: list[dict], source_url: str) -> int:
    """Save opportunities to the database."""
    from urllib.parse import urlparse
    
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence.repo import PortalRepository, OpportunityRepository
    from procurewatch.persistence.models import Portal, Opportunity
    
    parsed = urlparse(source_url)
    portal_name = f"quick_{parsed.netloc.replace('.', '_')}"
    
    saved_count = 0
    
    with get_session() as session:
        portal_repo = PortalRepository(session)
        opp_repo = OpportunityRepository(session)
        
        # Get or create portal
        portal = portal_repo.get_by_name(portal_name)
        if not portal:
            portal = Portal(
                name=portal_name,
                display_name=f"Quick Scrape - {parsed.netloc}",
                base_url=f"{parsed.scheme}://{parsed.netloc}",
                portal_type="crawl4ai",
                config_yaml=f"# Auto-generated from quick scrape\nseed_urls:\n  - {source_url}",
                enabled=True,
            )
            session.add(portal)
            session.flush()
        
        # Save opportunities
        for opp_data in opportunities:
            # Generate external_id if not present
            external_id = opp_data.get("external_id")
            if not external_id:
                # Use hash of title + closing date as fallback ID
                import hashlib
                hash_input = f"{opp_data.get('title', '')}{opp_data.get('closing_at', '')}"
                external_id = hashlib.md5(hash_input.encode()).hexdigest()[:12]
            
            # Check if already exists
            existing = opp_repo.get_by_external_id(portal.id, external_id)
            if existing:
                continue
            
            # Create opportunity
            opportunity = Opportunity(
                portal_id=portal.id,
                external_id=external_id,
                title=opp_data.get("title", "Unknown"),
                agency=opp_data.get("agency"),
                status=opp_data.get("status"),
                posted_at=_parse_date(opp_data.get("posted_at")),
                closing_at=_parse_date(opp_data.get("closing_at")),
                description=opp_data.get("description"),
                detail_url=opp_data.get("detail_url"),
                category=opp_data.get("category"),
                value_text=opp_data.get("value"),
                contact_name=opp_data.get("contact_name"),
                contact_email=opp_data.get("contact_email"),
                contact_phone=opp_data.get("contact_phone"),
                raw_data=opp_data,
            )
            session.add(opportunity)
            saved_count += 1
        
        # Update portal stats
        portal.last_scraped_at = datetime.utcnow()
        portal.total_opportunities = opp_repo.count_by_portal(portal.id)
        
        session.commit()
    
    return saved_count


def _parse_date(date_str: str | None) -> datetime | None:
    """Try to parse a date string."""
    if not date_str:
        return None
    
    try:
        import dateparser
        return dateparser.parse(date_str)
    except Exception:
        return None


@app.command(name="test")
def quick_test(
    url: str = typer.Argument(..., help="URL to test"),
    provider: Optional[str] = typer.Option(
        None,
        "--provider",
        help="LLM provider (e.g., openai/gpt-4o-mini, ollama/llama3.3)"
    ),
) -> None:
    """Test AI extraction on a URL without saving.
    
    Quick way to check if a URL can be scraped.
    
    Example:
        procurewatch quick test https://purchasing.alberta.ca/search
    """
    asyncio.run(_run_quick_test(url, provider))


async def _run_quick_test(url: str, provider: str | None) -> None:
    """Run quick test."""
    from procurewatch.core.backends.crawl4ai_backend import Crawl4AIBackend, LLMConfig
    
    console.print(f"\n[cyan]Testing extraction on:[/cyan] {url}\n")
    
    llm_config = LLMConfig.from_env()
    if provider:
        llm_config.provider = provider
    
    with console.status("[bold cyan]Extracting with AI..."):
        async with Crawl4AIBackend(llm_config=llm_config, headless=True) as backend:
            result = await backend.extract_opportunities(url)
    
    if result.error:
        console.print(f"[red]Failed:[/red] {result.error}")
        raise typer.Exit(1)
    
    console.print(f"[green]Success![/green]")
    console.print(f"  Opportunities found: [cyan]{len(result.opportunities)}[/cyan]")
    console.print(f"  Extraction method: [cyan]{result.method}[/cyan]")
    console.print(f"  Confidence: [cyan]{result.confidence:.1%}[/cyan]")
    console.print(f"  Time: [cyan]{result.elapsed_ms/1000:.1f}s[/cyan]")
    
    if result.opportunities:
        console.print("\n[bold]First opportunity:[/bold]")
        for key, value in result.opportunities[0].items():
            if value:
                console.print(f"  {key}: {value}")


@app.command(name="promote")
def quick_promote(
    portal_name: str = typer.Argument(..., help="Portal name from quick scrape"),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Output path for YAML config"
    ),
) -> None:
    """Promote a quick-scraped portal to a full configuration.
    
    Generates a YAML config file that can be used for scheduled,
    deterministic scraping.
    
    Example:
        procurewatch quick promote quick_purchasing_alberta_ca
    """
    from procurewatch.persistence.db import get_session
    from procurewatch.persistence.repo import PortalRepository
    
    with get_session() as session:
        repo = PortalRepository(session)
        portal = repo.get_by_name(portal_name)
        
        if not portal:
            err_console.print(f"[red]Portal not found:[/red] {portal_name}")
            raise typer.Exit(1)
        
        # Generate config
        output_path = output or Path(f"configs/portals/{portal_name.replace('quick_', '')}.yaml")
        
        config_content = f'''# Portal configuration promoted from quick scrape
# Original: {portal.display_name}
# Promoted at: {datetime.utcnow().isoformat()}

name: {portal_name.replace("quick_", "")}
display_name: "{portal.display_name.replace('Quick Scrape - ', '')}"
base_url: "{portal.base_url}"
portal_type: crawl4ai

seed_urls:
  - "{portal.base_url}"

backend:
  preferred: crawl4ai
  fallbacks: [playwright]
  
  crawl4ai:
    headless: true
    timeout_seconds: 60
    enable_stealth: true

politeness:
  concurrency: 1
  min_delay_ms: 2000
  max_delay_ms: 4000

discovery:
  pagination:
    type: auto
    max_pages: 10
  follow_detail_pages: true

extraction:
  mode: llm

enabled: true
tags:
  - promoted-from-quick
'''
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(config_content, encoding="utf-8")
        
        console.print(f"[green]Promoted portal config saved to:[/green] {output_path}")
        console.print("\nYou can now use standard scraping commands:")
        console.print(f"  [cyan]procurewatch scrape run --portal {portal_name.replace('quick_', '')}[/cyan]")
