"""Normalization and canonicalization of extracted data."""

from .parsing import (
    ParsedDate,
    ParsedMoney,
    ParsedStatus,
    parse_date,
    parse_money,
    parse_status,
    normalize_whitespace,
    clean_html_text,
    extract_first_url,
)
from .canonical import OpportunityCanonical, normalize_opportunity
from .diff import (
    FieldChange,
    DiffResult,
    compute_fingerprint,
    compute_diff,
    detect_event_type,
)

__all__ = [
    # Parsing
    "ParsedDate",
    "ParsedMoney",
    "ParsedStatus",
    "parse_date",
    "parse_money",
    "parse_status",
    "normalize_whitespace",
    "clean_html_text",
    "extract_first_url",
    # Canonical
    "OpportunityCanonical",
    "normalize_opportunity",
    # Diff
    "FieldChange",
    "DiffResult",
    "compute_fingerprint",
    "compute_diff",
    "detect_event_type",
]
