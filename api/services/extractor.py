"""Extraction pipeline orchestrator: rule-based -> LLM fallback."""

import logging
from dataclasses import dataclass, field
from typing import Any

from api.services.html_cleaner import clean_html, html_to_text
from api.services.llm_extractor import LLMResult, extract_with_llm
from api.services.rule_extractor import extract_structured_data
from api.services.schema_validator import build_validation_feedback, validate_against_schema

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Result from the extraction pipeline."""
    data: dict[str, Any]
    extraction_method: str  # "rule" | "llm"
    model_used: str | None = None
    tokens_used: int = 0
    warnings: list[str] = field(default_factory=list)


async def extract(
    html: str,
    url: str,
    schema: dict[str, Any] | None = None,
    prompt: str | None = None,
) -> ExtractionResult:
    """Run the three-tier extraction pipeline.

    1. Try rule-based extraction (JSON-LD, OG, meta tags)
    2. If insufficient, clean HTML and send to LLM
    3. Validate LLM output against schema; retry once on failure
    """
    rule_data = extract_structured_data(html, schema)
    if rule_data is not None:
        result_data = rule_data
        warnings: list[str] = []
        if schema:
            result_data, warnings = validate_against_schema(rule_data, schema)
        return ExtractionResult(
            data=result_data,
            extraction_method="rule",
            warnings=warnings,
        )

    cleaned = clean_html(html)
    content = html_to_text(cleaned)

    llm_result: LLMResult = await extract_with_llm(content, schema=schema, prompt=prompt)
    warnings = []

    if schema:
        validated, val_warnings = validate_against_schema(llm_result.data, schema)

        if val_warnings:
            feedback = build_validation_feedback(val_warnings, schema)
            try:
                retry_result = await extract_with_llm(
                    content, schema=schema, prompt=prompt, extra_context=feedback
                )
                validated_retry, retry_warnings = validate_against_schema(
                    retry_result.data, schema
                )
                if len(retry_warnings) < len(val_warnings):
                    validated = validated_retry
                    warnings = retry_warnings
                    llm_result = retry_result
                else:
                    warnings = val_warnings
            except Exception:
                logger.warning("Validation retry failed, using original result")
                warnings = val_warnings

        return ExtractionResult(
            data=validated,
            extraction_method="llm",
            model_used=llm_result.model_used,
            tokens_used=llm_result.tokens_used,
            warnings=warnings,
        )

    return ExtractionResult(
        data=llm_result.data,
        extraction_method="llm",
        model_used=llm_result.model_used,
        tokens_used=llm_result.tokens_used,
    )
