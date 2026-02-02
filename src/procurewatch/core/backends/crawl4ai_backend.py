"""
Crawl4AI Backend - AI-powered extraction without manual CSS selectors.

This backend uses Crawl4AI with LLM extraction strategies to automatically
extract structured data from ANY procurement website without manual configuration.

Key features:
- LLM-based schema inference (works on any site structure)
- Auto-generates CSS schemas for reuse (reduces LLM costs)
- Clean markdown extraction for descriptions
- JavaScript rendering via Playwright
- Stealth mode for bot detection avoidance
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from procurewatch.core.backends.base import (
    Backend,
    BackendError,
    FetchResult,
    RenderResult,
    RequestSpec,
)

if TYPE_CHECKING:
    from crawl4ai import AsyncWebCrawler, CrawlResult

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Schema for Procurement Opportunities
# =============================================================================

class OpportunitySchema(BaseModel):
    """Schema for extracted procurement opportunities.
    
    This schema tells the LLM what fields to extract.
    """
    
    title: str = Field(..., description="Title or name of the procurement/tender")
    external_id: str | None = Field(
        None, description="Unique identifier, tender number, solicitation ID, or reference number"
    )
    agency: str | None = Field(
        None, description="Issuing agency, department, ministry, or organization"
    )
    category: str | None = Field(
        None, description="Type or category of procurement (e.g., construction, IT, services)"
    )
    status: str | None = Field(
        None, description="Status of the tender (e.g., open, closed, awarded, cancelled)"
    )
    posted_at: str | None = Field(
        None, description="Publication or posting date in any format"
    )
    closing_at: str | None = Field(
        None, description="Bid deadline, closing date, or due date in any format"
    )
    opening_at: str | None = Field(
        None, description="Bid opening date if shown"
    )
    description: str | None = Field(
        None, description="Brief description or summary of the opportunity"
    )
    detail_url: str | None = Field(
        None, description="URL or link to the full details page"
    )
    value: str | None = Field(
        None, description="Estimated value, budget, or contract amount"
    )
    location: str | None = Field(
        None, description="Geographic location or region"
    )
    contact_name: str | None = Field(None, description="Contact person name")
    contact_email: str | None = Field(None, description="Contact email address")
    contact_phone: str | None = Field(None, description="Contact phone number")


@dataclass
class Crawl4AIResult:
    """Result from Crawl4AI extraction."""
    
    url: str
    opportunities: list[dict[str, Any]]
    markdown: str | None
    html: str
    method: str  # "llm" or "css_schema"
    confidence: float
    token_usage: dict[str, int] | None
    elapsed_ms: float
    error: str | None = None


@dataclass
class LLMConfig:
    """Configuration for LLM extraction."""
    
    provider: str = "deepseek/deepseek-chat"  # Default to DeepSeek (free, high quality)
    api_token: str | None = None
    temperature: float = 0.0  # Deterministic
    max_tokens: int = 4000
    
    # For local models (Ollama)
    base_url: str | None = None
    
    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Create config from environment variables.
        
        Supported providers and their environment variables:
        - deepseek/deepseek-chat -> DEEPSEEK_API_KEY (recommended, FREE)
        - gemini/gemini-2.0-flash -> GEMINI_API_KEY
        - gemini/gemini-1.5-pro -> GEMINI_API_KEY
        - openai/gpt-4o-mini -> OPENAI_API_KEY
        - anthropic/claude-3-5-sonnet -> ANTHROPIC_API_KEY
        - ollama/llama3.3 -> (no key needed, runs locally)
        - groq/llama3-70b -> GROQ_API_KEY
        """
        provider = os.getenv("CRAWL4AI_LLM_PROVIDER", "deepseek/deepseek-chat")
        
        # Check for API token based on provider prefix
        if provider.startswith("gemini"):
            api_token = os.getenv("GEMINI_API_KEY")
        elif provider.startswith("openai"):
            api_token = os.getenv("OPENAI_API_KEY")
        elif provider.startswith("anthropic"):
            api_token = os.getenv("ANTHROPIC_API_KEY")
        elif provider.startswith("groq"):
            api_token = os.getenv("GROQ_API_KEY")
        elif provider.startswith("deepseek"):
            api_token = os.getenv("DEEPSEEK_API_KEY")
        elif provider.startswith("ollama"):
            api_token = None  # Ollama doesn't need token
        else:
            api_token = os.getenv("LLM_API_KEY")
        
        return cls(
            provider=provider,
            api_token=api_token,
            base_url=os.getenv("CRAWL4AI_LLM_BASE_URL"),
        )


