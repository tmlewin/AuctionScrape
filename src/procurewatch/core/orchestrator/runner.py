"""
Scrape runner orchestrator.

Coordinates the full scraping workflow: fetch → extract → normalize → persist.
"""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TYPE_CHECKING

from procurewatch.core.config.models import PortalConfig, PortalType, BackendType
from procurewatch.core.backends.http_backend import HttpBackend
from procurewatch.core.backends.playwright_backend import PlaywrightBackend
from procurewatch.core.portals.base import PortalPlugin, OpportunityDraft
from procurewatch.core.portals.generic_table import GenericTablePortal
from procurewatch.core.normalize import normalize_opportunity, compute_fingerprint, compute_diff, detect_event_type
from procurewatch.persistence.models import Portal, Opportunity, OpportunityEvent, ScrapeRun, PageSnapshot
from procurewatch.persistence.db import get_sync_session

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)


@dataclass
class RunStats:
    """Statistics for a scrape run."""
    
    pages_scraped: int = 0
    pages_failed: int = 0
    opportunities_found: int = 0
    opportunities_new: int = 0
    opportunities_updated: int = 0
    opportunities_unchanged: int = 0
    errors_count: int = 0
    
    started_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None
    
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    
    @property
    def duration_seconds(self) -> float | None:
        """Get run duration in seconds."""
        if self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "pages_scraped": self.pages_scraped,
            "pages_failed": self.pages_failed,
            "opportunities_found": self.opportunities_found,
            "opportunities_new": self.opportunities_new,
            "opportunities_updated": self.opportunities_updated,
            "opportunities_unchanged": self.opportunities_unchanged,
            "errors_count": self.errors_count,
            "duration_seconds": self.duration_seconds,
        }


@dataclass
class RunContext:
    """Context for a scrape run."""
    
    portal_config: PortalConfig
    portal_db: Portal
    run_db: ScrapeRun
    session: Session
    stats: RunStats = field(default_factory=RunStats)
    
    # Configuration
    max_pages: int | None = None
    follow_details: bool = True
    dry_run: bool = False
    
    # Checkpoint for resume
    checkpoint: dict[str, Any] = field(default_factory=dict)


