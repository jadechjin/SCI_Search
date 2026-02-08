"""Configuration loading for paper-search."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel


class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = ""
    api_key: str = ""
    base_url: str | None = None
    temperature: float = 0.0
    max_tokens: int = 4096


class SearchSourceConfig(BaseModel):
    name: str
    api_key: str = ""
    enabled: bool = True
    rate_limit: float = 1.0


class AppConfig(BaseModel):
    llm: LLMConfig = LLMConfig()
    sources: dict[str, SearchSourceConfig] = {}
    default_max_results: int = 100
    domain: str = "general"
    relevance_batch_size: int = 10
    relevance_max_concurrency: int = 5
    dedup_enable_llm_pass: bool = True
    dedup_llm_max_candidates: int = 60
    mcp_decide_wait_timeout_s: float = 15.0
    mcp_poll_interval_s: float = 0.05


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_config(env_path: str | Path | None = None) -> AppConfig:
    """Load configuration from environment variables (.env file)."""
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv()

    llm = LLMConfig(
        provider=os.getenv("LLM_PROVIDER", "openai"),
        model=os.getenv("LLM_MODEL", ""),
        api_key=os.getenv(
            f"{os.getenv('LLM_PROVIDER', 'openai').upper()}_API_KEY",
            os.getenv("OPENAI_API_KEY", ""),
        ),
        base_url=os.getenv("LLM_BASE_URL") or None,
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.0")),
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
    )

    sources: dict[str, SearchSourceConfig] = {}
    serpapi_key = os.getenv("SERPAPI_API_KEY", "")
    if serpapi_key:
        sources["serpapi_scholar"] = SearchSourceConfig(
            name="serpapi_scholar",
            api_key=serpapi_key,
            enabled=True,
        )

    return AppConfig(
        llm=llm,
        sources=sources,
        default_max_results=int(os.getenv("DEFAULT_MAX_RESULTS", "100")),
        domain=os.getenv("DOMAIN", "general"),
        relevance_batch_size=int(os.getenv("RELEVANCE_BATCH_SIZE", "10")),
        relevance_max_concurrency=int(os.getenv("RELEVANCE_MAX_CONCURRENCY", "5")),
        dedup_enable_llm_pass=_env_bool("DEDUP_ENABLE_LLM_PASS", True),
        dedup_llm_max_candidates=int(os.getenv("DEDUP_LLM_MAX_CANDIDATES", "60")),
        mcp_decide_wait_timeout_s=float(
            os.getenv("MCP_DECIDE_WAIT_TIMEOUT_S", "15.0")
        ),
        mcp_poll_interval_s=float(os.getenv("MCP_POLL_INTERVAL_S", "0.05")),
    )
