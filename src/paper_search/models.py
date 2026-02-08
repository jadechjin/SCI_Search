"""Core data models for the paper search module.

All Pydantic models are defined here as the single source of truth.
Every other module imports from this file.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class IntentType(str, Enum):
    SURVEY = "survey"
    METHOD = "method"
    DATASET = "dataset"
    BASELINE = "baseline"


class PaperTag(str, Enum):
    METHOD = "method"
    REVIEW = "review"
    EMPIRICAL = "empirical"
    THEORETICAL = "theoretical"
    DATASET = "dataset"


# ---------------------------------------------------------------------------
# L1: Intent Parsing
# ---------------------------------------------------------------------------

class SearchConstraints(BaseModel):
    year_from: int | None = None
    year_to: int | None = None
    language: str | None = None
    max_results: int = 100


class ParsedIntent(BaseModel):
    topic: str
    concepts: list[str]
    intent_type: IntentType
    constraints: SearchConstraints = Field(default_factory=SearchConstraints)


# ---------------------------------------------------------------------------
# L2: Query Building
# ---------------------------------------------------------------------------

class SynonymMap(BaseModel):
    keyword: str
    synonyms: list[str]


class SearchQuery(BaseModel):
    keywords: list[str]
    synonym_map: list[SynonymMap] = []
    boolean_query: str


class SearchStrategy(BaseModel):
    queries: list[SearchQuery]
    sources: list[str]
    filters: SearchConstraints = Field(default_factory=SearchConstraints)


class UserFeedback(BaseModel):
    marked_relevant: list[str] = []
    marked_irrelevant: list[str] = []
    free_text_feedback: str | None = None


class QueryBuilderInput(BaseModel):
    intent: ParsedIntent
    previous_strategies: list[SearchStrategy] = []
    user_feedback: UserFeedback | None = None


# ---------------------------------------------------------------------------
# L3: Raw Search Results
# ---------------------------------------------------------------------------

class Author(BaseModel):
    name: str
    author_id: str | None = None


class RawPaper(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    doi: str | None = None
    title: str
    authors: list[Author] = []
    abstract: str | None = None
    snippet: str | None = None
    year: int | None = None
    venue: str | None = None
    source: str
    citation_count: int = 0
    full_text_url: str | None = None
    bibtex: str | None = None
    raw_data: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# L4: Scored Results
# ---------------------------------------------------------------------------

class ScoredPaper(BaseModel):
    paper: RawPaper
    relevance_score: float = Field(ge=0.0, le=1.0)
    relevance_reason: str
    tags: list[PaperTag] = []


# ---------------------------------------------------------------------------
# Final Output
# ---------------------------------------------------------------------------

class Facets(BaseModel):
    by_year: dict[int, int] = {}
    by_venue: dict[str, int] = {}
    top_authors: list[str] = []
    key_themes: list[str] = []


class SearchMetadata(BaseModel):
    query: str
    search_strategy: SearchStrategy
    total_found: int
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class Paper(BaseModel):
    id: str
    doi: str | None = None
    title: str
    authors: list[Author]
    abstract: str | None = None
    year: int | None = None
    venue: str | None = None
    source: str
    citation_count: int = 0
    relevance_score: float = Field(ge=0.0, le=1.0, default=0.0)
    relevance_reason: str = ""
    tags: list[PaperTag] = []
    full_text_url: str | None = None
    bibtex: str | None = None


class PaperCollection(BaseModel):
    metadata: SearchMetadata
    papers: list[Paper]
    facets: Facets = Field(default_factory=Facets)
