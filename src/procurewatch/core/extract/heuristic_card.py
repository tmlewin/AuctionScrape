"""
Heuristic card extraction for div/card-based layouts.

Detects repeating card structures and extracts canonical fields
without portal-specific configuration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from lxml import html as lxml_html
from lxml.html import HtmlElement
from thefuzz import fuzz

from ..config.synonyms import HEADER_SYNONYMS, find_canonical_field
from .base import ExtractionResult, Extractor, FieldMapping


FUZZY_MATCH_THRESHOLD = 75
MIN_CARD_COUNT = 3
MIN_CONFIDENCE_THRESHOLD = 0.4

REQUIRED_FIELDS = {"external_id", "title"}
IMPORTANT_FIELDS = {"closing_at", "posted_at", "status", "agency", "category", "detail_url"}

CARD_CLASS_HINTS = (
    "card",
    "result",
    "listing",
    "item",
    "opportunity",
    "search-result",
    "mat-card",
)

CONTAINER_CLASS_HINTS = (
    "results",
    "list",
    "items",
    "search-results",
    "listing",
    "content",
)

STATUS_CLASS_HINTS = (
    "status",
    "badge",
    "state",
    "tag",
    "chip",
    "label",
)

AGENCY_CLASS_HINTS = (
    "agency",
    "organization",
    "department",
    "buyer",
    "ministry",
    "fg-text",
    "org",
)

AGENCY_KEYWORDS = (
    "town",
    "city",
    "county",
    "municipal",
    "ministry",
    "department",
    "authority",
    "board",
    "district",
    "university",
    "college",
    "school",
    "government",
)

STATUS_TOKENS = (
    "open",
    "closed",
    "awarded",
    "expired",
    "cancelled",
    "canceled",
    "draft",
    "evaluation",
    "selection",
)

TITLE_STOPWORDS = {"view", "details", "more", "read more", "learn more"}

DATE_PATTERN = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},\s+\d{4})\b",
    re.IGNORECASE,
)


@dataclass
class _CardContainerCandidate:
    """Candidate container for repeated card elements."""

    score: float
    container: HtmlElement
    cards: list[HtmlElement]
    signature: str


class HeuristicCardExtractor(Extractor):
    """Extract data from card-based listing pages.

    Detects repeating card elements (divs, list items, custom tags)
    and extracts canonical fields using fuzzy label mapping.
    """

    def __init__(
        self,
        *,
        min_card_count: int = MIN_CARD_COUNT,
        fuzzy_threshold: int = FUZZY_MATCH_THRESHOLD,
        base_url: str | None = None,
    ) -> None:
        """Initialize the heuristic card extractor.

        Args:
            min_card_count: Minimum repeated elements to consider a container
            fuzzy_threshold: Minimum fuzzy match score (0-100)
            base_url: Base URL for resolving relative links
        """
        self.min_card_count = min_card_count
        self.fuzzy_threshold = fuzzy_threshold
        self.base_url = base_url

    @property
    def name(self) -> str:
        return "heuristic_card"

    def extract(self, html: str, url: str | None = None) -> ExtractionResult:
        """Extract data from card-based layouts.

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

        candidates = self._find_candidate_containers(doc)
        if not candidates:
            result.add_warning("No repeating card containers found")
            return result

        best = candidates[0]
        result.source_selector = best.signature

        records: list[dict[str, Any]] = []
        mappings: list[FieldMapping] = []
        unmapped: list[str] = []

        for index, card in enumerate(best.cards):
            record, card_mappings, card_unmapped = self._extract_card(card, base_url)
            if record:
                record["_row_index"] = index
                records.append(record)
            mappings.extend(card_mappings)
            unmapped.extend(card_unmapped)

        if not records:
            result.add_warning("No card records extracted")
            return result

        result.records = records
        result.record_count = len(records)
        result.field_mappings = self._dedupe_mappings(mappings)
        result.unmapped_headers = self._dedupe_unmapped(unmapped)
        result.confidence = self._calculate_confidence(result)

        if result.confidence < MIN_CONFIDENCE_THRESHOLD:
            result.add_warning("Card extraction confidence below threshold")

        return result

    def _find_candidate_containers(self, doc: HtmlElement) -> list[_CardContainerCandidate]:
        """Find repeating card containers in the document."""
        candidates: list[_CardContainerCandidate] = []

        for element in doc.xpath("//*"):
            children = [child for child in element if isinstance(child.tag, str)]
            if len(children) < self.min_card_count:
                continue

            grouped: dict[str, list[HtmlElement]] = {}
            for child in children:
                signature = self._child_signature(child)
                grouped.setdefault(signature, []).append(child)

            for signature, cards in grouped.items():
                if len(cards) < self.min_card_count:
                    continue
                score = self._score_container(element, cards, signature)
                if score > 0:
                    candidates.append(_CardContainerCandidate(score, element, cards, signature))

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:5]

    def _child_signature(self, element: HtmlElement) -> str:
        """Create a simple signature for an element based on tag and class."""
        classes = element.get("class", "")
        class_key = " ".join(sorted(classes.split())[:3]).lower()
        return f"{element.tag}|{class_key}"

    def _score_container(
        self,
        container: HtmlElement,
        cards: list[HtmlElement],
        signature: str,
    ) -> float:
        """Score a container based on repeated card structure."""
        count = len(cards)
        if count < self.min_card_count:
            return 0.0

        link_ratio = self._ratio_with_links(cards)
        text_ratio = self._ratio_with_text(cards)
        child_count = len([child for child in container if isinstance(child.tag, str)])
        similarity_ratio = count / child_count if child_count else 0.0

        class_hint_score = 0.0
        if self._has_class_hint(signature, CARD_CLASS_HINTS):
            class_hint_score += 2.0
        if self._container_has_hint(container):
            class_hint_score += 1.5
        if self._is_custom_tag(cards[0].tag):
            class_hint_score += 1.5

        count_score = min(count, 30)
        content_multiplier = 1 + (link_ratio * 2.0) + (text_ratio * 1.5)

        score = (
            count_score * content_multiplier
            + similarity_ratio * 2.0
            + class_hint_score
        )

        if link_ratio < 0.2 and text_ratio < 0.2:
            score *= 0.4

        return score

    def _ratio_with_links(self, cards: list[HtmlElement]) -> float:
        """Return ratio of cards that contain links."""
        if not cards:
            return 0.0
        linked = sum(1 for card in cards if card.xpath(".//a[@href]"))
        return linked / len(cards)

    def _ratio_with_text(self, cards: list[HtmlElement]) -> float:
        """Return ratio of cards with meaningful text content."""
        if not cards:
            return 0.0
        with_text = 0
        for card in cards:
            text = self._clean_text(card.text_content())
            if len(text) > 40:
                with_text += 1
        return with_text / len(cards)

    def _container_has_hint(self, container: HtmlElement) -> bool:
        """Check container class hints."""
        class_value = (container.get("class") or "").lower()
        return any(hint in class_value for hint in CONTAINER_CLASS_HINTS)

    def _has_class_hint(self, signature: str, hints: tuple[str, ...]) -> bool:
        """Check if a signature string contains any hint tokens."""
        return any(hint in signature for hint in hints)

    def _is_custom_tag(self, tag: str) -> bool:
        """Check if an element tag is a custom element tag."""
        return "-" in tag

    def _extract_card(
        self,
        card: HtmlElement,
        base_url: str | None,
    ) -> tuple[dict[str, Any], list[FieldMapping], list[str]]:
        """Extract fields from a single card element."""
        record: dict[str, Any] = {}
        mappings: list[FieldMapping] = []
        unmapped: list[str] = []

        detail_url, link_text = self._extract_primary_link(card, base_url)
        title = self._extract_title(card, link_text)

        if detail_url:
            record["detail_url"] = detail_url
        if title:
            record["title"] = title

        label_fields, label_mappings, label_unmapped = self._extract_label_value_pairs(card)
        mappings.extend(label_mappings)
        unmapped.extend(label_unmapped)

        for field_name, value in label_fields.items():
            if value and field_name not in record:
                record[field_name] = value

        external_id = self._extract_external_id(card, detail_url)
        if external_id and "external_id" not in record:
            record["external_id"] = external_id

        status = self._extract_status(card)
        if status and "status" not in record:
            record["status"] = status

        agency = self._extract_agency(card, title, status)
        if agency and "agency" not in record:
            record["agency"] = agency

        if "closing_at" not in record or "posted_at" not in record:
            date_fields = self._extract_dates(card)
            if date_fields:
                if "closing_at" not in record:
                    record["closing_at"] = date_fields[0]
                if "posted_at" not in record and len(date_fields) > 1:
                    record["posted_at"] = date_fields[1]

        if not (record.get("external_id") or record.get("title")):
            return {}, mappings, unmapped

        return record, mappings, unmapped

    def _extract_primary_link(
        self,
        card: HtmlElement,
        base_url: str | None,
    ) -> tuple[str | None, str | None]:
        """Extract the most likely detail link from a card."""
        best_score = 0
        best_href: str | None = None
        best_text: str | None = None

        for link in card.xpath(".//a[@href]"):
            href = link.get("href")
            if not href or href.startswith("#") or href.lower().startswith("javascript:"):
                continue

            text = self._clean_text(link.text_content())
            score = 0

            if text and len(text) > 3:
                score += min(len(text), 80)
            if self._has_class_hint((link.get("class") or "").lower(), ("title",)):
                score += 10
            if any(token in href for token in ("posting", "opportunity", "tender", "bid", "notice")):
                score += 20

            if score > best_score:
                best_score = score
                best_href = href
                best_text = text

        if not best_href:
            return None, None

        if base_url and not best_href.startswith(("http://", "https://")):
            best_href = urljoin(base_url, best_href)

        return best_href, best_text

    def _extract_title(self, card: HtmlElement, link_text: str | None) -> str | None:
        """Extract a likely title from the card."""
        if link_text and self._is_title_candidate(link_text):
            return link_text

        for selector in ("h1", "h2", "h3", "h4", "h5"):
            for element in card.cssselect(selector):
                text = self._clean_text(element.text_content())
                if self._is_title_candidate(text):
                    return text

        for element in card.cssselect("[class*='title']"):
            text = self._clean_text(element.text_content())
            if self._is_title_candidate(text):
                return text

        candidates = []
        for line in self._extract_text_lines(card):
            if self._is_title_candidate(line):
                candidates.append(line)

        if candidates:
            candidates.sort(key=len, reverse=True)
            return candidates[0]

        return None

    def _is_title_candidate(self, text: str | None) -> bool:
        """Check if text is a plausible title."""
        if not text:
            return False
        cleaned = text.strip()
        if len(cleaned) < 4 or len(cleaned) > 180:
            return False
        if cleaned.lower() in TITLE_STOPWORDS:
            return False
        return True

    def _extract_external_id(self, card: HtmlElement, detail_url: str | None) -> str | None:
        """Extract external identifier from attributes or links."""
        attr_candidates = self._extract_attribute_values(
            card,
            {
                "data-id",
                "data-bid-id",
                "data-opportunity-id",
                "data-posting-id",
                "data-item-id",
                "id",
            },
        )
        for value in attr_candidates:
            if value:
                return value

        if detail_url:
            parsed = urlparse(detail_url)
            if parsed.path:
                last_segment = parsed.path.rstrip("/").split("/")[-1]
                if last_segment and len(last_segment) >= 4:
                    return last_segment

            query = parse_qs(parsed.query)
            for key in ("id", "bid", "posting", "opportunity"):
                if key in query and query[key]:
                    return query[key][0]

        text_match = re.search(r"\b[A-Z]{2,}-\d{2,}[A-Z0-9-]*\b", card.text_content())
        if text_match:
            return text_match.group(0)

        return None

    def _extract_attribute_values(
        self,
        card: HtmlElement,
        attribute_names: set[str],
    ) -> list[str]:
        """Collect values from matching attributes in a card subtree."""
        values: list[str] = []
        for element in card.iter():
            for attr, value in element.attrib.items():
                if attr in attribute_names and value:
                    values.append(value)
        return values

    def _extract_status(self, card: HtmlElement) -> str | None:
        """Extract status from badge-like elements or text."""
        for element in card.iter():
            class_value = (element.get("class") or "").lower()
            if any(hint in class_value for hint in STATUS_CLASS_HINTS):
                text = self._clean_text(element.text_content())
                if text and len(text) <= 24:
                    return text

        text = self._clean_text(card.text_content()).lower()
        for token in ("open", "closed", "awarded", "expired", "cancelled", "canceled"):
            if token in text:
                return token.title()

        return None

    def _extract_agency(self, card: HtmlElement, title: str | None, status: str | None) -> str | None:
        """Extract agency/organization from card content."""
        candidates: list[tuple[float, str]] = []

        for element in card.iter():
            class_value = (element.get("class") or "").lower()
            if any(hint in class_value for hint in AGENCY_CLASS_HINTS):
                text = self._clean_text(element.text_content())
                score = self._score_agency_candidate(text)
                if score > 0:
                    candidates.append((score, text))

        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            return candidates[0][1]

        for line in self._extract_text_lines(card):
            if line == title or line == status:
                continue
            score = self._score_agency_candidate(line)
            if score > 0:
                candidates.append((score, line))

        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            return candidates[0][1]

        return None

    def _score_agency_candidate(self, text: str | None) -> float:
        """Score how likely a text is an agency/organization name."""
        if not text:
            return 0.0
        if len(text) < 3 or len(text) > 140:
            return 0.0
        if DATE_PATTERN.search(text):
            return 0.0

        lower = text.lower()
        score = 0.0

        if any(token in lower for token in AGENCY_KEYWORDS):
            score += 6.0
        if any(token in lower for token in STATUS_TOKENS):
            score -= 6.0

        length_score = max(0.0, 20.0 - abs(len(text) - 30))
        score += length_score / 2

        if len(text.split()) >= 2:
            score += 2.0

        return score

    def _extract_dates(self, card: HtmlElement) -> list[str]:
        """Extract date strings from card text."""
        text = self._clean_text(card.text_content())
        if not text:
            return []
        return [match.group(0) for match in DATE_PATTERN.finditer(text)]

    def _extract_label_value_pairs(
        self,
        card: HtmlElement,
    ) -> tuple[dict[str, str], list[FieldMapping], list[str]]:
        """Extract label-value pairs from a card and map to canonical fields."""
        pairs: list[tuple[str, str]] = []

        for dt in card.cssselect("dt"):
            label = self._clean_text(dt.text_content())
            dd = dt.getnext()
            if dd is not None and dd.tag == "dd":
                value = self._clean_text(dd.text_content())
                if label and value:
                    pairs.append((label, value))

        for row in card.cssselect("tr"):
            cells = row.cssselect("th, td")
            if len(cells) >= 2:
                label = self._clean_text(cells[0].text_content())
                value = self._clean_text(cells[1].text_content())
                if label and value:
                    pairs.append((label, value))

        for detail in card.cssselect("[class*='detail']"):
            headers = detail.cssselect("[class*='header']")
            values = detail.cssselect("[class*='value']")
            if headers and values:
                label = self._clean_text(headers[0].text_content())
                value = self._clean_text(values[0].text_content())
                if label and value:
                    pairs.append((label, value))

        for element in card.cssselect(".label, .field-label, .field-name, [class*='label']"):
            label = self._clean_text(element.text_content())
            if not label or len(label) > 60:
                continue
            value_element = element.getnext()
            if value_element is None:
                continue
            value = self._clean_text(value_element.text_content())
            if value:
                pairs.append((label, value))

        for line in self._extract_text_lines(card):
            if ":" in line and len(line) < 120:
                label, value = line.split(":", 1)
                label = self._clean_text(label)
                value = self._clean_text(value)
                if label and value:
                    pairs.append((label, value))

        mapped: dict[str, str] = {}
        mappings: list[FieldMapping] = []
        unmapped: list[str] = []

        for index, (label, value) in enumerate(pairs):
            canonical, confidence, match_type = self._match_label(label)
            if canonical:
                if canonical not in mapped:
                    mapped[canonical] = value
                mappings.append(FieldMapping(
                    header_text=label,
                    canonical_field=canonical,
                    column_index=index,
                    confidence=confidence,
                    match_type=match_type,
                ))
            else:
                unmapped.append(label)

        return mapped, mappings, unmapped

    def _match_label(self, label: str) -> tuple[str | None, float, str]:
        """Match a label to a canonical field using exact and fuzzy mapping."""
        normalized = self._normalize_label(label)
        if not normalized:
            return None, 0.0, "none"

        if any(token in normalized for token in ("posting", "posted", "publish", "issue", "open date")):
            return "posted_at", 0.9, "keyword"
        if any(token in normalized for token in ("closing", "close", "due", "deadline", "end")):
            return "closing_at", 0.9, "keyword"
        if any(token in normalized for token in ("reference", "solicitation", "rfp", "rfq", "bid", "notice")):
            return "external_id", 0.9, "keyword"
        if any(token in normalized for token in ("category", "type", "commodity", "classification")):
            return "category", 0.9, "keyword"
        if any(token in normalized for token in ("status", "state", "phase")):
            return "status", 0.9, "keyword"
        if any(token in normalized for token in ("agency", "organization", "department", "buyer", "ministry")):
            return "agency", 0.9, "keyword"

        exact = find_canonical_field(normalized)
        if exact:
            return exact, 1.0, "exact"

        best_match: str | None = None
        best_score = 0

        for field, aliases in HEADER_SYNONYMS.items():
            for alias in aliases:
                score = fuzz.ratio(normalized, alias.lower())
                if score > best_score and score >= self.fuzzy_threshold:
                    best_score = score
                    best_match = field

        if best_match:
            return best_match, 0.7, "fuzzy"

        return None, 0.0, "none"

    def _normalize_label(self, label: str) -> str:
        """Normalize a label for matching."""
        normalized = label.lower().strip()
        normalized = re.sub(r"[^a-z0-9#\s]", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _extract_text_lines(self, card: HtmlElement) -> list[str]:
        """Extract cleaned text lines from a card."""
        raw_text = card.text_content()
        if not raw_text:
            return []
        lines = [self._clean_text(line) for line in raw_text.splitlines()]
        return [line for line in lines if line]

    def _clean_text(self, text: str) -> str:
        """Normalize whitespace in text."""
        return re.sub(r"\s+", " ", text).strip() if text else ""

    def _calculate_confidence(self, result: ExtractionResult) -> float:
        """Calculate confidence score for card extraction."""
        if not result.records:
            return 0.0

        required_hits = 0
        field_scores: list[float] = []

        for record in result.records:
            fields_present = sum(1 for field in IMPORTANT_FIELDS if record.get(field))
            field_scores.append(fields_present / len(IMPORTANT_FIELDS))

            if record.get("external_id") or record.get("title"):
                required_hits += 1

        required_score = required_hits / len(result.records)
        field_score = sum(field_scores) / len(field_scores) if field_scores else 0.0
        record_factor = min(1.0, len(result.records) / 5)

        confidence = (
            field_score * 0.4
            + required_score * 0.4
            + record_factor * 0.2
        )

        return round(confidence, 3)

    def _dedupe_mappings(self, mappings: list[FieldMapping]) -> list[FieldMapping]:
        """Deduplicate field mappings by header/canonical pair."""
        seen: set[tuple[str, str]] = set()
        deduped: list[FieldMapping] = []
        for mapping in mappings:
            key = (mapping.header_text, mapping.canonical_field)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(mapping)
        return deduped

    def _dedupe_unmapped(self, labels: list[str]) -> list[str]:
        """Deduplicate unmapped labels while preserving order."""
        seen: set[str] = set()
        deduped: list[str] = []
        for label in labels:
            if label in seen:
                continue
            seen.add(label)
            deduped.append(label)
        return deduped
