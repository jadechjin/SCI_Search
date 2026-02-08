"""Materials science domain specialization for prompt templates."""

from __future__ import annotations

from pydantic import BaseModel


class DomainConfig(BaseModel):
    """Domain-specific configuration for prompt customization."""

    name: str
    description: str
    concept_categories: list[str]
    priority_sources: list[str]
    extra_intent_instructions: str


MATERIALS_SCIENCE = DomainConfig(
    name="materials_science",
    description="Materials science and engineering",
    concept_categories=[
        "Material System (composition, crystal structure, morphology)",
        "Processing (synthesis, heat treatment, deposition, sintering)",
        "Structure (grain size, texture, defects, interfaces, porosity)",
        "Properties (mechanical, electrical, thermal, magnetic, optical)",
        "Mechanism/Model (phase transformation, diffusion, DFT, MD, CALPHAD)",
        "Application/Constraints (service environment, cost, scalability)",
    ],
    priority_sources=[
        "semantic_scholar",
        "scopus",
        "web_of_science",
    ],
    extra_intent_instructions="""\
When analyzing materials science queries, also identify:
- Specific material families (oxides, sulfides, polymers, composites, coatings)
- Test standards (ASTM, ISO, IEC) if applicable
- Computational methods (DFT, MD, CALPHAD, phase-field) if applicable
- Whether the query implies structural/crystallographic data needs (ICSD, COD, Materials Project)
- Whether the query implies phase diagram or thermodynamic data needs
""",
)
