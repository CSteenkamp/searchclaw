"""LLM-based extraction using OpenAI (primary) and Anthropic (fallback)."""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import tiktoken

from api.config import get_settings

logger = logging.getLogger(__name__)

MAX_TOKENS = 8000
ENCODING = "cl100k_base"


@dataclass
class LLMResult:
    """Result from an LLM extraction call."""
    data: dict[str, Any]
    model_used: str
    tokens_used: int
    warnings: list[str] = field(default_factory=list)


def _count_tokens(text: str) -> int:
    """Count tokens using tiktoken."""
    enc = tiktoken.get_encoding(ENCODING)
    return len(enc.encode(text))


def _truncate_to_tokens(text: str, max_tokens: int = MAX_TOKENS) -> str:
    """Truncate text to fit within token budget."""
    enc = tiktoken.get_encoding(ENCODING)
    tokens = enc.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return enc.decode(tokens[:max_tokens])


def _build_system_prompt(schema: dict | None, prompt: str | None) -> str:
    """Build the system prompt for LLM extraction."""
    parts = [
        "You are a data extraction assistant. Extract structured data from the provided HTML content.",
        "Return ONLY valid JSON with no additional text or explanation.",
    ]
    if schema:
        parts.append(
            f"Extract data matching this exact schema (keys and types must match): {json.dumps(schema)}"
        )
        parts.append(
            "Type mappings: 'string' → JSON string, 'number' → JSON number, "
            "'boolean' → JSON boolean, 'array' or ['type'] → JSON array."
        )
    if prompt:
        parts.append(f"Additional context: {prompt}")
    if not schema and prompt:
        parts.append("Infer an appropriate JSON structure from the description above.")
    return "\n".join(parts)


async def _call_openai(system_prompt: str, content: str) -> tuple[dict, str, int]:
    """Call OpenAI API. Returns (data, model_name, tokens_used)."""
    import openai

    settings = get_settings()
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    model = settings.llm_model
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    result_text = response.choices[0].message.content or "{}"
    tokens = response.usage.total_tokens if response.usage else 0
    return json.loads(result_text), model, tokens


async def _call_anthropic(system_prompt: str, content: str) -> tuple[dict, str, int]:
    """Call Anthropic API as fallback. Returns (data, model_name, tokens_used)."""
    import anthropic

    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    model = settings.llm_fallback_model
    response = await client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt + "\nReturn ONLY valid JSON, no markdown fences or extra text.",
        messages=[{"role": "user", "content": content}],
    )
    result_text = response.content[0].text
    tokens = (response.usage.input_tokens or 0) + (response.usage.output_tokens or 0)
    if result_text.startswith("```"):
        lines = result_text.split("\n")
        result_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(result_text), model, tokens


async def extract_with_llm(
    cleaned_html: str,
    schema: dict | None = None,
    prompt: str | None = None,
    extra_context: str | None = None,
) -> LLMResult:
    """Extract structured data from cleaned HTML using LLM.

    Tries OpenAI first, falls back to Anthropic.
    Retries once on failure before switching models.
    """
    system_prompt = _build_system_prompt(schema, prompt)
    if extra_context:
        system_prompt += f"\n{extra_context}"

    content = _truncate_to_tokens(cleaned_html, MAX_TOKENS)

    for attempt in range(2):
        try:
            data, model, tokens = await _call_openai(system_prompt, content)
            return LLMResult(data=data, model_used=model, tokens_used=tokens)
        except Exception as e:
            logger.warning("OpenAI attempt %d failed: %s", attempt + 1, e)

    for attempt in range(2):
        try:
            data, model, tokens = await _call_anthropic(system_prompt, content)
            return LLMResult(data=data, model_used=model, tokens_used=tokens)
        except Exception as e:
            logger.warning("Anthropic attempt %d failed: %s", attempt + 1, e)

    raise RuntimeError("All LLM extraction attempts failed")
