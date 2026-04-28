"""Thin Gemini API wrapper for A0 company research.

Isolates the SDK so the provider can be swapped later without touching
research.py.  All callers should catch A0ResearchError and its subclasses.

Rate-limit handling (Q1=B decision, 2026-04-28):
    On 429 / RESOURCE_EXHAUSTED, exponential backoff + retry (MAX_RETRIES
    attempts).  Assumes billing is enabled on the key — retries are the
    "paid fallback" behaviour.  If all retries exhaust, raises A0ResearchError
    with a retry hint for decisions.log.

API constraint (discovered 2026-04-28):
    google_search grounding + response_mime_type="application/json" cannot
    be combined in the same call (400 INVALID_ARGUMENT).  response_schema
    alone is sufficient to obtain structured JSON output alongside grounding.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import types

LOGGER = logging.getLogger(__name__)

MODEL_ID = "gemini-2.5-pro"
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds; doubles each attempt (2s, 4s, 8s)


# ── Response / error types ─────────────────────────────────────────────────────


@dataclass
class GeminiResponse:
    """Structured result from a Gemini call."""

    content: dict[str, Any]
    sources: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)


class A0ResearchError(Exception):
    """Unrecoverable research error — caller should surface in decisions.log."""


class A0SchemaError(A0ResearchError):
    """Gemini response failed schema or JSON validation."""


class A0NoSourcesError(A0ResearchError):
    """Grounding returned zero usable sources after all attempts."""


# ── Public API ─────────────────────────────────────────────────────────────────


def call_research(prompt: str, response_schema: dict) -> GeminiResponse:
    """Call Gemini 2.5 Pro with google_search grounding + responseSchema.

    Note: response_mime_type must NOT be set alongside google_search tools —
    the API rejects that combination with 400 INVALID_ARGUMENT. response_schema
    alone is sufficient to constrain structured JSON output.

    On rate limit: exponential backoff up to MAX_RETRIES, then raises
    A0ResearchError.  Assumes billing is active (Q1=B).

    Args:
        prompt: Research prompt built from role context.
        response_schema: Gemini-compatible JSON schema dict.

    Returns:
        GeminiResponse with parsed content dict, source URLs, and usage stats.

    Raises:
        A0ResearchError: API error or exhausted retries.
        A0SchemaError: Response was not valid JSON or not a JSON object.
    """
    client = _make_client()
    last_exc: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            raw = client.models.generate_content(
                model=MODEL_ID,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    response_schema=response_schema,
                ),
            )
            return _parse_response(raw)

        except (A0SchemaError, A0ResearchError):
            raise  # don't retry our own errors

        except Exception as exc:
            last_exc = exc
            if _is_rate_limit(exc) and attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2**attempt)
                LOGGER.warning(
                    "Gemini rate limit (attempt %d/%d) — retrying in %.1fs. err=%s",
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                    exc,
                )
                time.sleep(delay)
                continue
            break

    raise A0ResearchError(
        f"Gemini API error after {MAX_RETRIES} attempt(s): {last_exc}. "
        "If this is a quota error, check billing is active on GEMINI_API_KEY account."
    ) from last_exc


def call_with_url_fetch(
    prompt: str,
    urls: list[str],
    response_schema: dict,
) -> GeminiResponse:
    """Fallback: inject explicit URLs into the prompt when grounding sources are thin.

    Called when call_research returns <3 grounding sources.  Adds the top
    URLs to the prompt so Gemini fetches them explicitly during grounding.

    Args:
        prompt: Original research prompt.
        urls: Source URLs to explicitly surface (capped at 5).
        response_schema: Gemini-compatible JSON schema dict.

    Returns:
        GeminiResponse with parsed content, sources, and usage stats.
    """
    url_block = "\n".join(f"  - {u}" for u in urls[:5])
    enriched = (
        f"{prompt}\n\n"
        f"Note: grounding returned thin sources on the first pass. "
        f"Please also consult these specific URLs:\n{url_block}"
    )
    client = _make_client()
    last_exc: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            raw = client.models.generate_content(
                model=MODEL_ID,
                contents=enriched,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    response_schema=response_schema,
                ),
            )
            return _parse_response(raw)

        except (A0SchemaError, A0ResearchError):
            raise

        except Exception as exc:
            last_exc = exc
            if _is_rate_limit(exc) and attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2**attempt)
                LOGGER.warning(
                    "Gemini fallback rate limit (attempt %d/%d) — retrying in %.1fs.",
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                time.sleep(delay)
                continue
            break

    raise A0ResearchError(
        f"Gemini fallback API error after {MAX_RETRIES} attempt(s): {last_exc}"
    ) from last_exc


# ── Internal helpers ───────────────────────────────────────────────────────────


def _make_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise A0ResearchError(
            "GEMINI_API_KEY environment variable is not set. "
            "Export it before running A0."
        )
    return genai.Client(api_key=api_key)


def _strip_markdown_fences(text: str) -> str:
    """Remove leading ```json / ``` fences that Gemini sometimes wraps output in."""
    import re
    stripped = text.strip()
    stripped = re.sub(r"^```(?:json)?\s*\n", "", stripped)
    stripped = re.sub(r"\n```\s*$", "", stripped)
    return stripped.strip()


def _parse_response(raw: Any) -> GeminiResponse:
    """Extract content, grounding sources, and usage from a raw Gemini response."""
    text = getattr(raw, "text", None)
    if not text:
        raise A0ResearchError("Gemini returned an empty response body")

    # Without response_mime_type, Gemini may wrap JSON in markdown fences.
    # Strip them before parsing.
    text = _strip_markdown_fences(text)

    try:
        content = json.loads(text)
    except json.JSONDecodeError as exc:
        raise A0SchemaError(
            f"Gemini response is not valid JSON: {exc}\n"
            f"First 500 chars: {text[:500]!r}"
        ) from exc

    if not isinstance(content, dict):
        raise A0SchemaError(
            f"Gemini response must be a JSON object; got {type(content).__name__}"
        )

    sources = _extract_sources(raw)
    usage = _extract_usage(raw)

    return GeminiResponse(content=content, sources=sources, usage=usage)


def _extract_sources(raw: Any) -> list[str]:
    """Pull grounding source URIs out of the Gemini response metadata."""
    sources: list[str] = []
    try:
        candidate = raw.candidates[0]
        metadata = getattr(candidate, "grounding_metadata", None)
        if metadata is None:
            return sources
        chunks = getattr(metadata, "grounding_chunks", None) or []
        for chunk in chunks:
            web = getattr(chunk, "web", None)
            if web:
                uri = getattr(web, "uri", None)
                if uri:
                    sources.append(uri)
    except (AttributeError, IndexError):
        pass
    return sources


def _extract_usage(raw: Any) -> dict[str, Any]:
    """Pull token counts out of usage_metadata."""
    try:
        um = getattr(raw, "usage_metadata", None)
        if um is None:
            return {}
        return {
            "prompt_tokens": getattr(um, "prompt_token_count", None),
            "output_tokens": getattr(um, "candidates_token_count", None),
            "total_tokens": getattr(um, "total_token_count", None),
        }
    except AttributeError:
        return {}


def _is_rate_limit(exc: Exception) -> bool:
    """Return True when the exception signals a 429 / quota / rate error."""
    msg = str(exc).lower()
    return any(
        token in msg
        for token in ("429", "quota", "rate_limit", "resource_exhausted", "ratequota")
    )
