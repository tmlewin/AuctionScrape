"""
Extraction pipeline for stacking multiple extraction strategies.

Tries structured data, table heuristics, card heuristics, and
optional rule-based extraction in order.
"""

from __future__ import annotations

from procurewatch.core.config.models import ExtractionConfig, ExtractionMode
from .base import Extractor, ExtractionResult
from .heuristic_card import HeuristicCardExtractor
from .heuristic_table import HeuristicTableExtractor
from .rules import RuleExtractor
from .structured import StructuredExtractor


class ExtractionPipeline(Extractor):
    """Pipeline of extraction strategies with fallback logic."""

    def __init__(
        self,
        extractors: list[Extractor] | None = None,
        config: ExtractionConfig | None = None,
        confidence_threshold: float = 0.4,
    ) -> None:
        """Initialize the extraction pipeline.

        Args:
            extractors: Optional list of extractors (default chain if None)
            config: Extraction configuration (for rule-based extraction)
            confidence_threshold: Minimum confidence to accept a result
        """
        self.extractors = extractors or [
            StructuredExtractor(),
            HeuristicTableExtractor(),
            HeuristicCardExtractor(),
        ]
        self.confidence_threshold = confidence_threshold
        self.config = config

        if config and config.listing.mode in (ExtractionMode.CSS_RULES, ExtractionMode.XPATH_RULES):
            self.extractors.append(RuleExtractor(config.listing))

    @property
    def name(self) -> str:
        return "pipeline"

    def extract(self, html: str, url: str | None = None) -> ExtractionResult:
        """Try extractors in order until one succeeds.

        Args:
            html: HTML content
            url: Source URL

        Returns:
            ExtractionResult from the first successful extractor
        """
        all_warnings: list[str] = []
        all_errors: list[str] = []

        for extractor in self.extractors:
            result = extractor.extract(html, url)
            all_warnings.extend(result.warnings)
            all_errors.extend(result.errors)

            if result.ok and result.confidence >= self.confidence_threshold:
                result.warnings = all_warnings
                result.errors = all_errors
                return result

        return ExtractionResult(
            extraction_method="pipeline_failed",
            confidence=0.0,
            warnings=all_warnings,
            errors=["All extraction strategies failed", *all_errors],
        )
