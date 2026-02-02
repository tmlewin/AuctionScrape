"""
Portal plugin base class and interfaces.

Defines the contract for portal-specific scraping logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, TYPE_CHECKING

if TYPE_CHECKING:
    from procurewatch.core.config.models import PortalConfig
    from procurewatch.core.backends.base import Backend, FetchResult
    from procurewatch.core.extract.base import ExtractionResult


@dataclass
class ListingItem:
    """A single item from a listing page.
    
    Represents an opportunity summary before detail page fetch.
    """
    
    # Extracted fields
    external_id: str | None = None
    title: str | None = None
    closing_at: str | None = None  # Raw string, normalized later
    posted_at: str | None = None
    status: str | None = None
    agency: str | None = None
    category: str | None = None
    
    # URL to detail page
    detail_url: str | None = None
    
    # Raw data for debugging
    raw_data: dict[str, Any] = field(default_factory=dict)
    
    # Extraction metadata
    confidence: float = 0.0
    row_index: int = 0
    
    @property
    def has_id(self) -> bool:
        """Check if we have an identifier."""
        return bool(self.external_id or self.title)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "external_id": self.external_id,
            "title": self.title,
            "closing_at": self.closing_at,
            "posted_at": self.posted_at,
            "status": self.status,
            "agency": self.agency,
            "category": self.category,
            "detail_url": self.detail_url,
            "confidence": self.confidence,
        }


@dataclass
class OpportunityDraft:
    """Draft opportunity ready for normalization.
    
    Contains both listing data and detail data if available.
    """
    
    # From listing
    listing_data: dict[str, Any] = field(default_factory=dict)
    
    # From detail page (if fetched)
    detail_data: dict[str, Any] | None = None
    
    # URLs
    source_url: str | None = None
    detail_url: str | None = None
    
    # Metadata
    extraction_confidence: float = 0.0
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    
    def merged_data(self) -> dict[str, Any]:
        """Merge listing and detail data, preferring detail values."""
        result = dict(self.listing_data)
        if self.detail_data:
            result.update(self.detail_data)
        result["source_url"] = self.source_url
        result["detail_url"] = self.detail_url
        result["confidence"] = self.extraction_confidence
        return result


@dataclass
class PageResult:
    """Result of processing a single page."""
    
    items: list[ListingItem]
    next_page_url: str | None = None
    page_number: int = 1
    total_pages: int | None = None
    extraction_confidence: float = 0.0
    errors: list[str] = field(default_factory=list)
    
    @property
    def has_next(self) -> bool:
        """Check if there's a next page."""
        return bool(self.next_page_url)


class PortalPlugin(ABC):
    """Base class for portal-specific scraping logic.
    
    Each portal type (generic_table, cards, search_form, etc.)
    implements this interface to handle its specific quirks.
    """
    
    def __init__(self, config: PortalConfig, backend: Backend) -> None:
        """Initialize the plugin.
        
        Args:
            config: Portal configuration
            backend: Backend for making requests
        """
        self.config = config
        self.backend = backend
    
    @property
    def name(self) -> str:
        """Get portal name."""
        return self.config.name
    
    @property
    @abstractmethod
    def plugin_type(self) -> str:
        """Get plugin type identifier."""
        pass
    
    @abstractmethod
    async def scrape_listing_page(self, url: str) -> PageResult:
        """Scrape a single listing page.
        
        Args:
            url: URL of the listing page
            
        Returns:
            PageResult with extracted items and pagination info
        """
        pass
    
    @abstractmethod
    async def scrape_detail_page(self, url: str) -> dict[str, Any]:
        """Scrape a detail page for a single opportunity.
        
        Args:
            url: URL of the detail page
            
        Returns:
            Dictionary of extracted fields
        """
        pass
    
    async def scrape_all_pages(
        self,
        start_url: str | None = None,
        max_pages: int | None = None,
    ) -> AsyncIterator[PageResult]:
        """Iterate through all listing pages.
        
        Args:
            start_url: Starting URL (defaults to first seed URL)
            max_pages: Maximum pages to scrape (defaults to config value)
            
        Yields:
            PageResult for each page
        """
        url = start_url or self.config.seed_urls[0]
        max_pages = max_pages or self.config.discovery.pagination.max_pages
        
        page_num = 0
        while url and page_num < max_pages:
            page_num += 1
            
            result = await self.scrape_listing_page(url)
            result.page_number = page_num
            
            yield result
            
            url = result.next_page_url
    
    async def scrape_opportunities(
        self,
        max_pages: int | None = None,
        follow_details: bool | None = None,
    ) -> AsyncIterator[OpportunityDraft]:
        """Scrape all opportunities from the portal.
        
        Args:
            max_pages: Maximum pages to scrape
            follow_details: Whether to follow detail page links
            
        Yields:
            OpportunityDraft for each opportunity
        """
        follow_details = (
            follow_details
            if follow_details is not None
            else self.config.discovery.follow_detail_pages
        )
        
        async for page in self.scrape_all_pages(max_pages=max_pages):
            for item in page.items:
                draft = OpportunityDraft(
                    listing_data=item.to_dict(),
                    source_url=self.config.seed_urls[0],
                    detail_url=item.detail_url,
                    extraction_confidence=item.confidence,
                )
                
                # Follow detail page if configured and available
                if follow_details and item.detail_url:
                    try:
                        detail_data = await self.scrape_detail_page(item.detail_url)
                        draft.detail_data = detail_data
                        # Average the confidences
                        if "confidence" in detail_data:
                            draft.extraction_confidence = (
                                item.confidence + detail_data["confidence"]
                            ) / 2
                    except Exception:
                        # Log but continue - detail page failure shouldn't block listing
                        pass
                
                yield draft
    
    def detect_pagination(self, html: str) -> str | None:
        """Detect the next page URL from HTML.
        
        Default implementation looks for common pagination patterns.
        Override for custom pagination logic.
        
        Args:
            html: Page HTML content
            
        Returns:
            Next page URL or None
        """
        from lxml import html as lxml_html
        from urllib.parse import urljoin
        
        try:
            tree = lxml_html.fromstring(html)
        except Exception:
            return None
        
        # Use hint selector if provided
        hint = self.config.discovery.pagination.selector_hint
        if hint:
            elements = tree.cssselect(hint)
            if elements:
                href = elements[0].get("href")
                if href:
                    return urljoin(str(self.config.base_url), href)
        
        # Common next page patterns
        next_selectors = [
            'a[rel="next"]',
            'a.next',
            'a.pagination-next',
            'a[aria-label*="Next"]',
            'a[title*="Next"]',
            'li.next a',
            '.pagination a:contains("Next")',
            '.pagination a:contains(">")',
            'a:contains("Next Page")',
        ]
        
        for selector in next_selectors:
            try:
                elements = tree.cssselect(selector)
                if elements:
                    href = elements[0].get("href")
                    if href and not href.startswith("#"):
                        return urljoin(str(self.config.base_url), href)
            except Exception:
                continue
        
        return None
