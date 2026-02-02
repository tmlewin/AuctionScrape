"""
Playwright Backend implementation for browser automation.

Provides async browser-based fetching with:
- JavaScript rendering
- Cookie persistence across sessions
- Form filling (text, select, checkbox, date)
- Screenshot capture on errors
- Stealth mode for bot detection avoidance
- Human-in-the-loop pause for login/captcha
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .base import (
    Backend,
    BackendError,
    BlockedError,
    FetchResult,
    RenderResult,
    RequestSpec,
)

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright

logger = logging.getLogger(__name__)


# =============================================================================
# Playwright-specific data structures
# =============================================================================


@dataclass
class BrowserAction:
    """Specification for a browser action."""
    
    action: str  # click, fill, select, check, wait, scroll, etc.
    selector: str | None = None
    value: str | None = None
    wait_for: str | None = None
    timeout_ms: int = 30000
    optional: bool = False


@dataclass
class ActionResult:
    """Result of a browser action."""
    
    success: bool
    action: str
    selector: str | None = None
    error: str | None = None
    screenshot_path: str | None = None


@dataclass
class FormField:
    """Specification for a form field to fill."""
    
    selector: str
    value: str
    field_type: str = "text"  # text, select, checkbox, radio, date
    clear_first: bool = True
    optional: bool = False


@dataclass
class FormResult:
    """Result of form filling operation."""
    
    success: bool
    fields_filled: int = 0
    fields_failed: list[str] = field(default_factory=list)
    screenshot_path: str | None = None


# =============================================================================
# Browser Error Classes
# =============================================================================


class BrowserError(BackendError):
    """Base exception for browser errors."""
    pass


class NavigationTimeout(BrowserError):
    """Page didn't load in time."""
    pass


class ElementNotFound(BrowserError):
    """Selector didn't match any element."""
    pass


class ActionFailed(BrowserError):
    """Click/fill/submit failed."""
    pass


class PageBlocked(BrowserError):
    """Bot detection or access denied."""
    pass


# =============================================================================
# Stealth Script
# =============================================================================


STEALTH_SCRIPT = """
// Override navigator.webdriver - primary detection method
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});

// Override navigator.plugins to look like a real browser
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
        { name: 'Native Client', filename: 'internal-nacl-plugin' }
    ]
});

// Override navigator.languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en']
});

// Add Chrome runtime
window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {}
};

// Override permissions query
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);

// Override WebGL vendor/renderer
const getParameterProxyHandler = {
    apply: function(target, thisArg, args) {
        const param = args[0];
        const gl = thisArg;
        if (param === 37445) {  // UNMASKED_VENDOR_WEBGL
            return 'Google Inc. (NVIDIA)';
        }
        if (param === 37446) {  // UNMASKED_RENDERER_WEBGL
            return 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1080 Direct3D11 vs_5_0 ps_5_0, D3D11)';
        }
        return Reflect.apply(target, thisArg, args);
    }
};

try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl') || canvas.getContext('webgl2');
    if (gl) {
        gl.getParameter = new Proxy(gl.getParameter, getParameterProxyHandler);
    }
} catch (e) {}

// Console log protection
console.log = (function(originalLog) {
    return function() {
        // Filter out automation detection logs
        return originalLog.apply(console, arguments);
    };
})(console.log);
"""


# =============================================================================
# PlaywrightBackend Implementation
# =============================================================================


