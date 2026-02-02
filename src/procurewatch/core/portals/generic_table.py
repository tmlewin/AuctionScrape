"""
Generic table portal plugin.

Handles portals that display opportunities in HTML tables.
Uses heuristic table extraction for data parsing.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING
from urllib.parse import urljoin

from lxml import html as lxml_html

from .base import PortalPlugin, PageResult, ListingItem
from procurewatch.core.extract import ExtractionPipeline
from procurewatch.core.backends.base import RequestSpec

if TYPE_CHECKING:
    from procurewatch.core.config.models import PortalConfig
    from procurewatch.core.backends.base import Backend


logger = logging.getLogger(__name__)


class GenericTablePortal(PortalPlugin):
    """Portal plugin for table-based listing pages.
    
    Uses HeuristicTableExtractor to find and parse HTML tables
    containing opportunity listings.
    """
    
    def __init__(self, config: PortalConfig, backend: Backend) -> None:
        super().__init__(config, backend)
        
        # Configure the extraction pipeline with portal-specific settings
        self.extractor = ExtractionPipeline(
            config=config.extraction,
            confidence_threshold=config.extraction.confidence_threshold,
        )
    
    @property
    def plugin_type(self) -> str:
        return "generic_table"
    
    async def scrape_listing_page(self, url: str) -> PageResult:
        """Scrape a listing page containing a table of opportunities."""
        errors: list[str] = []
        
        # Create request spec
        request = RequestSpec(
            url=url,
            portal_name=self.config.name,
            page_type="listing",
        )
        
        # Fetch the page
        try:
            fetch_result = await self.backend.fetch(request)
            if not fetch_result.ok:
                return PageResult(
                    items=[],
                    errors=[f"Fetch failed: {fetch_result.status_code} - {fetch_result.error}"],
                )
        except Exception as e:
            return PageResult(
                items=[],
                errors=[f"Fetch error: {str(e)}"],
            )
        
        html = fetch_result.html
        if not html:
            return PageResult(
                items=[],
                errors=["Empty response"],
            )
        
        # Extract table data
        extraction = self.extractor.extract(html, url)
        
        if not extraction.ok:
            errors.extend(extraction.errors)
            if extraction.warnings:
                errors.extend(extraction.warnings)
        
        # Convert records to ListingItems
        items: list[ListingItem] = []
        base_url = str(self.config.base_url)
        
        for i, record in enumerate(extraction.records):
            item = ListingItem(
                external_id=record.get("external_id"),
                title=record.get("title"),
                closing_at=record.get("closing_at"),
                posted_at=record.get("posted_at"),
                status=record.get("status"),
                agency=record.get("agency"),
                category=record.get("category"),
                detail_url=self._resolve_url(record.get("detail_url"), base_url),
                raw_data=record,
                confidence=extraction.confidence,
                row_index=i,
            )
            
            # Only include items with some identifying information
            if item.has_id:
                items.append(item)
        
        # Detect next page
        next_page_url = self.detect_pagination(html)
        if next_page_url:
            next_page_url = self._resolve_url(next_page_url, url)
        
        return PageResult(
            items=items,
            next_page_url=next_page_url,
            extraction_confidence=extraction.confidence,
            errors=errors,
        )
    
    async def scrape_detail_page(self, url: str) -> dict[str, Any]:
        """Scrape a detail page for additional opportunity data."""
        # Create request spec
        request = RequestSpec(
            url=url,
            portal_name=self.config.name,
            page_type="detail",
        )
        
        # Fetch the page
        try:
            fetch_result = await self.backend.fetch(request)
            if not fetch_result.ok:
                return {"_error": f"Fetch failed: {fetch_result.status_code}"}
        except Exception as e:
            return {"_error": f"Fetch error: {str(e)}"}
        
        html = fetch_result.html
        if not html:
            return {"_error": "Empty response"}
        
        # Extract using configured rules or heuristics
        return self._extract_detail_data(html, url)
    
    def _extract_detail_data(self, html: str, url: str) -> dict[str, Any]:
        """Extract data from a detail page.
        
        Uses CSS selector rules if configured, otherwise falls back
        to heuristic extraction of key-value pairs.
        """
        data: dict[str, Any] = {}
        
        try:
            tree = lxml_html.fromstring(html)
        except Exception as e:
            return {"_error": f"Parse error: {str(e)}"}
        
        detail_config = self.config.extraction.detail
        
        # Use configured field rules if available
        if detail_config.fields:
            for field_name, rule in detail_config.fields.items():
                value = self._extract_field(tree, rule, url)
                if value:
                    data[field_name] = value
        
        # Extract description with configured selector
        if detail_config.description_selector:
            desc_elements = tree.cssselect(detail_config.description_selector)
            if desc_elements:
                data["description"] = self._get_text_content(desc_elements[0])
        
        # Fall back to heuristic extraction for common patterns
        if not data or len(data) < 3:
            heuristic_data = self._heuristic_detail_extraction(tree)
            # Merge, preferring configured extractions
            for key, value in heuristic_data.items():
                if key not in data:
                    data[key] = value
        
        data["source_url"] = url
        data["confidence"] = 0.7 if data else 0.3
        
        return data
    
    def _extract_field(
        self,
        tree: lxml_html.HtmlElement,
        rule: Any,  # FieldExtractionRule
        base_url: str,
    ) -> str | None:
        """Extract a single field using configured rules."""
        for selector in rule.selectors:
            try:
                # Try CSS first
                elements = tree.cssselect(selector)
                if not elements:
                    # Try as XPath
                    elements = tree.xpath(selector)
                
                if elements:
                    element = elements[0]
                    
                    # Get value from attribute or text
                    if rule.attribute:
                        value = element.get(rule.attribute)
                        if value and rule.attribute == "href":
                            value = urljoin(base_url, value)
                    else:
                        value = self._get_text_content(element)
                    
                    if value:
                        # Apply regex if configured
                        if rule.regex:
                            import re
                            match = re.search(rule.regex, value)
                            if match:
                                value = match.group(1) if match.groups() else match.group(0)
                        
                        # Clean if configured
                        if rule.clean:
                            value = " ".join(value.split())
                        
                        return value
            except Exception:
                continue
        
        return None
    
    def _heuristic_detail_extraction(self, tree: lxml_html.HtmlElement) -> dict[str, Any]:
        """Extract data from detail page using heuristics.
        
        Looks for common label-value patterns in the page.
        """
        data: dict[str, Any] = {}
        
        # Common label patterns to look for
        label_patterns = {
            "title": ["title", "solicitation title", "project name", "bid title"],
            "external_id": ["solicitation number", "bid number", "rfp number", "id", "number"],
            "closing_at": ["closing date", "due date", "deadline", "close date", "end date"],
            "posted_at": ["posted date", "publish date", "open date", "issue date"],
            "status": ["status", "bid status", "state"],
            "agency": ["agency", "department", "organization", "buyer"],
            "category": ["category", "type", "commodity", "classification"],
            "description": ["description", "scope", "details", "summary"],
            "contact_name": ["contact", "buyer name", "procurement officer"],
            "contact_email": ["email", "contact email"],
            "estimated_value": ["estimated value", "budget", "value", "amount"],
        }
        
        # Look for definition lists (dt/dd pairs)
        for dt in tree.cssselect("dt"):
            label = self._get_text_content(dt).lower().strip()
            dd = dt.getnext()
            if dd is not None and dd.tag == "dd":
                value = self._get_text_content(dd)
                field = self._match_label(label, label_patterns)
                if field and value:
                    data[field] = value
        
        # Look for table rows with label cells
        for row in tree.cssselect("tr"):
            cells = row.cssselect("th, td")
            if len(cells) >= 2:
                label = self._get_text_content(cells[0]).lower().strip()
                value = self._get_text_content(cells[1])
                field = self._match_label(label, label_patterns)
                if field and value:
                    data[field] = value
        
        # Look for labeled divs/spans
        for element in tree.cssselect(".label, .field-label, [class*='label']"):
            label = self._get_text_content(element).lower().strip()
            # Look for adjacent value element
            value_elem = element.getnext()
            if value_elem is not None:
                value = self._get_text_content(value_elem)
                field = self._match_label(label, label_patterns)
                if field and value:
                    data[field] = value
        
        return data
    
    def _match_label(self, label: str, patterns: dict[str, list[str]]) -> str | None:
        """Match a label to a canonical field name."""
        label = label.lower().rstrip(":")
        
        for field, keywords in patterns.items():
            for keyword in keywords:
                if keyword in label:
                    return field
        
        return None
    
    def _get_text_content(self, element: lxml_html.HtmlElement) -> str:
        """Get text content from an element."""
        text = element.text_content()
        return " ".join(text.split()) if text else ""
    
    def _resolve_url(self, url: str | None, base_url: str) -> str | None:
        """Resolve a relative URL against a base."""
        if not url:
            return None
        if url.startswith(("http://", "https://")):
            return url
        return urljoin(base_url, url)
