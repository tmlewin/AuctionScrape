"""
Rule-based extractor for CSS/XPath selector-driven extraction.

Uses config-defined selectors to extract listing fields from
HTML content with optional attribute and regex processing.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from lxml import html as lxml_html
from lxml.html import HtmlElement

from procurewatch.core.config.models import ExtractionMode, FieldExtractionRule, ListingExtractionConfig
from .base import ExtractionResult, Extractor


MIN_CONFIDENCE_THRESHOLD = 0.4


class RuleExtractor(Extractor):
    """Extract listing data using explicit CSS or XPath rules."""

    def __init__(
        self,
        config: ListingExtractionConfig,
        *,
        base_url: str | None = None,
    ) -> None:
        """Initialize the rule extractor.

        Args:
            config: Listing extraction configuration
            base_url: Base URL for resolving relative links
        """
        self.config = config
        self.base_url = base_url

    @property
    def name(self) -> str:
        return "rules"

    def extract(self, html: str, url: str | None = None) -> ExtractionResult:
        """Extract data using configured selector rules.

        Args:
            html: HTML content
            url: Source URL for resolving links

        Returns:
            ExtractionResult with extracted records
        """
        result = ExtractionResult(extraction_method=self.name)
        base_url = url or self.base_url

        try:
            tree = lxml_html.fromstring(html)
        except Exception as e:
            result.add_error(f"Failed to parse HTML: {e}")
            return result

        if not self.config.fields:
            result.add_warning("No rule fields configured")
            return result

        if self.config.container_selector:
            containers = self._select_elements(tree, self.config.container_selector)
            if not containers:
                result.add_warning("No containers matched rule selector")
                return result

            records = self._extract_from_containers(containers, base_url)
            result.source_selector = self.config.container_selector
        else:
            records = self._extract_from_field_lists(tree, base_url)

        result.records = records
        result.record_count = len(records)
        result.confidence = self._calculate_confidence(records)

        if result.confidence < MIN_CONFIDENCE_THRESHOLD:
            result.add_warning("Rule extraction confidence below threshold")

        return result

    def _extract_from_containers(
        self,
        containers: list[HtmlElement],
        base_url: str | None,
    ) -> list[dict[str, Any]]:
        """Extract records by iterating container elements."""
        records: list[dict[str, Any]] = []

        for index, container in enumerate(containers):
            record: dict[str, Any] = {}
            for field_name, rule in self.config.fields.items():
                value = self._extract_field(container, rule, base_url)
                if value:
                    record[field_name] = value

            if record:
                record["_row_index"] = index
                records.append(record)

        return records

    def _extract_from_field_lists(
        self,
        tree: HtmlElement,
        base_url: str | None,
    ) -> list[dict[str, Any]]:
        """Extract records by aligning field selector lists."""
        field_values: dict[str, list[str]] = {}

        for field_name, rule in self.config.fields.items():
            values = self._extract_values(tree, rule, base_url)
            if values:
                field_values[field_name] = values

        if not field_values:
            return []

        max_len = max(len(values) for values in field_values.values())
        records: list[dict[str, Any]] = []

        for index in range(max_len):
            record: dict[str, Any] = {}
            for field_name, values in field_values.items():
                if index < len(values) and values[index]:
                    record[field_name] = values[index]
            if record:
                record["_row_index"] = index
                records.append(record)

        return records

    def _extract_field(
        self,
        container: HtmlElement,
        rule: FieldExtractionRule,
        base_url: str | None,
    ) -> str | None:
        """Extract a single field using configured selectors."""
        for selector in rule.selectors:
            elements = self._select_elements(container, selector)
            if not elements:
                continue
            value = self._extract_value(elements[0], rule, base_url)
            if value:
                return value
        return None

    def _extract_values(
        self,
        container: HtmlElement,
        rule: FieldExtractionRule,
        base_url: str | None,
    ) -> list[str]:
        """Extract multiple values using configured selectors."""
        for selector in rule.selectors:
            elements = self._select_elements(container, selector)
            if not elements:
                continue
            values = []
            for element in elements:
                value = self._extract_value(element, rule, base_url)
                if value:
                    values.append(value)
            if values:
                return values
        return []

    def _select_elements(self, container: HtmlElement, selector: str) -> list[HtmlElement]:
        """Select elements using CSS or XPath based on mode or selector."""
        if self._should_use_xpath(selector):
            try:
                return list(container.xpath(selector))
            except Exception:
                return []

        try:
            elements = container.cssselect(selector)
        except Exception:
            elements = []

        if not elements and self._looks_like_xpath(selector):
            try:
                return list(container.xpath(selector))
            except Exception:
                return []

        return list(elements)

    def _should_use_xpath(self, selector: str) -> bool:
        """Check if XPath should be used based on configured mode."""
        if self.config.mode == ExtractionMode.XPATH_RULES:
            return True
        return self._looks_like_xpath(selector)

    def _looks_like_xpath(self, selector: str) -> bool:
        """Heuristic check for XPath selector syntax."""
        return selector.startswith("/") or selector.startswith(".//") or selector.startswith("(")

    def _extract_value(
        self,
        element: HtmlElement,
        rule: FieldExtractionRule,
        base_url: str | None,
    ) -> str | None:
        """Extract and clean a value from an element."""
        if rule.attribute:
            value = element.get(rule.attribute)
            if value and rule.attribute in {"href", "src"} and base_url:
                value = urljoin(base_url, value)
        else:
            value = element.text_content()

        if not value:
            return None

        if rule.regex:
            match = re.search(rule.regex, value)
            if not match:
                return None
            value = match.group(1) if match.groups() else match.group(0)

        if rule.clean:
            value = re.sub(r"\s+", " ", value).strip()

        return value or None

    def _calculate_confidence(self, records: list[dict[str, Any]]) -> float:
        """Calculate confidence based on field completeness and required fields."""
        if not records:
            return 0.0

        total_fields = len(self.config.fields)
        required_fields = {
            field_name
            for field_name, rule in self.config.fields.items()
            if rule.required
        }

        field_scores: list[float] = []
        required_scores: list[float] = []

        for record in records:
            if total_fields:
                present = sum(1 for field in self.config.fields if record.get(field))
                field_scores.append(present / total_fields)

            if required_fields:
                required_present = sum(1 for field in required_fields if record.get(field))
                required_scores.append(required_present / len(required_fields))

        field_score = sum(field_scores) / len(field_scores) if field_scores else 0.0
        required_score = sum(required_scores) / len(required_scores) if required_scores else 1.0
        record_factor = min(1.0, len(records) / 5)

        confidence = (
            field_score * 0.4
            + required_score * 0.4
            + record_factor * 0.2
        )

        return round(confidence, 3)
