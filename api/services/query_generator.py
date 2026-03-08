"""Simple keyword-based search query generation from natural language prompts."""

import re
from collections import Counter

# Common stop words to filter out
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "it",
    "they", "them", "their", "this", "that", "these", "those",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "and", "or", "but", "not", "so", "if", "then", "than", "too",
    "very", "just", "about", "all", "also", "each", "every", "both",
    "find", "get", "give", "list", "show", "tell", "what", "which",
    "who", "whom", "how", "where", "when", "why",
})


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from text, ordered by importance."""
    # Normalize and tokenize
    words = re.findall(r"[A-Za-z0-9]+(?:'[a-z]+)?", text.lower())
    # Filter stop words and very short tokens
    keywords = [w for w in words if w not in _STOP_WORDS and len(w) > 1]
    # Rank by frequency (preserving first-seen order for ties)
    counts = Counter(keywords)
    seen = set()
    unique = []
    for w in keywords:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    unique.sort(key=lambda w: -counts[w])
    return unique


def generate_search_queries(prompt: str, max_queries: int = 3) -> list[str]:
    """Generate 1-3 search queries from a natural language prompt.

    Uses simple keyword extraction and reformulation — no LLM required.
    """
    keywords = _extract_keywords(prompt)
    if not keywords:
        return [prompt.strip()[:100]]

    queries: list[str] = []

    # Query 1: top keywords joined (most direct)
    top = keywords[:5]
    queries.append(" ".join(top))

    if max_queries >= 2 and len(keywords) > 2:
        # Query 2: rearranged / subset for diversity
        q2_words = keywords[:3]
        q2 = " ".join(q2_words)
        if q2 != queries[0]:
            queries.append(q2)

    if max_queries >= 3 and len(keywords) > 3:
        # Query 3: use later keywords for breadth
        q3_words = keywords[1:4]
        q3 = " ".join(q3_words)
        if q3 not in queries:
            queries.append(q3)

    # Deduplicate and cap
    seen_set: set[str] = set()
    deduped: list[str] = []
    for q in queries:
        if q not in seen_set:
            seen_set.add(q)
            deduped.append(q)
    return deduped[:max_queries]
