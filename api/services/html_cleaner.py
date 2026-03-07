"""HTML cleaning and text extraction utilities."""

import re

from bs4 import BeautifulSoup, Comment

REMOVE_TAGS = {"script", "style", "svg", "noscript", "iframe", "object", "embed"}

REMOVE_SELECTORS = [
    "nav", "footer", "header",
    "[role='navigation']", "[role='banner']", "[role='contentinfo']",
    ".nav", ".navbar", ".footer", ".header", ".sidebar", ".menu",
    ".ad", ".ads", ".advertisement", ".cookie-banner", ".popup",
    "#nav", "#footer", "#header", "#sidebar", "#menu",
]


def clean_html(raw_html: str, max_chars: int = 32000) -> str:
    """Strip non-content elements from HTML and truncate to max_chars."""
    soup = BeautifulSoup(raw_html, "lxml")

    for tag in soup.find_all(REMOVE_TAGS):
        tag.decompose()

    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    for selector in REMOVE_SELECTORS:
        for el in soup.select(selector):
            el.decompose()

    cleaned = str(soup)
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
    return cleaned


def html_to_text(html: str) -> str:
    """Convert HTML to plain text, collapsing whitespace."""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator="\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
