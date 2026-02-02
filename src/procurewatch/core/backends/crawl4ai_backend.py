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
- Multi-page pagination with session management
- Deep scrape (follow detail page links)
- Advanced search/filter criteria
- Rate limiting and retry logic
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import urljoin, urlparse

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
# Quick Mode Configuration Models
# =============================================================================


class QuickPaginationType(str, Enum):
    """Pagination types for Quick Mode."""
    
    AUTO = "auto"  # Auto-detect pagination
    CLICK_NEXT = "click_next"
    LOAD_MORE = "load_more"
    INFINITE_SCROLL = "infinite_scroll"
    URL_PARAM = "url_param"
    NONE = "none"


class QuickSearchFilter(BaseModel):
    """Advanced search/filter criteria for Quick Mode."""
    
    keywords: list[str] = Field(
        default_factory=list,
        description="Keywords to search for in titles/descriptions"
    )
    status: list[str] = Field(
        default_factory=list,
        description="Status filters (open, closed, awarded)"
    )
    categories: list[str] = Field(
        default_factory=list,
        description="Category/type filters"
    )
    since_days: int | None = Field(
        default=None,
        description="Only include opportunities posted within N days"
    )
    closing_within_days: int | None = Field(
        default=None,
        description="Only include opportunities closing within N days"
    )
    min_value: float | None = Field(
        default=None,
        description="Minimum opportunity value"
    )
    max_value: float | None = Field(
        default=None,
        description="Maximum opportunity value"
    )
    location: str | None = Field(
        default=None,
        description="Geographic location filter"
    )


class QuickModeConfig(BaseModel):
    """Configuration for Quick Mode multi-page scraping."""
    
    # Pagination settings
    max_pages: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum pages to scrape"
    )
    pagination_type: QuickPaginationType = Field(
        default=QuickPaginationType.AUTO,
        description="Pagination strategy"
    )
    next_button_selector: str | None = Field(
        default=None,
        description="Custom selector for next button"
    )
    load_more_selector: str | None = Field(
        default=None,
        description="Custom selector for load more button"
    )
    
    # Deep scrape settings
    follow_detail_pages: bool = Field(
        default=False,
        description="Follow detail_url links for full descriptions"
    )
    max_detail_pages: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum detail pages to scrape"
    )
    detail_fields: list[str] = Field(
        default_factory=lambda: ["description", "attachments", "contact_email", "contact_phone"],
        description="Fields to extract from detail pages"
    )
    
    # Search/filter criteria
    filters: QuickSearchFilter = Field(
        default_factory=QuickSearchFilter,
        description="Search and filter criteria"
    )
    
    # Rate limiting
    delay_between_pages_ms: int = Field(
        default=2000,
        ge=500,
        le=30000,
        description="Delay between page requests in milliseconds"
    )
    delay_between_details_ms: int = Field(
        default=1500,
        ge=500,
        le=30000,
        description="Delay between detail page requests"
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retries on failure"
    )
    retry_backoff_factor: float = Field(
        default=2.0,
        ge=1.0,
        le=10.0,
        description="Exponential backoff multiplier"
    )
    
    # Error handling
    stop_on_error: bool = Field(
        default=False,
        description="Stop scraping on first error"
    )
    min_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum extraction confidence to continue"
    )
    screenshot_on_error: bool = Field(
        default=True,
        description="Save screenshot when errors occur"
    )
    
    # Content settings
    deduplicate: bool = Field(
        default=True,
        description="Remove duplicate opportunities"
    )
    content_pruning: bool = Field(
        default=True,
        description="Enable content pruning to reduce tokens"
    )


@dataclass
class MultiPageResult:
    """Result from multi-page Quick Mode scraping."""
    
    url: str
    total_pages: int
    pages_scraped: int
    pages_failed: int
    opportunities: list[dict[str, Any]]
    detail_pages_scraped: int = 0
    detail_pages_failed: int = 0
    total_elapsed_ms: float = 0.0
    avg_confidence: float = 0.0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    pagination_type_detected: str = "none"
    stopped_reason: str | None = None  # Why pagination stopped


# =============================================================================
# Pagination Detection Heuristics
# =============================================================================


