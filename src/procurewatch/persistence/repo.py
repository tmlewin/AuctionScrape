"""
Repository pattern for database operations.

Provides clean abstractions for CRUD operations on domain models,
including upsert logic with change detection for opportunities.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, Sequence

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .models import (
    Document,
    Opportunity,
    OpportunityEvent,
    PageSnapshot,
    Portal,
    RunLock,
    ScheduledJob,
    ScrapeRun,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# =============================================================================
# Portal Repository
# =============================================================================


class PortalRepository:
    """Repository for Portal CRUD operations."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def get_by_id(self, portal_id: int) -> Portal | None:
        """Get portal by ID."""
        return self.session.get(Portal, portal_id)
    
    def get_by_name(self, name: str) -> Portal | None:
        """Get portal by unique name."""
        stmt = select(Portal).where(Portal.name == name)
        return self.session.execute(stmt).scalar_one_or_none()
    
    def get_all(self, enabled_only: bool = False) -> Sequence[Portal]:
        """Get all portals."""
        stmt = select(Portal)
        if enabled_only:
            stmt = stmt.where(Portal.enabled == True)  # noqa: E712
        stmt = stmt.order_by(Portal.name)
        return self.session.execute(stmt).scalars().all()
    
    def create(
        self,
        name: str,
        base_url: str,
        portal_type: str = "generic_table",
        display_name: str | None = None,
        config_hash: str | None = None,
    ) -> Portal:
        """Create a new portal."""
        portal = Portal(
            name=name,
            base_url=base_url,
            portal_type=portal_type,
            display_name=display_name,
            config_hash=config_hash,
        )
        self.session.add(portal)
        self.session.flush()
        return portal
    
    def upsert(
        self,
        name: str,
        base_url: str,
        portal_type: str = "generic_table",
        display_name: str | None = None,
        config_hash: str | None = None,
    ) -> tuple[Portal, bool]:
        """Create or update a portal.
        
        Returns:
            Tuple of (portal, created) where created is True if new
        """
        existing = self.get_by_name(name)
        
        if existing:
            existing.base_url = base_url
            existing.portal_type = portal_type
            existing.display_name = display_name
            existing.config_hash = config_hash
            self.session.flush()
            return existing, False
        
        portal = self.create(
            name=name,
            base_url=base_url,
            portal_type=portal_type,
            display_name=display_name,
            config_hash=config_hash,
        )
        return portal, True
    
    def update_last_scraped(self, portal_id: int, success: bool = True) -> None:
        """Update portal's last scraped timestamp."""
        stmt = (
            update(Portal)
            .where(Portal.id == portal_id)
            .values(
                last_scraped_at=datetime.utcnow(),
                last_success_at=datetime.utcnow() if success else Portal.last_success_at,
                total_runs=Portal.total_runs + 1,
            )
        )
        self.session.execute(stmt)
    
    def delete(self, portal_id: int) -> bool:
        """Delete a portal by ID."""
        portal = self.get_by_id(portal_id)
        if portal:
            self.session.delete(portal)
            return True
        return False


# =============================================================================
# Opportunity Repository
# =============================================================================


