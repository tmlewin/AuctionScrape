"""
Heuristic table extraction with header synonym mapping.

Automatically finds HTML tables and maps headers to canonical
fields using fuzzy matching against a synonym dictionary.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

from lxml import html as lxml_html
from lxml.html import HtmlElement
from thefuzz import fuzz

from ..config.synonyms import HEADER_SYNONYMS, find_canonical_field
from .base import ExtractionResult, Extractor, FieldMapping

if TYPE_CHECKING:
    pass


# Minimum fuzzy match score to consider a match
FUZZY_MATCH_THRESHOLD = 75

# Minimum confidence to consider extraction successful
MIN_CONFIDENCE_THRESHOLD = 0.4

# Required fields for a valid opportunity listing
REQUIRED_FIELDS = {"external_id", "title"}
IMPORTANT_FIELDS = {"closing_at", "posted_at", "status", "agency"}


class HeuristicTableExtractor(Extractor):
    """Extract data from HTML tables using heuristic header mapping.
    
    Features:
    - Automatic table detection (finds best candidate)
    - Header synonym matching (exact + fuzzy)
    - Confidence scoring
    - Link extraction for detail URLs
    """
    
    def __init__(
        self,
        table_selector: str | None = None,
        row_selector: str | None = None,
        header_aliases: dict[str, list[str]] | None = None,
        fuzzy_threshold: int = FUZZY_MATCH_THRESHOLD,
        base_url: str | None = None,
    ):
        """Initialize extractor.
        
        Args:
            table_selector: CSS selector for table (auto-detect if None)
            row_selector: CSS selector for rows (default: tbody tr)
            header_aliases: Additional header aliases to merge with defaults
            fuzzy_threshold: Minimum fuzzy match score (0-100)
            base_url: Base URL for resolving relative links
        """
        self.table_selector = table_selector
        self.row_selector = row_selector or "tbody tr"
        self.fuzzy_threshold = fuzzy_threshold
        self.base_url = base_url
        
        # Merge header aliases with defaults
        self.header_aliases = {**HEADER_SYNONYMS}
        if header_aliases:
            for field, aliases in header_aliases.items():
                if field in self.header_aliases:
                    self.header_aliases[field].extend(aliases)
                else:
                    self.header_aliases[field] = aliases
    
    @property
    def name(self) -> str:
        return "heuristic_table"
    
    def extract(self, html: str, url: str | None = None) -> ExtractionResult:
        """Extract data from HTML tables.
        
        Args:
            html: HTML content
            url: Source URL for resolving links
            
        Returns:
            ExtractionResult with extracted records
        """
        result = ExtractionResult(extraction_method=self.name)
        base_url = url or self.base_url
        
        try:
            doc = lxml_html.fromstring(html)
        except Exception as e:
            result.add_error(f"Failed to parse HTML: {e}")
            return result
        
        # Find tables
        tables = self._find_tables(doc)
        
        if not tables:
            result.add_warning("No tables found in document")
            return result
        
        # Try each table, keep best result
        best_result: ExtractionResult | None = None
        
        for table in tables:
            table_result = self._extract_table(table, base_url)
            
            if table_result.ok:
                if best_result is None or table_result.confidence > best_result.confidence:
                    best_result = table_result
        
        if best_result:
            return best_result
        
        # If no table succeeded, return last attempt with warnings
        result.add_warning(f"Tried {len(tables)} tables, none matched required fields")
        return result
    
    def _find_tables(self, doc: HtmlElement) -> list[HtmlElement]:
        """Find candidate tables in the document.
        
        Args:
            doc: Parsed HTML document
            
        Returns:
            List of table elements, sorted by likelihood
        """
        tables = []
        
        # If specific selector provided, use it
        if self.table_selector:
            try:
                from lxml.cssselect import CSSSelector
                selector = CSSSelector(self.table_selector)
                tables = selector(doc)
            except Exception:
                # Fall back to XPath
                tables = doc.xpath(f"//{self.table_selector}")
        else:
            # Find all tables
            tables = doc.xpath("//table")
        
        # Score and sort tables
        scored_tables = []
        for table in tables:
            score = self._score_table(table)
            if score > 0:
                scored_tables.append((score, table))
        
        # Sort by score descending
        scored_tables.sort(key=lambda x: x[0], reverse=True)
        
        return [t[1] for t in scored_tables[:5]]  # Return top 5
    
    def _score_table(self, table: HtmlElement) -> float:
        """Score a table's likelihood of containing procurement data.
        
        Args:
            table: Table element
            
        Returns:
            Score (higher = more likely)
        """
        score = 0.0
        
        # Check for headers
        headers = self._extract_headers(table)
        if not headers:
            return 0
        
        # Score based on header matches
        for header in headers:
            canonical = self._match_header(header)
            if canonical:
                if canonical in REQUIRED_FIELDS:
                    score += 10
                elif canonical in IMPORTANT_FIELDS:
                    score += 5
                else:
                    score += 2
        
        # Check row count
        rows = table.xpath(".//tbody/tr") or table.xpath(".//tr")
        row_count = len(rows)
        
        if row_count == 0:
            return 0
        elif row_count < 3:
            score *= 0.5  # Probably not a data table
        elif row_count > 100:
            score *= 1.2  # Lots of data is good
        
        # Penalize nested tables
        nested = table.xpath(".//table")
        if nested:
            score *= 0.5
        
        return score
    
    def _extract_headers(self, table: HtmlElement) -> list[str]:
        """Extract header texts from a table.
        
        Args:
            table: Table element
            
        Returns:
            List of header texts
        """
        headers = []
        
        # Try thead first
        header_cells = table.xpath(".//thead//th")
        if not header_cells:
            # Try first row
            header_cells = table.xpath(".//tr[1]/th")
        if not header_cells:
            # Try first row td
            header_cells = table.xpath(".//tr[1]/td")
        
        for cell in header_cells:
            text = self._get_cell_text(cell)
            headers.append(text)
        
        return headers
    
    def _get_cell_text(self, cell: HtmlElement) -> str:
        """Extract clean text from a cell.
        
        Args:
            cell: Cell element
            
        Returns:
            Cleaned text content
        """
        text = cell.text_content()
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def _get_cell_link(self, cell: HtmlElement, base_url: str | None) -> str | None:
        """Extract first link from a cell.
        
        Args:
            cell: Cell element
            base_url: Base URL for resolving relative links
            
        Returns:
            Absolute URL or None
        """
        links = cell.xpath(".//a/@href")
        if links:
            href = links[0]
            if base_url and not href.startswith(("http://", "https://")):
                href = urljoin(base_url, href)
            return href
        return None
    
    def _match_header(self, header: str) -> str | None:
        """Match a header text to a canonical field name.
        
        Args:
            header: Raw header text
            
        Returns:
            Canonical field name or None
        """
        normalized = header.lower().strip()
        
        if not normalized:
            return None
        
        # Try exact match first
        canonical = find_canonical_field(normalized)
        if canonical:
            return canonical
        
        # Try fuzzy matching
        best_match: str | None = None
        best_score = 0
        
        for field, aliases in self.header_aliases.items():
            for alias in aliases:
                score = fuzz.ratio(normalized, alias.lower())
                if score > best_score and score >= self.fuzzy_threshold:
                    best_score = score
                    best_match = field
        
        return best_match
    
    def _extract_table(self, table: HtmlElement, base_url: str | None) -> ExtractionResult:
        """Extract data from a single table.
        
        Args:
            table: Table element
            base_url: Base URL for links
            
        Returns:
            ExtractionResult
        """
        result = ExtractionResult(extraction_method=self.name)
        
        # Get headers
        headers = self._extract_headers(table)
        if not headers:
            result.add_warning("No headers found in table")
            return result
        
        # Map headers to fields
        mappings: list[FieldMapping] = []
        unmapped: list[str] = []
        
        for i, header in enumerate(headers):
            canonical = self._match_header(header)
            if canonical:
                # Calculate confidence based on match type
                exact = find_canonical_field(header.lower()) is not None
                confidence = 1.0 if exact else 0.7
                
                mappings.append(FieldMapping(
                    header_text=header,
                    canonical_field=canonical,
                    column_index=i,
                    confidence=confidence,
                    match_type="exact" if exact else "fuzzy",
                ))
            else:
                unmapped.append(header)
        
        result.field_mappings = mappings
        result.unmapped_headers = unmapped
        
        # Check if we have required fields
        mapped_fields = {m.canonical_field for m in mappings}
        has_required = bool(mapped_fields & REQUIRED_FIELDS)
        
        if not has_required:
            result.add_warning(f"Missing required fields. Have: {mapped_fields}")
            result.confidence = 0.2
            return result
        
        # Extract rows
        rows = table.xpath(".//tbody/tr")
        if not rows:
            # Try without tbody
            rows = table.xpath(".//tr[position()>1]")
        
        records: list[dict[str, Any]] = []
        
        for row_idx, row in enumerate(rows):
            cells = row.xpath("./td")
            if not cells:
                continue
            
            record: dict[str, Any] = {}
            row_has_data = False
            
            for mapping in mappings:
                if mapping.column_index < len(cells):
                    cell = cells[mapping.column_index]
                    value = self._get_cell_text(cell)
                    
                    if value:
                        record[mapping.canonical_field] = value
                        row_has_data = True
                    
                    # Also extract links for certain fields
                    if mapping.canonical_field in ("external_id", "title", "detail_url"):
                        link = self._get_cell_link(cell, base_url)
                        if link:
                            record["detail_url"] = link
            
            if row_has_data:
                record["_row_index"] = row_idx
                records.append(record)
        
        result.records = records
        result.record_count = len(records)
        
        # Calculate overall confidence
        result.confidence = self._calculate_confidence(result)
        
        return result
    
    def _calculate_confidence(self, result: ExtractionResult) -> float:
        """Calculate overall extraction confidence.
        
        Args:
            result: Extraction result
            
        Returns:
            Confidence score (0.0 - 1.0)
        """
        if not result.records:
            return 0.0
        
        # Start with base confidence from field mappings
        mapping_confidence = sum(m.confidence for m in result.field_mappings)
        max_mapping_confidence = len(result.field_mappings) + len(result.unmapped_headers)
        
        if max_mapping_confidence == 0:
            return 0.0
        
        field_score = mapping_confidence / max_mapping_confidence
        
        # Check for required fields
        mapped_fields = {m.canonical_field for m in result.field_mappings}
        required_score = len(mapped_fields & REQUIRED_FIELDS) / len(REQUIRED_FIELDS)
        important_score = len(mapped_fields & IMPORTANT_FIELDS) / len(IMPORTANT_FIELDS)
        
        # Record count factor
        record_factor = min(1.0, len(result.records) / 5)  # At least 5 records for full score
        
        # Combine factors
        confidence = (
            field_score * 0.3 +
            required_score * 0.4 +
            important_score * 0.2 +
            record_factor * 0.1
        )
        
        return round(confidence, 3)