NEXT_BUTTON_SELECTORS = [
    # ARIA-based (highest priority - catches Alberta site)
    "[aria-label*='next page']",
    "[aria-label*='Next page']",
    "[aria-label*='Go to next']",
    "[aria-label*='go to next']",
    "[aria-label*='Next']",
    "[aria-label*='next']",
    # Title attribute (for icon buttons)
    "[title*='Next']",
    "[title*='next page']",
    "[title*='Go to next']",
    # Arrow icons in buttons (icon-based pagination like Alberta)
    "button:has(img[alt*='forward'])",
    "button:has(img[alt*='Forward'])",
    "button:has(img[alt*='next'])",
    "button:has(img[alt*='Next'])",
    "button:has(svg[class*='forward'])",
    "button:has(svg[class*='arrow-right'])",
    "button:has(svg[class*='chevron-right'])",
    "a:has(svg[class*='chevron-right'])",
    "button:has(i[class*='arrow-right'])",
    "button:has(i[class*='chevron-right'])",
    # Text-based (common patterns)
    "button:has-text('Next')",
    "a:has-text('Next')",
    "button:has-text('next')",
    "a:has-text('next')",
    "button:has-text('›')",  # Right chevron
    "a:has-text('›')",
    "button:has-text('»')",  # Double right chevron
    "a:has-text('»')",
    "button:has-text('→')",  # Right arrow
    "a:has-text('→')",
    "button:has-text('>')",
    "a:has-text('>')",
    "button:has-text('>>')",
    "a:has-text('>>')",
    # Class-based
    ".pagination-next",
    ".next-page",
    ".next",
    ".page-next",
    "[class*='pagination'][class*='next']",
    "[class*='pager'][class*='next']",
    "[class*='next-btn']",
    "[class*='btn-next']",
    # Rel attribute
    "a[rel='next']",
    # Data attributes
    "[data-testid*='next']",
    "[data-testid*='pagination-next']",
    "[data-action*='next']",
]

LOAD_MORE_SELECTORS = [
    "button:has-text('Load More')",
    "button:has-text('Load more')",
    "button:has-text('Show More')",
    "button:has-text('Show more')",
    "button:has-text('View More')",
    "button:has-text('See More')",
    "a:has-text('Load More')",
    "a:has-text('Show More')",
    ".load-more",
    ".show-more",
    "[class*='load-more']",
    "[class*='loadMore']",
    "[data-testid*='load-more']",
]

INFINITE_SCROLL_INDICATORS = [
    "[data-infinite-scroll]",
    "[class*='infinite']",
    "[class*='virtual-scroll']",
    "[class*='lazy-load']",
]

