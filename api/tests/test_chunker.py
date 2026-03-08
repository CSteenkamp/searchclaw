"""Tests for content chunking — spec 5.3."""

import pytest

from api.services.chunker import chunk_text


class TestFixedChunking:
    def test_basic_fixed_chunking(self):
        text = "Hello world. " * 100  # ~1300 chars
        chunks = chunk_text(text, max_size=200, overlap=20, strategy="fixed")
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk["char_count"] <= 200
            assert "index" in chunk
            assert "metadata" in chunk

    def test_overlap_exists(self):
        text = "word " * 200  # 1000 chars
        chunks = chunk_text(text, max_size=100, overlap=20, strategy="fixed")
        assert len(chunks) > 1
        # Check that consecutive chunks share some content
        for i in range(len(chunks) - 1):
            end_of_current = chunks[i]["text"][-20:]
            start_of_next = chunks[i + 1]["text"][:40]
            # The overlap region should share some words
            current_words = set(end_of_current.split())
            next_words = set(start_of_next.split())
            assert current_words & next_words, "Chunks should have overlapping content"

    def test_breaks_at_word_boundary(self):
        text = "abcdefghij " * 20
        chunks = chunk_text(text, max_size=50, overlap=0, strategy="fixed")
        for chunk in chunks:
            # Should not break in the middle of a word
            assert not chunk["text"].endswith("abcde")


class TestSentenceChunking:
    def test_sentence_boundaries(self):
        text = "First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence."
        chunks = chunk_text(text, max_size=60, overlap=0, strategy="sentence")
        assert len(chunks) >= 2
        # Each chunk should end with a complete sentence (period)
        for chunk in chunks[:-1]:  # Last chunk may not end with period
            assert chunk["text"].rstrip().endswith(".")

    def test_sentence_respects_max_size(self):
        text = "Short. " * 50
        chunks = chunk_text(text, max_size=50, overlap=0, strategy="sentence")
        for chunk in chunks:
            assert chunk["char_count"] <= 60  # Some tolerance for sentence boundary


class TestSemanticChunking:
    def test_splits_on_headings(self):
        text = (
            "# Introduction\n\n"
            "This is the intro paragraph with enough content to matter.\n\n"
            "## Methods\n\n"
            "This is the methods section with detailed content here.\n\n"
            "## Results\n\n"
            "This is the results section with findings detailed here."
        )
        chunks = chunk_text(text, max_size=200, overlap=0, strategy="semantic")
        assert len(chunks) >= 2

    def test_heading_detection_in_metadata(self):
        text = (
            "# Introduction\n\n"
            "Content of the introduction section that is long enough to be its own chunk. " * 5 + "\n\n"
            "## Methods\n\n"
            "Content of the methods section that is also quite long for testing. " * 5
        )
        chunks = chunk_text(text, max_size=200, overlap=0, strategy="semantic")
        # At least one chunk should have a heading in metadata
        headings = [c["metadata"].get("heading") for c in chunks if c["metadata"].get("heading")]
        assert len(headings) > 0

    def test_falls_back_to_sentence_for_large_sections(self):
        # A single section that's much larger than max_size
        text = "# Big Section\n\n" + "This is a sentence. " * 100
        chunks = chunk_text(text, max_size=100, overlap=0, strategy="semantic")
        assert len(chunks) > 1


class TestEdgeCases:
    def test_empty_text(self):
        chunks = chunk_text("", max_size=500, overlap=50, strategy="fixed")
        assert chunks == []

    def test_whitespace_only(self):
        chunks = chunk_text("   \n\n  ", max_size=500, overlap=50, strategy="fixed")
        assert chunks == []

    def test_text_shorter_than_max_size(self):
        chunks = chunk_text("Short text.", max_size=500, overlap=50, strategy="fixed")
        assert len(chunks) == 1
        assert chunks[0]["text"] == "Short text."
        assert chunks[0]["index"] == 0
        assert chunks[0]["metadata"]["position"] == "start"

    def test_single_sentence(self):
        chunks = chunk_text("Just one sentence.", max_size=500, overlap=50, strategy="sentence")
        assert len(chunks) == 1

    def test_position_metadata(self):
        text = "word " * 200
        chunks = chunk_text(text, max_size=100, overlap=10, strategy="fixed")
        assert chunks[0]["metadata"]["position"] == "start"
        assert chunks[-1]["metadata"]["position"] == "end"
        if len(chunks) > 2:
            assert chunks[1]["metadata"]["position"] == "middle"


class TestChunkMetadata:
    def test_index_sequential(self):
        text = "Hello world. " * 100
        chunks = chunk_text(text, max_size=100, overlap=10, strategy="fixed")
        for i, chunk in enumerate(chunks):
            assert chunk["index"] == i

    def test_char_count_accurate(self):
        text = "Test content. " * 50
        chunks = chunk_text(text, max_size=100, overlap=10, strategy="fixed")
        for chunk in chunks:
            assert chunk["char_count"] == len(chunk["text"])

    def test_all_strategies_produce_chunks(self):
        text = "Content here. " * 100
        for strategy in ["fixed", "sentence", "semantic"]:
            chunks = chunk_text(text, max_size=100, overlap=10, strategy=strategy)
            assert len(chunks) > 0, f"Strategy '{strategy}' produced no chunks"
