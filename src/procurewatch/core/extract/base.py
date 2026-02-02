"""
Extraction base classes and data structures.

Defines the interface for all extraction strategies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FieldMapping:
    """Mapping of a table header to a canonical field."""
    
    header_text: str  # Original header text
    canonical_field: str  # Mapped field name
    column_index: int  # Column position
    confidence: float  # Mapping confidence (0.0 - 1.0)
    match_type: str = "exact"  # exact, fuzzy, positional


@dataclass
class ExtractionResult:
    """Result of an extraction operation."""
    
    # Extracted records
    records: list[dict[str, Any]] = field(default_factory=list)
    
    # Extraction metadata
    confidence: float = 0.0  # Overall confidence (0.0 - 1.0)
    record_count: int = 0
    
    # Mapping information
    field_mappings: list[FieldMapping] = field(default_factory=list)
    unmapped_headers: list[str] = field(default_factory=list)
    
    # Warnings and errors
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    
    # Debug info
    source_selector: str | None = None  # CSS selector used
    extraction_method: str | None = None  # Method used
    
    @property
    def ok(self) -> bool:
        """Check if extraction was successful."""
        return len(self.records) > 0 and self.confidence > 0.3
    
    @property
    def mapped_field_count(self) -> int:
        """Count of successfully mapped fields."""
        return len(self.field_mappings)
    
    def add_warning(self, message: str) -> None:
        """Add a warning message."""
        self.warnings.append(message)
    
    def add_error(self, message: str) -> None:
        """Add an error message."""
        self.errors.append(message)


@dataclass
class ListingItem:
    """A single item from a listing page.
    
    Represents an opportunity summary before detail page fetch.
    """
    
    # Extracted fields
    external_id: str | None = None
    title: str | None = None
    closing_at: str | None = None  # Raw string, normalized later
    posted_at: str | None = None
    status: str | None = None
    agency: str | None = None
    category: str | None = None
    
    # URL to detail page
    detail_url: str | None = None
    
    # Raw data for debugging
    raw_data: dict[str, Any] = field(default_factory=dict)
    
    # Extraction metadata
    confidence: float = 0.0
    row_index: int = 0
    
    @property
    def has_id(self) -> bool:
        """Check if we have an identifier."""
        return bool(self.external_id or self.title)


class Extractor(ABC):
    """Abstract base class for extraction strategies."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Extractor identifier."""
        pass
    
    @abstractmethod
    def extract(self, html: str, url: str | None = None) -> ExtractionResult:
        """Extract data from HTML content.
        
        Args:
            html: HTML content to parse
            url: Source URL for context
            
        Returns:
            ExtractionResult with extracted data
        """
        pass
    
    def extract_listings(self, html: str, url: str | None = None) -> list[ListingItem]:
        """Extract listing items from a listing page.
        
        Convenience method that converts ExtractionResult to ListingItems.
        
        Args:
            html: HTML content
            url: Source URL
            
        Returns:
            List of ListingItem objects
        """
        result = self.extract(html, url)
        items = []
        
        for i, record in enumerate(result.records):
            item = ListingItem(
                external_id=record.get("external_id"),
                title=record.get("title"),
                closing_at=record.get("closing_at"),
                posted_at=record.get("posted_at"),
                status=record.get("status"),
                agency=record.get("agency"),
                category=record.get("category"),
                detail_url=record.get("detail_url"),
                raw_data=record,
                confidence=result.confidence,
                row_index=i,
            )
            items.append(item)
        
        return items
