"""
Canonical opportunity model for normalized data.

Provides a clean interface between raw extraction and database persistence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from .parsing import (
    parse_date,
    parse_money,
    parse_status,
    normalize_whitespace,
    clean_html_text,
)


@dataclass
class OpportunityCanonical:
    """Normalized opportunity data ready for persistence.
    
    This is the clean, validated representation of an opportunity
    after extraction and normalization.
    """
    
    # Required identifiers
    portal_name: str
    external_id: str
    
    # Core fields
    title: str | None = None
    description: str | None = None
    description_markdown: str | None = None
    
    # Dates (normalized to datetime)
    posted_at: datetime | None = None
    closing_at: datetime | None = None
    awarded_at: datetime | None = None
    
    # Status (normalized)
    status: str = "UNKNOWN"
    
    # Classification
    category: str | None = None
    commodity_codes: list[str] = field(default_factory=list)
    
    # Organization
    agency: str | None = None
    department: str | None = None
    location: str | None = None
    
    # Contact
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    
    # Value (normalized to Decimal)
    estimated_value: Decimal | None = None
    estimated_value_currency: str = "USD"
    award_amount: Decimal | None = None
    
    # Award info
    awardee: str | None = None
    
    # URLs
    source_url: str | None = None
    detail_url: str | None = None
    
    # Raw data for debugging
    raw_data: dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    extraction_confidence: float = 0.0
    normalization_warnings: list[str] = field(default_factory=list)
    
    def compute_fingerprint(self) -> str:
        """Compute a content-based fingerprint for change detection.
        
        The fingerprint is based on core content fields, not metadata.
        """
        content_parts = [
            self.external_id,
            self.title or "",
            self.description or "",
            self.status,
            self.category or "",
            self.agency or "",
            str(self.closing_at) if self.closing_at else "",
            str(self.estimated_value) if self.estimated_value else "",
        ]
        
        content_string = "|".join(content_parts)
        return hashlib.sha256(content_string.encode()).hexdigest()[:32]
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for persistence."""
        data = asdict(self)
        
        # Convert Decimal to float for JSON serialization
        if data["estimated_value"] is not None:
            data["estimated_value"] = float(data["estimated_value"])
        if data["award_amount"] is not None:
            data["award_amount"] = float(data["award_amount"])
        
        # Convert commodity_codes list to comma-separated string
        if data["commodity_codes"]:
            data["commodity_codes"] = ",".join(data["commodity_codes"])
        else:
            data["commodity_codes"] = None
        
        return data


