"""Rule-based extraction — JSON-LD, Open Graph, meta tags."""

import json
from typing import Any

from bs4 import BeautifulSoup


def extract_json_ld(soup: BeautifulSoup) -> list[dict]:
    """Extract all JSON-LD blocks from the page."""
    results = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)
        except (json.JSONDecodeError, TypeError):
            continue
    return results


def extract_open_graph(soup: BeautifulSoup) -> dict[str, str]:
    """Extract Open Graph meta tags."""
    og = {}
    for meta in soup.find_all("meta"):
        prop = meta.get("property", "") or meta.get("name", "")
        content = meta.get("content", "")
        if prop.startswith("og:") and content:
            key = prop[3:].replace(":", "_")
            og[key] = content
    return og


def extract_meta_tags(soup: BeautifulSoup) -> dict[str, str]:
    """Extract standard meta tags (description, author, etc.)."""
    meta = {}
    for tag in soup.find_all("meta"):
        name = tag.get("name", "")
        content = tag.get("content", "")
        if name and content and not name.startswith("og:"):
            meta[name] = content
    return meta


def _flatten_json_ld(items: list[dict]) -> dict[str, Any]:
    """Flatten JSON-LD items into a single dict for schema matching."""
    flat: dict[str, Any] = {}
    for item in items:
        for k, v in item.items():
            if k.startswith("@"):
                continue
            if k not in flat:
                flat[k] = v
    return flat


def _match_to_schema(data: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any] | None:
    """Try to map extracted data keys to the requested schema keys (case-insensitive)."""
    lower_data = {k.lower(): v for k, v in data.items()}
    result: dict[str, Any] = {}
    for key in schema:
        lk = key.lower()
        if lk in lower_data:
            result[key] = lower_data[lk]
    if len(result) >= len(schema) / 2:
        return result
    return None


def extract_structured_data(html: str, schema: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Try to extract structured data from the page using rule-based methods."""
    soup = BeautifulSoup(html, "lxml")

    json_ld = extract_json_ld(soup)
    if json_ld:
        flat = _flatten_json_ld(json_ld)
        if schema:
            matched = _match_to_schema(flat, schema)
            if matched:
                return matched
        elif flat:
            return flat

    og = extract_open_graph(soup)
    if og:
        if schema:
            matched = _match_to_schema(og, schema)
            if matched:
                return matched
        elif og:
            return og

    meta = extract_meta_tags(soup)
    if meta:
        if schema:
            matched = _match_to_schema(meta, schema)
            if matched:
                return matched
        elif meta:
            return meta

    return None
