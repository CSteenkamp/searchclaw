"""Tests for query normalization and cache key consistency."""

import pytest
from api.services.query_normalizer import normalize_query


def test_normalize_lowercase():
    assert normalize_query("Hello World") == "hello world"


def test_normalize_strip_whitespace():
    assert normalize_query("  hello   world  ") == "hello world"


def test_normalize_collapse_spaces():
    assert normalize_query("hello    world") == "hello world"


def test_normalize_trailing_punctuation():
    assert normalize_query("what is python?") == "what is python"
    assert normalize_query("hello world!") == "hello world"
    assert normalize_query("test...") == "test"


def test_normalize_unicode():
    # Full-width to ASCII
    assert normalize_query("ｈｅｌｌｏ") == "hello"


def test_normalize_consistent_cache_keys():
    """Different user inputs that mean the same thing should produce the same key."""
    assert normalize_query("Kubernetes Tutorial") == normalize_query("kubernetes tutorial")
    assert normalize_query("  kubernetes  tutorial  ") == normalize_query("kubernetes tutorial")
    assert normalize_query("kubernetes tutorial?") == normalize_query("kubernetes tutorial")


def test_normalize_preserves_meaningful_punctuation():
    # Hyphens, slashes, etc. should be preserved
    assert normalize_query("node.js vs deno") == "node.js vs deno"
    assert normalize_query("c++ tutorial") == "c++ tutorial"
