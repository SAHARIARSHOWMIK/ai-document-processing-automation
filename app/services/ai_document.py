"""
AI document service: classification + structured field extraction via Claude.

Two tasks, matching the project spec:
  Task 1 - Classification: extracted text -> document_type, confidence, reason
  Task 2 - Field extraction: document_type + extracted text -> structured
           fields, missing_fields, uncertain_fields, confidence, summary

Both tasks force structured output via tool-use (no free text), and both
are validated against Pydantic schemas. Any failure (bad API call, missing
tool_use, schema validation error) falls back to a safe low-confidence
result rather than crashing - mirroring app/services/ai_analysis.py from
Project 1.

AI quality rules (from the spec) enforced here:
  - Output must be structured (forced tool-use).
  - Missing/uncertain fields must be listed.
  - Low confidence triggers human review (enforced by the classification
    router using settings.classification_*_threshold, not here).
  - The AI never approves or exports documents - this module only produces
    *proposed* structured data.
"""

import logging

from app.config import settings
from app.models import DocumentType
from app.schemas import (
    DOCUMENT_FIELD_SCHEMAS,
    ClassificationResult,
    ExtractionResult,
)

logger = logging.getLogger("doc_automation.ai_document")


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

CLASSIFICATION_SYSTEM_PROMPT = """You are an AI assistant inside a business document automation system.
Your job is to read the extracted text of a single uploaded document and
classify which of these document types it is:

  invoice          - a bill requesting payment for goods/services
  receipt          - proof of a completed payment/transaction
  purchase_order   - a buyer's order to a supplier for goods/services
  contract         - a legal agreement between two or more parties
  unknown          - none of the above, or the text is unclear/unreadable

Be conservative with confidence:
  - 0.80+ only when the document type is unambiguous.
  - 0.60-0.79 when reasonably confident but some ambiguity exists.
  - below 0.60 when unsure, or when classifying as 'unknown'.

Always respond by calling the submit_classification tool. Do not respond
with plain text.
"""

CLASSIFICATION_TOOL = {
    "name": "submit_classification",
    "description": "Submit the document type classification.",
    "input_schema": {
        "type": "object",
        "properties": {
            "document_type": {
                "type": "string",
                "enum": [t.value for t in DocumentType],
            },
            "confidence": {"type": "number", "description": "0.0 to 1.0"},
            "reason": {"type": "string", "description": "Why this classification was chosen."},
        },
        "required": ["document_type", "confidence", "reason"],
    },
}


def _classification_fallback(reason: str) -> ClassificationResult:
    return ClassificationResult(
        document_type=DocumentType.UNKNOWN,
        confidence=0.0,
        reason=f"AI classification could not be completed reliably: {reason}",
    )


def classify_with_claude(text: str) -> tuple[ClassificationResult, dict]:
    """Call Claude to classify the document. Returns (result, raw_response)."""
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    try:
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=512,
            system=CLASSIFICATION_SYSTEM_PROMPT,
            tools=[CLASSIFICATION_TOOL],
            tool_choice={"type": "tool", "name": "submit_classification"},
            messages=[{"role": "user", "content": f"Extracted document text:\n\n{text}"}],
        )
    except Exception as exc:
        logger.error("Anthropic classification call failed: %s", exc)
        return _classification_fallback(f"API call failed: {exc}"), {"error": str(exc), "mode": "claude"}

    tool_use = next((b for b in response.content if getattr(b, "type", None) == "tool_use"), None)
    if tool_use is None:
        return _classification_fallback("model did not return structured output"), {
            "error": "no tool_use block",
            "mode": "claude",
        }

    try:
        result = ClassificationResult.model_validate(tool_use.input)
    except Exception as exc:
        logger.error("Classification output failed schema validation: %s", exc)
        return _classification_fallback(f"schema validation failed: {exc}"), {
            "error": str(exc),
            "mode": "claude",
            "raw_input": tool_use.input,
        }

    return result, {"mode": "claude", "raw_input": tool_use.input}


def classify_document(text: str) -> tuple[ClassificationResult, dict]:
    """Main entrypoint for classification. Uses the mock classifier when
    DEMO_MODE=true or no API key is configured."""
    if settings.demo_mode or not settings.anthropic_api_key:
        from app.services.mock_document_ai import mock_classify

        return mock_classify(text), {"mode": "mock"}

    return classify_with_claude(text)


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------

