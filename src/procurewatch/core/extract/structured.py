"""
Structured data extractor for JSON-LD and embedded JSON.

Extracts opportunity data from:
- JSON-LD schema.org markup
- Embedded JSON in script tags
- Data attributes on elements
- API-style JSON responses
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from lxml import html as lxml_html

from .base import Extractor, ExtractionResult, FieldMapping

logger = logging.getLogger(__name__)


# Schema.org types that might contain procurement data
RELEVANT_SCHEMA_TYPES = [
    "Event",
    "Offer",
    "Product",
    "Service",
    "GovernmentService",
    "Thing",
]

# Mapping from schema.org properties to canonical fields
SCHEMA_FIELD_MAPPING = {
    # Identifiers
    "identifier": "external_id",
    "@id": "external_id",
    "sku": "external_id",
    
    # Title/Name
    "name": "title",
    "headline": "title",
    "alternateName": "title",
    
    # Description
    "description": "description",
    "abstract": "description",
    
    # Dates
    "startDate": "posted_at",
    "datePublished": "posted_at",
    "datePosted": "posted_at",
    "endDate": "closing_at",
    "validThrough": "closing_at",
    "expires": "closing_at",
    
    # Organization
    "provider": "agency",
    "seller": "agency",
    "organizer": "agency",
    "author": "agency",
    
    # Category
    "category": "category",
    "@type": "category",
    
    # Location
    "location": "location",
    "areaServed": "location",
    
    # Value
    "price": "estimated_value",
    "priceCurrency": "estimated_value_currency",
    
    # URLs
    "url": "detail_url",
    "mainEntityOfPage": "source_url",
    
    # Contact
    "contactPoint": "contact_info",
    "email": "contact_email",
    "telephone": "contact_phone",
}


class StructuredExtractor(Extractor):
    """Extractor for structured data (JSON-LD, embedded JSON).
    
    Looks for structured data in:
    1. JSON-LD script tags (<script type="application/ld+json">)
    2. Embedded JSON in script tags with known patterns
    3. Data attributes on elements
    4. Direct JSON content (for API responses)
    """
    
    def __init__(
        self,
        *,
        prefer_jsonld: bool = True,
        extract_embedded: bool = True,
        json_path_hints: list[str] | None = None,
    ):
        """Initialize the structured extractor.
        
        Args:
            prefer_jsonld: Prioritize JSON-LD over other sources
            extract_embedded: Also look for embedded JSON in scripts
            json_path_hints: JSONPath-like hints for finding data (e.g., "data.results")
        """
        self.prefer_jsonld = prefer_jsonld
        self.extract_embedded = extract_embedded
        self.json_path_hints = json_path_hints or []
    
    @property
    def name(self) -> str:
        return "structured"
    
    def extract(self, html: str, url: str | None = None) -> ExtractionResult:
        """Extract structured data from HTML or JSON content.
        
        Args:
            html: HTML content (or raw JSON)
            url: Source URL for context
            
        Returns:
            ExtractionResult with extracted records
        """
        records: list[dict[str, Any]] = []
        field_mappings: list[FieldMapping] = []
        warnings: list[str] = []
        errors: list[str] = []
        extraction_method = None
        
        # Try to detect if content is raw JSON
        content = html.strip()
        if content.startswith(("{", "[")):
            try:
                json_data = json.loads(content)
                records = self._extract_from_json(json_data)
                extraction_method = "raw_json"
                if records:
                    return self._build_result(
                        records, field_mappings, warnings, errors,
                        extraction_method, 0.9
                    )
            except json.JSONDecodeError:
                pass  # Not valid JSON, continue with HTML parsing
        
        # Parse as HTML
        try:
            tree = lxml_html.fromstring(html)
        except Exception as e:
            errors.append(f"HTML parse error: {e}")
            return self._build_result(records, field_mappings, warnings, errors, None, 0.0)
        
        # 1. Try JSON-LD extraction
        if self.prefer_jsonld:
            jsonld_records = self._extract_jsonld(tree)
            if jsonld_records:
                records.extend(jsonld_records)
                extraction_method = "jsonld"
        
        # 2. Try embedded JSON in script tags
        if self.extract_embedded and not records:
            embedded_records = self._extract_embedded_json(tree)
            if embedded_records:
                records.extend(embedded_records)
                extraction_method = "embedded_json"
        
        # 3. Try data attributes
        if not records:
            data_attr_records = self._extract_data_attributes(tree)
            if data_attr_records:
                records.extend(data_attr_records)
                extraction_method = "data_attributes"
        
        # 4. Try JSON-LD if we haven't yet
        if not self.prefer_jsonld and not records:
            jsonld_records = self._extract_jsonld(tree)
            if jsonld_records:
                records.extend(jsonld_records)
                extraction_method = "jsonld"
        
        # Calculate confidence
        confidence = 0.0
        if records:
            # Higher confidence for more complete records
            avg_fields = sum(len([v for v in r.values() if v]) for r in records) / len(records)
            confidence = min(0.95, 0.5 + (avg_fields / 20))
        
        return self._build_result(
            records, field_mappings, warnings, errors,
            extraction_method, confidence
        )
    
    def _extract_jsonld(self, tree: lxml_html.HtmlElement) -> list[dict[str, Any]]:
        """Extract data from JSON-LD script tags."""
        records: list[dict[str, Any]] = []
        
        # Find all JSON-LD script tags
        scripts = tree.cssselect('script[type="application/ld+json"]')
        
        for script in scripts:
            text = script.text_content()
            if not text:
                continue
            
            try:
                data = json.loads(text)
                
                # Handle @graph arrays
                if isinstance(data, dict) and "@graph" in data:
                    items = data["@graph"]
                elif isinstance(data, list):
                    items = data
                else:
                    items = [data]
                
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    
                    # Check if this is a relevant schema type
                    schema_type = item.get("@type", "")
                    if isinstance(schema_type, list):
                        schema_type = schema_type[0] if schema_type else ""
                    
                    # Map to canonical fields
                    record = self._map_jsonld_to_canonical(item)
                    if record and any(record.values()):
                        records.append(record)
                        
            except json.JSONDecodeError:
                continue
        
        return records
    
    def _map_jsonld_to_canonical(self, item: dict[str, Any]) -> dict[str, Any]:
        """Map JSON-LD properties to canonical field names."""
        record: dict[str, Any] = {}
        
        for schema_prop, canonical_field in SCHEMA_FIELD_MAPPING.items():
            if schema_prop in item:
                value = item[schema_prop]
                
                # Handle nested objects
                if isinstance(value, dict):
                    # Try to extract name or value
                    value = value.get("name") or value.get("value") or value.get("@value")
                elif isinstance(value, list):
                    # Take first item
                    if value:
                        first = value[0]
                        if isinstance(first, dict):
                            value = first.get("name") or first.get("value")
                        else:
                            value = first
                
                if value:
                    record[canonical_field] = str(value)
        
        # Store original data for debugging
        record["_jsonld"] = item
        
        return record
    
    def _extract_embedded_json(self, tree: lxml_html.HtmlElement) -> list[dict[str, Any]]:
        """Extract data from embedded JSON in script tags."""
        records: list[dict[str, Any]] = []
        
        # Common patterns for embedded data
        patterns = [
            r"window\.__DATA__\s*=\s*({.+?});",
            r"window\.initialData\s*=\s*({.+?});",
            r"var\s+data\s*=\s*({.+?});",
            r"var\s+bids\s*=\s*(\[.+?\]);",
            r"var\s+opportunities\s*=\s*(\[.+?\]);",
            r"JSON\.parse\s*\(\s*'(.+?)'\s*\)",
        ]
        
        # Get all script content
        for script in tree.cssselect("script:not([src])"):
            text = script.text_content()
            if not text:
                continue
            
            for pattern in patterns:
                matches = re.findall(pattern, text, re.DOTALL)
                for match in matches:
                    try:
                        # Unescape if needed
                        if match.startswith("'") or match.startswith('"'):
                            match = match[1:-1]
                        match = match.replace("\\'", "'").replace('\\"', '"')
                        
                        data = json.loads(match)
                        extracted = self._extract_from_json(data)
                        records.extend(extracted)
                    except json.JSONDecodeError:
                        continue
        
        return records
    
    def _extract_from_json(self, data: Any) -> list[dict[str, Any]]:
        """Extract records from parsed JSON data."""
        records: list[dict[str, Any]] = []
        
        # If it's a list, try each item
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    record = self._normalize_json_record(item)
                    if record and any(record.values()):
                        records.append(record)
            return records
        
        # If it's a dict, look for common data patterns
        if isinstance(data, dict):
            # Try path hints first
            for path in self.json_path_hints:
                nested = self._get_nested(data, path)
                if nested:
                    if isinstance(nested, list):
                        for item in nested:
                            if isinstance(item, dict):
                                record = self._normalize_json_record(item)
                                if record:
                                    records.append(record)
                    elif isinstance(nested, dict):
                        record = self._normalize_json_record(nested)
                        if record:
                            records.append(record)
                    if records:
                        return records
            
            # Common API response patterns
            for key in ["data", "results", "items", "records", "bids", "opportunities", "listings"]:
                if key in data:
                    nested = data[key]
                    if isinstance(nested, list):
                        for item in nested:
                            if isinstance(item, dict):
                                record = self._normalize_json_record(item)
                                if record:
                                    records.append(record)
                        if records:
                            return records
            
            # Treat the whole object as a single record
            record = self._normalize_json_record(data)
            if record and any(record.values()):
                records.append(record)
        
        return records
    
    def _normalize_json_record(self, item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a JSON record to canonical fields."""
        record: dict[str, Any] = {}
        
        # Direct field mappings (common API field names)
        field_mappings = {
            # ID
            "id": "external_id",
            "bid_id": "external_id",
            "solicitation_id": "external_id",
            "opportunity_id": "external_id",
            "reference": "external_id",
            "number": "external_id",
            
            # Title
            "title": "title",
            "name": "title",
            "subject": "title",
            "description_short": "title",
            
            # Description
            "description": "description",
            "details": "description",
            "summary": "description",
            "scope": "description",
            
            # Dates
            "close_date": "closing_at",
            "closing_date": "closing_at",
            "due_date": "closing_at",
            "deadline": "closing_at",
            "end_date": "closing_at",
            "post_date": "posted_at",
            "posted_date": "posted_at",
            "publish_date": "posted_at",
            "open_date": "posted_at",
            
            # Status
            "status": "status",
            "state": "status",
            "phase": "status",
            
            # Organization
            "agency": "agency",
            "organization": "agency",
            "department": "department",
            "buyer": "agency",
            
            # Category
            "category": "category",
            "type": "category",
            "commodity": "category",
            
            # Location
            "location": "location",
            "place": "location",
            "region": "location",
            
            # Value
            "value": "estimated_value",
            "amount": "estimated_value",
            "budget": "estimated_value",
            "estimated_value": "estimated_value",
            
            # URLs
            "url": "detail_url",
            "link": "detail_url",
            "href": "detail_url",
            
            # Contact
            "contact": "contact_name",
            "contact_name": "contact_name",
            "buyer_name": "contact_name",
            "email": "contact_email",
            "contact_email": "contact_email",
            "phone": "contact_phone",
            "contact_phone": "contact_phone",
        }
        
        for json_field, canonical_field in field_mappings.items():
            if json_field in item and item[json_field]:
                value = item[json_field]
                # Don't overwrite with lower-priority field
                if canonical_field not in record or not record[canonical_field]:
                    if isinstance(value, (str, int, float)):
                        record[canonical_field] = str(value)
                    elif isinstance(value, dict):
                        # Try to get a simple value
                        record[canonical_field] = str(
                            value.get("name") or value.get("value") or value.get("text") or ""
                        )
        
        # Store raw data
        record["_raw"] = item
        
        return record
    
    def _extract_data_attributes(self, tree: lxml_html.HtmlElement) -> list[dict[str, Any]]:
        """Extract data from data-* attributes on elements."""
        records: list[dict[str, Any]] = []
        
        # Look for elements with multiple data attributes (likely data rows)
        for element in tree.cssselect("[data-id], [data-bid-id], [data-item]"):
            record: dict[str, Any] = {}
            
            for attr, value in element.attrib.items():
                if attr.startswith("data-"):
                    field_name = attr[5:].replace("-", "_")  # data-bid-id -> bid_id
                    
                    # Map to canonical
                    if field_name in ("id", "bid_id", "item_id"):
                        record["external_id"] = value
                    elif field_name in ("title", "name"):
                        record["title"] = value
                    elif field_name in ("status", "state"):
                        record["status"] = value
                    elif field_name in ("date", "deadline", "due"):
                        record["closing_at"] = value
                    else:
                        record[field_name] = value
            
            if record and any(v for k, v in record.items() if not k.startswith("_")):
                records.append(record)
        
        return records
    
    def _get_nested(self, data: dict[str, Any], path: str) -> Any:
        """Get a nested value from a dict using dot notation."""
        parts = path.split(".")
        current = data
        
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit():
                idx = int(part)
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return None
            else:
                return None
        
        return current
    
    def _build_result(
        self,
        records: list[dict[str, Any]],
        field_mappings: list[FieldMapping],
        warnings: list[str],
        errors: list[str],
        extraction_method: str | None,
        confidence: float,
    ) -> ExtractionResult:
        """Build the extraction result."""
        return ExtractionResult(
            records=records,
            confidence=confidence,
            record_count=len(records),
            field_mappings=field_mappings,
            unmapped_headers=[],
            warnings=warnings,
            errors=errors,
            extraction_method=extraction_method,
        )
