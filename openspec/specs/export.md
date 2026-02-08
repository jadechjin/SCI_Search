# Spec: Export Utilities

## Capability: export-utilities

### Requirement: export_json function (REQ-1)
`export_json(collection: PaperCollection, indent: int = 2) -> str` returns valid JSON string representing the full collection including metadata, papers, and facets.

### Requirement: export_bibtex function (REQ-2)
`export_bibtex(collection: PaperCollection) -> str` returns a BibTeX string with one `@article{}` entry per paper. Each entry has fields: author, title, year, journal (venue), doi (if present), url (if present).

### Requirement: BibTeX key generation (REQ-3)
BibTeX keys follow the pattern `{firstauthor_lastname}_{year}_{first_title_word}` (lowercased, ASCII-safe). Collision avoidance: append `_a`, `_b`, etc. for duplicates within a collection.

### Requirement: BibTeX special character escaping (REQ-4)
Characters `& % _ # { }` in field values are escaped with backslash. Titles are wrapped in `{...}` to preserve capitalization.

### Requirement: export_markdown function (REQ-5)
`export_markdown(collection: PaperCollection) -> str` returns a Markdown table with columns: #, Title, Authors, Year, Venue, Score. One row per paper, sorted as-is from the collection.

### Requirement: Empty collection handling (REQ-6)
All export functions handle empty collections gracefully:
- `export_json`: valid JSON with `"papers": []`
- `export_bibtex`: empty string `""`
- `export_markdown`: header + separator only (no data rows)

---

## PBT Properties

### PROP-1: export_json idempotency
For any PaperCollection `c`, `export_json(c) == export_json(c)` (same output on repeated calls).

**Falsification**: Generate random PaperCollection, call export_json twice, compare strings.

### PROP-2: export_json round-trip preservation
For any PaperCollection `c`, `json.loads(export_json(c))["papers"]` has length `len(c.papers)` and preserves all paper IDs.

**Falsification**: Generate random collection, export to JSON, parse back, verify paper count and ID set equality.

### PROP-3: export_bibtex entry count
For any PaperCollection `c`, the number of `@article{` occurrences in `export_bibtex(c)` equals `len(c.papers)`.

**Falsification**: Generate collection with N random papers, count `@article{` in output, assert == N.

### PROP-4: export_markdown row count
For any PaperCollection `c` with `N` papers, `export_markdown(c)` has exactly `N + 2` non-empty lines (1 header + 1 separator + N data rows).

**Falsification**: Generate collection, split output by newlines, filter empty, assert count == len(papers) + 2.

### PROP-5: BibTeX key uniqueness
For any PaperCollection `c`, all BibTeX keys in `export_bibtex(c)` are unique.

**Falsification**: Generate collection with duplicate author/year/title-prefix papers, extract keys, assert no duplicates.
