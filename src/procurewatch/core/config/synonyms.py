"""
Header synonym mappings for heuristic table extraction.

This module provides canonical field name mappings to various
header texts commonly found in procurement portals. Used by
HeuristicTableExtractor for automatic column mapping.
"""

from __future__ import annotations

# =============================================================================
# Canonical Field -> Possible Header Texts
# =============================================================================

HEADER_SYNONYMS: dict[str, list[str]] = {
    # Primary identifiers
    "external_id": [
        "solicitation #",
        "solicitation number",
        "solicitation no",
        "bid #",
        "bid number",
        "bid no",
        "rfp #",
        "rfp number",
        "rfq #",
        "rfq number",
        "itb #",
        "itb number",
        "reference #",
        "reference number",
        "reference no",
        "ref #",
        "ref no",
        "id",
        "number",
        "no.",
        "#",
        "opportunity id",
        "opp id",
        "project #",
        "project number",
        "contract #",
        "contract number",
        "procurement id",
        "tender #",
        "tender number",
        "tender no",
        "notice id",
        "notice #",
    ],
    
    # Title/Description
    "title": [
        "title",
        "name",
        "description",
        "project title",
        "project name",
        "solicitation title",
        "bid title",
        "opportunity",
        "opportunity title",
        "subject",
        "summary",
        "brief description",
        "short description",
        "item",
        "procurement title",
        "contract title",
        "tender title",
        "notice title",
    ],
    
    # Closing/Due date
    "closing_at": [
        "closing",
        "closing date",
        "close date",
        "closing date/time",
        "close date/time",
        "due date",
        "due",
        "deadline",
        "bid due",
        "bid due date",
        "response due",
        "response due date",
        "submission deadline",
        "submission due",
        "submit by",
        "submit before",
        "offer due",
        "offer deadline",
        "ends",
        "end date",
        "expiration",
        "expiration date",
        "expires",
        "response deadline",
        "bid closing",
        "bid deadline",
        "tender closing",
        "tender deadline",
    ],
    
    # Posted/Published date
    "posted_at": [
        "posted",
        "posted date",
        "post date",
        "published",
        "published date",
        "publish date",
        "issue date",
        "issued",
        "issued date",
        "release date",
        "released",
        "open date",
        "opened",
        "start date",
        "advertisement date",
        "advertised",
        "notice date",
        "date posted",
        "date published",
        "date issued",
        "created",
        "created date",
    ],
    
    # Status
    "status": [
        "status",
        "state",
        "bid status",
        "solicitation status",
        "opportunity status",
        "current status",
        "phase",
        "stage",
    ],
    
    # Category/Type
    "category": [
        "category",
        "categories",
        "type",
        "bid type",
        "solicitation type",
        "procurement type",
        "opportunity type",
        "commodity",
        "commodities",
        "commodity code",
        "nigp",
        "nigp code",
        "naics",
        "naics code",
        "unspsc",
        "classification",
        "service type",
        "goods/services",
    ],
    
    # Agency/Department
    "agency": [
        "agency",
        "agencies",
        "department",
        "dept",
        "organization",
        "org",
        "issuing agency",
        "issuing department",
        "issuing organization",
        "buyer",
        "buyer agency",
        "purchasing agency",
        "contracting agency",
        "entity",
        "government entity",
        "office",
        "division",
        "bureau",
        "ministry",
        "authority",
    ],
    
    # Contact information
    "contact_name": [
        "contact",
        "contact name",
        "buyer name",
        "purchasing agent",
        "contracting officer",
        "point of contact",
        "poc",
        "contact person",
        "representative",
        "agent",
    ],
    "contact_email": [
        "email",
        "e-mail",
        "contact email",
        "buyer email",
        "email address",
    ],
    "contact_phone": [
        "phone",
        "telephone",
        "contact phone",
        "phone number",
        "tel",
    ],
    
    # Value/Amount
    "estimated_value": [
        "value",
        "estimated value",
        "est. value",
        "amount",
        "estimated amount",
        "budget",
        "estimated budget",
        "contract value",
        "award amount",
        "total value",
        "price",
        "cost",
        "funding",
    ],
    
    # Location
    "location": [
        "location",
        "place",
        "place of performance",
        "delivery location",
        "site",
        "work location",
        "city",
        "state",
        "region",
        "county",
        "address",
        "jurisdiction",
    ],
    
    # Award information
    "awardee": [
        "awardee",
        "awarded to",
        "winner",
        "vendor",
        "contractor",
        "successful bidder",
        "selected vendor",
    ],
    "award_date": [
        "award date",
        "awarded",
        "date awarded",
        "award",
        "contract award date",
    ],
    "award_amount": [
        "award amount",
        "awarded amount",
        "contract amount",
        "final amount",
        "final value",
    ],
    
    # Documents
    "documents": [
        "documents",
        "attachments",
        "files",
        "downloads",
        "document",
        "attachment",
        "file",
        "download",
        "bid documents",
        "solicitation documents",
        "rfp documents",
    ],
    
    # Links
    "detail_url": [
        "details",
        "view",
        "view details",
        "more info",
        "more information",
        "link",
        "url",
        "see details",
        "full details",
    ],
}


# =============================================================================
# Status Value Mappings
# =============================================================================

STATUS_SYNONYMS: dict[str, list[str]] = {
    "OPEN": [
        "open",
        "active",
        "accepting bids",
        "accepting responses",
        "accepting submissions",
        "in progress",
        "current",
        "live",
        "available",
        "published",
        "posted",
        "issued",
        "advertised",
        "pending",
        "pending award",
        "under review",
        "evaluation",
        "bidding",
    ],
    "CLOSED": [
        "closed",
        "bid closed",
        "submissions closed",
        "response closed",
        "ended",
        "complete",
        "completed",
        "finished",
        "past due",
        "no longer accepting",
    ],
    "AWARDED": [
        "awarded",
        "award made",
        "contract awarded",
        "winner selected",
        "selected",
        "award complete",
        "under contract",
    ],
    "EXPIRED": [
        "expired",
        "lapsed",
        "past",
        "outdated",
        "stale",
    ],
    "CANCELLED": [
        "cancelled",
        "canceled",
        "withdrawn",
        "revoked",
        "terminated",
        "void",
        "deleted",
        "removed",
    ],
}


def normalize_status(raw_status: str) -> str:
    """Normalize a raw status string to canonical status.
    
    Args:
        raw_status: Raw status text from portal
        
    Returns:
        Canonical status string (OPEN, CLOSED, etc.)
    """
    normalized = raw_status.lower().strip()
    
    for canonical, synonyms in STATUS_SYNONYMS.items():
        if normalized in synonyms:
            return canonical
            
    return "UNKNOWN"


def get_synonyms_for_field(field_name: str) -> list[str]:
    """Get all synonyms for a canonical field name.
    
    Args:
        field_name: Canonical field name (e.g., 'closing_at')
        
    Returns:
        List of possible header texts for this field
    """
    return HEADER_SYNONYMS.get(field_name, [])


def find_canonical_field(header_text: str) -> str | None:
    """Find the canonical field name for a header text.
    
    Args:
        header_text: Raw header text from table
        
    Returns:
        Canonical field name if found, None otherwise
    """
    normalized = header_text.lower().strip()
    
    for canonical, synonyms in HEADER_SYNONYMS.items():
        if normalized in [s.lower() for s in synonyms]:
            return canonical
            
    return None
