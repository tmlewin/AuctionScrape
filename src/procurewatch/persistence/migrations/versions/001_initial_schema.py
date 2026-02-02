"""Initial schema

Revision ID: 001
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create initial database schema."""
    
    # Portals table
    op.create_table(
        "portals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("portal_type", sa.String(length=50), nullable=False, server_default="generic_table"),
        sa.Column("config_hash", sa.String(length=64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("last_scraped_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("total_opportunities", sa.Integer(), server_default="0"),
        sa.Column("total_runs", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portals_name", "portals", ["name"], unique=True)
    
    # Scheduled jobs table
    op.create_table(
        "scheduled_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("portals_json", sa.JSON(), nullable=True),
        sa.Column("schedule_type", sa.String(length=50), nullable=False, server_default="daily"),
        sa.Column("time_of_day", sa.String(length=10), nullable=True),
        sa.Column("cron_expression", sa.String(length=100), nullable=True),
        sa.Column("timezone", sa.String(length=50), server_default="UTC"),
        sa.Column("jitter_minutes", sa.Integer(), server_default="0"),
        sa.Column("blackout_start", sa.String(length=10), nullable=True),
        sa.Column("blackout_end", sa.String(length=10), nullable=True),
        sa.Column("max_runtime_minutes", sa.Integer(), server_default="120"),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scheduled_jobs_name", "scheduled_jobs", ["name"], unique=True)
    
    # Scrape runs table
    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("portal_id", sa.Integer(), nullable=True),
        sa.Column("run_type", sa.String(length=50), nullable=False, server_default="manual"),
        sa.Column("scheduled_job_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="RUNNING"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("pages_scraped", sa.Integer(), server_default="0"),
        sa.Column("pages_failed", sa.Integer(), server_default="0"),
        sa.Column("opportunities_found", sa.Integer(), server_default="0"),
        sa.Column("opportunities_new", sa.Integer(), server_default="0"),
        sa.Column("opportunities_updated", sa.Integer(), server_default="0"),
        sa.Column("errors_count", sa.Integer(), server_default="0"),
        sa.Column("checkpoint", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_traceback", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["portal_id"], ["portals.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["scheduled_job_id"], ["scheduled_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scrape_runs_portal_id", "scrape_runs", ["portal_id"])
    op.create_index("ix_scrape_runs_started_at", "scrape_runs", ["started_at"])
    op.create_index("ix_scrape_runs_status", "scrape_runs", ["status"])
    
    # Opportunities table
    op.create_table(
        "opportunities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("portal_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=1000), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("description_markdown", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(), nullable=True),
        sa.Column("closing_at", sa.DateTime(), nullable=True),
        sa.Column("awarded_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="UNKNOWN"),
        sa.Column("category", sa.String(length=500), nullable=True),
        sa.Column("commodity_codes", sa.String(length=500), nullable=True),
        sa.Column("agency", sa.String(length=500), nullable=True),
        sa.Column("department", sa.String(length=500), nullable=True),
        sa.Column("location", sa.String(length=500), nullable=True),
        sa.Column("contact_name", sa.String(length=200), nullable=True),
        sa.Column("contact_email", sa.String(length=200), nullable=True),
        sa.Column("contact_phone", sa.String(length=50), nullable=True),
        sa.Column("estimated_value", sa.Float(), nullable=True),
        sa.Column("estimated_value_currency", sa.String(length=3), server_default="USD"),
        sa.Column("award_amount", sa.Float(), nullable=True),
        sa.Column("awardee", sa.String(length=500), nullable=True),
        sa.Column("source_url", sa.String(length=2000), nullable=True),
        sa.Column("detail_url", sa.String(length=2000), nullable=True),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("extraction_confidence", sa.Float(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["portal_id"], ["portals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("portal_id", "external_id", name="uq_opportunity_portal_external"),
    )
    op.create_index("ix_opportunities_portal_id", "opportunities", ["portal_id"])
    op.create_index("ix_opportunities_external_id", "opportunities", ["external_id"])
    op.create_index("ix_opportunities_fingerprint", "opportunities", ["fingerprint"])
    op.create_index("ix_opportunities_posted_at", "opportunities", ["posted_at"])
    op.create_index("ix_opportunities_closing_at", "opportunities", ["closing_at"])
    op.create_index("ix_opportunities_status", "opportunities", ["status"])
    op.create_index("ix_opportunities_agency", "opportunities", ["agency"])
    op.create_index("ix_opportunity_closing_status", "opportunities", ["closing_at", "status"])
    op.create_index("ix_opportunity_portal_status", "opportunities", ["portal_id", "status"])
    
    # Opportunity events table
    op.create_table(
        "opportunity_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("opportunity_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("diff", sa.JSON(), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["scrape_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_opportunity_events_opportunity_id", "opportunity_events", ["opportunity_id"])
    op.create_index("ix_opportunity_events_run_id", "opportunity_events", ["run_id"])
    op.create_index("ix_opportunity_events_event_type", "opportunity_events", ["event_type"])
    op.create_index("ix_opportunity_events_created_at", "opportunity_events", ["created_at"])
    op.create_index("ix_event_type_created", "opportunity_events", ["event_type", "created_at"])
    
    # Documents table
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("opportunity_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=True),
        sa.Column("file_type", sa.String(length=50), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("local_path", sa.String(length=500), nullable=True),
        sa.Column("downloaded_at", sa.DateTime(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_opportunity_id", "documents", ["opportunity_id"])
    
    # Page snapshots table
    op.create_table(
        "page_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("portal_id", sa.Integer(), nullable=True),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=False),
        sa.Column("html_path", sa.String(length=500), nullable=True),
        sa.Column("screenshot_path", sa.String(length=500), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("extraction_confidence", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["portal_id"], ["portals.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["scrape_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_page_snapshots_run_id", "page_snapshots", ["run_id"])
    op.create_index("ix_page_snapshots_portal_id", "page_snapshots", ["portal_id"])
    op.create_index("ix_page_snapshots_reason", "page_snapshots", ["reason"])
    op.create_index("ix_page_snapshots_created_at", "page_snapshots", ["created_at"])
    
    # Run locks table
    op.create_table(
        "run_locks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("lock_name", sa.String(length=100), nullable=False),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("holder_id", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_run_locks_lock_name", "run_locks", ["lock_name"], unique=True)


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table("run_locks")
    op.drop_table("page_snapshots")
    op.drop_table("documents")
    op.drop_table("opportunity_events")
    op.drop_table("opportunities")
    op.drop_table("scrape_runs")
    op.drop_table("scheduled_jobs")
    op.drop_table("portals")
