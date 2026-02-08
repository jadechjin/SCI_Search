"""Tests for library public API."""

from __future__ import annotations

import inspect

import paper_search


class TestPublicAPI:
    def test_all_exports_importable(self):
        for name in paper_search.__all__:
            obj = getattr(paper_search, name, None)
            assert obj is not None, f"{name} not importable from paper_search"

    def test_search_is_async(self):
        assert inspect.iscoroutinefunction(paper_search.search)

    def test_export_functions_importable(self):
        from paper_search import export_bibtex, export_json, export_markdown
        assert callable(export_json)
        assert callable(export_bibtex)
        assert callable(export_markdown)

    def test_models_importable(self):
        from paper_search import Paper, PaperCollection, ParsedIntent, SearchStrategy
        assert Paper is not None
        assert PaperCollection is not None
        assert ParsedIntent is not None
        assert SearchStrategy is not None
