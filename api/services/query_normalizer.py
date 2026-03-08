"""Query normalization for consistent cache keys."""

import re
import unicodedata


def normalize_query(q: str) -> str:
    """Normalize a search query for cache key consistency.

    - Lowercase
    - Strip extra whitespace
    - Remove trailing punctuation
    - Normalize unicode
    """
    # Unicode normalize
    q = unicodedata.normalize("NFKC", q)
    # Lowercase
    q = q.lower().strip()
    # Collapse whitespace
    q = re.sub(r"\s+", " ", q)
    # Strip trailing punctuation
    q = q.rstrip("?!.,;:")
    return q


def reformulate_query(q: str) -> str:
    """Generate a reformulated query for deep search mode.

    Extracts keywords and appends community/discussion site hints
    to surface diverse results.
    """
    # Remove common stop words for a keyword-focused reformulation
    stop_words = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "dare", "ought",
        "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "above", "below",
        "between", "out", "off", "over", "under", "again", "further", "then",
        "once", "and", "but", "or", "nor", "not", "so", "yet", "both",
        "either", "neither", "each", "every", "all", "any", "few", "more",
        "most", "other", "some", "such", "no", "only", "own", "same", "than",
        "too", "very", "just", "because", "if", "when", "where", "how", "what",
        "which", "who", "whom", "this", "that", "these", "those", "i", "me",
        "my", "we", "our", "you", "your", "he", "him", "his", "she", "her",
        "it", "its", "they", "them", "their",
    }

    words = q.lower().split()
    keywords = [w for w in words if w not in stop_words and len(w) > 1]

    if not keywords:
        keywords = words[:5]

    keyword_query = " ".join(keywords[:8])
    return f"{keyword_query} site:reddit.com OR site:news.ycombinator.com"