def _field_schema_description(document_type: DocumentType) -> str:
    """Build a human-readable list of fields for the given document type,
    derived from the Pydantic schema in app.schemas.DOCUMENT_FIELD_SCHEMAS."""
    schema_cls = DOCUMENT_FIELD_SCHEMAS.get(document_type)
    if not schema_cls:
        return "(no field schema available for this document type)"

    lines = []
    for field_name, field_info in schema_cls.model_fields.items():
        annotation = field_info.annotation
        type_name = getattr(annotation, "__name__", str(annotation))
        lines.append(f"  - {field_name}: {type_name}")
    return "\n".join(lines)


EXTRACTION_SYSTEM_PROMPT_TEMPLATE = """You are an AI assistant inside a business document automation system.
The document has already been classified as: {document_type}

Extract the following fields from the document text. Dates must be ISO
format (YYYY-MM-DD). Amounts must be plain numbers (no currency symbols or
commas). If a field cannot be found, omit it or set it to null - do not
guess.

Fields to extract:
{field_list}

Also identify:
  - missing_fields: required information that should exist but could not be found
  - uncertain_fields: fields you extracted but are not confident about
  - confidence: overall extraction confidence, 0.0 to 1.0 (be conservative)
  - summary: a one-sentence, human-friendly summary of this document

Always respond by calling the submit_extraction tool. Do not respond with
plain text. Never approve or export this document - extraction only.
"""

EXTRACTION_TOOL = {
    "name": "submit_extraction",
    "description": "Submit structured field extraction for a business document.",
    "input_schema": {
        "type": "object",
        "properties": {
            "extracted_fields": {
                "type": "object",
                "description": "The extracted field values, matching the requested field list.",
            },
            "missing_fields": {"type": "array", "items": {"type": "string"}},
            "uncertain_fields": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number", "description": "0.0 to 1.0"},
            "summary": {"type": "string"},
        },
        "required": ["extracted_fields", "missing_fields", "uncertain_fields", "confidence", "summary"],
    },
}


def _extraction_fallback(document_type: DocumentType, reason: str) -> ExtractionResult:
    return ExtractionResult(
        document_type=document_type,
        extracted_fields={},
        missing_fields=[],
        uncertain_fields=[],
        confidence=0.0,
        summary=f"AI field extraction could not be completed reliably: {reason}",
    )


def extract_with_claude(document_type: DocumentType, text: str) -> tuple[ExtractionResult, dict]:
    """Call Claude to extract structured fields. Returns (result, raw_response)."""
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    system_prompt = EXTRACTION_SYSTEM_PROMPT_TEMPLATE.format(
        document_type=document_type.value,
        field_list=_field_schema_description(document_type),
    )

    try:
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=1536,
            system=system_prompt,
            tools=[EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "submit_extraction"},
            messages=[{"role": "user", "content": f"Extracted document text:\n\n{text}"}],
        )
    except Exception as exc:
        logger.error("Anthropic extraction call failed: %s", exc)
        return _extraction_fallback(document_type, f"API call failed: {exc}"), {"error": str(exc), "mode": "claude"}

    tool_use = next((b for b in response.content if getattr(b, "type", None) == "tool_use"), None)
    if tool_use is None:
        return _extraction_fallback(document_type, "model did not return structured output"), {
            "error": "no tool_use block",
            "mode": "claude",
        }

    raw_input = dict(tool_use.input)
    raw_input["document_type"] = document_type.value

    try:
        result = ExtractionResult.model_validate(raw_input)
    except Exception as exc:
        logger.error("Extraction output failed schema validation: %s", exc)
        return _extraction_fallback(document_type, f"schema validation failed: {exc}"), {
            "error": str(exc),
            "mode": "claude",
            "raw_input": raw_input,
        }

    # Validate (and normalize) extracted_fields against the per-type schema.
    # Lenient: unknown extra keys are dropped, missing/None fields stay None.
    schema_cls = DOCUMENT_FIELD_SCHEMAS.get(document_type)
    if schema_cls:
        try:
            validated_fields = schema_cls.model_validate(result.extracted_fields)
            result.extracted_fields = validated_fields.model_dump()
        except Exception as exc:
            logger.warning("extracted_fields failed per-type schema validation: %s", exc)
            # Keep the AI's raw fields but flag low confidence so it routes to review.
            result.confidence = min(result.confidence, 0.5)
            result.uncertain_fields = list(set(result.uncertain_fields) | {"(schema validation issue - review all fields)"})

    return result, {"mode": "claude", "raw_input": raw_input}


def extract_fields(document_type: DocumentType, text: str) -> tuple[ExtractionResult, dict]:
    """Main entrypoint for field extraction. Uses the mock extractor when
    DEMO_MODE=true or no API key is configured."""
    if settings.demo_mode or not settings.anthropic_api_key:
        from app.services.mock_document_ai import mock_extract_fields

        return mock_extract_fields(document_type, text), {"mode": "mock"}

    return extract_with_claude(document_type, text)
