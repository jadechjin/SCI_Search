"""Tests for export utilities."""

from __future__ import annotations

import json

import pytest

from paper_search.export import export_bibtex, export_json, export_markdown
from paper_search.models import (
    Author,
    Facets,
    Paper,
    PaperCollection,
    SearchMetadata,
    SearchStrategy,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_collection(papers: list[Paper]) -> PaperCollection:
    return PaperCollection(
        metadata=SearchMetadata(
            query="test",
            search_strategy=SearchStrategy(queries=[], sources=[]),
            total_found=len(papers),
        ),
        papers=papers,
        facets=Facets(),
    )


_EMPTY = _make_collection([])

_SINGLE = _make_collection([
    Paper(
        id="p1",
        title="Perovskite Solar Cells",
        authors=[Author(name="Wang Lei"), Author(name="Zhang Wei")],
        year=2023,
        venue="Nature Energy",
        source="test",
        doi="10.1234/test",
        full_text_url="https://example.com/p1",
        relevance_score=0.95,
        relevance_reason="Highly relevant",
    ),
])

_MULTI = _make_collection([
    Paper(
        id="p1",
        title="Paper Alpha",
        authors=[Author(name="Alice Smith")],
        year=2023,
        venue="Journal A",
        source="test",
        relevance_score=0.9,
    ),
    Paper(
        id="p2",
        title="Paper Beta",
        authors=[Author(name="Bob Jones"), Author(name="Carol Lee")],
        year=2022,
        venue="Journal B",
        source="test",
        relevance_score=0.7,
    ),
    Paper(
        id="p3",
        title="Paper Gamma",
        authors=[
            Author(name="Dave Wilson"),
            Author(name="Eve Brown"),
            Author(name="Frank Green"),
            Author(name="Grace Black"),
        ],
        year=2021,
        source="test",
        relevance_score=0.5,
    ),
])

_SPECIAL = _make_collection([
    Paper(
        id="sp1",
        title="Fe & Co alloys: 10% improvement",
        authors=[Author(name="Kim_Park")],
        year=2023,
        venue="J. Mater. Sci. & Tech.",
        source="test",
        relevance_score=0.8,
    ),
])


# ---------------------------------------------------------------------------
# JSON tests
# ---------------------------------------------------------------------------

class TestExportJson:
    def test_valid_json(self):
        output = export_json(_SINGLE)
        parsed = json.loads(output)
        assert "papers" in parsed
        assert "metadata" in parsed

    def test_preserves_papers(self):
        output = export_json(_MULTI)
        parsed = json.loads(output)
        ids = {p["id"] for p in parsed["papers"]}
        assert ids == {"p1", "p2", "p3"}

    def test_idempotent(self):
        a = export_json(_MULTI)
        b = export_json(_MULTI)
        assert a == b

    def test_empty(self):
        output = export_json(_EMPTY)
        parsed = json.loads(output)
        assert parsed["papers"] == []


# ---------------------------------------------------------------------------
# BibTeX tests
# ---------------------------------------------------------------------------

class TestExportBibtex:
    def test_entry_count(self):
        output = export_bibtex(_MULTI)
        assert output.count("@article{") == 3

    def test_key_uniqueness(self):
        # Create papers that would generate the same key
        dup_papers = _make_collection([
            Paper(
                id="d1",
                title="Alpha method",
                authors=[Author(name="Smith John")],
                year=2023,
                source="test",
                relevance_score=0.9,
            ),
            Paper(
                id="d2",
                title="Alpha approach",
                authors=[Author(name="Smith Jane")],
                year=2023,
                source="test",
                relevance_score=0.8,
            ),
        ])
        output = export_bibtex(dup_papers)
        # Extract keys
        import re
        keys = re.findall(r"@article\{([^,]+),", output)
        assert len(keys) == len(set(keys)), f"Duplicate keys found: {keys}"

    def test_special_chars_escaped(self):
        output = export_bibtex(_SPECIAL)
        assert r"\&" in output
        assert r"\_" in output

    def test_empty(self):
        assert export_bibtex(_EMPTY) == ""

    def test_missing_fields_omitted(self):
        # Paper with no doi, no venue, no url
        minimal = _make_collection([
            Paper(
                id="m1",
                title="Minimal",
                authors=[Author(name="Test Author")],
                source="test",
                relevance_score=0.5,
            ),
        ])
        output = export_bibtex(minimal)
        assert "doi" not in output
        assert "journal" not in output
        assert "url" not in output
        assert "@article{" in output


# ---------------------------------------------------------------------------
# Markdown tests
# ---------------------------------------------------------------------------

class TestExportMarkdown:
    def test_row_count(self):
        output = export_markdown(_MULTI)
        lines = [l for l in output.split("\n") if l.strip()]
        assert len(lines) == 3 + 2  # 3 papers + header + separator

    def test_header(self):
        output = export_markdown(_SINGLE)
        first_line = output.split("\n")[0]
        for col in ["Title", "Authors", "Year", "Venue", "Score"]:
            assert col in first_line

    def test_empty(self):
        output = export_markdown(_EMPTY)
        lines = [l for l in output.split("\n") if l.strip()]
        assert len(lines) == 2  # header + separator only

    def test_score_format(self):
        output = export_markdown(_SINGLE)
        assert "0.95" in output