def normalize_opportunity(
    raw: dict[str, Any],
    *,
    portal_name: str,
    source_url: str | None = None,
) -> OpportunityCanonical:
    """Normalize raw extracted data to canonical form.
    
    Args:
        raw: Raw extracted data dictionary
        portal_name: Name of the source portal
        source_url: URL the data was extracted from
        
    Returns:
        OpportunityCanonical with normalized data
    """
    warnings: list[str] = []
    
    # Extract external ID (required)
    external_id = _get_first(raw, ["external_id", "id", "bid_id", "rfp_id", "solicitation_id"])
    if not external_id:
        # Try to generate from title if missing
        title = _get_first(raw, ["title", "name", "description"])
        if title:
            external_id = hashlib.md5(title.encode()).hexdigest()[:16]
            warnings.append(f"Generated external_id from title hash")
        else:
            external_id = f"unknown_{datetime.utcnow().timestamp()}"
            warnings.append("No external_id found, using timestamp")
    
    # Parse title
    title = _get_first(raw, ["title", "name", "project_title", "solicitation_title"])
    if title:
        title = clean_html_text(title)[:1000]  # Truncate to DB limit
    
    # Parse description
    description = _get_first(raw, ["description", "details", "summary", "scope"])
    description_markdown = raw.get("description_markdown")
    if description:
        description = clean_html_text(description)
    
    # Parse dates
    closing_at = None
    closing_raw = _get_first(raw, ["closing_at", "close_date", "due_date", "deadline", "end_date"])
    if closing_raw:
        parsed = parse_date(closing_raw)
        if parsed.value:
            closing_at = parsed.value
        elif parsed.confidence == 0:
            warnings.append(f"Could not parse closing date: {closing_raw}")
    
    posted_at = None
    posted_raw = _get_first(raw, ["posted_at", "post_date", "publish_date", "open_date", "start_date"])
    if posted_raw:
        parsed = parse_date(posted_raw)
        if parsed.value:
            posted_at = parsed.value
    
    awarded_at = None
    awarded_raw = _get_first(raw, ["awarded_at", "award_date"])
    if awarded_raw:
        parsed = parse_date(awarded_raw)
        if parsed.value:
            awarded_at = parsed.value
    
    # Parse status
    status = "UNKNOWN"
    status_raw = _get_first(raw, ["status", "state", "bid_status"])
    if status_raw:
        parsed = parse_status(status_raw)
        status = parsed.status
    else:
        # Try to infer status from dates
        now = datetime.utcnow()
        if closing_at:
            if closing_at > now:
                status = "OPEN"
            else:
                status = "CLOSED"
        if awarded_at:
            status = "AWARDED"
    
    # Parse value
    estimated_value = None
    estimated_value_currency = "USD"
    value_raw = _get_first(raw, ["estimated_value", "value", "amount", "budget", "contract_value"])
    if value_raw:
        parsed = parse_money(value_raw)
        if parsed.amount:
            estimated_value = parsed.amount
            estimated_value_currency = parsed.currency
    
    award_amount = None
    award_raw = _get_first(raw, ["award_amount", "awarded_value", "contract_amount"])
    if award_raw:
        parsed = parse_money(award_raw)
        if parsed.amount:
            award_amount = parsed.amount
    
    # Extract other fields
    agency = _get_first(raw, ["agency", "department", "organization", "buyer"])
    if agency:
        agency = normalize_whitespace(agency)[:500]
    
    department = raw.get("department")
    if department:
        department = normalize_whitespace(department)[:500]
    
    category = _get_first(raw, ["category", "type", "commodity", "classification"])
    if category:
        category = normalize_whitespace(category)[:500]
    
    commodity_codes = []
    codes_raw = raw.get("commodity_codes")
    if codes_raw:
        if isinstance(codes_raw, list):
            commodity_codes = [str(c) for c in codes_raw]
        elif isinstance(codes_raw, str):
            commodity_codes = [c.strip() for c in codes_raw.split(",")]
    
    location = raw.get("location")
    if location:
        location = normalize_whitespace(location)[:500]
    
    # Contact info
    contact_name = _get_first(raw, ["contact_name", "contact", "buyer_name"])
    contact_email = _get_first(raw, ["contact_email", "email"])
    contact_phone = _get_first(raw, ["contact_phone", "phone"])
    
    # URLs
    detail_url = raw.get("detail_url")
    
    # Awardee
    awardee = _get_first(raw, ["awardee", "vendor", "winner", "contractor"])
    
    # Confidence
    confidence = raw.get("confidence", 0.0)
    if isinstance(confidence, str):
        try:
            confidence = float(confidence)
        except ValueError:
            confidence = 0.0
    
    return OpportunityCanonical(
        portal_name=portal_name,
        external_id=str(external_id),
        title=title,
        description=description,
        description_markdown=description_markdown,
        posted_at=posted_at,
        closing_at=closing_at,
        awarded_at=awarded_at,
        status=status,
        category=category,
        commodity_codes=commodity_codes,
        agency=agency,
        department=department,
        location=location,
        contact_name=contact_name,
        contact_email=contact_email,
        contact_phone=contact_phone,
        estimated_value=estimated_value,
        estimated_value_currency=estimated_value_currency,
        award_amount=award_amount,
        awardee=awardee,
        source_url=source_url,
        detail_url=detail_url,
        raw_data=raw,
        extraction_confidence=confidence,
        normalization_warnings=warnings,
    )


def _get_first(data: dict[str, Any], keys: list[str]) -> Any | None:
    """Get the first non-None value from a list of keys."""
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return value
    return None
