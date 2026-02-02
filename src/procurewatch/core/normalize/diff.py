"""
Fingerprinting and diff computation for change tracking.

Provides utilities to detect and describe changes between opportunity versions.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .canonical import OpportunityCanonical


@dataclass
class FieldChange:
    """A single field change."""
    
    field: str
    old_value: Any
    new_value: Any
    significance: str = "medium"  # low, medium, high


@dataclass
class DiffResult:
    """Result of comparing two opportunity versions."""
    
    changes: list[FieldChange]
    old_fingerprint: str
    new_fingerprint: str
    is_significant: bool
    summary: str
    
    @property
    def has_changes(self) -> bool:
        """Check if there are any changes."""
        return len(self.changes) > 0
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "changes": [
                {
                    "field": c.field,
                    "old": _serialize_value(c.old_value),
                    "new": _serialize_value(c.new_value),
                    "significance": c.significance,
                }
                for c in self.changes
            ],
            "old_fingerprint": self.old_fingerprint,
            "new_fingerprint": self.new_fingerprint,
            "is_significant": self.is_significant,
            "summary": self.summary,
        }


def compute_fingerprint(opp: OpportunityCanonical | dict[str, Any]) -> str:
    """Compute a content-based fingerprint for an opportunity.
    
    The fingerprint is based on core content fields, not metadata.
    Changes to these fields indicate a meaningful content change.
    
    Args:
        opp: OpportunityCanonical or dictionary with opportunity data
        
    Returns:
        32-character hex fingerprint
    """
    if isinstance(opp, OpportunityCanonical):
        return opp.compute_fingerprint()
    
    # Dictionary version
    content_parts = [
        str(opp.get("external_id", "")),
        str(opp.get("title", "")),
        str(opp.get("description", "")),
        str(opp.get("status", "")),
        str(opp.get("category", "")),
        str(opp.get("agency", "")),
        str(opp.get("closing_at", "")),
        str(opp.get("estimated_value", "")),
    ]
    
    content_string = "|".join(content_parts)
    return hashlib.sha256(content_string.encode()).hexdigest()[:32]


# Fields with their change significance
FIELD_SIGNIFICANCE: dict[str, str] = {
    # High significance - core business data
    "title": "high",
    "status": "high",
    "closing_at": "high",
    "estimated_value": "high",
    "award_amount": "high",
    "awardee": "high",
    
    # Medium significance - important metadata
    "description": "medium",
    "agency": "medium",
    "department": "medium",
    "category": "medium",
    "posted_at": "medium",
    "awarded_at": "medium",
    "contact_name": "medium",
    "contact_email": "medium",
    
    # Low significance - supplementary data
    "contact_phone": "low",
    "location": "low",
    "commodity_codes": "low",
    "detail_url": "low",
    "description_markdown": "low",
}


def compute_diff(
    old: OpportunityCanonical | dict[str, Any],
    new: OpportunityCanonical | dict[str, Any],
) -> DiffResult:
    """Compute the difference between two opportunity versions.
    
    Args:
        old: Previous version of the opportunity
        new: Current version of the opportunity
        
    Returns:
        DiffResult with list of changes and summary
    """
    # Convert to dictionaries for comparison
    old_dict = old.to_dict() if isinstance(old, OpportunityCanonical) else old
    new_dict = new.to_dict() if isinstance(new, OpportunityCanonical) else new
    
    # Compute fingerprints
    old_fingerprint = compute_fingerprint(old)
    new_fingerprint = compute_fingerprint(new)
    
    # Quick check - if fingerprints match, no significant changes
    if old_fingerprint == new_fingerprint:
        return DiffResult(
            changes=[],
            old_fingerprint=old_fingerprint,
            new_fingerprint=new_fingerprint,
            is_significant=False,
            summary="No changes",
        )
    
    # Find all changed fields
    changes: list[FieldChange] = []
    
    # Compare tracked fields
    for field, significance in FIELD_SIGNIFICANCE.items():
        old_value = old_dict.get(field)
        new_value = new_dict.get(field)
        
        if _values_differ(old_value, new_value):
            changes.append(FieldChange(
                field=field,
                old_value=old_value,
                new_value=new_value,
                significance=significance,
            ))
    
    # Determine if changes are significant
    high_changes = [c for c in changes if c.significance == "high"]
    is_significant = len(high_changes) > 0
    
    # Generate summary
    summary = _generate_summary(changes)
    
    return DiffResult(
        changes=changes,
        old_fingerprint=old_fingerprint,
        new_fingerprint=new_fingerprint,
        is_significant=is_significant,
        summary=summary,
    )


def _values_differ(old: Any, new: Any) -> bool:
    """Check if two values are different (handling None, empty strings, etc.)."""
    # Normalize None and empty strings
    if old is None or old == "":
        old = None
    if new is None or new == "":
        new = None
    
    # Both None/empty
    if old is None and new is None:
        return False
    
    # One is None/empty
    if old is None or new is None:
        return True
    
    # Compare as strings for consistency
    return str(old) != str(new)


def _serialize_value(value: Any) -> Any:
    """Serialize a value for JSON storage."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, dict)):
        return value
    return str(value)


def _generate_summary(changes: list[FieldChange]) -> str:
    """Generate a human-readable summary of changes."""
    if not changes:
        return "No changes"
    
    high_changes = [c for c in changes if c.significance == "high"]
    medium_changes = [c for c in changes if c.significance == "medium"]
    low_changes = [c for c in changes if c.significance == "low"]
    
    parts = []
    
    if high_changes:
        fields = [c.field for c in high_changes]
        if "status" in fields:
            status_change = next(c for c in high_changes if c.field == "status")
            parts.append(f"Status: {status_change.old_value} → {status_change.new_value}")
        else:
            parts.append(f"Changed: {', '.join(fields)}")
    
    if medium_changes and not high_changes:
        fields = [c.field for c in medium_changes[:3]]  # Limit to 3
        parts.append(f"Updated: {', '.join(fields)}")
    
    if low_changes and not high_changes and not medium_changes:
        parts.append(f"{len(low_changes)} minor field(s) updated")
    
    return "; ".join(parts) if parts else f"{len(changes)} field(s) changed"


def detect_event_type(
    old: OpportunityCanonical | dict[str, Any] | None,
    new: OpportunityCanonical | dict[str, Any],
) -> str:
    """Detect the event type based on old and new versions.
    
    Args:
        old: Previous version (None for new opportunities)
        new: Current version
        
    Returns:
        Event type string: NEW, UPDATED, CLOSED, AWARDED
    """
    if old is None:
        return "NEW"
    
    new_dict = new.to_dict() if isinstance(new, OpportunityCanonical) else new
    old_dict = old.to_dict() if isinstance(old, OpportunityCanonical) else old
    
    new_status = new_dict.get("status", "UNKNOWN")
    old_status = old_dict.get("status", "UNKNOWN")
    
    # Check for status transitions
    if old_status != new_status:
        if new_status == "CLOSED":
            return "CLOSED"
        if new_status == "AWARDED":
            return "AWARDED"
        if new_status == "EXPIRED":
            return "EXPIRED"
    
    # Check for any other changes
    diff = compute_diff(old, new)
    if diff.has_changes:
        return "UPDATED"
    
    return "UPDATED"  # Default to UPDATED even if no diff (fingerprint check might differ)