DISABLED_INDICATORS = [
    "disabled",
    "is-disabled",
    "btn-disabled",
    "inactive",
    "unavailable",
]


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
            Extract ALL listings from the results table or list on this page.
            
            This could be: tenders, contracts, bids, RFPs, RFQs, solicitations, 
            opportunities, awards, or any government procurement listings.
            
            For each row/item, extract:
            - Title: Name, title, or description of the listing
            - External ID: Any reference number, contract #, bid #, solicitation #
            - Agency: Organization, department, ministry, or vendor name
            - Category: Type or category if shown
            - Status: Current status (open, active, closed, awarded, etc.)
            - Posted date: Start date, begin date, or publication date
            - Closing date: End date, deadline, due date, or expiration
            - Description: Brief summary if visible
            - Detail URL: Link to full details (make URLs absolute)
            - Value: Dollar amount, budget, or contract value if shown
            - Location: Geographic location if shown
            
            IMPORTANT:
            - Extract ALL rows from the table, do NOT skip any
            - Look for data in tables, lists, cards, or grid layouts
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
                chunk_token_threshold=3000,  # Smaller chunks to fit free tier limits (12k TPM)
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

    # =========================================================================
    # Multi-Page Quick Mode Methods
    # =========================================================================

    async def extract_multi_page(
        self,
        url: str,
        config: QuickModeConfig | None = None,
        progress_callback: Callable[[int, int, int], None] | None = None,
    ) -> MultiPageResult:
        """Extract opportunities from multiple pages with pagination detection.
        
        This is the main entry point for multi-page Quick Mode scraping.
        
        Args:
            url: Starting URL to scrape
            config: Quick mode configuration (uses defaults if not provided)
            progress_callback: Optional callback(page_num, total_opps, errors)
            
        Returns:
            MultiPageResult with all extracted opportunities
        """
        config = config or QuickModeConfig()
        start_time = datetime.utcnow()
        
        all_opportunities: list[dict[str, Any]] = []
        seen_ids: set[str] = set()  # For deduplication
        errors: list[str] = []
        warnings: list[str] = []
        pages_scraped = 0
        pages_failed = 0
        detail_pages_scraped = 0
        detail_pages_failed = 0
        total_confidence = 0.0
        pagination_type_detected = "none"
        stopped_reason = None
        
        # Create unique session ID for this scrape
        session_id = f"quick_{uuid.uuid4().hex[:8]}"
        
        try:
            from crawl4ai import CacheMode, CrawlerRunConfig
        except ImportError as e:
            raise BackendError(
                "Crawl4AI not installed. Run: pip install crawl4ai",
                cause=e,
            ) from e
        
        crawler = await self._ensure_crawler()
        
        logger.info(f"Starting multi-page extraction: {url} (max_pages={config.max_pages})")
        
        current_url = url
        page_num = 0
        
        while page_num < config.max_pages:
            page_num += 1
            retry_count = 0
            page_success = False
            
            while retry_count <= config.max_retries and not page_success:
                try:
                    logger.info(f"Extracting page {page_num}/{config.max_pages}: {current_url}")
                    
                    # Build crawler config for this page
                    run_config = await self._build_page_config(
                        session_id=session_id,
                        is_first_page=(page_num == 1),
                        config=config,
                    )
                    
                    # Execute extraction
                    result = await crawler.arun(url=current_url, config=run_config)
                    
                    if not result.success:
                        raise BackendError(
                            f"Crawl failed: {result.error_message}",
                            url=current_url,
                        )
                    
                    # Parse opportunities from this page
                    page_opps = self._parse_extracted_content(result.extracted_content)
                    confidence = self._calculate_confidence(page_opps)
                    total_confidence += confidence
                    
                    # Check confidence threshold
                    if confidence < config.min_confidence:
                        warnings.append(
                            f"Page {page_num} low confidence: {confidence:.2%}"
                        )
                        if config.stop_on_error:
                            stopped_reason = f"Low confidence on page {page_num}"
                            break
                    
                    # Apply filters
                    filtered_opps = self._apply_filters(page_opps, config.filters, url)
                    
                    # Deduplicate
                    if config.deduplicate:
                        new_opps = []
                        for opp in filtered_opps:
                            opp_id = self._get_opportunity_id(opp)
                            if opp_id not in seen_ids:
                                seen_ids.add(opp_id)
                                new_opps.append(opp)
                        filtered_opps = new_opps
                    
                    all_opportunities.extend(filtered_opps)
                    pages_scraped += 1
                    page_success = True
                    
                    logger.info(
                        f"Page {page_num}: {len(filtered_opps)} opportunities "
                        f"(total: {len(all_opportunities)}, confidence: {confidence:.2%})"
                    )
                    
                    # Progress callback
                    if progress_callback:
                        progress_callback(page_num, len(all_opportunities), len(errors))
                    
                    # Check if we should continue pagination
                    if page_num >= config.max_pages:
                        stopped_reason = "Reached max_pages limit"
                        break
                    
                    if len(page_opps) == 0:
                        stopped_reason = "No opportunities found on page"
                        break
                    
                    # Detect and execute pagination
                    pagination_result = await self._handle_pagination(
                        html=result.html or "",
                        current_url=result.url or current_url,
                        session_id=session_id,
                        config=config,
                        crawler=crawler,
                    )
                    
                    if not pagination_result["success"]:
                        stopped_reason = pagination_result.get("reason", "Pagination ended")
                        break
                    
                    pagination_type_detected = pagination_result.get("type", "none")
                    
                    # Rate limiting between pages
                    await asyncio.sleep(config.delay_between_pages_ms / 1000)
                    
                except Exception as e:
                    retry_count += 1
                    error_msg = f"Page {page_num} attempt {retry_count} failed: {e}"
                    logger.warning(error_msg)
                    
                    if retry_count > config.max_retries:
                        errors.append(error_msg)
                        pages_failed += 1
                        if config.stop_on_error:
                            stopped_reason = f"Error on page {page_num}"
                            break
                    else:
                        # Exponential backoff
                        wait_time = config.delay_between_pages_ms / 1000 * (
                            config.retry_backoff_factor ** (retry_count - 1)
                        )
                        await asyncio.sleep(wait_time)
            
            if stopped_reason:
                break
        
        # Deep scrape: Follow detail page links
        if config.follow_detail_pages and all_opportunities:
            detail_result = await self._deep_scrape_details(
                opportunities=all_opportunities,
                config=config,
                session_id=session_id,
                crawler=crawler,
            )
            detail_pages_scraped = detail_result["scraped"]
            detail_pages_failed = detail_result["failed"]
            errors.extend(detail_result["errors"])
        
        # Clean up session
        try:
            await crawler.crawler_strategy.kill_session(session_id)
        except Exception as e:
            logger.debug(f"Session cleanup failed: {e}")
        
        elapsed_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        avg_confidence = total_confidence / pages_scraped if pages_scraped > 0 else 0.0
        
        logger.info(
            f"Multi-page extraction complete: {len(all_opportunities)} opportunities "
            f"from {pages_scraped} pages in {elapsed_ms/1000:.1f}s"
        )
        
        return MultiPageResult(
            url=url,
            total_pages=config.max_pages,
            pages_scraped=pages_scraped,
            pages_failed=pages_failed,
            opportunities=all_opportunities,
            detail_pages_scraped=detail_pages_scraped,
            detail_pages_failed=detail_pages_failed,
            total_elapsed_ms=elapsed_ms,
            avg_confidence=avg_confidence,
            errors=errors,
            warnings=warnings,
            pagination_type_detected=pagination_type_detected,
            stopped_reason=stopped_reason,
        )

    async def _build_page_config(
        self,
        session_id: str,
        is_first_page: bool,
        config: QuickModeConfig,
    ) -> Any:
        """Build CrawlerRunConfig for a page extraction."""
        from crawl4ai import (
            CacheMode,
            CrawlerRunConfig,
            LLMConfig as C4LLMConfig,
            LLMExtractionStrategy,
        )
        
        # Build LLM extraction strategy
        llm_config = C4LLMConfig(
            provider=self._llm_config.provider,
            api_token=self._llm_config.api_token,
            base_url=self._llm_config.base_url,
        )
        
        instruction = """
        Extract ALL listings from the results table or list on this page.
        
        This could be: tenders, contracts, bids, RFPs, RFQs, solicitations, 
        opportunities, awards, or any government procurement listings.
        
        For each row/item in the results, extract:
        - title: Name, title, or description of the listing
        - external_id: Any reference number, contract #, bid #, solicitation #, ID
        - agency: Organization, department, ministry, or vendor name
        - category: Type or category if shown
        - status: Current status (open, active, closed, awarded, sent, etc.)
        - posted_at: Start date, begin date, posted date, or publication date
        - closing_at: End date, deadline, due date, or expiration date
        - description: Brief summary if visible
        - detail_url: Link to full details (convert to absolute URL)
        - value: Dollar amount, budget, or contract value if shown
        - location: Geographic location if shown
        
        IMPORTANT:
        - Extract ALL rows from the table, do NOT skip any
        - Look for data in tables, lists, cards, or grid layouts
        - Convert relative URLs to absolute URLs
        - Keep dates in their original format
        """
        
        strategy = LLMExtractionStrategy(
            llm_config=llm_config,
            schema=OpportunitySchema.model_json_schema(),
            extraction_type="schema",
            instruction=instruction,
            chunk_token_threshold=3000,  # Smaller chunks for free tier (12k TPM limit)
            overlap_rate=0.1,
            apply_chunking=True,
            input_format="fit_markdown",
            extra_args={
                "temperature": self._llm_config.temperature,
                "max_tokens": self._llm_config.max_tokens,
            },
        )
        
        # Build config with content pruning
        try:
            from crawl4ai import DefaultMarkdownGenerator, PruningContentFilter
            
            content_filter = PruningContentFilter(
                threshold=0.4,
                threshold_type="dynamic",
                min_word_threshold=5,
            ) if config.content_pruning else None
            
            markdown_generator = DefaultMarkdownGenerator(
                content_filter=content_filter
            ) if content_filter else None
            
            return CrawlerRunConfig(
                session_id=session_id,
                extraction_strategy=strategy,
                cache_mode=CacheMode.BYPASS,
                page_timeout=self._timeout * 1000,
                wait_for="css:body",
                delay_before_return_html=2.0,
                markdown_generator=markdown_generator,
                excluded_tags=["nav", "footer", "aside", "header", "script", "style"],
                remove_overlay_elements=True,
                js_only=not is_first_page,  # Only execute JS on subsequent pages
            )
        except ImportError:
            return CrawlerRunConfig(
                session_id=session_id,
                extraction_strategy=strategy,
                cache_mode=CacheMode.BYPASS,
                page_timeout=self._timeout * 1000,
                wait_for="css:body",
                delay_before_return_html=2.0,
                js_only=not is_first_page,
            )

    async def _handle_pagination(
        self,
        html: str,
        current_url: str,
        session_id: str,
        config: QuickModeConfig,
        crawler: Any,
    ) -> dict[str, Any]:
        """Detect and execute pagination.
        
        Returns:
            dict with keys: success, type, reason
        """
        from crawl4ai import CacheMode, CrawlerRunConfig
        
        pagination_type = config.pagination_type
        
        # Auto-detect pagination type if needed
        if pagination_type == QuickPaginationType.AUTO:
            pagination_type = self._detect_pagination_type(html, config)
        
        if pagination_type == QuickPaginationType.NONE:
            return {"success": False, "type": "none", "reason": "No pagination detected"}
        
        # Build JavaScript for pagination
        js_code = None
        wait_for = None
        
        if pagination_type == QuickPaginationType.CLICK_NEXT:
            selector = config.next_button_selector
            if not selector:
                selector = self._find_next_button_selector(html)
            
            if not selector:
                return {"success": False, "type": "click_next", "reason": "Next button not found"}
            
            # Check if button is disabled
            if self._is_button_disabled(html, selector):
                return {"success": False, "type": "click_next", "reason": "Next button disabled"}
            
            js_code = f'''
            (async () => {{
                const button = document.querySelector("{selector}");
                if (button && !button.disabled) {{
                    const beforeCount = document.querySelectorAll('[class*="result"], [class*="item"], [class*="row"], [class*="opportunity"], [class*="tender"]').length;
                    button.click();
                    // Wait for content change
                    await new Promise(resolve => setTimeout(resolve, 1500));
                    return true;
                }}
                return false;
            }})();
            '''
            wait_for = "js:() => true"  # Wait handled in JS
            
        elif pagination_type == QuickPaginationType.LOAD_MORE:
            selector = config.load_more_selector
            if not selector:
                selector = self._find_load_more_selector(html)
            
            if not selector:
                return {"success": False, "type": "load_more", "reason": "Load More button not found"}
            
            js_code = f'''
            (async () => {{
                const button = document.querySelector("{selector}");
                if (button && !button.disabled) {{
                    const beforeCount = document.querySelectorAll('[class*="result"], [class*="item"], [class*="opportunity"]').length;
                    button.click();
                    await new Promise(resolve => setTimeout(resolve, 2000));
                    const afterCount = document.querySelectorAll('[class*="result"], [class*="item"], [class*="opportunity"]').length;
                    return afterCount > beforeCount;
                }}
                return false;
            }})();
            '''
            
        elif pagination_type == QuickPaginationType.INFINITE_SCROLL:
            js_code = """
            (async () => {
                const container = document.scrollingElement || document.documentElement;
                const beforeHeight = container.scrollHeight;
                const beforeCount = document.querySelectorAll('[class*="result"], [class*="item"], [class*="opportunity"]').length;
                
                window.scrollTo(0, container.scrollHeight);
                await new Promise(resolve => setTimeout(resolve, 2000));
                
                const afterHeight = container.scrollHeight;
                const afterCount = document.querySelectorAll('[class*="result"], [class*="item"], [class*="opportunity"]').length;
                
                return afterHeight > beforeHeight || afterCount > beforeCount;
            })();
            """
        
        if not js_code:
            return {"success": False, "type": str(pagination_type.value), "reason": "No pagination action"}
        
        # Execute pagination
        try:
            pagination_config = CrawlerRunConfig(
                session_id=session_id,
                js_code=js_code,
                wait_for=wait_for,
                js_only=True,
                cache_mode=CacheMode.BYPASS,
            )
            
            result = await crawler.arun(url=current_url, config=pagination_config)
            
            if result.success:
                return {"success": True, "type": str(pagination_type.value)}
            else:
                return {
                    "success": False,
                    "type": str(pagination_type.value),
                    "reason": result.error_message or "Pagination action failed",
                }
                
        except Exception as e:
            return {
                "success": False,
                "type": str(pagination_type.value),
                "reason": str(e),
            }

    def _detect_pagination_type(self, html: str, config: QuickModeConfig) -> QuickPaginationType:
        """Auto-detect the pagination type from HTML."""
        html_lower = html.lower()
        
        # Check for infinite scroll indicators
        for indicator in INFINITE_SCROLL_INDICATORS:
            if indicator.lower().strip("[]") in html_lower:
                logger.debug("Detected infinite scroll pagination")
                return QuickPaginationType.INFINITE_SCROLL
        
        # Check for Load More button
        if self._find_load_more_selector(html):
            logger.debug("Detected load more pagination")
            return QuickPaginationType.LOAD_MORE
        
        # Check for Next button
        if self._find_next_button_selector(html):
            logger.debug("Detected click next pagination")
            return QuickPaginationType.CLICK_NEXT
        
        logger.debug("No pagination detected")
        return QuickPaginationType.NONE

    def _find_next_button_selector(self, html: str) -> str | None:
        """Find a working Next button selector in the HTML.
        
        Uses multiple detection strategies to find pagination controls.
        """
        html_lower = html.lower()
        
        # Strategy 1: Check for aria-label patterns (most reliable)
        aria_patterns = [
            (r'aria-label\s*=\s*["\'][^"\']*next\s*page[^"\']*["\']', "[aria-label*='next page']"),
            (r'aria-label\s*=\s*["\'][^"\']*go\s*to\s*next[^"\']*["\']', "[aria-label*='Go to next']"),
            (r'aria-label\s*=\s*["\'][^"\']*next[^"\']*["\']', "[aria-label*='next']"),
        ]
        for pattern, selector in aria_patterns:
            if re.search(pattern, html_lower):
                logger.debug(f"Found pagination via aria-label: {selector}")
                return selector
        
        # Strategy 2: Check for title attributes on buttons
        title_patterns = [
            (r'title\s*=\s*["\'][^"\']*next\s*page[^"\']*["\']', "[title*='next page']"),
            (r'title\s*=\s*["\'][^"\']*next[^"\']*["\']', "[title*='next']"),
        ]
        for pattern, selector in title_patterns:
            if re.search(pattern, html_lower):
                logger.debug(f"Found pagination via title: {selector}")
                return selector
        
        # Strategy 3: Check for forward/arrow icons (for icon-based pagination like Alberta)
        icon_patterns = [
            (r'(arrow.?forward|forward.?arrow)', "button:has(img[alt*='forward'])"),
            (r'(chevron.?right|right.?chevron)', "button:has(svg[class*='chevron-right'])"),
            (r'icon.?next', "button:has([class*='icon-next'])"),
        ]
        for pattern, selector in icon_patterns:
            if re.search(pattern, html_lower):
                logger.debug(f"Found pagination via icon: {selector}")
                return selector
        
        # Strategy 4: Check for text-based patterns
        text_patterns = [
            (r'>\s*next\s*<', "button:has-text('Next')"),
            (r'>\s*next\s+page\s*<', "button:has-text('Next Page')"),
            (r'>\s*›\s*<', "button:has-text('›')"),
            (r'>\s*»\s*<', "button:has-text('»')"),
            (r'>\s*→\s*<', "button:has-text('→')"),
        ]
        for pattern, selector in text_patterns:
            if re.search(pattern, html_lower):
                logger.debug(f"Found pagination via text: {selector}")
                return selector
        
        # Strategy 5: Check for class-based patterns
        class_patterns = [
            (r'class\s*=\s*["\'][^"\']*pagination[^"\']*next[^"\']*["\']', ".pagination-next"),
            (r'class\s*=\s*["\'][^"\']*next[^"\']*page[^"\']*["\']', ".next-page"),
            (r'class\s*=\s*["\'][^"\']*pager[^"\']*next[^"\']*["\']', "[class*='pager'][class*='next']"),
        ]
        for pattern, selector in class_patterns:
            if re.search(pattern, html_lower):
                logger.debug(f"Found pagination via class: {selector}")
                return selector
        
        # Strategy 6: Check for rel="next" links
        if re.search(r'rel\s*=\s*["\']next["\']', html_lower):
            logger.debug("Found pagination via rel='next'")
            return "a[rel='next']"
        
        # Strategy 7: Check for data attributes
        data_patterns = [
            (r'data-testid\s*=\s*["\'][^"\']*next[^"\']*["\']', "[data-testid*='next']"),
            (r'data-action\s*=\s*["\'][^"\']*next[^"\']*["\']', "[data-action*='next']"),
        ]
        for pattern, selector in data_patterns:
            if re.search(pattern, html_lower):
                logger.debug(f"Found pagination via data attribute: {selector}")
                return selector
        
        return None

    def _find_load_more_selector(self, html: str) -> str | None:
        """Find a working Load More button selector in the HTML."""
        html_lower = html.lower()
        
        for selector in LOAD_MORE_SELECTORS:
            if ":has-text(" in selector:
                match = re.search(r":has-text\('([^']+)'\)", selector)
                if match:
                    text = match.group(1).lower()
                    if f">{text}<" in html_lower or f">{text} <" in html_lower:
                        return selector
            elif selector.startswith(".") or "[class*=" in selector:
                class_pattern = selector.replace("[class*='", "").replace("']", "").replace(".", "")
                if class_pattern in html_lower:
                    return selector
        
        return None

    def _is_button_disabled(self, html: str, selector: str) -> bool:
        """Check if a pagination button appears to be disabled."""
        # This is a heuristic check - in practice, the JS execution will verify
        html_lower = html.lower()
        
        for indicator in DISABLED_INDICATORS:
            # Check if disabled class/attribute appears near pagination elements
            if f'class="[^"]*{indicator}' in html_lower:
                return True
            if f"disabled" in html_lower:
                # More specific check would require parsing
                pass
        
        return False

    def _parse_extracted_content(self, content: str | None) -> list[dict[str, Any]]:
        """Parse extracted content into list of opportunities."""
        if not content:
            return []
        
        try:
            extracted = json.loads(content)
            if isinstance(extracted, list):
                return extracted
            elif isinstance(extracted, dict):
                return extracted.get("opportunities", [extracted])
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse extracted content: {e}")
        
        return []

    def _get_opportunity_id(self, opp: dict[str, Any]) -> str:
        """Generate a unique ID for an opportunity for deduplication."""
        # Prefer external_id if available
        if opp.get("external_id"):
            return str(opp["external_id"])
        
        # Fall back to hash of title + closing date
        import hashlib
        hash_input = f"{opp.get('title', '')}{opp.get('closing_at', '')}{opp.get('agency', '')}"
        return hashlib.md5(hash_input.encode()).hexdigest()[:16]

    def _apply_filters(
        self,
        opportunities: list[dict[str, Any]],
        filters: QuickSearchFilter,
        base_url: str,
    ) -> list[dict[str, Any]]:
        """Apply search/filter criteria to opportunities."""
        if not any([
            filters.keywords,
            filters.status,
            filters.categories,
            filters.since_days,
            filters.closing_within_days,
            filters.min_value,
            filters.max_value,
            filters.location,
        ]):
            # No filters to apply - just fix URLs
            return [self._fix_urls(opp, base_url) for opp in opportunities]
        
        filtered = []
        now = datetime.utcnow()
        
        for opp in opportunities:
            # Fix URLs first
            opp = self._fix_urls(opp, base_url)
            
            # Keyword filter
            if filters.keywords:
                text = f"{opp.get('title', '')} {opp.get('description', '')}".lower()
                if not any(kw.lower() in text for kw in filters.keywords):
                    continue
            
            # Status filter
            if filters.status:
                opp_status = (opp.get("status") or "").lower()
                if not any(s.lower() in opp_status for s in filters.status):
                    continue
            
            # Category filter
            if filters.categories:
                opp_category = (opp.get("category") or "").lower()
                if not any(c.lower() in opp_category for c in filters.categories):
                    continue
            
            # Location filter
            if filters.location:
                opp_location = (opp.get("location") or "").lower()
                if filters.location.lower() not in opp_location:
                    continue
            
            # Date filters (best effort - dates may not be parsed)
            if filters.since_days or filters.closing_within_days:
                try:
                    import dateparser
                    
                    if filters.since_days:
                        posted = dateparser.parse(opp.get("posted_at", ""))
                        if posted:
                            cutoff = now - timedelta(days=filters.since_days)
                            if posted < cutoff:
                                continue
                    
                    if filters.closing_within_days:
                        closing = dateparser.parse(opp.get("closing_at", ""))
                        if closing:
                            deadline = now + timedelta(days=filters.closing_within_days)
                            if closing > deadline:
                                continue
                except ImportError:
                    logger.debug("dateparser not available for date filtering")
            
            # Value filters (best effort)
            if filters.min_value or filters.max_value:
                value_str = opp.get("value", "")
                if value_str:
                    try:
                        # Extract numeric value
                        value_num = float(re.sub(r"[^\d.]", "", value_str))
                        if filters.min_value and value_num < filters.min_value:
                            continue
                        if filters.max_value and value_num > filters.max_value:
                            continue
                    except (ValueError, TypeError):
                        pass
            
            filtered.append(opp)
        
        return filtered

    def _fix_urls(self, opp: dict[str, Any], base_url: str) -> dict[str, Any]:
        """Convert relative URLs to absolute."""
        if opp.get("detail_url"):
            url = opp["detail_url"]
            if url.startswith("/"):
                parsed = urlparse(base_url)
                opp["detail_url"] = f"{parsed.scheme}://{parsed.netloc}{url}"
            elif not url.startswith("http"):
                opp["detail_url"] = urljoin(base_url, url)
        return opp

    async def _deep_scrape_details(
        self,
        opportunities: list[dict[str, Any]],
        config: QuickModeConfig,
        session_id: str,
        crawler: Any,
    ) -> dict[str, Any]:
        """Follow detail page links to get full descriptions.
        
        Returns:
            dict with keys: scraped, failed, errors
        """
        from crawl4ai import CacheMode, CrawlerRunConfig
        
        scraped = 0
        failed = 0
        errors: list[str] = []
        
        # Filter opportunities that have detail_url
        with_urls = [
            (i, opp) for i, opp in enumerate(opportunities)
            if opp.get("detail_url")
        ]
        
        if not with_urls:
            logger.info("No detail URLs to scrape")
            return {"scraped": 0, "failed": 0, "errors": []}
        
        logger.info(f"Deep scraping {min(len(with_urls), config.max_detail_pages)} detail pages")
        
        for idx, (opp_idx, opp) in enumerate(with_urls[:config.max_detail_pages]):
            detail_url = opp["detail_url"]
            
            try:
                # Extract detail page content
                result = await self.extract_detail_page(
                    url=detail_url,
                    fields=config.detail_fields,
                )
                
                if result.get("success"):
                    # Merge detail data into opportunity
                    for field in config.detail_fields:
                        if result.get(field):
                            opportunities[opp_idx][field] = result[field]
                    scraped += 1
                else:
                    failed += 1
                    if result.get("error"):
                        errors.append(f"Detail page {detail_url}: {result['error']}")
                
                # Rate limiting
                if idx < len(with_urls) - 1:
                    await asyncio.sleep(config.delay_between_details_ms / 1000)
                    
            except Exception as e:
                failed += 1
                errors.append(f"Detail page {detail_url}: {e}")
                if config.stop_on_error:
                    break
        
        return {"scraped": scraped, "failed": failed, "errors": errors}

    async def extract_detail_page(
        self,
        url: str,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Extract additional fields from a detail page.
        
        Args:
            url: Detail page URL
            fields: Specific fields to extract
            
        Returns:
            dict with extracted fields and success status
        """
        fields = fields or ["description", "attachments", "contact_email", "contact_phone"]
        
        crawler = await self._ensure_crawler()
        
        try:
            from crawl4ai import (
                CacheMode,
                CrawlerRunConfig,
                LLMConfig as C4LLMConfig,
                LLMExtractionStrategy,
            )
            
            # Build instruction for detail extraction
            field_list = ", ".join(fields)
            instruction = f"""
            Extract the following information from this procurement detail page:
            
            Fields to extract: {field_list}
            
            - description: Full description of the procurement (as complete as possible)
            - attachments: List of any downloadable documents/attachments with URLs
            - contact_name: Contact person name
            - contact_email: Contact email address
            - contact_phone: Contact phone number
            - requirements: Any specific requirements or qualifications
            - timeline: Important dates and deadlines
            - submission_instructions: How to submit a bid/proposal
            
            Return only the requested fields that are present on the page.
            """
            
            llm_config = C4LLMConfig(
                provider=self._llm_config.provider,
                api_token=self._llm_config.api_token,
                base_url=self._llm_config.base_url,
            )
            
            strategy = LLMExtractionStrategy(
                llm_config=llm_config,
                extraction_type="schema",
                instruction=instruction,
                chunk_token_threshold=4000,
                input_format="fit_markdown",
            )
            
            config = CrawlerRunConfig(
                extraction_strategy=strategy,
                cache_mode=CacheMode.BYPASS,
                page_timeout=self._timeout * 1000,
                wait_for="css:body",
                delay_before_return_html=1.5,
            )
            
            result = await crawler.arun(url=url, config=config)
            
            if not result.success:
                return {"success": False, "error": result.error_message}
            
            # Parse extracted content
            if result.extracted_content:
                try:
                    extracted = json.loads(result.extracted_content)
                    if isinstance(extracted, list) and len(extracted) > 0:
                        extracted = extracted[0]
                    if isinstance(extracted, dict):
                        extracted["success"] = True
                        return extracted
                except json.JSONDecodeError:
                    pass
            
            # Fall back to markdown description
            if result.markdown:
                md_content = getattr(result.markdown, "raw_markdown", str(result.markdown))
                return {
                    "success": True,
                    "description": md_content[:5000] if md_content else None,
                }
            
            return {"success": False, "error": "No content extracted"}
            
        except Exception as e:
            logger.warning(f"Detail extraction failed for {url}: {e}")
            return {"success": False, "error": str(e)}
    
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
