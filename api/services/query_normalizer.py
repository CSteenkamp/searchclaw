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