class Crawl4AIBackend(Backend):
    """AI-powered scraping backend using Crawl4AI.
    
    This backend can extract structured data from ANY website without
    manual CSS/XPath configuration. It uses LLM to understand page
    structure and extract opportunities.
    
    Usage:
        async with Crawl4AIBackend() as backend:
            result = await backend.extract_opportunities(url)
            for opp in result.opportunities:
                print(opp["title"])
    """
    
    def __init__(
        self,
        llm_config: LLMConfig | None = None,
        headless: bool = True,
        timeout: int = 60,
        enable_stealth: bool = True,
    ):
        """Initialize Crawl4AI backend.
        
        Args:
            llm_config: LLM configuration. If None, reads from environment.
            headless: Run browser in headless mode.
            timeout: Page load timeout in seconds.
            enable_stealth: Enable anti-detection measures.
        """
        self._llm_config = llm_config or LLMConfig.from_env()
        self._headless = headless
        self._timeout = timeout
        self._enable_stealth = enable_stealth
        self._crawler: AsyncWebCrawler | None = None
        self._total_tokens_used = 0
    
    @property
    def name(self) -> str:
        return "crawl4ai"
    
    @property
    def supports_javascript(self) -> bool:
        return True
    
    async def _ensure_crawler(self) -> "AsyncWebCrawler":
        """Lazily initialize the crawler."""
        if self._crawler is None:
            try:
                from crawl4ai import AsyncWebCrawler, BrowserConfig
            except ImportError as e:
                raise BackendError(
                    "Crawl4AI not installed. Run: pip install crawl4ai",
                    cause=e,
                ) from e
            
            browser_config = BrowserConfig(
                headless=self._headless,
                browser_type="chromium",
                viewport_width=1920,
                viewport_height=1080,
                verbose=False,  # Disable Unicode logging on Windows
            )
            
            self._crawler = AsyncWebCrawler(config=browser_config)
            await self._crawler.__aenter__()
        
        return self._crawler
    
    async def fetch(self, request: RequestSpec) -> FetchResult:
        """Fetch URL with JavaScript rendering.
        
        For basic fetching without LLM extraction.
        """
        start_time = datetime.utcnow()
        crawler = await self._ensure_crawler()
        
        try:
            from crawl4ai import CacheMode, CrawlerRunConfig
            
            config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                page_timeout=self._timeout * 1000,
                wait_for="css:body",
            )
            
            result = await crawler.arun(url=request.url, config=config)
            
            elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            if not result.success:
                return FetchResult(
                    url=request.url,
                    final_url=request.url,
                    status_code=500,
                    html="",
                    headers={},
                    cookies={},
                    elapsed_ms=elapsed,
                    error=result.error_message,
                )
            
            return FetchResult(
                url=request.url,
                final_url=result.url or request.url,
                status_code=200,
                html=result.html or "",
                headers={},
                cookies={},
                elapsed_ms=elapsed,
            )
            
        except Exception as e:
            elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
            logger.exception(f"Fetch failed: {request.url}")
            return FetchResult(
                url=request.url,
                final_url=request.url,
                status_code=500,
                html="",
                headers={},
                cookies={},
                elapsed_ms=elapsed,
                error=str(e),
            )
    
    async def extract_opportunities(
        self,
        url: str,
        cached_schema: dict[str, Any] | None = None,
        instruction: str | None = None,
    ) -> Crawl4AIResult:
        """Extract procurement opportunities using LLM.
        
        This is the main method for AI-powered extraction. It can either:
        1. Use a cached CSS schema (fast, free) if provided
        2. Use LLM extraction (slower, costs tokens) otherwise
        
        Args:
            url: URL to scrape
            cached_schema: Previously generated CSS schema for reuse
            instruction: Custom extraction instruction for LLM
            
        Returns:
            Crawl4AIResult with extracted opportunities
        """
        start_time = datetime.utcnow()
        crawler = await self._ensure_crawler()
        
        try:
            from crawl4ai import (
                CacheMode,
                CrawlerRunConfig,
                LLMConfig as C4LLMConfig,
                LLMExtractionStrategy,
            )
        except ImportError as e:
            raise BackendError(
                "Crawl4AI not installed. Run: pip install crawl4ai",
                cause=e,
            ) from e
        
        # Build extraction strategy
        if cached_schema:
            # Use cached CSS schema (FREE, fast)
            try:
                from crawl4ai import JsonCssExtractionStrategy
                
                strategy = JsonCssExtractionStrategy(cached_schema, verbose=True)
                method = "css_schema"
                logger.info(f"Using cached CSS schema for {url}")
            except Exception as e:
                logger.warning(f"Failed to use cached schema, falling back to LLM: {e}")
                cached_schema = None
        
        if not cached_schema:
            # Use LLM extraction (costs tokens, but works on any site)
            default_instruction = """
            Extract ALL procurement/tender opportunities from this page.
            
            For each opportunity, extract:
            - Title: The name or title of the tender/procurement
            - External ID: Any reference number, tender ID, or solicitation number
            - Agency: The government department, ministry, or organization
            - Category: Type of procurement (construction, IT, services, etc.)
            - Status: Current status (open, closed, awarded, etc.)
            - Posted date: When the opportunity was published
            - Closing date: Bid deadline or due date
            - Description: Brief summary if visible
            - Detail URL: Link to full details (make URLs absolute)
            - Value: Budget or estimated value if shown
            - Location: Geographic location if shown
            
            IMPORTANT:
            - Extract ALL opportunities visible on the page
            - Do NOT skip any opportunities
            - Convert relative URLs to absolute URLs
            - Keep dates in their original format
            """
            
            llm_config = C4LLMConfig(
                provider=self._llm_config.provider,
                api_token=self._llm_config.api_token,
                base_url=self._llm_config.base_url,
            )
            
            strategy = LLMExtractionStrategy(
                llm_config=llm_config,
                schema=OpportunitySchema.model_json_schema(),
                extraction_type="schema",
                instruction=instruction or default_instruction,
                chunk_token_threshold=4000,  # Smaller chunks to fit free tier limits
                overlap_rate=0.1,
                apply_chunking=True,
                input_format="fit_markdown",  # Use cleaned/pruned content, NOT raw HTML
                extra_args={
                    "temperature": self._llm_config.temperature,
                    "max_tokens": self._llm_config.max_tokens,
                },
            )
            method = "llm"
            logger.info(f"Using LLM extraction for {url}")
        
        # Configure crawler run with content filtering to reduce token count
        try:
            from crawl4ai import DefaultMarkdownGenerator, PruningContentFilter
            
            # Prune boilerplate content (nav, footer, ads) to reduce token count
            content_filter = PruningContentFilter(
                threshold=0.4,  # Lower = keep more content
                threshold_type="dynamic",
                min_word_threshold=5,
            )
            markdown_generator = DefaultMarkdownGenerator(content_filter=content_filter)
            
            config = CrawlerRunConfig(
                extraction_strategy=strategy,
                cache_mode=CacheMode.BYPASS,
                page_timeout=self._timeout * 1000,
                wait_for="css:body",
                delay_before_return_html=2.0,  # Wait for dynamic content
                markdown_generator=markdown_generator,
                excluded_tags=["nav", "footer", "aside", "header", "script", "style"],
                remove_overlay_elements=True,
            )
        except ImportError:
            # Fallback without content filter
            config = CrawlerRunConfig(
                extraction_strategy=strategy,
                cache_mode=CacheMode.BYPASS,
                page_timeout=self._timeout * 1000,
                wait_for="css:body",
                delay_before_return_html=2.0,
            )
        
        # Execute crawl
        try:
            result = await crawler.arun(url=url, config=config)
            elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            if not result.success:
                return Crawl4AIResult(
                    url=url,
                    opportunities=[],
                    markdown=None,
                    html=result.html or "",
                    method=method,
                    confidence=0.0,
                    token_usage=None,
                    elapsed_ms=elapsed,
                    error=result.error_message,
                )
            
            # Parse extracted content
            opportunities = []
            if result.extracted_content:
                try:
                    extracted = json.loads(result.extracted_content)
                    if isinstance(extracted, list):
                        opportunities = extracted
                    elif isinstance(extracted, dict):
                        # Sometimes LLM returns {"opportunities": [...]}
                        opportunities = extracted.get("opportunities", [extracted])
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse extracted content: {e}")
            
            # Get token usage if available
            token_usage = None
            if method == "llm" and hasattr(strategy, "show_usage"):
                try:
                    # Crawl4AI tracks usage internally
                    token_usage = getattr(strategy, "_total_usage", None)
                except Exception:
                    pass
            
            # Calculate confidence based on extraction quality
            confidence = self._calculate_confidence(opportunities)
            
            logger.info(
                f"Extracted {len(opportunities)} opportunities from {url} "
                f"(method={method}, confidence={confidence:.2f}, elapsed={elapsed:.0f}ms)"
            )
            
            return Crawl4AIResult(
                url=url,
                opportunities=opportunities,
                markdown=getattr(result.markdown, "raw_markdown", None) if result.markdown else None,
                html=result.html or "",
                method=method,
                confidence=confidence,
                token_usage=token_usage,
                elapsed_ms=elapsed,
            )
            
        except Exception as e:
            elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
            logger.exception(f"Extraction failed: {url}")
            return Crawl4AIResult(
                url=url,
                opportunities=[],
                markdown=None,
                html="",
                method=method,
                confidence=0.0,
                token_usage=None,
                elapsed_ms=elapsed,
                error=str(e),
            )
    
    async def generate_schema(
        self,
        sample_html: str,
        description: str = "Extract procurement opportunities",
    ) -> dict[str, Any]:
        """Generate a reusable CSS schema from sample HTML.
        
        This uses LLM ONCE to create a CSS schema that can be reused
        for unlimited future extractions (no more LLM costs).
        
        Args:
            sample_html: Sample HTML from the target site
            description: What to extract
            
        Returns:
            CSS schema dict that can be saved and reused
        """
        try:
            from crawl4ai import JsonCssExtractionStrategy, LLMConfig as C4LLMConfig
        except ImportError as e:
            raise BackendError(
                "Crawl4AI not installed. Run: pip install crawl4ai",
                cause=e,
            ) from e
        
        llm_config = C4LLMConfig(
            provider=self._llm_config.provider,
            api_token=self._llm_config.api_token,
            base_url=self._llm_config.base_url,
        )
        
        query = f"""
        {description}
        
        Extract the following fields for each opportunity:
        - title: The tender/procurement title
        - external_id: Reference number or tender ID
        - agency: Issuing organization
        - status: Current status
        - posted_at: Publication date
        - closing_at: Bid deadline
        - detail_url: Link to full details
        - category: Type of procurement
        - value: Budget or estimated value
        """
        
        schema = await JsonCssExtractionStrategy.agenerate_schema(
            html=sample_html[:15000],  # Limit sample size
            schema_type="CSS",
            query=query,
            llm_config=llm_config,
        )
        
        logger.info(f"Generated CSS schema with {len(schema.get('fields', []))} fields")
        return schema
    
    def _calculate_confidence(self, opportunities: list[dict[str, Any]]) -> float:
        """Calculate extraction confidence based on data quality."""
        if not opportunities:
            return 0.0
        
        # Required fields that should be present
        required_fields = {"title"}
        important_fields = {"external_id", "agency", "closing_at", "posted_at", "status"}
        
        total_score = 0.0
        for opp in opportunities:
            score = 0.0
            
            # Check required fields
            for field in required_fields:
                if opp.get(field):
                    score += 0.4
            
            # Check important fields
            filled_important = sum(1 for f in important_fields if opp.get(f))
            score += 0.6 * (filled_important / len(important_fields))
            
            total_score += score
        
        return min(total_score / len(opportunities), 1.0)
    
    async def close(self) -> None:
        """Clean up crawler resources."""
        if self._crawler is not None:
            await self._crawler.__aexit__(None, None, None)
            self._crawler = None


