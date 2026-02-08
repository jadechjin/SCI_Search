# Spec: SerpAPI Adapter — Parsing & Normalization

## REQ-6: Summary Parsing — Authors

**Given** `publication_info.summary = "ZH Zhou, Y Liu - 2021 - Springer"`,
**When** `_parse_summary()` is called,
**Then** returns `authors = [Author(name="ZH Zhou"), Author(name="Y Liu")]`

**Given** `publication_info.summary = "2021 - Springer"` (no author segment),
**When** `_parse_summary()` is called,
**Then** returns `authors = []`

## REQ-7: Summary Parsing — Year

**Given** summary contains a 4-digit number matching `19xx` or `20xx`,
**When** `_parse_summary()` is called,
**Then** `year` is that number as int.

**Given** summary contains no valid year,
**Then** `year = None`

## REQ-8: Summary Parsing — Venue

**Given** `summary = "A Smith - 2022 - Nature Communications"`,
**When** `_parse_summary()` is called,
**Then** `venue = "Nature Communications"` (hostname-like strings filtered out)

**Given** `summary = "A Smith - 2022 - books.google.com"`,
**Then** `venue = None` (hostname filtered)

## REQ-9: DOI Extraction

**Given** `link = "https://doi.org/10.1234/test.paper.2024"`,
**When** `_extract_doi()` is called,
**Then** returns `"10.1234/test.paper.2024"`

**Given** text contains no DOI pattern,
**Then** returns `None`

## REQ-10: Citation Count

**Given** result has `inline_links.cited_by.total = 42`,
**When** parsed to RawPaper,
**Then** `citation_count = 42`

**Given** result has no `inline_links` or no `cited_by`,
**Then** `citation_count = 0`

---

## PBT Properties

### PROP-6: Parse Never Crashes
**Invariant**: `_parse_summary(s)` never raises an exception for any string `s`.
**Falsification**: Hypothesis generates random strings (including empty, unicode, very long); assert no exception.

### PROP-7: DOI Format Valid
**Invariant**: If `_extract_doi()` returns non-None, result matches `^10\.\d{4,9}/\S+$`.
**Falsification**: Generate strings with embedded DOI-like patterns; assert format or None.

### PROP-8: Author Name Non-Empty
**Invariant**: Every `Author` in parsed result has `name` that is non-empty and stripped.
**Falsification**: Generate varied summary strings; assert no empty author names.

### PROP-9: Citation Count Non-Negative
**Invariant**: `paper.citation_count >= 0` for all parsed papers.
**Falsification**: Generate result dicts with missing/negative/null cited_by; assert >= 0.
