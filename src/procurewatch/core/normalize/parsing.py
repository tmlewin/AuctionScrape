"""
Parsing utilities for normalizing extracted data.

Handles date, money, and status parsing from various formats.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, date, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import dateparser


# =============================================================================
# Date Parsing
# =============================================================================


@dataclass
class ParsedDate:
    """Result of parsing a date string."""
    
    value: datetime | None
    original: str
    confidence: float  # 0.0 - 1.0
    format_detected: str | None = None


def parse_date(
    value: str | datetime | date | None,
    *,
    prefer_day_first: bool = False,
    relative_base: datetime | None = None,
    timezone_name: str | None = None,
) -> ParsedDate:
    """Parse a date/datetime from various formats.
    
    Handles:
    - ISO 8601 formats
    - US formats (MM/DD/YYYY)
    - International formats (DD/MM/YYYY)
    - Natural language ("next Tuesday", "in 5 days")
    - Relative dates ("2 days ago")
    - Time-only (assumes today's date)
    
    Args:
        value: String or datetime to parse
        prefer_day_first: Prefer DD/MM/YYYY over MM/DD/YYYY
        relative_base: Base datetime for relative parsing
        timezone_name: Timezone to apply (e.g., "America/Los_Angeles")
        
    Returns:
        ParsedDate with parsed value and metadata
    """
    if value is None:
        return ParsedDate(value=None, original="", confidence=0.0)
    
    original = str(value).strip()
    
    if not original:
        return ParsedDate(value=None, original=original, confidence=0.0)
    
    # Already a datetime
    if isinstance(value, datetime):
        return ParsedDate(
            value=value,
            original=original,
            confidence=1.0,
            format_detected="datetime",
        )
    
    # Date object - convert to datetime
    if isinstance(value, date) and not isinstance(value, datetime):
        dt = datetime.combine(value, time.min)
        return ParsedDate(
            value=dt,
            original=original,
            confidence=1.0,
            format_detected="date",
        )
    
    # Clean the string
    text = _clean_date_string(original)
    
    if not text:
        return ParsedDate(value=None, original=original, confidence=0.0)
    
    # Try common patterns first (faster than dateparser)
    result = _try_common_patterns(text)
    if result:
        return ParsedDate(
            value=result[0],
            original=original,
            confidence=result[1],
            format_detected=result[2],
        )
    
    # Fall back to dateparser for complex/natural language dates
    settings = {
        "PREFER_DAY_OF_MONTH": "first",
        "PREFER_DATES_FROM": "future",  # Deadlines are usually in the future
        "RETURN_AS_TIMEZONE_AWARE": False,
        "STRICT_PARSING": False,
    }
    
    if prefer_day_first:
        settings["DATE_ORDER"] = "DMY"
    else:
        settings["DATE_ORDER"] = "MDY"
    
    if relative_base:
        settings["RELATIVE_BASE"] = relative_base
    
    if timezone_name:
        settings["TIMEZONE"] = timezone_name
    
    try:
        parsed = dateparser.parse(text, settings=settings)
        if parsed:
            # Calculate confidence based on specificity
            confidence = _calculate_date_confidence(text, parsed)
            return ParsedDate(
                value=parsed,
                original=original,
                confidence=confidence,
                format_detected="dateparser",
            )
    except Exception:
        pass
    
    return ParsedDate(value=None, original=original, confidence=0.0)


def _clean_date_string(text: str) -> str:
    """Clean and normalize a date string for parsing."""
    # Remove common prefixes
    prefixes = [
        r"^due:\s*",
        r"^closes?:\s*",
        r"^deadline:\s*",
        r"^closing\s+date:\s*",
        r"^open\s+until:\s*",
        r"^posted:\s*",
        r"^published:\s*",
        r"^date:\s*",
    ]
    for prefix in prefixes:
        text = re.sub(prefix, "", text, flags=re.IGNORECASE)
    
    # Normalize whitespace
    text = " ".join(text.split())
    
    # Remove trailing timezone abbreviations that confuse parsing
    text = re.sub(r"\s+(PT|PST|PDT|MT|MST|MDT|CT|CST|CDT|ET|EST|EDT)\s*$", "", text, flags=re.IGNORECASE)
    
    return text.strip()


def _try_common_patterns(text: str) -> tuple[datetime, float, str] | None:
    """Try to parse using common date patterns (fast path)."""
    patterns = [
        # ISO 8601
        (r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", 1.0, "iso8601"),
        (r"^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})", 0.95, "iso_space"),
        (r"^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})", 0.95, "iso_space_no_sec"),
        (r"^(\d{4})-(\d{2})-(\d{2})", 0.9, "iso_date"),
        
        # US format (MM/DD/YYYY)
        (r"^(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?", 0.85, "us_datetime"),
        (r"^(\d{1,2})/(\d{1,2})/(\d{4})", 0.85, "us_date"),
        
        # US format short year (MM/DD/YY)
        (r"^(\d{1,2})/(\d{1,2})/(\d{2})\b", 0.75, "us_date_short"),
    ]
    
    for pattern, confidence, name in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            try:
                groups = match.groups()
                
                if name.startswith("iso"):
                    year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                    hour = int(groups[3]) if len(groups) > 3 and groups[3] else 0
                    minute = int(groups[4]) if len(groups) > 4 and groups[4] else 0
                    second = int(groups[5]) if len(groups) > 5 and groups[5] else 0
                    
                elif name.startswith("us"):
                    month, day, year = int(groups[0]), int(groups[1]), int(groups[2])
                    if year < 100:
                        year += 2000 if year < 50 else 1900
                    
                    hour, minute, second = 0, 0, 0
                    if len(groups) > 3 and groups[3]:
                        hour = int(groups[3])
                        minute = int(groups[4]) if groups[4] else 0
                        second = int(groups[5]) if len(groups) > 5 and groups[5] else 0
                        
                        # Handle AM/PM
                        if len(groups) > 6 and groups[6]:
                            ampm = groups[6].upper()
                            if ampm == "PM" and hour < 12:
                                hour += 12
                            elif ampm == "AM" and hour == 12:
                                hour = 0
                else:
                    continue
                
                dt = datetime(year, month, day, hour, minute, second)
                return (dt, confidence, name)
                
            except (ValueError, IndexError):
                continue
    
    return None


def _calculate_date_confidence(text: str, parsed: datetime) -> float:
    """Calculate confidence score for a parsed date."""
    confidence = 0.7  # Base for dateparser
    
    # More specific formats get higher confidence
    if re.search(r"\d{4}", text):  # Has 4-digit year
        confidence += 0.1
    
    if re.search(r"\d{1,2}:\d{2}", text):  # Has time
        confidence += 0.1
    
    # Relative dates get lower confidence
    relative_words = ["today", "tomorrow", "yesterday", "ago", "next", "last"]
    if any(word in text.lower() for word in relative_words):
        confidence -= 0.1
    
    return min(1.0, max(0.0, confidence))


# =============================================================================
# Money Parsing
# =============================================================================


@dataclass
class ParsedMoney:
    """Result of parsing a money/currency value."""
    
    amount: Decimal | None
    currency: str
    original: str
    confidence: float


# Currency symbols and their codes
CURRENCY_SYMBOLS = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
    "C$": "CAD",
    "A$": "AUD",
    "CA$": "CAD",
    "AU$": "AUD",
    "US$": "USD",
}

# Currency code patterns
CURRENCY_CODES = {"USD", "EUR", "GBP", "JPY", "CAD", "AUD", "INR", "CHF", "CNY"}


def parse_money(
    value: str | float | Decimal | None,
    *,
    default_currency: str = "USD",
) -> ParsedMoney:
    """Parse a monetary value from various formats.
    
    Handles:
    - Currency symbols ($1,234.56)
    - Currency codes (USD 1234.56)
    - Plain numbers (1234.56)
    - Ranges (returns midpoint)
    - K/M/B suffixes ($1.5M)
    
    Args:
        value: String or number to parse
        default_currency: Currency code when not detected
        
    Returns:
        ParsedMoney with parsed amount and currency
    """
    if value is None:
        return ParsedMoney(amount=None, currency=default_currency, original="", confidence=0.0)
    
    original = str(value).strip()
    
    if not original:
        return ParsedMoney(amount=None, currency=default_currency, original=original, confidence=0.0)
    
    # Already a number
    if isinstance(value, (int, float, Decimal)):
        return ParsedMoney(
            amount=Decimal(str(value)),
            currency=default_currency,
            original=original,
            confidence=1.0,
        )
    
    text = original.upper()
    
    # Try to detect currency
    currency = default_currency
    confidence = 0.8
    
    # Check for currency codes
    for code in CURRENCY_CODES:
        if code in text:
            currency = code
            confidence = 0.95
            break
    
    # Check for currency symbols
    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in original:
            currency = code
            confidence = 0.9
            break
    
    # Extract the numeric part
    # Remove currency symbols and codes
    numeric_text = text
    for code in CURRENCY_CODES:
        numeric_text = numeric_text.replace(code, "")
    for symbol in CURRENCY_SYMBOLS:
        numeric_text = numeric_text.replace(symbol.upper(), "")
    
    # Handle ranges (take midpoint or first value)
    range_match = re.search(r"([\d,.]+)\s*(?:-|to)\s*([\d,.]+)", numeric_text)
    if range_match:
        low = _parse_numeric(range_match.group(1))
        high = _parse_numeric(range_match.group(2))
        if low is not None and high is not None:
            amount = (low + high) / 2
            confidence *= 0.9  # Lower confidence for ranges
            return ParsedMoney(
                amount=Decimal(str(amount)),
                currency=currency,
                original=original,
                confidence=confidence,
            )
    
    # Handle K/M/B suffixes
    suffix_match = re.search(r"([\d,.]+)\s*([KMB])\b", numeric_text)
    if suffix_match:
        base = _parse_numeric(suffix_match.group(1))
        suffix = suffix_match.group(2)
        if base is not None:
            multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
            amount = base * multipliers.get(suffix, 1)
            return ParsedMoney(
                amount=Decimal(str(amount)),
                currency=currency,
                original=original,
                confidence=confidence,
            )
    
    # Extract plain number
    number_match = re.search(r"[\d,.]+", numeric_text)
    if number_match:
        amount = _parse_numeric(number_match.group())
        if amount is not None:
            return ParsedMoney(
                amount=Decimal(str(amount)),
                currency=currency,
                original=original,
                confidence=confidence,
            )
    
    return ParsedMoney(amount=None, currency=currency, original=original, confidence=0.0)


def _parse_numeric(text: str) -> float | None:
    """Parse a numeric string, handling commas and decimals."""
    text = text.strip()
    if not text:
        return None
    
    # Determine if comma or period is the decimal separator
    # by looking at the last separator
    last_comma = text.rfind(",")
    last_period = text.rfind(".")
    
    if last_comma > last_period:
        # European format: 1.234,56
        text = text.replace(".", "").replace(",", ".")
    else:
        # US format: 1,234.56
        text = text.replace(",", "")
    
    try:
        return float(text)
    except ValueError:
        return None


# =============================================================================
# Status Parsing
# =============================================================================


@dataclass
class ParsedStatus:
    """Result of parsing a status string."""
    
    status: str  # Canonical status
    original: str
    confidence: float


# Status mappings (normalized status -> patterns)
STATUS_PATTERNS: dict[str, list[str]] = {
    "OPEN": [
        "open",
        "active",
        "accepting",
        "in progress",
        "pending",
        "current",
        "live",
        "ongoing",
        "available",
        "accepting bids",
        "accepting quotes",
        "accepting proposals",
        "open for bid",
        "open for quote",
        "bidding open",
    ],
    "CLOSED": [
        "closed",
        "ended",
        "expired",
        "deadline passed",
        "no longer accepting",
        "bidding closed",
        "submission closed",
        "past deadline",
        "time expired",
    ],
    "AWARDED": [
        "awarded",
        "award",
        "winner selected",
        "contract awarded",
        "vendor selected",
        "successful bidder",
        "awardee",
    ],
    "CANCELLED": [
        "cancelled",
        "canceled",
        "withdrawn",
        "rescinded",
        "voided",
        "terminated",
        "discontinued",
        "abandoned",
    ],
    "PENDING": [
        "pending",
        "under review",
        "in review",
        "evaluation",
        "being evaluated",
        "under evaluation",
        "in evaluation",
    ],
}


def parse_status(
    value: str | None,
    *,
    default: str = "UNKNOWN",
) -> ParsedStatus:
    """Parse a status string to a canonical status value.
    
    Args:
        value: Status string to parse
        default: Default status when parsing fails
        
    Returns:
        ParsedStatus with canonical status
    """
    if value is None:
        return ParsedStatus(status=default, original="", confidence=0.0)
    
    original = str(value).strip()
    
    if not original:
        return ParsedStatus(status=default, original=original, confidence=0.0)
    
    text = original.lower()
    
    # Check each status pattern
    for status, patterns in STATUS_PATTERNS.items():
        for pattern in patterns:
            if pattern in text:
                # Exact match gets higher confidence
                confidence = 0.95 if text == pattern else 0.85
                return ParsedStatus(
                    status=status,
                    original=original,
                    confidence=confidence,
                )
    
    # Try fuzzy matching for close matches
    for status, patterns in STATUS_PATTERNS.items():
        for pattern in patterns:
            # Check if the status text is mostly contained
            if _fuzzy_contains(text, pattern, threshold=0.8):
                return ParsedStatus(
                    status=status,
                    original=original,
                    confidence=0.7,
                )
    
    return ParsedStatus(status=default, original=original, confidence=0.3)


def _fuzzy_contains(text: str, pattern: str, threshold: float = 0.8) -> bool:
    """Check if text fuzzy-contains a pattern."""
    # Simple word-based containment check
    pattern_words = set(pattern.split())
    text_words = set(text.split())
    
    if not pattern_words:
        return False
    
    matched = len(pattern_words & text_words)
    ratio = matched / len(pattern_words)
    
    return ratio >= threshold


# =============================================================================
# Utility Functions
# =============================================================================


def normalize_whitespace(text: str | None) -> str:
    """Normalize whitespace in text."""
    if text is None:
        return ""
    return " ".join(text.split())


def extract_first_url(text: str | None) -> str | None:
    """Extract the first URL from text."""
    if text is None:
        return None
    
    url_pattern = r'https?://[^\s<>"\'{}|\\^`\[\]]+'
    match = re.search(url_pattern, text)
    
    return match.group(0) if match else None


def clean_html_text(text: str | None) -> str:
    """Clean text extracted from HTML."""
    if text is None:
        return ""
    
    # Remove common HTML artifacts
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"&amp;?", "&", text)
    text = re.sub(r"&lt;?", "<", text)
    text = re.sub(r"&gt;?", ">", text)
    text = re.sub(r"&quot;?", '"', text)
    text = re.sub(r"&#39;?", "'", text)
    
    # Normalize whitespace
    return normalize_whitespace(text)