class ScrapeRunner:
    """Orchestrates the complete scraping workflow.
    
    Coordinates:
    - Backend selection and initialization
    - Portal plugin selection
    - Page iteration and extraction
    - Normalization and change detection
    - Database persistence
    - Error handling and snapshots
    """
    
    def __init__(
        self,
        portal_config: PortalConfig,
        *,
        session: Session | None = None,
        dry_run: bool = False,
    ) -> None:
        """Initialize the scrape runner.
        
        Args:
            portal_config: Portal configuration
            session: Database session (will create if not provided)
            dry_run: If True, don't persist changes
        """
        self.config = portal_config
        self._session = session
        self._owns_session = session is None
        self.dry_run = dry_run
        
        # Will be initialized when run starts
        self.backend: HttpBackend | PlaywrightBackend | None = None
        self.plugin: PortalPlugin | None = None
        self.context: RunContext | None = None
    
    async def run(
        self,
        max_pages: int | None = None,
        follow_details: bool | None = None,
        run_type: str = "manual",
    ) -> RunStats:
        """Execute a complete scrape run.
        
        Args:
            max_pages: Maximum pages to scrape (overrides config)
            follow_details: Follow detail page links (overrides config)
            run_type: Type of run (manual, scheduled, test)
            
        Returns:
            RunStats with execution statistics
        """
        stats = RunStats()
        
        try:
            # Get or create session
            session = self._session or get_sync_session()
            
            # Get or create portal record
            portal_db = self._get_or_create_portal(session)
            
            # Create run record
            run_db = ScrapeRun(
                portal_id=portal_db.id,
                run_type=run_type,
                status="RUNNING",
                started_at=datetime.utcnow(),
            )
            session.add(run_db)
            session.commit()
            
            # Create context
            self.context = RunContext(
                portal_config=self.config,
                portal_db=portal_db,
                run_db=run_db,
                session=session,
                stats=stats,
                max_pages=max_pages,
                follow_details=follow_details if follow_details is not None else self.config.discovery.follow_detail_pages,
                dry_run=self.dry_run,
            )
            
            # Initialize backend
            self.backend = self._create_backend()
            
            # Initialize plugin
            self.plugin = self._create_plugin()
            
            # Execute scraping
            await self._execute_scrape()
            
            # Mark run as complete
            run_db.status = "COMPLETED"
            run_db.finished_at = datetime.utcnow()
            run_db.pages_scraped = stats.pages_scraped
            run_db.pages_failed = stats.pages_failed
            run_db.opportunities_found = stats.opportunities_found
            run_db.opportunities_new = stats.opportunities_new
            run_db.opportunities_updated = stats.opportunities_updated
            run_db.errors_count = stats.errors_count
            
            # Update portal stats
            portal_db.last_scraped_at = datetime.utcnow()
            portal_db.last_success_at = datetime.utcnow()
            portal_db.total_runs += 1
            
            session.commit()
            
        except Exception as e:
            stats.errors_count += 1
            stats.errors.append(str(e))
            
            logger.exception(f"Scrape run failed for {self.config.name}")
            
            # Update run status
            if self.context and self.context.run_db:
                self.context.run_db.status = "FAILED"
                self.context.run_db.finished_at = datetime.utcnow()
                self.context.run_db.error_message = str(e)
                self.context.run_db.error_traceback = traceback.format_exc()
                self.context.run_db.errors_count = stats.errors_count
                self.context.session.commit()
        
        finally:
            stats.finished_at = datetime.utcnow()
            
            # Close backend
            if self.backend:
                await self.backend.close()
            
            # Close session if we own it
            if self._owns_session and self._session:
                self._session.close()
        
        return stats
    
    async def _execute_scrape(self) -> None:
        """Execute the main scraping loop."""
        if not self.plugin or not self.context:
            raise RuntimeError("Runner not initialized")
        
        stats = self.context.stats
        
        # Iterate through all pages
        async for page in self.plugin.scrape_all_pages(
            max_pages=self.context.max_pages
        ):
            stats.pages_scraped += 1
            
            if page.errors:
                stats.pages_failed += 1
                stats.errors.extend(page.errors)
                stats.errors_count += len(page.errors)
                continue
            
            # Process each item on the page
            for item in page.items:
                stats.opportunities_found += 1
                
                # Create draft
                draft = OpportunityDraft(
                    listing_data=item.to_dict(),
                    source_url=self.config.seed_urls[0],
                    detail_url=item.detail_url,
                    extraction_confidence=item.confidence,
                )
                
                # Follow detail page if configured
                if self.context.follow_details and item.detail_url:
                    try:
                        detail_data = await self.plugin.scrape_detail_page(item.detail_url)
                        draft.detail_data = detail_data
                    except Exception as e:
                        stats.warnings.append(f"Detail page failed: {item.detail_url}: {e}")
                
                # Normalize and persist
                try:
                    event_type = await self._persist_opportunity(draft)
                    if event_type == "NEW":
                        stats.opportunities_new += 1
                    elif event_type == "UPDATED":
                        stats.opportunities_updated += 1
                    else:
                        stats.opportunities_unchanged += 1
                except Exception as e:
                    stats.errors_count += 1
                    stats.errors.append(f"Persist failed: {e}")
            
            logger.info(
                f"Page {page.page_number}: {len(page.items)} items, "
                f"next={page.next_page_url is not None}"
            )
    
    async def _persist_opportunity(self, draft: OpportunityDraft) -> str:
        """Normalize and persist an opportunity.
        
        Returns:
            Event type: NEW, UPDATED, or UNCHANGED
        """
        if not self.context:
            raise RuntimeError("Runner not initialized")
        
        session = self.context.session
        portal_db = self.context.portal_db
        run_db = self.context.run_db
        
        # Normalize the data
        canonical = normalize_opportunity(
            draft.merged_data(),
            portal_name=self.config.name,
            source_url=draft.source_url,
        )
        
        # Compute fingerprint
        fingerprint = compute_fingerprint(canonical)
        
        # Check if opportunity exists
        existing = session.query(Opportunity).filter(
            Opportunity.portal_id == portal_db.id,
            Opportunity.external_id == canonical.external_id,
        ).first()
        
        if existing:
            # Check for changes
            if existing.fingerprint == fingerprint:
                # No changes - just update last_seen
                existing.last_seen_at = datetime.utcnow()
                if not self.dry_run:
                    session.commit()
                return "UNCHANGED"
            
            # Has changes - compute diff
            old_data = {
                "external_id": existing.external_id,
                "title": existing.title,
                "description": existing.description,
                "status": existing.status,
                "category": existing.category,
                "agency": existing.agency,
                "closing_at": existing.closing_at,
                "estimated_value": existing.estimated_value,
            }
            
            diff = compute_diff(old_data, canonical.to_dict())
            event_type = detect_event_type(old_data, canonical.to_dict())
            
            if self.dry_run:
                # In dry run, just return the event type without persisting
                return "UPDATED"
            
            # Update the opportunity
            existing.title = canonical.title
            existing.description = canonical.description
            existing.description_markdown = canonical.description_markdown
            existing.posted_at = canonical.posted_at
            existing.closing_at = canonical.closing_at
            existing.awarded_at = canonical.awarded_at
            existing.status = canonical.status
            existing.category = canonical.category
            existing.commodity_codes = ",".join(canonical.commodity_codes) if canonical.commodity_codes else None
            existing.agency = canonical.agency
            existing.department = canonical.department
            existing.location = canonical.location
            existing.contact_name = canonical.contact_name
            existing.contact_email = canonical.contact_email
            existing.contact_phone = canonical.contact_phone
            existing.estimated_value = float(canonical.estimated_value) if canonical.estimated_value else None
            existing.estimated_value_currency = canonical.estimated_value_currency
            existing.award_amount = float(canonical.award_amount) if canonical.award_amount else None
            existing.awardee = canonical.awardee
            existing.source_url = canonical.source_url
            existing.detail_url = canonical.detail_url
            existing.raw_data = canonical.raw_data
            existing.extraction_confidence = canonical.extraction_confidence
            existing.fingerprint = fingerprint
            existing.last_seen_at = datetime.utcnow()
            
            # Create event
            event = OpportunityEvent(
                opportunity_id=existing.id,
                run_id=run_db.id,
                event_type=event_type,
                diff=diff.to_dict(),
                message=diff.summary,
            )
            session.add(event)
            
            session.commit()
            
            return "UPDATED"
        
        else:
            # New opportunity
            if self.dry_run:
                # In dry run, just count without persisting
                return "NEW"
            
            opp = Opportunity(
                portal_id=portal_db.id,
                external_id=canonical.external_id,
                fingerprint=fingerprint,
                title=canonical.title,
                description=canonical.description,
                description_markdown=canonical.description_markdown,
                posted_at=canonical.posted_at,
                closing_at=canonical.closing_at,
                awarded_at=canonical.awarded_at,
                status=canonical.status,
                category=canonical.category,
                commodity_codes=",".join(canonical.commodity_codes) if canonical.commodity_codes else None,
                agency=canonical.agency,
                department=canonical.department,
                location=canonical.location,
                contact_name=canonical.contact_name,
                contact_email=canonical.contact_email,
                contact_phone=canonical.contact_phone,
                estimated_value=float(canonical.estimated_value) if canonical.estimated_value else None,
                estimated_value_currency=canonical.estimated_value_currency,
                award_amount=float(canonical.award_amount) if canonical.award_amount else None,
                awardee=canonical.awardee,
                source_url=canonical.source_url,
                detail_url=canonical.detail_url,
                raw_data=canonical.raw_data,
                extraction_confidence=canonical.extraction_confidence,
                last_seen_at=datetime.utcnow(),
            )
            session.add(opp)
            session.flush()  # Get the ID
            
            # Create NEW event
            event = OpportunityEvent(
                opportunity_id=opp.id,
                run_id=run_db.id,
                event_type="NEW",
                message=f"New opportunity: {canonical.title or canonical.external_id}",
            )
            session.add(event)
            
            # Update portal count
            portal_db.total_opportunities += 1
            
            session.commit()
            
            return "NEW"
    
    def _get_or_create_portal(self, session: Session) -> Portal:
        """Get or create the portal database record."""
        portal = session.query(Portal).filter(
            Portal.name == self.config.name
        ).first()
        
        if not portal:
            portal = Portal(
                name=self.config.name,
                display_name=self.config.display_name,
                base_url=str(self.config.base_url),
                portal_type=self.config.portal_type.value,
                enabled=self.config.enabled,
            )
            session.add(portal)
            session.commit()
        
        return portal
    
    def _create_backend(self) -> HttpBackend | PlaywrightBackend:
        """Create the appropriate backend based on config.
        
        Backend selection logic:
        1. Use preferred backend from config
        2. For search_form portal type, force PlaywrightBackend
        3. Fall back to HttpBackend if Playwright fails/unavailable
        
        Returns:
            Appropriate backend instance
        """
        from procurewatch.core.backends.playwright_backend import PlaywrightBackend
        
        backend_config = self.config.backend
        politeness = self.config.politeness
        portal_type = self.config.portal_type
        
        # Determine which backend to use
        use_playwright = (
            backend_config.preferred == BackendType.PLAYWRIGHT
            or portal_type == PortalType.SEARCH_FORM
        )
        
        if use_playwright:
            # Create Playwright backend
            playwright_config = self.config.playwright
            
            # Determine cookie path
            cookies_path = None
            if playwright_config.cookies_persist:
                if playwright_config.cookies_path:
                    cookies_path = playwright_config.cookies_path
                else:
                    cookies_path = f"data/cookies/{self.config.name}.json"
            
            # Determine screenshots path
            screenshots_path = None
            if playwright_config.screenshots_on_error:
                if playwright_config.screenshots_path:
                    screenshots_path = playwright_config.screenshots_path
                else:
                    screenshots_path = f"snapshots/{self.config.name}"
            
            logger.info(f"Using PlaywrightBackend for portal: {self.config.name}")
            
            return PlaywrightBackend(
                headless=backend_config.headless,
                timeout=backend_config.timeout_seconds,
                browser_type=playwright_config.browser,
                viewport_width=playwright_config.viewport_width,
                viewport_height=playwright_config.viewport_height,
                user_agent=playwright_config.user_agent,
                stealth=playwright_config.stealth,
                cookies_path=cookies_path,
                screenshots_path=screenshots_path,
                screenshots_on_error=playwright_config.screenshots_on_error,
            )
        
        # Default to HTTP backend
        logger.info(f"Using HttpBackend for portal: {self.config.name}")
        
        return HttpBackend(
            timeout=backend_config.timeout_seconds,
            max_retries=politeness.max_retries,
            retry_backoff=politeness.retry_backoff_factor,
        )
    
    def _create_plugin(self) -> PortalPlugin:
        """Create the appropriate plugin based on portal type.
        
        Portal type to plugin mapping:
        - GENERIC_TABLE -> GenericTablePortal
        - SEARCH_FORM -> SearchFormPortal
        - GENERIC_CARDS -> GenericTablePortal (fallback for now)
        - API_BASED -> GenericTablePortal (fallback for now)
        - CUSTOM -> GenericTablePortal (fallback for now)
        
        Returns:
            Appropriate portal plugin instance
        """
        from procurewatch.core.portals.search_form import SearchFormPortal
        
        if not self.backend:
            raise RuntimeError("Backend not initialized")
        
        portal_type = self.config.portal_type
        
        if portal_type == PortalType.GENERIC_TABLE:
            logger.debug(f"Using GenericTablePortal for: {self.config.name}")
            return GenericTablePortal(self.config, self.backend)
        
        elif portal_type == PortalType.SEARCH_FORM:
            # SearchFormPortal requires PlaywrightBackend
            if not self.backend.supports_javascript:
                raise RuntimeError(
                    f"Portal '{self.config.name}' is type search_form but backend "
                    f"'{self.backend.name}' does not support JavaScript. "
                    "Set backend.preferred: playwright in portal config."
                )
            
            logger.debug(f"Using SearchFormPortal for: {self.config.name}")
            return SearchFormPortal(self.config, self.backend)  # type: ignore
        
        elif portal_type == PortalType.GENERIC_CARDS:
            # TODO: Implement GenericCardsPortal
            logger.warning(f"generic_cards not implemented, using GenericTablePortal")
            return GenericTablePortal(self.config, self.backend)
        
        elif portal_type == PortalType.API_BASED:
            # TODO: Implement APIPortal
            logger.warning(f"api_based not implemented, using GenericTablePortal")
            return GenericTablePortal(self.config, self.backend)
        
        else:
            # Default fallback
            logger.warning(f"Unknown portal type {portal_type}, using GenericTablePortal")
            return GenericTablePortal(self.config, self.backend)


async def run_portal_scrape(
    portal_name: str,
    *,
    max_pages: int | None = None,
    follow_details: bool | None = None,
    dry_run: bool = False,
) -> RunStats:
    """Convenience function to scrape a portal by name.
    
    Args:
        portal_name: Portal configuration name
        max_pages: Maximum pages to scrape
        follow_details: Follow detail page links
        dry_run: Don't persist changes
        
    Returns:
        RunStats with execution statistics
    """
    from procurewatch.core.config.loader import load_portal_config
    
    config = load_portal_config(portal_name)
    runner = ScrapeRunner(config, dry_run=dry_run)
    
    return await runner.run(
        max_pages=max_pages,
        follow_details=follow_details,
    )