# =============================================================================
# Quick Mode Helper Functions
# =============================================================================

async def quick_scrape(
    url: str,
    max_pages: int = 1,
    llm_provider: str | None = None,
) -> list[dict[str, Any]]:
    """Quick scrape a URL with AI-powered extraction.
    
    This is the main entry point for "just scrape this URL" functionality.
    No configuration needed - the LLM figures out the page structure.
    
    Args:
        url: URL to scrape
        max_pages: Maximum pages to scrape (pagination)
        llm_provider: LLM provider (e.g., "openai/gpt-4o-mini", "ollama/llama3.3")
        
    Returns:
        List of extracted opportunities as dicts
        
    Example:
        opportunities = await quick_scrape("https://tenders.gov.au")
        for opp in opportunities:
            print(f"{opp['title']} - closes {opp.get('closing_at', 'N/A')}")
    """
    config = LLMConfig.from_env()
    if llm_provider:
        config.provider = llm_provider
    
    async with Crawl4AIBackend(llm_config=config) as backend:
        result = await backend.extract_opportunities(url)
        
        if result.error:
            logger.error(f"Quick scrape failed: {result.error}")
            return []
        
        return result.opportunities


async def generate_portal_config(
    url: str,
    portal_name: str,
    output_path: str | None = None,
) -> str:
    """Generate a draft YAML config from a successful scrape.
    
    This creates a portal config that can be used for deterministic
    scraping in the future.
    
    Args:
        url: URL that was successfully scraped
        portal_name: Name for the portal
        output_path: Where to save the YAML (optional)
        
    Returns:
        YAML config as string
    """
    from urllib.parse import urlparse
    
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    
    yaml_content = f'''# Auto-generated portal config for {portal_name}
# Generated from: {url}
# Generated at: {datetime.utcnow().isoformat()}

name: {portal_name}
display_name: "{portal_name.replace('_', ' ').title()}"
base_url: "{base_url}"
portal_type: crawl4ai  # Uses AI-powered extraction

seed_urls:
  - "{url}"

backend:
  preferred: crawl4ai
  fallbacks: [playwright, http]
  
  crawl4ai:
    headless: true
    timeout_seconds: 60
    enable_stealth: true
    
    # LLM configuration (reads from environment by default)
    # llm_provider: openai/gpt-4o-mini
    # llm_provider: ollama/llama3.3  # For local models

politeness:
  concurrency: 1
  min_delay_ms: 2000
  max_delay_ms: 4000

discovery:
  pagination:
    type: auto  # AI detects pagination
    max_pages: 10
  follow_detail_pages: true

extraction:
  mode: llm  # AI-powered extraction
  # Once you have a cached schema, you can switch to:
  # mode: css_schema
  # schema_path: "configs/schemas/{portal_name}_schema.json"

enabled: true
tags:
  - auto-generated
'''
    
    if output_path:
        import pathlib
        path = pathlib.Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml_content, encoding="utf-8")
        logger.info(f"Saved portal config to {output_path}")
    
    return yaml_content
