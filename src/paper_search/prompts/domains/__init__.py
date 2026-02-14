"""Domain configuration loader."""

from __future__ import annotations

import os

from paper_search.prompts.domains.materials_science import DomainConfig


def _load_custom_domain_from_env(domain: str) -> DomainConfig | None:
    """Load custom domain config from .env using same-name variable.

    Example:
        DOMAIN=makesi
        makesi=makesi is ...
    """
    raw = os.getenv(domain)
    if raw is None:
        raw = os.getenv(domain.upper())
    if raw is None or not raw.strip():
        return None

    content = raw.strip()
    return DomainConfig(
        name=domain,
        description=content,
        concept_categories=[],
        priority_sources=[],
        extra_intent_instructions=(
            f'Custom domain "{domain}" loaded from environment.\n'
            f"Domain terminology/description:\n{content}\n"
            "When parsing intent and building queries, follow this terminology "
            "and expand key concepts accordingly."
        ),
    )


def get_domain_config(domain: str) -> DomainConfig | None:
    """Load domain-specific config by name. Returns None for general/unknown."""
    domain = (domain or "").strip()
    if not domain or domain == "general":
        return None

    match domain:
        case "materials_science":
            from paper_search.prompts.domains.materials_science import MATERIALS_SCIENCE

            return MATERIALS_SCIENCE
        case _:
            return _load_custom_domain_from_env(domain)
