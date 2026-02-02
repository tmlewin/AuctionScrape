"""
Search form portal plugin.

Handles portals that require:
1. Navigation from homepage to search area
2. Filling out a search form
3. Submitting the form
4. Extracting results from dynamically-loaded content
5. Browser-based pagination (click next, load more, infinite scroll)

Requires PlaywrightBackend.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, TYPE_CHECKING
from urllib.parse import urljoin

from lxml import html as lxml_html

from .base import PortalPlugin, PageResult, ListingItem, OpportunityDraft
from procurewatch.core.extract import ExtractionPipeline
from procurewatch.core.backends.base import RequestSpec

if TYPE_CHECKING:
    from procurewatch.core.config.models import (
        PortalConfig,
        NavigationAction,
        FormField,
        PaginationType,
    )
    from procurewatch.core.backends.playwright_backend import PlaywrightBackend

logger = logging.getLogger(__name__)


# =============================================================================
# Dynamic Variable Resolution
# =============================================================================


def resolve_dynamic_value(value: str, context: dict[str, Any] | None = None) -> str:
    """Resolve dynamic variables in a value string.
    
    Supported variables:
    - ${TODAY} - Current date (YYYY-MM-DD)
    - ${TODAY-Nd} - N days ago
    - ${TODAY+Nd} - N days from now
    - ${LAST_RUN_DATE} - Date of last successful scrape
    - ${env:VAR_NAME} - Environment variable
    
    Args:
        value: String potentially containing variables
        context: Optional context dict with extra variables
        
    Returns:
        Resolved string value
    """
    import os
    
    context = context or {}
    today = datetime.now().date()
    
    # ${TODAY}
    value = value.replace("${TODAY}", today.isoformat())
    
    # ${TODAY-Nd} or ${TODAY+Nd}
    date_pattern = r'\$\{TODAY([+-])(\d+)d\}'
    for match in re.finditer(date_pattern, value):
        sign = match.group(1)
        days = int(match.group(2))
        delta = timedelta(days=days if sign == "+" else -days)
        result_date = today + delta
        value = value.replace(match.group(0), result_date.isoformat())
    
    # ${LAST_RUN_DATE}
    if "${LAST_RUN_DATE}" in value:
        last_run = context.get("last_run_date", today - timedelta(days=30))
        if isinstance(last_run, datetime):
            last_run = last_run.date()
        value = value.replace("${LAST_RUN_DATE}", last_run.isoformat())
    
    # ${env:VAR_NAME}
    env_pattern = r'\$\{env:([^}]+)\}'
    for match in re.finditer(env_pattern, value):
        var_name = match.group(1)
        env_value = os.environ.get(var_name, "")
        value = value.replace(match.group(0), env_value)
    
    # Custom context variables
    for key, val in context.items():
        placeholder = f"${{{key}}}"
        if placeholder in value:
            value = value.replace(placeholder, str(val))
    
    return value


# =============================================================================
# SearchFormPortal Implementation
# =============================================================================


class SearchFormPortal(PortalPlugin):
    """Portal plugin for search form-based listing pages.
    
    Handles the complete workflow:
    1. Navigate to search page (optional multi-step navigation)
    2. Fill form fields with configured values
    3. Submit form and wait for results
    4. Extract results from rendered page
    5. Handle pagination (click next, load more, infinite scroll)
    
    Requires PlaywrightBackend for JavaScript rendering.
    """
    
    def __init__(
        self,
        config: PortalConfig,
        backend: PlaywrightBackend,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the search form portal plugin.
        
        Args:
            config: Portal configuration
            backend: PlaywrightBackend instance (required)
            context: Optional context for dynamic variable resolution
        """
        super().__init__(config, backend)
        
        # Type assertion - we need PlaywrightBackend
        if not backend.supports_javascript:
            raise ValueError(
                f"SearchFormPortal requires a JavaScript-capable backend. "
                f"Got: {backend.name}"
            )
        
        self.playwright_backend: PlaywrightBackend = backend
        self.context = context or {}
        
        # Configure the extraction pipeline for results
        self.extractor = ExtractionPipeline(
            config=config.extraction,
            confidence_threshold=config.extraction.confidence_threshold,
        )
        
        # Track state
        self._initialized = False
        self._current_page = 0
    
    @property
    def plugin_type(self) -> str:
        return "search_form"
    
    async def _execute_navigation_steps(self) -> bool:
        """Execute navigation steps to reach the search form.
        
        Returns:
            True if navigation successful
        """
        steps = self.config.navigation.steps
        
        if not steps:
            logger.debug("No navigation steps configured")
            return True
        
        logger.info(f"Executing {len(steps)} navigation steps")
        
        for i, step in enumerate(steps):
            logger.debug(f"Navigation step {i+1}: {step.action}")
            
            try:
                # Check condition if specified
                if step.condition:
                    exists = await self.playwright_backend.wait_for_selector(
                        step.condition,
                        timeout_ms=2000,
                    )
                    if not exists:
                        logger.debug(f"Condition not met, skipping step: {step.condition}")
                        continue
                
                if step.action.value == "click":
                    if not step.selector:
                        logger.warning("Click action requires selector")
                        continue
                    
                    result = await self.playwright_backend.click(
                        step.selector,
                        wait_for=step.wait_for,
                        timeout_ms=step.timeout_ms,
                    )
                    
                    if not result.success and not step.optional:
                        raise Exception(f"Click failed: {result.error}")
                
                elif step.action.value == "wait":
                    if step.duration_ms:
                        await asyncio.sleep(step.duration_ms / 1000)
                
                elif step.action.value == "wait_for":
                    if step.selector:
                        success = await self.playwright_backend.wait_for_selector(
                            step.selector,
                            timeout_ms=step.timeout_ms,
                        )
                        if not success and not step.optional:
                            raise Exception(f"Element not found: {step.selector}")
                
                elif step.action.value == "fill":
                    if step.selector and step.value:
                        resolved_value = resolve_dynamic_value(step.value, self.context)
                        result = await self.playwright_backend.fill(
                            step.selector,
                            resolved_value,
                            timeout_ms=step.timeout_ms,
                        )
                        if not result.success and not step.optional:
                            raise Exception(f"Fill failed: {result.error}")
                
                elif step.action.value == "goto":
                    if step.value:
                        url = resolve_dynamic_value(step.value, self.context)
                        await self.playwright_backend.fetch(
                            RequestSpec(url=url, timeout=step.timeout_ms / 1000)
                        )
                
                elif step.action.value == "pause_for_human":
                    message = step.message or "Please complete the required action..."
                    await self.playwright_backend.pause_for_human(message)
                
                elif step.action.value == "scroll":
                    # Scroll down the page
                    page = await self.playwright_backend._get_page()
                    await page.evaluate("window.scrollBy(0, window.innerHeight)")
                
                elif step.action.value == "hover":
                    if step.selector:
                        page = await self.playwright_backend._get_page()
                        await page.hover(step.selector, timeout=step.timeout_ms)
                
            except Exception as e:
                if step.optional:
                    logger.warning(f"Optional navigation step failed: {e}")
                else:
                    logger.error(f"Navigation step failed: {e}")
                    return False
        
        return True
    
    async def _fill_search_form(self) -> bool:
        """Fill and submit the search form.
        
        Returns:
            True if form submitted successfully
        """
        form_config = self.config.search_form
        
        if not form_config:
            logger.debug("No search form configuration")
            return True
        
        logger.info("Filling search form")
        
        # Wait for form to be ready
        if form_config.form_selector:
            success = await self.playwright_backend.wait_for_selector(
                form_config.form_selector,
                timeout_ms=10000,
            )
            if not success:
                logger.warning(f"Form not found: {form_config.form_selector}")
        
        # Fill each field
        for field in form_config.fields:
            try:
                # Resolve dynamic value
                resolved_value = resolve_dynamic_value(field.value, self.context)
                
                if not resolved_value and field.optional:
                    logger.debug(f"Skipping empty optional field: {field.name}")
                    continue
                
                logger.debug(f"Filling field '{field.name}': {field.selector}")
                
                if field.type.value == "text":
                    result = await self.playwright_backend.fill(
                        field.selector,
                        resolved_value,
                        clear_first=field.clear_first,
                    )
                
                elif field.type.value == "select":
                    result = await self.playwright_backend.select_option(
                        field.selector,
                        label=resolved_value,
                    )
                
                elif field.type.value == "checkbox":
                    if resolved_value.lower() in ("true", "1", "yes", "on"):
                        result = await self.playwright_backend.check(field.selector)
                    else:
                        # Uncheck if needed
                        page = await self.playwright_backend._get_page()
                        is_checked = await page.is_checked(field.selector)
                        if is_checked:
                            await page.uncheck(field.selector)
                        result = type("Result", (), {"success": True})()
                
                elif field.type.value == "radio":
                    result = await self.playwright_backend.check(field.selector)
                
                elif field.type.value == "date":
                    # Date inputs may need special handling
                    result = await self.playwright_backend.fill(
                        field.selector,
                        resolved_value,
                        clear_first=True,
                    )
                
                elif field.type.value == "autocomplete":
                    # Type text and wait for dropdown
                    result = await self.playwright_backend.fill(
                        field.selector,
                        resolved_value,
                        clear_first=True,
                    )
                    # Wait a moment for autocomplete
                    await asyncio.sleep(0.5)
                    # Try to select first option
                    page = await self.playwright_backend._get_page()
                    try:
                        await page.click(
                            f"{field.selector} + * li:first-child, "
                            f".autocomplete-item:first-child, "
                            f"[role='option']:first-child",
                            timeout=2000,
                        )
                    except Exception:
                        pass  # Autocomplete might work without explicit selection
                    result = type("Result", (), {"success": True})()
                
                else:
                    # Default to text fill
                    result = await self.playwright_backend.fill(
                        field.selector,
                        resolved_value,
                    )
                
                if not result.success and not field.optional:
                    logger.error(f"Failed to fill field '{field.name}'")
                    return False
                
                # Small delay between fields
                await asyncio.sleep(0.1)
                
            except Exception as e:
                if field.optional:
                    logger.warning(f"Optional field failed: {field.name}: {e}")
                else:
                    logger.error(f"Field failed: {field.name}: {e}")
                    return False
        
        # Submit the form
        submit_config = form_config.submit
        
        logger.info("Submitting search form")
        
        if submit_config.method == "click" and submit_config.selector:
            result = await self.playwright_backend.click(
                submit_config.selector,
                wait_for=submit_config.wait_for,
                timeout_ms=submit_config.wait_timeout_ms,
            )
            
            if not result.success:
                logger.error(f"Submit click failed: {result.error}")
                return False
        
        elif submit_config.method == "enter":
            page = await self.playwright_backend._get_page()
            await page.keyboard.press("Enter")
        
        # Wait for results
        if submit_config.wait_for:
            success = await self.playwright_backend.wait_for_selector(
                submit_config.wait_for,
                timeout_ms=submit_config.wait_timeout_ms,
            )
            if not success:
                logger.warning(f"Results not found after submit: {submit_config.wait_for}")
        else:
            # Default wait for page to stabilize
            await asyncio.sleep(2)
        
        return True
    
    async def _initialize_search(self) -> bool:
        """Navigate to search and fill form (first page only).
        
        Returns:
            True if initialization successful
        """
        if self._initialized:
            return True
        
        # Navigate to seed URL
        seed_url = self.config.seed_urls[0]
        logger.info(f"Navigating to seed URL: {seed_url}")
        
        await self.playwright_backend.fetch(
            RequestSpec(url=seed_url, timeout=self.config.backend.timeout_seconds)
        )
        
        # Execute navigation steps
        if not await self._execute_navigation_steps():
            return False
        
        # Fill and submit form
        if not await self._fill_search_form():
            return False
        
        self._initialized = True
        return True
    
    async def _handle_pagination(self) -> bool:
        """Handle browser-based pagination.
        
        Returns:
            True if next page loaded, False if no more pages
        """
        pagination = self.config.discovery.pagination
        
        if pagination.type.value == "none":
            return False
        
        page = await self.playwright_backend._get_page()
        
        if pagination.type.value == "click_next":
            # Find and click next button
            selector = pagination.next_button_selector or pagination.selector_hint
            
            if not selector:
                # Try common next button patterns
                selectors = [
                    "[aria-label*='Next']",
                    "[aria-label*='next']",
                    "button:has-text('Next')",
                    "a:has-text('Next')",
                    ".pagination-next",
                    ".next-page",
                    "a[rel='next']",
                ]
                for sel in selectors:
                    try:
                        exists = await page.query_selector(sel)
                        if exists:
                            selector = sel
                            break
                    except Exception:
                        continue
            
            if not selector:
                logger.debug("No next button selector found")
                return False
            
            # Check if button is disabled
            try:
                button = await page.query_selector(selector)
                if not button:
                    return False
                
                # Check for disabled state
                if pagination.disabled_class:
                    classes = await button.get_attribute("class") or ""
                    if pagination.disabled_class in classes:
                        logger.debug("Next button is disabled")
                        return False
                
                is_disabled = await button.get_attribute("disabled")
                if is_disabled is not None:
                    logger.debug("Next button is disabled")
                    return False
                
                # Click the button
                await button.click()
                
                # Wait for new content
                if pagination.wait_for_selector:
                    await page.wait_for_selector(
                        pagination.wait_for_selector,
                        timeout=pagination.wait_after_click_ms,
                    )
                else:
                    await asyncio.sleep(pagination.wait_after_click_ms / 1000)
                
                return True
                
            except Exception as e:
                logger.debug(f"Pagination click failed: {e}")
                return False
        
        elif pagination.type.value == "load_more":
            selector = pagination.next_button_selector or "button:has-text('Load More')"
            
            try:
                button = await page.query_selector(selector)
                if not button:
                    return False
                
                await button.click()
                await asyncio.sleep(pagination.wait_after_click_ms / 1000)
                return True
                
            except Exception:
                return False
        
        elif pagination.type.value == "infinite_scroll":
            container = pagination.scroll_container or "body"
            item_selector = pagination.item_selector
            
            try:
                # Get current item count
                initial_count = 0
                if item_selector:
                    items = await page.query_selector_all(item_selector)
                    initial_count = len(items)
                
                # Scroll down
                await page.evaluate(
                    f"document.querySelector('{container}').scrollBy(0, window.innerHeight)"
                )
                
                # Wait for new items
                await asyncio.sleep(pagination.scroll_pause_ms / 1000)
                
                # Check if new items loaded
                if item_selector:
                    items = await page.query_selector_all(item_selector)
                    new_count = len(items)
                    return new_count > initial_count
                
                return True  # Assume success if no item selector
                
            except Exception:
                return False
        
        return False
    
    async def scrape_listing_page(self, url: str) -> PageResult:
        """Scrape a listing page.
        
        For SearchFormPortal, this scrapes the current browser state
        rather than navigating to a URL (pagination is handled internally).
        
        Args:
            url: URL (may be ignored for search form portals)
            
        Returns:
            PageResult with extracted items
        """
        errors: list[str] = []
        
        # Initialize search on first call
        if not self._initialized:
            success = await self._initialize_search()
            if not success:
                return PageResult(
                    items=[],
                    errors=["Failed to initialize search"],
                )
        
        # Get current page content
        html = await self.playwright_backend.get_page_content()
        current_url = await self.playwright_backend.get_page_url()
        
        if not html:
            return PageResult(
                items=[],
                errors=["Empty page content"],
            )
        
        # Extract table data
        extraction = self.extractor.extract(html, current_url)
        
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
            
            if item.has_id:
                items.append(item)
        
        self._current_page += 1
        
        return PageResult(
            items=items,
            page_number=self._current_page,
            next_page_url=None,  # We handle pagination internally
            extraction_confidence=extraction.confidence,
            errors=errors,
        )
    
    async def scrape_detail_page(self, url: str) -> dict[str, Any]:
        """Scrape a detail page for additional opportunity data.
        
        Args:
            url: URL of the detail page
            
        Returns:
            Dictionary of extracted fields
        """
        # Fetch the detail page
        try:
            result = await self.playwright_backend.fetch(
                RequestSpec(
                    url=url,
                    portal_name=self.config.name,
                    page_type="detail",
                    timeout=self.config.backend.timeout_seconds,
                )
            )
            
            if not result.ok:
                return {"_error": f"Fetch failed: {result.status_code}"}
        
        except Exception as e:
            return {"_error": f"Fetch error: {str(e)}"}
        
        html = result.html
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
            for key, value in heuristic_data.items():
                if key not in data:
                    data[key] = value
        
        data["source_url"] = url
        data["confidence"] = 0.7 if data else 0.3
        
        return data
    
    def _extract_field(
        self,
        tree: lxml_html.HtmlElement,
        rule: Any,
        base_url: str,
    ) -> str | None:
        """Extract a single field using configured rules."""
        for selector in rule.selectors:
            try:
                elements = tree.cssselect(selector)
                if not elements:
                    elements = tree.xpath(selector)
                
                if elements:
                    element = elements[0]
                    
                    if rule.attribute:
                        value = element.get(rule.attribute)
                        if value and rule.attribute == "href":
                            value = urljoin(base_url, value)
                    else:
                        value = self._get_text_content(element)
                    
                    if value:
                        if rule.regex:
                            import re
                            match = re.search(rule.regex, value)
                            if match:
                                value = match.group(1) if match.groups() else match.group(0)
                        
                        if rule.clean:
                            value = " ".join(value.split())
                        
                        return value
            except Exception:
                continue
        
        return None
    
    def _heuristic_detail_extraction(self, tree: lxml_html.HtmlElement) -> dict[str, Any]:
        """Extract data from detail page using heuristics."""
        data: dict[str, Any] = {}
        
        label_patterns = {
            "title": ["title", "solicitation title", "project name", "bid title"],
            "external_id": ["solicitation number", "bid number", "rfp number", "id", "number"],
            "closing_at": ["closing date", "due date", "deadline", "close date", "end date"],
            "posted_at": ["posted date", "publish date", "open date", "issue date"],
            "status": ["status", "bid status", "state"],
            "agency": ["agency", "department", "organization", "buyer", "ministry"],
            "category": ["category", "type", "commodity", "classification"],
            "description": ["description", "scope", "details", "summary"],
            "contact_name": ["contact", "buyer name", "procurement officer"],
            "contact_email": ["email", "contact email"],
            "estimated_value": ["estimated value", "budget", "value", "amount"],
        }
        
        # Look for definition lists
        for dt in tree.cssselect("dt"):
            label = self._get_text_content(dt).lower().strip()
            dd = dt.getnext()
            if dd is not None and dd.tag == "dd":
                value = self._get_text_content(dd)
                field = self._match_label(label, label_patterns)
                if field and value:
                    data[field] = value
        
        # Look for table rows
        for row in tree.cssselect("tr"):
            cells = row.cssselect("th, td")
            if len(cells) >= 2:
                label = self._get_text_content(cells[0]).lower().strip()
                value = self._get_text_content(cells[1])
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
    
    async def scrape_all_pages(
        self,
        start_url: str | None = None,
        max_pages: int | None = None,
    ) -> AsyncIterator[PageResult]:
        """Iterate through all listing pages using browser-based pagination.
        
        Args:
            start_url: Starting URL (uses seed URL if not provided)
            max_pages: Maximum pages to scrape
            
        Yields:
            PageResult for each page
        """
        max_pages = max_pages or self.config.discovery.pagination.max_pages
        
        page_num = 0
        
        while page_num < max_pages:
            page_num += 1
            
            # Scrape current page
            result = await self.scrape_listing_page(start_url or "")
            result.page_number = page_num
            
            yield result
            
            # If we got an error or no items, stop
            if result.errors or not result.items:
                logger.info(f"Stopping pagination at page {page_num}: "
                          f"errors={len(result.errors)}, items={len(result.items)}")
                break
            
            # Try to navigate to next page
            has_next = await self._handle_pagination()
            
            if not has_next:
                logger.info(f"No more pages after page {page_num}")
                break
            
            # Small delay before processing next page
            await asyncio.sleep(0.5)
