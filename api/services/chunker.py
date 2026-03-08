"""Content chunking for RAG pipelines — fixed, sentence, and semantic strategies."""

import re
from typing import Optional


def _find_nearest_heading(text: str, position: int) -> Optional[str]:
    """Find the nearest markdown heading before a given character position."""
    heading = None
    for match in re.finditer(r"^(#{1,6})\s+(.+)$", text[:position], re.MULTILINE):
        heading = match.group(2).strip()
    return heading


def _get_position_label(index: int, total: int) -> str:
    """Return position label: start, middle, or end."""
    if total <= 1:
        return "start"
    if index == 0:
        return "start"
    if index == total - 1:
        return "end"
    return "middle"


def _chunk_fixed(text: str, max_size: int, overlap: int) -> list[dict]:
    """Split text at max_size characters, breaking at word boundaries, with overlap."""
    chunks = []
    start = 0

    while start < len(text):
        end = start + max_size

        if end >= len(text):
            chunk_text = text[start:]
        else:
            # Break at word boundary
            break_point = text.rfind(" ", start, end)
            if break_point > start:
                end = break_point
            chunk_text = text[start:end]

        chunk_text = chunk_text.strip()
        if chunk_text:
            chunks.append({
                "text": chunk_text,
                "char_count": len(chunk_text),
                "heading": _find_nearest_heading(text, start),
            })

        # Move start forward, accounting for overlap
        if end >= len(text):
            break
        start = end - overlap
        if start <= (end - max_size):
            start = end  # Avoid infinite loop

    return chunks


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences using regex."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if s.strip()]


def _chunk_sentence(text: str, max_size: int, overlap: int) -> list[dict]:
    """Split at sentence boundaries, accumulating until max_size."""
    sentences = _split_sentences(text)
    chunks = []
    current_sentences: list[str] = []
    current_len = 0

    for sentence in sentences:
        sentence_len = len(sentence)

        if current_len + sentence_len + 1 > max_size and current_sentences:
            chunk_text = " ".join(current_sentences).strip()
            if chunk_text:
                chunks.append({
                    "text": chunk_text,
                    "char_count": len(chunk_text),
                    "heading": _find_nearest_heading(text, text.find(current_sentences[0])),
                })

            # Overlap: keep sentences from end of previous chunk
            overlap_sentences: list[str] = []
            overlap_len = 0
            for s in reversed(current_sentences):
                if overlap_len + len(s) > overlap:
                    break
                overlap_sentences.insert(0, s)
                overlap_len += len(s) + 1

            current_sentences = overlap_sentences
            current_len = sum(len(s) + 1 for s in current_sentences)

        current_sentences.append(sentence)
        current_len += sentence_len + 1

    # Remaining sentences
    if current_sentences:
        chunk_text = " ".join(current_sentences).strip()
        if chunk_text:
            chunks.append({
                "text": chunk_text,
                "char_count": len(chunk_text),
                "heading": _find_nearest_heading(text, text.find(current_sentences[0])),
            })

    return chunks


def _chunk_semantic(text: str, max_size: int, overlap: int) -> list[dict]:
    """Split on markdown headings and paragraph breaks. Falls back to sentence splitting for oversized sections."""
    # Split on headings or double newlines
    sections = re.split(r"(?=^#{1,6}\s+.+$)|\n\n+", text, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s and s.strip()]

    chunks = []
    current_parts: list[str] = []
    current_len = 0

    for section in sections:
        section_len = len(section)

        if section_len > max_size:
            # Flush current accumulation
            if current_parts:
                chunk_text = "\n\n".join(current_parts).strip()
                if chunk_text:
                    chunks.append({
                        "text": chunk_text,
                        "char_count": len(chunk_text),
                        "heading": _find_nearest_heading(text, text.find(current_parts[0])),
                    })
                current_parts = []
                current_len = 0

            # Fall back to sentence splitting for this oversized section
            sub_chunks = _chunk_sentence(section, max_size, overlap)
            chunks.extend(sub_chunks)
            continue

        if current_len + section_len + 2 > max_size and current_parts:
            chunk_text = "\n\n".join(current_parts).strip()
            if chunk_text:
                chunks.append({
                    "text": chunk_text,
                    "char_count": len(chunk_text),
                    "heading": _find_nearest_heading(text, text.find(current_parts[0])),
                })
            current_parts = []
            current_len = 0

        current_parts.append(section)
        current_len += section_len + 2

    # Remaining parts
    if current_parts:
        chunk_text = "\n\n".join(current_parts).strip()
        if chunk_text:
            chunks.append({
                "text": chunk_text,
                "char_count": len(chunk_text),
                "heading": _find_nearest_heading(text, text.find(current_parts[0])),
            })

    return chunks


def chunk_text(
    text: str,
    max_size: int = 500,
    overlap: int = 50,
    strategy: str = "fixed",
) -> list[dict]:
    """Chunk text using the specified strategy.

    Returns a list of chunk dicts with: index, text, char_count, metadata.
    """
    if not text or not text.strip():
        return []

    # If text is shorter than max_size, return single chunk
    if len(text.strip()) <= max_size:
        return [{
            "index": 0,
            "text": text.strip(),
            "char_count": len(text.strip()),
            "metadata": {
                "heading": _find_nearest_heading(text, 0),
                "position": "start",
            },
        }]

    if strategy == "sentence":
        raw_chunks = _chunk_sentence(text, max_size, overlap)
    elif strategy == "semantic":
        raw_chunks = _chunk_semantic(text, max_size, overlap)
    else:
        raw_chunks = _chunk_fixed(text, max_size, overlap)

    # Add index and position metadata
    total = len(raw_chunks)
    result = []
    for i, chunk in enumerate(raw_chunks):
        result.append({
            "index": i,
            "text": chunk["text"],
            "char_count": chunk["char_count"],
            "metadata": {
                "heading": chunk.get("heading"),
                "position": _get_position_label(i, total),
            },
        })

    return result
