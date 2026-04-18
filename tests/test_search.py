"""Tests for search service."""

from __future__ import annotations

import pytest

from src.search.embeddings import build_embedding_text


def test_build_embedding_text_full():
    text = build_embedding_text(
        name="MG996R Servo Bracket",
        description="Parametric bracket for MG996R servo",
        category="joint",
        body_zone="arm",
        tags=["servo", "bracket"],
        material_hints=["PLA", "PETG"],
        connector_standard="M3",
    )
    assert "MG996R Servo Bracket" in text
    assert "joint" in text
    assert "arm" in text
    assert "servo" in text
    assert "M3" in text


def test_build_embedding_text_minimal():
    text = build_embedding_text(
        name="Simple Part",
        description=None,
        category="frame",
        body_zone=None,
        tags=[],
        material_hints=[],
        connector_standard=None,
    )
    assert "Simple Part" in text
    assert "frame" in text
    # No crash with all-None optional fields


def test_embedding_text_is_string():
    text = build_embedding_text("x", None, "other", None, [], [], None)
    assert isinstance(text, str)
    assert len(text) > 0
