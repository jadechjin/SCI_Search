"""Export utilities for PaperCollection."""

from __future__ import annotations

import re
import string

from paper_search.models import Author, Paper, PaperCollection


def export_json(collection: PaperCollection, indent: int = 2) -> str:
    """Serialize collection to JSON string."""
    return collection.model_dump_json(indent=indent)


def export_bibtex(collection: PaperCollection) -> str:
    """Generate BibTeX entries for all papers."""
    if not collection.papers:
        return ""
    seen_keys: set[str] = set()
    entries = []
    for paper in collection.papers:
        key = _make_bibtex_key(paper, seen_keys)
        entries.append(_format_bibtex_entry(paper, key))
    return "\n\n".join(entries)


def export_markdown(collection: PaperCollection) -> str:
    """Generate Markdown table of papers."""
    header = "| # | Title | Authors | Year | Venue | Score |"
    sep = "|---|-------|---------|------|-------|-------|"
    rows = []
    for i, paper in enumerate(collection.papers, 1):
        authors = _format_authors_short(paper.authors)
        year = str(paper.year) if paper.year else "-"
        venue = paper.venue or "-"
        rows.append(
            f"| {i} | {paper.title} | {authors} | {year} | {venue} | {paper.relevance_score:.2f} |"
        )
    return "\n".join([header, sep] + rows)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_BIBTEX_SPECIAL = str.maketrans({
    "&": r"\&",
    "%": r"\%",
    "_": r"\_",
    "#": r"\#",
})


def _escape_bibtex(text: str) -> str:
    """Escape BibTeX special characters."""
    return text.translate(_BIBTEX_SPECIAL)


def _make_bibtex_key(paper: Paper, seen: set[str]) -> str:
    """Generate a unique BibTeX key for a paper."""
    # First author last name
    if paper.authors:
        name = paper.authors[0].name.split()[-1].lower()
    else:
        name = "unknown"

    # Year
    year = str(paper.year) if paper.year else "nd"

    # First word of title
    words = re.findall(r"[a-zA-Z]+", paper.title)
    first_word = words[0].lower() if words else "untitled"

    base = re.sub(r"[^a-z0-9_]", "", f"{name}_{year}_{first_word}")

    # Collision avoidance
    key = base
    suffix_idx = 0
    while key in seen:
        key = f"{base}_{string.ascii_lowercase[suffix_idx]}"
        suffix_idx += 1
    seen.add(key)
    return key


def _format_bibtex_entry(paper: Paper, key: str) -> str:
    """Format a single paper as a BibTeX @article entry."""
    lines = [f"@article{{{key},"]

    # Author
    if paper.authors:
        author_str = " and ".join(a.name for a in paper.authors)
        lines.append(f"  author = {{{_escape_bibtex(author_str)}}},")
    else:
        lines.append("  author = {Unknown},")

    # Title (wrapped in braces to preserve capitalization)
    lines.append(f"  title = {{{{{_escape_bibtex(paper.title)}}}}},")

    # Year
    if paper.year:
        lines.append(f"  year = {{{paper.year}}},")

    # Journal/venue
    if paper.venue:
        lines.append(f"  journal = {{{_escape_bibtex(paper.venue)}}},")

    # DOI
    if paper.doi:
        lines.append(f"  doi = {{{paper.doi}}},")

    # URL
    if paper.full_text_url:
        lines.append(f"  url = {{{paper.full_text_url}}},")

    lines.append("}")
    return "\n".join(lines)


def _format_authors_short(authors: list[Author]) -> str:
    """Format author list for Markdown display."""
    if not authors:
        return "-"
    names = [a.name for a in authors]
    if len(names) <= 3:
        return ", ".join(names)
    return f"{names[0]} et al."