class OpportunityRepository:
    """Repository for Opportunity CRUD operations with change tracking."""
    
    # Fields to compare for change detection
    TRACKED_FIELDS = [
        "title",
        "description",
        "status",
        "closing_at",
        "posted_at",
        "category",
        "agency",
        "estimated_value",
        "contact_name",
        "contact_email",
        "awardee",
        "award_amount",
    ]
    
    def __init__(self, session: Session):
        self.session = session
    
    def get_by_id(self, opportunity_id: int) -> Opportunity | None:
        """Get opportunity by ID."""
        return self.session.get(Opportunity, opportunity_id)
    
    def get_by_external_id(self, portal_id: int, external_id: str) -> Opportunity | None:
        """Get opportunity by portal and external ID."""
        stmt = select(Opportunity).where(
            and_(
                Opportunity.portal_id == portal_id,
                Opportunity.external_id == external_id,
            )
        )
        return self.session.execute(stmt).scalar_one_or_none()
    
    def get_by_fingerprint(self, fingerprint: str) -> Opportunity | None:
        """Get opportunity by content fingerprint."""
        stmt = select(Opportunity).where(Opportunity.fingerprint == fingerprint)
        return self.session.execute(stmt).scalar_one_or_none()
    
    def list_opportunities(
        self,
        portal_id: int | None = None,
        status: str | None = None,
        closing_within_days: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Opportunity]:
        """List opportunities with filters."""
        stmt = select(Opportunity)
        
        conditions = []
        if portal_id is not None:
            conditions.append(Opportunity.portal_id == portal_id)
        if status is not None:
            conditions.append(Opportunity.status == status)
        if closing_within_days is not None:
            from datetime import timedelta
            cutoff = datetime.utcnow() + timedelta(days=closing_within_days)
            conditions.append(Opportunity.closing_at <= cutoff)
            conditions.append(Opportunity.closing_at >= datetime.utcnow())
        
        if conditions:
            stmt = stmt.where(and_(*conditions))
        
        stmt = stmt.order_by(Opportunity.closing_at.asc().nullslast())
        stmt = stmt.limit(limit).offset(offset)
        
        return self.session.execute(stmt).scalars().all()
    
    def compute_fingerprint(self, data: dict[str, Any]) -> str:
        """Compute a content fingerprint for deduplication.
        
        Uses stable fields that are unlikely to change between scrapes.
        """
        # Use stable identifying fields
        stable_fields = ["title", "external_id", "agency", "posted_at"]
        fingerprint_data = {k: data.get(k) for k in stable_fields if data.get(k)}
        
        # Create deterministic JSON and hash
        json_str = json.dumps(fingerprint_data, sort_keys=True, default=str)
        return hashlib.sha256(json_str.encode()).hexdigest()[:16]
    
    def compute_diff(
        self,
        existing: Opportunity,
        new_data: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        """Compute differences between existing opportunity and new data.
        
        Returns:
            Dict of field -> {"old": value, "new": value}
        """
        diff: dict[str, dict[str, Any]] = {}
        
        for field in self.TRACKED_FIELDS:
            old_value = getattr(existing, field, None)
            new_value = new_data.get(field)
            
            # Normalize for comparison
            if isinstance(old_value, datetime) and isinstance(new_value, datetime):
                # Compare to minute precision
                old_value = old_value.replace(second=0, microsecond=0)
                new_value = new_value.replace(second=0, microsecond=0)
            
            if old_value != new_value:
                diff[field] = {"old": old_value, "new": new_value}
        
        return diff
    
    def upsert(
        self,
        portal_id: int,
        external_id: str,
        data: dict[str, Any],
        run_id: int | None = None,
    ) -> tuple[Opportunity, str, dict[str, Any] | None]:
        """Create or update an opportunity with change tracking.
        
        Args:
            portal_id: Portal ID
            external_id: External identifier from source
            data: Opportunity data
            run_id: Current scrape run ID for event tracking
            
        Returns:
            Tuple of (opportunity, event_type, diff)
            event_type is "NEW", "UPDATED", or "UNCHANGED"
        """
        existing = self.get_by_external_id(portal_id, external_id)
        fingerprint = self.compute_fingerprint({**data, "external_id": external_id})
        
        if existing is None:
            # New opportunity
            opportunity = Opportunity(
                portal_id=portal_id,
                external_id=external_id,
                fingerprint=fingerprint,
                **{k: v for k, v in data.items() if hasattr(Opportunity, k)},
            )
            self.session.add(opportunity)
            self.session.flush()
            
            # Create NEW event
            event = OpportunityEvent(
                opportunity_id=opportunity.id,
                run_id=run_id,
                event_type="NEW",
                message="Opportunity discovered",
            )
            self.session.add(event)
            
            return opportunity, "NEW", None
        
        # Existing opportunity - check for changes
        diff = self.compute_diff(existing, data)
        
        if not diff:
            # No changes, just update last_seen
            existing.last_seen_at = datetime.utcnow()
            return existing, "UNCHANGED", None
        
        # Update changed fields
        for field, values in diff.items():
            setattr(existing, field, values["new"])
        
        existing.fingerprint = fingerprint
        existing.last_seen_at = datetime.utcnow()
        
        # Preserve raw data
        if "raw_data" in data:
            existing.raw_data = data["raw_data"]
        
        # Create UPDATED event with diff
        event = OpportunityEvent(
            opportunity_id=existing.id,
            run_id=run_id,
            event_type="UPDATED",
            diff=self._serialize_diff(diff),
            message=f"Updated {len(diff)} field(s)",
        )
        self.session.add(event)
        
        return existing, "UPDATED", diff
    
    def _serialize_diff(self, diff: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Serialize diff for JSON storage."""
        serialized = {}
        for field, values in diff.items():
            serialized[field] = {
                "old": self._serialize_value(values["old"]),
                "new": self._serialize_value(values["new"]),
            }
        return serialized
    
    def _serialize_value(self, value: Any) -> Any:
        """Serialize a value for JSON storage."""
        if isinstance(value, datetime):
            return value.isoformat()
        return value
    
    def record_event(
        self,
        opportunity_id: int,
        event_type: str,
        run_id: int | None = None,
        diff: dict[str, Any] | None = None,
        message: str | None = None,
    ) -> OpportunityEvent:
        """Record an event for an opportunity."""
        event = OpportunityEvent(
            opportunity_id=opportunity_id,
            run_id=run_id,
            event_type=event_type,
            diff=diff,
            message=message,
        )
        self.session.add(event)
        self.session.flush()
        return event
    
    def get_events(
        self,
        opportunity_id: int | None = None,
        event_type: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> Sequence[OpportunityEvent]:
        """Get opportunity events with filters."""
        stmt = select(OpportunityEvent)
        
        conditions = []
        if opportunity_id is not None:
            conditions.append(OpportunityEvent.opportunity_id == opportunity_id)
        if event_type is not None:
            conditions.append(OpportunityEvent.event_type == event_type)
        if since is not None:
            conditions.append(OpportunityEvent.created_at >= since)
        
        if conditions:
            stmt = stmt.where(and_(*conditions))
        
        stmt = stmt.order_by(OpportunityEvent.created_at.desc())
        stmt = stmt.limit(limit)
        
        return self.session.execute(stmt).scalars().all()
    
    def count_by_status(self, portal_id: int | None = None) -> dict[str, int]:
        """Count opportunities grouped by status."""
        stmt = select(
            Opportunity.status,
            func.count(Opportunity.id),
        ).group_by(Opportunity.status)
        
        if portal_id is not None:
            stmt = stmt.where(Opportunity.portal_id == portal_id)
        
        result = self.session.execute(stmt).all()
        return {status: count for status, count in result}


# =============================================================================
# Run Repository
# =============================================================================


class RunRepository:
    """Repository for ScrapeRun operations."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def create(
        self,
        portal_id: int | None = None,
        run_type: str = "manual",
        scheduled_job_id: int | None = None,
    ) -> ScrapeRun:
        """Create a new scrape run."""
        run = ScrapeRun(
            portal_id=portal_id,
            run_type=run_type,
            scheduled_job_id=scheduled_job_id,
            status="RUNNING",
        )
        self.session.add(run)
        self.session.flush()
        return run
    
    def get_by_id(self, run_id: int) -> ScrapeRun | None:
        """Get run by ID."""
        return self.session.get(ScrapeRun, run_id)
    
    def update_stats(
        self,
        run_id: int,
        pages_scraped: int | None = None,
        pages_failed: int | None = None,
        opportunities_found: int | None = None,
        opportunities_new: int | None = None,
        opportunities_updated: int | None = None,
        errors_count: int | None = None,
    ) -> None:
        """Increment run statistics."""
        run = self.get_by_id(run_id)
        if not run:
            return
        
        if pages_scraped is not None:
            run.pages_scraped += pages_scraped
        if pages_failed is not None:
            run.pages_failed += pages_failed
        if opportunities_found is not None:
            run.opportunities_found += opportunities_found
        if opportunities_new is not None:
            run.opportunities_new += opportunities_new
        if opportunities_updated is not None:
            run.opportunities_updated += opportunities_updated
        if errors_count is not None:
            run.errors_count += errors_count
    
    def complete(
        self,
        run_id: int,
        status: str = "COMPLETED",
        error_message: str | None = None,
        error_traceback: str | None = None,
    ) -> None:
        """Mark a run as complete."""
        run = self.get_by_id(run_id)
        if not run:
            return
        
        run.status = status
        run.finished_at = datetime.utcnow()
        run.error_message = error_message
        run.error_traceback = error_traceback
    
    def save_checkpoint(self, run_id: int, checkpoint: dict[str, Any]) -> None:
        """Save checkpoint for resume capability."""
        run = self.get_by_id(run_id)
        if run:
            run.checkpoint = checkpoint
    
    def get_recent(
        self,
        portal_id: int | None = None,
        limit: int = 20,
    ) -> Sequence[ScrapeRun]:
        """Get recent runs."""
        stmt = select(ScrapeRun)
        
        if portal_id is not None:
            stmt = stmt.where(ScrapeRun.portal_id == portal_id)
        
        stmt = stmt.order_by(ScrapeRun.started_at.desc())
        stmt = stmt.limit(limit)
        
        return self.session.execute(stmt).scalars().all()
    
    def save_snapshot(
        self,
        run_id: int | None,
        portal_id: int | None,
        url: str,
        reason: str,
        html_path: str | None = None,
        screenshot_path: str | None = None,
        status_code: int | None = None,
        extraction_confidence: float | None = None,
        error_message: str | None = None,
    ) -> PageSnapshot:
        """Save a page snapshot for debugging."""
        snapshot = PageSnapshot(
            run_id=run_id,
            portal_id=portal_id,
            url=url,
            reason=reason,
            html_path=html_path,
            screenshot_path=screenshot_path,
            status_code=status_code,
            extraction_confidence=extraction_confidence,
            error_message=error_message,
        )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot


# =============================================================================
# Lock Repository
# =============================================================================


class LockRepository:
    """Repository for distributed run locks."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def acquire(
        self,
        lock_name: str,
        holder_id: str,
        ttl_seconds: int = 3600,
    ) -> bool:
        """Attempt to acquire a lock.
        
        Returns:
            True if lock acquired, False if already held
        """
        now = datetime.utcnow()
        from datetime import timedelta
        expires_at = now + timedelta(seconds=ttl_seconds)
        
        # Check for existing valid lock
        stmt = select(RunLock).where(
            and_(
                RunLock.lock_name == lock_name,
                RunLock.expires_at > now,
            )
        )
        existing = self.session.execute(stmt).scalar_one_or_none()
        
        if existing:
            return False
        
        # Clean up expired locks
        self.session.query(RunLock).filter(
            RunLock.lock_name == lock_name,
            RunLock.expires_at <= now,
        ).delete()
        
        # Create new lock
        lock = RunLock(
            lock_name=lock_name,
            holder_id=holder_id,
            acquired_at=now,
            expires_at=expires_at,
        )
        self.session.add(lock)
        
        try:
            self.session.flush()
            return True
        except Exception:
            return False
    
    def release(self, lock_name: str, holder_id: str) -> bool:
        """Release a lock.
        
        Returns:
            True if lock was released, False if not held by this holder
        """
        result = self.session.query(RunLock).filter(
            and_(
                RunLock.lock_name == lock_name,
                RunLock.holder_id == holder_id,
            )
        ).delete()
        return result > 0
    
    def extend(self, lock_name: str, holder_id: str, ttl_seconds: int = 3600) -> bool:
        """Extend a lock's TTL.
        
        Returns:
            True if extended, False if not held by this holder
        """
        from datetime import timedelta
        expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        
        result = self.session.query(RunLock).filter(
            and_(
                RunLock.lock_name == lock_name,
                RunLock.holder_id == holder_id,
            )
        ).update({"expires_at": expires_at})
        
        return result > 0
    
    def is_locked(self, lock_name: str) -> bool:
        """Check if a lock is currently held."""
        stmt = select(RunLock).where(
            and_(
                RunLock.lock_name == lock_name,
                RunLock.expires_at > datetime.utcnow(),
            )
        )
        return self.session.execute(stmt).scalar_one_or_none() is not None