class PlaywrightBackend(Backend):
    """Playwright-based browser automation backend.
    
    Features:
    - JavaScript rendering for dynamic pages
    - Cookie/session persistence across runs
    - Form filling (text, select, checkbox, date)
    - Screenshot capture on errors
    - Stealth mode for bot detection avoidance
    - Human-in-the-loop pause for login/captcha
    """
    
    def __init__(
        self,
        headless: bool = True,
        timeout: float = 30.0,
        browser_type: str = "chromium",
        viewport_width: int = 1920,
        viewport_height: int = 1080,
        user_agent: str | None = None,
        stealth: bool = True,
        cookies_path: Path | str | None = None,
        screenshots_path: Path | str | None = None,
        screenshots_on_error: bool = True,
    ):
        """Initialize Playwright backend.
        
        Args:
            headless: Run browser in headless mode
            timeout: Default timeout in seconds
            browser_type: Browser to use (chromium, firefox, webkit)
            viewport_width: Browser viewport width
            viewport_height: Browser viewport height
            user_agent: Custom user agent string
            stealth: Enable stealth mode for bot detection avoidance
            cookies_path: Path to persist cookies
            screenshots_path: Directory for error screenshots
            screenshots_on_error: Capture screenshots on errors
        """
        self.headless = headless
        self.timeout = timeout
        self.timeout_ms = int(timeout * 1000)
        self.browser_type = browser_type
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.stealth = stealth
        self.screenshots_on_error = screenshots_on_error
        
        # Default user agent
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        
        # Cookie persistence
        if cookies_path:
            self.cookies_path = Path(cookies_path)
            self.cookies_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self.cookies_path = None
        
        # Screenshots directory
        if screenshots_path:
            self.screenshots_path = Path(screenshots_path)
            self.screenshots_path.mkdir(parents=True, exist_ok=True)
        else:
            self.screenshots_path = Path("snapshots")
            self.screenshots_path.mkdir(parents=True, exist_ok=True)
        
        # Playwright objects (initialized on first use)
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
    
    @property
    def name(self) -> str:
        return "playwright"
    
    @property
    def supports_javascript(self) -> bool:
        return True
    
    async def _ensure_browser(self) -> None:
        """Initialize browser if not already running."""
        if self._browser is not None and self._browser.is_connected():
            return
        
        # Import playwright here to avoid import errors if not installed
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise BackendError(
                "Playwright is not installed. Run: playwright install chromium",
                cause=e,
            ) from e
        
        # Start playwright
        self._playwright = await async_playwright().start()
        
        # Select browser type
        if self.browser_type == "firefox":
            browser_launcher = self._playwright.firefox
        elif self.browser_type == "webkit":
            browser_launcher = self._playwright.webkit
        else:
            browser_launcher = self._playwright.chromium
        
        # Launch arguments for stealth
        launch_args = []
        if self.stealth:
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--disable-extensions",
                f"--window-size={self.viewport_width},{self.viewport_height}",
            ]
        
        # Launch browser
        try:
            self._browser = await browser_launcher.launch(
                headless=self.headless,
                args=launch_args if self.browser_type == "chromium" else [],
            )
        except Exception as e:
            raise BackendError(
                f"Failed to launch {self.browser_type} browser. "
                "Run: playwright install chromium",
                cause=e,
            ) from e
        
        logger.info(f"Launched {self.browser_type} browser (headless={self.headless})")
    
    async def _ensure_context(self) -> BrowserContext:
        """Get or create browser context with cookie persistence."""
        await self._ensure_browser()
        
        if self._context is not None:
            return self._context
        
        # Context options
        context_options: dict[str, Any] = {
            "viewport": {"width": self.viewport_width, "height": self.viewport_height},
            "user_agent": self.user_agent,
            "locale": "en-US",
            "timezone_id": "America/New_York",
        }
        
        # Load saved storage state (cookies + localStorage)
        if self.cookies_path and self.cookies_path.exists():
            try:
                context_options["storage_state"] = str(self.cookies_path)
                logger.info(f"Loading cookies from {self.cookies_path}")
            except Exception as e:
                logger.warning(f"Failed to load cookies: {e}")
        
        # Create context
        self._context = await self._browser.new_context(**context_options)  # type: ignore
        
        # Add stealth scripts
        if self.stealth:
            await self._context.add_init_script(STEALTH_SCRIPT)
        
        return self._context
    
    async def _get_page(self) -> Page:
        """Get or create a page."""
        context = await self._ensure_context()
        
        if self._page is None or self._page.is_closed():
            self._page = await context.new_page()
            
            # Set default timeout
            self._page.set_default_timeout(self.timeout_ms)
        
        return self._page
    
    async def _save_cookies(self) -> None:
        """Save cookies to file for persistence."""
        if not self.cookies_path or not self._context:
            return
        
        try:
            await self._context.storage_state(path=str(self.cookies_path))
            logger.debug(f"Saved cookies to {self.cookies_path}")
        except Exception as e:
            logger.warning(f"Failed to save cookies: {e}")
    
    async def _capture_screenshot(self, page: Page, prefix: str = "error") -> str | None:
        """Capture screenshot for debugging."""
        if not self.screenshots_on_error:
            return None
        
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{prefix}_{timestamp}.png"
            filepath = self.screenshots_path / filename
            
            await page.screenshot(path=str(filepath), full_page=True)
            logger.info(f"Screenshot saved: {filepath}")
            
            return str(filepath)
        except Exception as e:
            logger.warning(f"Failed to capture screenshot: {e}")
            return None
    
    async def fetch(self, request: RequestSpec) -> FetchResult:
        """Fetch a URL with JavaScript rendering.
        
        Args:
            request: Request specification
            
        Returns:
            FetchResult with rendered content
        """
        page = await self._get_page()
        start_time = datetime.utcnow()
        screenshot_path: str | None = None
        
        try:
            # Navigate to URL
            response = await page.goto(
                request.url,
                timeout=int(request.timeout * 1000),
                wait_until="networkidle",
            )
            
            if response is None:
                raise NavigationTimeout(f"No response from {request.url}", url=request.url)
            
            # Wait for page to stabilize
            await page.wait_for_load_state("networkidle")
            
            # Get page content
            html = await page.content()
            final_url = page.url
            status_code = response.status if response else 200
            
            # Check for blocking
            if status_code in {403, 406, 418, 451}:
                screenshot_path = await self._capture_screenshot(page, "blocked")
                raise BlockedError(
                    f"Request blocked with status {status_code}",
                    url=request.url,
                    status_code=status_code,
                )
            
            # Check content for bot detection
            html_lower = html.lower()
            blocked_indicators = [
                "access denied",
                "captcha",
                "challenge-platform",
                "cf-browser-verification",
                "please verify you are human",
            ]
            
            for indicator in blocked_indicators:
                if indicator in html_lower and len(html) < 50000:
                    screenshot_path = await self._capture_screenshot(page, "blocked")
                    raise BlockedError(
                        f"Bot detection triggered: '{indicator}' found",
                        url=request.url,
                        status_code=status_code,
                    )
            
            # Calculate elapsed time
            elapsed_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            # Get cookies
            cookies = {}
            for cookie in await page.context.cookies():
                cookies[cookie["name"]] = cookie["value"]
            
            # Save cookies for persistence
            await self._save_cookies()
            
            return FetchResult(
                url=request.url,
                final_url=final_url,
                status_code=status_code,
                html=html,
                headers=dict(response.headers) if response else {},
                cookies=cookies,
                elapsed_ms=elapsed_ms,
            )
            
        except BlockedError:
            raise
        except Exception as e:
            # Capture error screenshot
            screenshot_path = await self._capture_screenshot(page, "error")
            
            elapsed_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            if "timeout" in str(e).lower():
                raise NavigationTimeout(
                    f"Navigation timeout: {request.url}",
                    url=request.url,
                    cause=e,
                ) from e
            
            raise BrowserError(
                f"Browser error: {e}",
                url=request.url,
                cause=e,
            ) from e
    
    async def render(self, request: RequestSpec) -> RenderResult:
        """Render page with JavaScript and return extended result.
        
        Args:
            request: Request specification
            
        Returns:
            RenderResult with HTML, screenshot, and console logs
        """
        page = await self._get_page()
        start_time = datetime.utcnow()
        console_logs: list[str] = []
        
        # Capture console logs
        page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))
        
        try:
            # Navigate
            response = await page.goto(
                request.url,
                timeout=int(request.timeout * 1000),
                wait_until="networkidle",
            )
            
            # Wait for stability
            await page.wait_for_load_state("networkidle")
            
            # Get content
            html = await page.content()
            final_url = page.url
            status_code = response.status if response else 200
            
            # Capture screenshot
            screenshot_path = await self._capture_screenshot(page, "render")
            
            # Get cookies
            cookies = {}
            for cookie in await page.context.cookies():
                cookies[cookie["name"]] = cookie["value"]
            
            elapsed_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            await self._save_cookies()
            
            return RenderResult(
                url=request.url,
                final_url=final_url,
                status_code=status_code,
                html=html,
                headers=dict(response.headers) if response else {},
                cookies=cookies,
                elapsed_ms=elapsed_ms,
                screenshot_path=screenshot_path,
                console_logs=console_logs,
            )
            
        except Exception as e:
            await self._capture_screenshot(page, "render_error")
            raise BrowserError(
                f"Render error: {e}",
                url=request.url,
                cause=e,
            ) from e
    
    async def click(
        self,
        selector: str,
        wait_for: str | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Click an element.
        
        Args:
            selector: CSS selector for element to click
            wait_for: Optional selector to wait for after click
            timeout_ms: Timeout in milliseconds
            
        Returns:
            ActionResult with success status
        """
        page = await self._get_page()
        timeout = timeout_ms or self.timeout_ms
        
        try:
            await page.click(selector, timeout=timeout)
            
            if wait_for:
                await page.wait_for_selector(wait_for, timeout=timeout)
            
            return ActionResult(success=True, action="click", selector=selector)
            
        except Exception as e:
            screenshot_path = await self._capture_screenshot(page, "click_error")
            return ActionResult(
                success=False,
                action="click",
                selector=selector,
                error=str(e),
                screenshot_path=screenshot_path,
            )
    
    async def fill(
        self,
        selector: str,
        value: str,
        clear_first: bool = True,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Fill a text input.
        
        Args:
            selector: CSS selector for input
            value: Value to fill
            clear_first: Clear existing value first
            timeout_ms: Timeout in milliseconds
            
        Returns:
            ActionResult with success status
        """
        page = await self._get_page()
        timeout = timeout_ms or self.timeout_ms
        
        try:
            if clear_first:
                await page.fill(selector, "", timeout=timeout)
            
            await page.fill(selector, value, timeout=timeout)
            
            return ActionResult(success=True, action="fill", selector=selector)
            
        except Exception as e:
            screenshot_path = await self._capture_screenshot(page, "fill_error")
            return ActionResult(
                success=False,
                action="fill",
                selector=selector,
                error=str(e),
                screenshot_path=screenshot_path,
            )
    
    async def select_option(
        self,
        selector: str,
        value: str | None = None,
        label: str | None = None,
        index: int | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Select an option from a dropdown.
        
        Args:
            selector: CSS selector for select element
            value: Option value to select
            label: Option label to select
            index: Option index to select
            timeout_ms: Timeout in milliseconds
            
        Returns:
            ActionResult with success status
        """
        page = await self._get_page()
        timeout = timeout_ms or self.timeout_ms
        
        try:
            if value:
                await page.select_option(selector, value=value, timeout=timeout)
            elif label:
                await page.select_option(selector, label=label, timeout=timeout)
            elif index is not None:
                await page.select_option(selector, index=index, timeout=timeout)
            else:
                raise ValueError("Must provide value, label, or index")
            
            return ActionResult(success=True, action="select", selector=selector)
            
        except Exception as e:
            screenshot_path = await self._capture_screenshot(page, "select_error")
            return ActionResult(
                success=False,
                action="select",
                selector=selector,
                error=str(e),
                screenshot_path=screenshot_path,
            )
    
    async def check(self, selector: str, timeout_ms: int | None = None) -> ActionResult:
        """Check a checkbox or radio button.
        
        Args:
            selector: CSS selector for checkbox/radio
            timeout_ms: Timeout in milliseconds
            
        Returns:
            ActionResult with success status
        """
        page = await self._get_page()
        timeout = timeout_ms or self.timeout_ms
        
        try:
            await page.check(selector, timeout=timeout)
            return ActionResult(success=True, action="check", selector=selector)
            
        except Exception as e:
            screenshot_path = await self._capture_screenshot(page, "check_error")
            return ActionResult(
                success=False,
                action="check",
                selector=selector,
                error=str(e),
                screenshot_path=screenshot_path,
            )
    
    async def wait_for_selector(
        self,
        selector: str,
        state: str = "visible",
        timeout_ms: int | None = None,
    ) -> bool:
        """Wait for element to appear.
        
        Args:
            selector: CSS selector
            state: Element state to wait for (visible, attached, hidden, detached)
            timeout_ms: Timeout in milliseconds
            
        Returns:
            True if element found, False if timeout
        """
        page = await self._get_page()
        timeout = timeout_ms or self.timeout_ms
        
        try:
            await page.wait_for_selector(selector, state=state, timeout=timeout)  # type: ignore
            return True
        except Exception:
            return False
    
    async def fill_form(self, fields: list[FormField]) -> FormResult:
        """Fill a complete form.
        
        Args:
            fields: List of FormField specifications
            
        Returns:
            FormResult with success status
        """
        page = await self._get_page()
        filled = 0
        failed: list[str] = []
        
        for field in fields:
            try:
                if field.field_type == "text":
                    result = await self.fill(
                        field.selector,
                        field.value,
                        clear_first=field.clear_first,
                    )
                elif field.field_type == "select":
                    result = await self.select_option(field.selector, label=field.value)
                elif field.field_type in ("checkbox", "radio"):
                    if field.value.lower() in ("true", "1", "yes"):
                        result = await self.check(field.selector)
                    else:
                        result = ActionResult(success=True, action="skip", selector=field.selector)
                elif field.field_type == "date":
                    # Date inputs often need special handling
                    result = await self.fill(field.selector, field.value)
                else:
                    result = await self.fill(field.selector, field.value)
                
                if result.success:
                    filled += 1
                else:
                    if not field.optional:
                        failed.append(f"{field.selector}: {result.error}")
                        
            except Exception as e:
                if not field.optional:
                    failed.append(f"{field.selector}: {str(e)}")
            
            # Small delay between fields to mimic human behavior
            await asyncio.sleep(0.1)
        
        screenshot_path = None
        if failed:
            screenshot_path = await self._capture_screenshot(page, "form_error")
        
        return FormResult(
            success=len(failed) == 0,
            fields_filled=filled,
            fields_failed=failed,
            screenshot_path=screenshot_path,
        )
    
    async def execute_actions(self, actions: list[BrowserAction]) -> list[ActionResult]:
        """Execute a sequence of browser actions.
        
        Args:
            actions: List of BrowserAction specifications
            
        Returns:
            List of ActionResult for each action
        """
        page = await self._get_page()
        results: list[ActionResult] = []
        
        for action in actions:
            try:
                if action.action == "click":
                    result = await self.click(
                        action.selector or "",
                        wait_for=action.wait_for,
                        timeout_ms=action.timeout_ms,
                    )
                elif action.action == "fill":
                    result = await self.fill(
                        action.selector or "",
                        action.value or "",
                        timeout_ms=action.timeout_ms,
                    )
                elif action.action == "select":
                    result = await self.select_option(
                        action.selector or "",
                        label=action.value,
                        timeout_ms=action.timeout_ms,
                    )
                elif action.action == "check":
                    result = await self.check(
                        action.selector or "",
                        timeout_ms=action.timeout_ms,
                    )
                elif action.action == "wait":
                    await asyncio.sleep(action.timeout_ms / 1000)
                    result = ActionResult(success=True, action="wait")
                elif action.action == "wait_for":
                    success = await self.wait_for_selector(
                        action.selector or "",
                        timeout_ms=action.timeout_ms,
                    )
                    result = ActionResult(
                        success=success,
                        action="wait_for",
                        selector=action.selector,
                    )
                elif action.action == "scroll":
                    await page.evaluate("window.scrollBy(0, window.innerHeight)")
                    result = ActionResult(success=True, action="scroll")
                elif action.action == "goto":
                    await page.goto(action.value or "", timeout=action.timeout_ms)
                    result = ActionResult(success=True, action="goto")
                else:
                    result = ActionResult(
                        success=False,
                        action=action.action,
                        error=f"Unknown action: {action.action}",
                    )
                
                results.append(result)
                
                if not result.success and not action.optional:
                    break
                    
            except Exception as e:
                result = ActionResult(
                    success=False,
                    action=action.action,
                    selector=action.selector,
                    error=str(e),
                )
                results.append(result)
                
                if not action.optional:
                    break
        
        return results
    
    async def get_cookies(self) -> list[dict[str, Any]]:
        """Get current cookies.
        
        Returns:
            List of cookie dictionaries
        """
        context = await self._ensure_context()
        return await context.cookies()
    
    async def set_cookies(self, cookies: list[dict[str, Any]]) -> None:
        """Set cookies.
        
        Args:
            cookies: List of cookie dictionaries
        """
        context = await self._ensure_context()
        await context.add_cookies(cookies)
    
    async def screenshot(self, path: str, full_page: bool = False) -> str:
        """Take a screenshot.
        
        Args:
            path: Path to save screenshot
            full_page: Capture full scrollable page
            
        Returns:
            Path to saved screenshot
        """
        page = await self._get_page()
        await page.screenshot(path=path, full_page=full_page)
        return path
    
    async def pause_for_human(self, message: str = "Please complete the action and press Enter...") -> None:
        """Pause for human intervention (login/captcha).
        
        Only works in headed mode.
        
        Args:
            message: Message to display
        """
        if self.headless:
            logger.warning("pause_for_human called in headless mode - skipping")
            return
        
        print(f"\n{'='*60}")
        print(f"HUMAN INTERVENTION REQUIRED")
        print(f"{'='*60}")
        print(f"\n{message}\n")
        
        # Wait for user input
        input("Press Enter when ready to continue...")
        
        # Give page time to update after human action
        await asyncio.sleep(1)
        
        # Save any new cookies
        await self._save_cookies()
    
    async def get_page_content(self) -> str:
        """Get current page HTML content.
        
        Returns:
            HTML content string
        """
        page = await self._get_page()
        return await page.content()
    
    async def get_page_url(self) -> str:
        """Get current page URL.
        
        Returns:
            Current URL
        """
        page = await self._get_page()
        return page.url
    
    async def close(self) -> None:
        """Close browser and clean up resources."""
        # Save cookies before closing
        await self._save_cookies()
        
        if self._page and not self._page.is_closed():
            await self._page.close()
            self._page = None
        
        if self._context:
            await self._context.close()
            self._context = None
        
        if self._browser:
            await self._browser.close()
            self._browser = None
        
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        
        logger.info("Playwright backend closed")
