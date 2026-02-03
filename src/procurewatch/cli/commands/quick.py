"""
Quick Mode CLI - AI-powered scraping with zero configuration.

Point at any URL -> Get structured procurement data.
No manual CSS selectors, no YAML configuration needed.

Features:
- Multi-page pagination (auto-detect Next, Load More, Infinite Scroll)
- Advanced search/filter criteria (keywords, date range, categories)
- Deep scrape (follow detail page links for full descriptions)
- Config-driven parameters (max_pages, filters, search terms)
- Robust error handling with retry logic and rate limiting
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
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

# Force UTF-8 on Windows to avoid encoding issues
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    # Reconfigure stdout/stderr to use UTF-8 with error replacement
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

console = Console(force_terminal=True)
err_console = Console(stderr=True, force_terminal=True)

app = typer.Typer(
    name="quick",
    help="AI-powered scraping - point at any URL, get structured data",
    no_args_is_help=True,
)


@app.command(name="scrape")
def quick_scrape(
    url: str = typer.Argument(..., help="URL to scrape"),
    # Pagination options
    max_pages: int = typer.Option(1, "--max-pages", "-p", help="Maximum pages to scrape"),
    pagination: Optional[str] = typer.Option(
        None,
        "--pagination",
        help="Pagination type: auto, click_next, load_more, infinite_scroll, none",
    ),
    next_selector: Optional[str] = typer.Option(
        None,
        "--next-selector",
        help="Custom CSS selector for Next button",
    ),
    # Search/filter options
    keywords: Optional[str] = typer.Option(
        None,
        "--keywords", "-k",
        help="Comma-separated keywords to filter by",
    ),
    status: Optional[str] = typer.Option(
        None,
        "--status",
        help="Status filter (open, closed, awarded)",
    ),
    categories: Optional[str] = typer.Option(
        None,
        "--categories",
        help="Comma-separated category filters",
    ),
    since_days: Optional[int] = typer.Option(
        None,
        "--since",
        help="Only opportunities posted within N days",
    ),
    closing_within: Optional[int] = typer.Option(
        None,
        "--closing-within",
        help="Only opportunities closing within N days",
    ),
    location: Optional[str] = typer.Option(
        None,
        "--location",
        help="Geographic location filter",
    ),
    min_value: Optional[float] = typer.Option(
        None,
        "--min-value",
        help="Minimum opportunity value",
    ),
    max_value: Optional[float] = typer.Option(
        None,
        "--max-value",
        help="Maximum opportunity value",
    ),
    # Deep scrape options
    deep_scrape: bool = typer.Option(
        False,
        "--deep/--no-deep",
        help="Follow detail page links for full descriptions",
    ),
    max_details: int = typer.Option(
        50,
        "--max-details",
        help="Maximum detail pages to scrape",
    ),
    # Output options
    output: Optional[Path] = typer.Option(
        None, "--output", "-o",
        help="Save results to JSON file",
    ),
    save_db: bool = typer.Option(
        False, "--save", "-s",
        help="Save opportunities to database",
    ),
    # Provider options
    provider: Optional[str] = typer.Option(
        None,
        "--provider",
        help="LLM provider (e.g., groq/llama-3.3-70b-versatile, ollama/llama3.3)",
    ),
    provider_prompt: bool = typer.Option(
        False,
        "--provider-prompt",
        help="Interactively select LLM provider",
    ),
    headless: bool = typer.Option(
        True,
        "--headless/--headed",
        help="Run browser headless",
    ),
    # Advanced options
    delay: int = typer.Option(
        2000,
        "--delay",
        help="Delay between pages in milliseconds",
    ),
    retries: int = typer.Option(
        3,
        "--retries",
        help="Maximum retry attempts on failure",
    ),
    stop_on_error: bool = typer.Option(
        False,
        "--stop-on-error",
        help="Stop scraping on first error",
    ),
    generate_config: bool = typer.Option(
        False,
        "--generate-config", "-g",
        help="Generate portal YAML config from results",
    ),
) -> None:
    """Scrape ANY URL with AI-powered extraction.
    
    No configuration needed - the AI figures out the page structure
    and extracts procurement opportunities automatically.
    
    \b
    EXAMPLES:
    
    # Basic single-page scrape
    procurewatch quick scrape https://purchasing.alberta.ca/search
    
    # Multi-page scrape with auto-pagination
    procurewatch quick scrape https://tenders.gov.au --max-pages 5
    
    # Search with filters
    procurewatch quick scrape https://merx.com --keywords "IT,software" --status open
    
    # Deep scrape with full descriptions
    procurewatch quick scrape https://example.com --deep --max-pages 3
    
    # Scrape with date filters
    procurewatch quick scrape https://example.com --since 30 --closing-within 14
    
    # Export to JSON and save to database
    procurewatch quick scrape https://example.com -o results.json --save
    
    # Use Groq (FREE) with multiple pages
    procurewatch quick scrape https://example.com --provider groq/llama-3.3-70b-versatile -p 10
    """
    asyncio.run(_run_quick_scrape(
        url=url,
        max_pages=max_pages,
        pagination=pagination,
        next_selector=next_selector,
        keywords=keywords,
        status=status,
        categories=categories,
        since_days=since_days,
        closing_within=closing_within,
        location=location,
        min_value=min_value,
        max_value=max_value,
        deep_scrape=deep_scrape,
        max_details=max_details,
        output=output,
        save_db=save_db,
        provider=provider,
        provider_prompt=provider_prompt,
        headless=headless,
        delay=delay,
        retries=retries,
        stop_on_error=stop_on_error,
        generate_config=generate_config,
    ))


async def _run_quick_scrape(
    url: str,
    max_pages: int,
    pagination: str | None,
    next_selector: str | None,
    keywords: str | None,
    status: str | None,
    categories: str | None,
    since_days: int | None,
    closing_within: int | None,
    location: str | None,
    min_value: float | None,
    max_value: float | None,
    deep_scrape: bool,
    max_details: int,
    output: Path | None,
    save_db: bool,
    provider: str | None,
    provider_prompt: bool,
    headless: bool,
    delay: int,
    retries: int,
    stop_on_error: bool,
    generate_config: bool,
) -> None:
    """Run the quick scrape operation."""
    from procurewatch.core.backends.crawl4ai_backend import (
        Crawl4AIBackend,
        LLMConfig,
        QuickModeConfig,
        QuickPaginationType,
        QuickSearchFilter,
        generate_portal_config,
    )
    
    console.print()
    
    # Determine effective provider early for display
    env_provider = os.getenv("CRAWL4AI_LLM_PROVIDER", "deepseek/deepseek-chat")
    effective_provider = provider or env_provider

    if provider_prompt and not provider:
        choices = [
            "deepseek/deepseek-chat",
            "groq/llama-3.3-70b-versatile",
            "gemini/gemini-1.5-pro",
            "openai/gpt-4o-mini",
            "ollama/llama3.3",
        ]
        console.print("\n[bold]Select LLM provider:[/bold]")
        for index, choice in enumerate(choices, 1):
            label = "[dim] (default)[/dim]" if choice == env_provider else ""
            console.print(f"  {index}. {choice}{label}")
        selection = typer.prompt("Enter choice number", default="1")
        try:
            selection_index = int(selection) - 1
            if 0 <= selection_index < len(choices):
                effective_provider = choices[selection_index]
        except ValueError:
            pass
    
    # Build feature list for display
    features = []
    if max_pages > 1:
        features.append(f"[cyan]{max_pages}[/cyan] pages")
    if deep_scrape:
        features.append("[green]deep scrape[/green]")
    if keywords:
        features.append(f"keywords: [yellow]{keywords}[/yellow]")
    if status:
        features.append(f"status: [yellow]{status}[/yellow]")
    if since_days:
        features.append(f"since [yellow]{since_days}d[/yellow]")
    if closing_within:
        features.append(f"closing within [yellow]{closing_within}d[/yellow]")
    
    feature_str = ", ".join(features) if features else "single page"
    
    console.print(Panel.fit(
        f"[bold cyan]Quick Scrape[/bold cyan]\n\n"
        f"URL: [yellow]{url}[/yellow]\n"
        f"Mode: {feature_str}\n"
        f"LLM Provider: {effective_provider}",
        title="[bold]AI-Powered Multi-Page Extraction[/bold]",
        border_style="cyan",
    ))
    console.print()
    
    # Check for API key based on provider
    if not _check_api_key(effective_provider):
        raise typer.Exit(1)
    
    # Build configuration
    pagination_type = QuickPaginationType.AUTO
    if pagination:
        try:
            pagination_type = QuickPaginationType(pagination.lower())
        except ValueError:
            err_console.print(f"[red]Invalid pagination type:[/red] {pagination}")
            err_console.print("Valid options: auto, click_next, load_more, infinite_scroll, none")
            raise typer.Exit(1)
    
    # Build search filters
    search_filter = QuickSearchFilter(
        keywords=[k.strip() for k in keywords.split(",")] if keywords else [],
        status=[s.strip() for s in status.split(",")] if status else [],
        categories=[c.strip() for c in categories.split(",")] if categories else [],
        since_days=since_days,
        closing_within_days=closing_within,
        location=location,
        min_value=min_value,
        max_value=max_value,
    )
    
    # Build quick mode config
    quick_config = QuickModeConfig(
        max_pages=max_pages,
        pagination_type=pagination_type,
        next_button_selector=next_selector,
        follow_detail_pages=deep_scrape,
        max_detail_pages=max_details,
        filters=search_filter,
        delay_between_pages_ms=delay,
        max_retries=retries,
        stop_on_error=stop_on_error,
    )
    
    # Configure LLM
    llm_config = LLMConfig.from_env()
    if effective_provider:
        llm_config.provider = effective_provider
    
    # Progress tracking
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Initializing AI crawler...", total=max_pages)
        
        def update_progress(page: int, total_opps: int, errors: int) -> None:
            status = f"[cyan]Page {page}/{max_pages} - {total_opps} opportunities"
            if errors:
                status += f" - [yellow]{errors} errors[/yellow]"
            progress.update(task, completed=page, description=status)
        
        try:
            async with Crawl4AIBackend(
                llm_config=llm_config,
                headless=headless,
                timeout=60,
            ) as backend:
                progress.update(task, description=f"[cyan]Extracting from {url}...")
                
                # Use multi-page extraction
                result = await backend.extract_multi_page(
                    url=url,
                    config=quick_config,
                    progress_callback=update_progress,
                )
                
                if result.errors and len(result.opportunities) == 0:
                    progress.stop()
                    err_console.print(f"\n[red]Extraction failed:[/red]")
                    for error in result.errors[:5]:
                        err_console.print(f"  - {error}")
                    raise typer.Exit(1)
                
                progress.update(
                    task,
                    completed=result.pages_scraped,
                    description=f"[green]Extracted {len(result.opportunities)} opportunities",
                )
                
        except Exception as e:
            progress.stop()
            err_console.print(f"\n[red]Error:[/red] {e}")
            raise typer.Exit(1)
    
    console.print()
    
    if not result.opportunities:
        console.print("[yellow]No opportunities found.[/yellow]")
        console.print("\nPossible reasons:")
        console.print("  - The page might not contain procurement data")
        console.print("  - Filters may be too restrictive")
        console.print("  - The AI might need a different instruction")
        console.print("  - The page might require authentication")
        raise typer.Exit(0)
    
    # Display results
    _display_multi_page_results(result)
    
    # Save to JSON if requested
    if output:
        output.write_text(
            json.dumps(result.opportunities, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        console.print(f"\n[green]Saved {len(result.opportunities)} opportunities to {output}[/green]")
    
    # Save to database if requested
    if save_db:
        count = await _save_to_database(result.opportunities, url)
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


def _check_api_key(provider: str) -> bool:
    """Check if the required API key is set for the provider."""
    if provider.startswith("deepseek"):
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key or api_key == "your-deepseek-api-key-here":
            err_console.print(
                "[yellow]DEEPSEEK_API_KEY not set.[/yellow]\n\n"
                "[bold]To get your free DeepSeek API key:[/bold]\n"
                "  1. Go to: [cyan]https://platform.deepseek.com/[/cyan]\n"
                "  2. Sign up (email or Google)\n"
                "  3. Go to 'API Keys' in sidebar\n"
                "  4. Click 'Create new API key'\n"
                "  5. Paste in .env file as DEEPSEEK_API_KEY=sk-...\n\n"
                "[green]DeepSeek is FREE to start with generous limits![/green]\n\n"
                "[dim]Alternative: Use Groq (free):[/dim]\n"
                "  [cyan]--provider groq/llama-3.3-70b-versatile[/cyan]"
            )
            return False
    elif provider.startswith("gemini"):
        if not os.getenv("GEMINI_API_KEY"):
            err_console.print(
                "[yellow]GEMINI_API_KEY not set.[/yellow]\n\n"
                "[bold]To get your free Gemini API key:[/bold]\n"
                "  1. Go to: [cyan]https://aistudio.google.com[/cyan]\n"
                "  2. Click 'Get API key' then 'Create API key'\n"
                "  3. Copy the key\n\n"
                "[dim]Alternative: Use Groq (free):[/dim]\n"
                "  [cyan]--provider groq/llama-3.3-70b-versatile[/cyan]"
            )
            return False
    elif provider.startswith("openai"):
        if not os.getenv("OPENAI_API_KEY"):
            err_console.print(
                "[yellow]OPENAI_API_KEY not set.[/yellow]\n"
                "Set it with: [cyan]set OPENAI_API_KEY=your-key[/cyan]\n"
                "Or use Groq (free): [cyan]--provider groq/llama-3.3-70b-versatile[/cyan]"
            )
            return False
    elif provider.startswith("groq"):
        if not os.getenv("GROQ_API_KEY"):
            err_console.print(
                "[yellow]GROQ_API_KEY not set.[/yellow]\n"
                "Get free key at: [cyan]https://console.groq.com/[/cyan]\n"
                "Or use DeepSeek (free): [cyan]--provider deepseek/deepseek-chat[/cyan]"
            )
            return False
    # Ollama doesn't need a key
    
    return True


def _display_multi_page_results(result) -> None:
    """Display multi-page extraction results."""
    from rich.text import Text
    
    # Build status color
    if result.pages_failed == 0:
        status_color = "green"
        status_text = "Success"
    elif result.pages_scraped > result.pages_failed:
        status_color = "yellow"
        status_text = "Partial"
    else:
        status_color = "red"
        status_text = "Failed"
    
    # Summary panel
    summary_lines = [
        f"[bold {status_color}]{len(result.opportunities)} opportunities extracted[/bold {status_color}]",
        "",
        f"Pages scraped: [cyan]{result.pages_scraped}[/cyan]/{result.total_pages}",
    ]
    
    if result.pages_failed > 0:
        summary_lines.append(f"Pages failed: [red]{result.pages_failed}[/red]")
    
    if result.detail_pages_scraped > 0:
        summary_lines.append(f"Detail pages: [cyan]{result.detail_pages_scraped}[/cyan]")
    
    # NEW: Show pre-flight analysis metadata
    if result.total_records_detected:
        summary_lines.append(
            f"Total records detected: [bold cyan]{result.total_records_detected:,}[/bold cyan]"
        )
        if result.records_per_page_detected:
            estimated_pages = (result.total_records_detected + result.records_per_page_detected - 1) // result.records_per_page_detected
            summary_lines.append(
                f"  [dim]({result.records_per_page_detected} per page, ~{estimated_pages} pages total)[/dim]"
            )
    
    if result.page_type_detected:
        summary_lines.append(f"Page type: [cyan]{result.page_type_detected}[/cyan]")
    
    if result.form_auto_clicked:
        summary_lines.append("[yellow]Search form auto-clicked[/yellow]")
    
    summary_lines.extend([
        "",
        f"Pagination: [cyan]{result.pagination_type_detected}[/cyan]",
        f"Avg confidence: [{'green' if result.avg_confidence > 0.7 else 'yellow'}]{result.avg_confidence:.1%}[/]",
        f"Time: {result.total_elapsed_ms/1000:.1f}s",
    ])
    
    if result.preflight_analysis_ms > 0:
        summary_lines.append(f"  [dim](pre-flight: {result.preflight_analysis_ms:.0f}ms)[/dim]")
    
    if result.stopped_reason:
        summary_lines.append(f"\nStopped: [dim]{result.stopped_reason}[/dim]")
    
    console.print(Panel.fit(
        "\n".join(summary_lines),
        title=f"[bold]Extraction Results - {status_text}[/bold]",
        border_style=status_color,
    ))
    console.print()
    
    # Show warnings if any
    if result.warnings:
        for warning in result.warnings[:3]:
            console.print(f"[yellow]Warning:[/yellow] {warning}")
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
    
    for i, opp in enumerate(result.opportunities[:25], 1):  # Show first 25
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
    
    if len(result.opportunities) > 25:
        console.print(f"\n[dim]... and {len(result.opportunities) - 25} more opportunities[/dim]")
    
    # Show sample of first opportunity with all fields
    console.print()
    console.print("[bold]Sample opportunity (all fields):[/bold]")
    sample = result.opportunities[0]
    for key, value in sample.items():
        if value:
            # Truncate long values
            display_value = str(value)
            if len(display_value) > 100:
                display_value = display_value[:97] + "..."
            console.print(f"  [cyan]{key}:[/cyan] {display_value}")


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
        help="LLM provider (e.g., groq/llama-3.3-70b-versatile)",
    ),
    max_pages: int = typer.Option(1, "--max-pages", "-p", help="Pages to test"),
) -> None:
    """Test AI extraction on a URL without saving.
    
    Quick way to check if a URL can be scraped and test pagination.
    
    Example:
        procurewatch quick test https://purchasing.alberta.ca/search
        procurewatch quick test https://example.com --max-pages 3
    """
    asyncio.run(_run_quick_test(url, provider, max_pages))


async def _run_quick_test(url: str, provider: str | None, max_pages: int) -> None:
    """Run quick test."""
    from procurewatch.core.backends.crawl4ai_backend import (
        Crawl4AIBackend,
        LLMConfig,
        QuickModeConfig,
    )
    
    console.print(f"\n[cyan]Testing extraction on:[/cyan] {url}")
    console.print(f"[cyan]Max pages:[/cyan] {max_pages}\n")
    
    llm_config = LLMConfig.from_env()
    if provider:
        llm_config.provider = provider
    
    quick_config = QuickModeConfig(max_pages=max_pages)
    
    with console.status("[bold cyan]Extracting with AI..."):
        async with Crawl4AIBackend(llm_config=llm_config, headless=True) as backend:
            if max_pages > 1:
                result = await backend.extract_multi_page(url, quick_config)
                console.print(f"[green]Success![/green]")
                console.print(f"  Pages scraped: [cyan]{result.pages_scraped}[/cyan]")
                console.print(f"  Opportunities found: [cyan]{len(result.opportunities)}[/cyan]")
                console.print(f"  Pagination detected: [cyan]{result.pagination_type_detected}[/cyan]")
                console.print(f"  Avg confidence: [cyan]{result.avg_confidence:.1%}[/cyan]")
                console.print(f"  Time: [cyan]{result.total_elapsed_ms/1000:.1f}s[/cyan]")
                
                if result.stopped_reason:
                    console.print(f"  Stopped: [yellow]{result.stopped_reason}[/yellow]")
                
                if result.opportunities:
                    console.print("\n[bold]First opportunity:[/bold]")
                    for key, value in result.opportunities[0].items():
                        if value:
                            display = str(value)[:80]
                            console.print(f"  {key}: {display}")
            else:
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
