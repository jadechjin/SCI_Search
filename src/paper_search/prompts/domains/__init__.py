"""Domain configuration loader."""

from __future__ import annotations

from paper_search.prompts.domains.materials_science import DomainConfig


def get_domain_config(domain: str) -> DomainConfig | None:
    """Load domain-specific config by name. Returns None for general/unknown."""
    match domain:
        case "materials_science":
            from paper_search.prompts.domains.materials_science import MATERIALS_SCIENCE

            return MATERIALS_SCIENCE
        case _:
            return None
