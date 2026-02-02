"""
SQLAlchemy ORM models for ProcureWatch.

Defines the complete database schema including:
- Portals: Tender portal configurations
- Opportunities: Individual procurement opportunities
- OpportunityEvents: Change tracking history
- ScrapeRuns: Execution logs
- PageSnapshots: HTML captures for debugging
- ScheduledJobs: Scheduler state
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Use orjson for JSON columns if available
try:
    import orjson
    
    def json_serializer(obj: Any) -> str:
        return orjson.dumps(obj).decode("utf-8")
    
    def json_deserializer(s: str) -> Any:
        return orjson.loads(s)
        
except ImportError:
    import json
    json_serializer = json.dumps
    json_deserializer = json.loads

from sqlalchemy import JSON


if TYPE_CHECKING:
    pass


# =============================================================================
# Base Class
# =============================================================================


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    
    type_annotation_map = {
        dict[str, Any]: JSON,
    }


# =============================================================================
# Mixins
# =============================================================================


class TimestampMixin:
    """Mixin providing created_at and updated_at columns."""
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=None,
        onupdate=datetime.utcnow,
        nullable=True,
    )


# =============================================================================
# Portal Model
# =============================================================================


class Portal(Base, TimestampMixin):
    """Tender portal configuration and metadata."""
    
    __tablename__ = "portals"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    portal_type: Mapped[str] = mapped_column(String(50), nullable=False, default="generic_table")
    
    # Configuration hash for detecting config changes
    config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    
    # Status
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    # Statistics
    total_opportunities: Mapped[int] = mapped_column(Integer, default=0)
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    
    # Relationships
    opportunities: Mapped[list["Opportunity"]] = relationship(
        "Opportunity",
        back_populates="portal",
        cascade="all, delete-orphan",
    )
    scrape_runs: Mapped[list["ScrapeRun"]] = relationship(
        "ScrapeRun",
        back_populates="portal",
        cascade="all, delete-orphan",
    )
    
    def __repr__(self) -> str:
        return f"<Portal(id={self.id}, name='{self.name}')>"


# =============================================================================
# Opportunity Model
# =============================================================================


class Opportunity(Base, TimestampMixin):
    """Individual procurement opportunity/tender posting."""
    
    __tablename__ = "opportunities"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portal_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("portals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Primary identifiers
    external_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    
    # Core fields
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Dates
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    closing_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    awarded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    # Status
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="UNKNOWN",
        index=True,
    )
    
    # Classification
    category: Mapped[str | None] = mapped_column(String(500), nullable=True)
    commodity_codes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    # Organization
    agency: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    department: Mapped[str | None] = mapped_column(String(500), nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    # Contact
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    
    # Value
    estimated_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_value_currency: Mapped[str] = mapped_column(String(3), default="USD")
    award_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    
    # Award
    awardee: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    # URLs
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    detail_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    
    # Raw data (preserved for debugging/reprocessing)
    raw_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    
    # Extraction metadata
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
    
    # Relationships
    portal: Mapped["Portal"] = relationship("Portal", back_populates="opportunities")
    events: Mapped[list["OpportunityEvent"]] = relationship(
        "OpportunityEvent",
        back_populates="opportunity",
        cascade="all, delete-orphan",
        order_by="OpportunityEvent.created_at.desc()",
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document",
        back_populates="opportunity",
        cascade="all, delete-orphan",
    )
    
    # Constraints
    __table_args__ = (
        UniqueConstraint("portal_id", "external_id", name="uq_opportunity_portal_external"),
        Index("ix_opportunity_closing_status", "closing_at", "status"),
        Index("ix_opportunity_portal_status", "portal_id", "status"),
    )
    
    def __repr__(self) -> str:
        return f"<Opportunity(id={self.id}, external_id='{self.external_id}', title='{self.title[:50] if self.title else ''}...')>"


# =============================================================================
# Opportunity Event Model
# =============================================================================


class OpportunityEvent(Base):
    """Change tracking event for opportunities.
    
    Records every change to an opportunity with the event type
    and a diff of what changed.
    """
    
    __tablename__ = "opportunity_events"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opportunity_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("scrape_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    
    # Event details
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    
    # What changed (JSON diff)
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    
    # Additional context
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )
    
    # Relationships
    opportunity: Mapped["Opportunity"] = relationship(
        "Opportunity",
        back_populates="events",
    )
    run: Mapped["ScrapeRun | None"] = relationship(
        "ScrapeRun",
        back_populates="events",
    )
    
    __table_args__ = (
        Index("ix_event_type_created", "event_type", "created_at"),
    )
    
    def __repr__(self) -> str:
        return f"<OpportunityEvent(id={self.id}, type='{self.event_type}', opp_id={self.opportunity_id})>"


# =============================================================================
# Document Model
# =============================================================================


class Document(Base, TimestampMixin):
    """Document attachment associated with an opportunity."""
    
    __tablename__ = "documents"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opportunity_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Document info
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    # Local storage (if downloaded)
    local_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    # Content hash for deduplication
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    
    # Relationships
    opportunity: Mapped["Opportunity"] = relationship(
        "Opportunity",
        back_populates="documents",
    )
    
    def __repr__(self) -> str:
        return f"<Document(id={self.id}, name='{self.name}')>"


# =============================================================================
# Scrape Run Model
# =============================================================================


class ScrapeRun(Base):
    """Execution log for a scrape run."""
    
    __tablename__ = "scrape_runs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portal_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("portals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    
    # Run identification
    run_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="manual",  # manual, scheduled, test
    )
    scheduled_job_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("scheduled_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    # Status
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="RUNNING",
        index=True,
    )
    
    # Timing
    started_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    # Statistics
    pages_scraped: Mapped[int] = mapped_column(Integer, default=0)
    pages_failed: Mapped[int] = mapped_column(Integer, default=0)
    opportunities_found: Mapped[int] = mapped_column(Integer, default=0)
    opportunities_new: Mapped[int] = mapped_column(Integer, default=0)
    opportunities_updated: Mapped[int] = mapped_column(Integer, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # Checkpoint for resume
    checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    
    # Error details
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Relationships
    portal: Mapped["Portal | None"] = relationship(
        "Portal",
        back_populates="scrape_runs",
    )
    events: Mapped[list["OpportunityEvent"]] = relationship(
        "OpportunityEvent",
        back_populates="run",
    )
    snapshots: Mapped[list["PageSnapshot"]] = relationship(
        "PageSnapshot",
        back_populates="run",
        cascade="all, delete-orphan",
    )
    scheduled_job: Mapped["ScheduledJob | None"] = relationship(
        "ScheduledJob",
        back_populates="runs",
    )
    
    @property
    def duration_seconds(self) -> float | None:
        """Calculate run duration in seconds."""
        if self.finished_at and self.started_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None
    
    def __repr__(self) -> str:
        return f"<ScrapeRun(id={self.id}, portal_id={self.portal_id}, status='{self.status}')>"


# =============================================================================
# Page Snapshot Model
# =============================================================================


class PageSnapshot(Base):
    """HTML snapshot for debugging extraction issues."""
    
    __tablename__ = "page_snapshots"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("scrape_runs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    portal_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("portals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    
    # Page info
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    
    # Why we saved this snapshot
    reason: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )  # LAYOUT_DRIFT, ERROR, BLOCKED, LOW_CONFIDENCE, etc.
    
    # File storage
    html_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    screenshot_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    # Metadata
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )
    
    # Relationships
    run: Mapped["ScrapeRun | None"] = relationship(
        "ScrapeRun",
        back_populates="snapshots",
    )
    
    def __repr__(self) -> str:
        return f"<PageSnapshot(id={self.id}, reason='{self.reason}', url='{self.url[:50]}...')>"


# =============================================================================
# Scheduled Job Model
# =============================================================================


class ScheduledJob(Base, TimestampMixin):
    """Scheduler job state (mirrors APScheduler for visibility)."""
    
    __tablename__ = "scheduled_jobs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    
    # Status
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Configuration
    portals_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    schedule_type: Mapped[str] = mapped_column(String(50), nullable=False, default="daily")
    time_of_day: Mapped[str | None] = mapped_column(String(10), nullable=True)  # HH:MM
    cron_expression: Mapped[str | None] = mapped_column(String(100), nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC")
    jitter_minutes: Mapped[int] = mapped_column(Integer, default=0)
    
    # Blackout window
    blackout_start: Mapped[str | None] = mapped_column(String(10), nullable=True)
    blackout_end: Mapped[str | None] = mapped_column(String(10), nullable=True)
    
    # Runtime limits
    max_runtime_minutes: Mapped[int] = mapped_column(Integer, default=120)
    
    # Execution history
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    
    # Relationships
    runs: Mapped[list["ScrapeRun"]] = relationship(
        "ScrapeRun",
        back_populates="scheduled_job",
    )
    
    def __repr__(self) -> str:
        return f"<ScheduledJob(id={self.id}, name='{self.name}', enabled={self.enabled})>"


# =============================================================================
# Lock Model (for overlap protection)
# =============================================================================


class RunLock(Base):
    """Distributed lock for preventing overlapping runs."""
    
    __tablename__ = "run_locks"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lock_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    holder_id: Mapped[str] = mapped_column(String(100), nullable=False)  # Process/run identifier
    
    def __repr__(self) -> str:
        return f"<RunLock(name='{self.lock_name}', holder='{self.holder_id}')>"
