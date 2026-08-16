"""Default section heading → taxonomy key mapping.

The mapping is case-insensitive and tries prefix matching. A YAML override
can replace this at runtime.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

DEFAULT_SECTION_MAP: dict[str, str] = {
    "purpose": "purpose_goals",
    "goals": "purpose_goals",
    "history with psychedelics": "relevant_experience_history",
    "relevant experience": "relevant_experience_history",
    "medical history": "medical_history",
    "condition checklist": "condition_checklist",
    "medications": "medications",
    "prescription medications": "medications",
    "supplements": "supplements",
    "substance use": "substance_use",
    "mental health": "mental_emotional_health",
    "mental and emotional health": "mental_emotional_health",
    "trauma": "trauma_history",
    "trauma history": "trauma_history",
    "personal": "personal",
    "family": "family_relationships",
    "family / relationships": "family_relationships",
    "relationships": "family_relationships",
    "living situation": "living_situation_support",
    "diet": "diet",
    "sleep": "sleep",
    "sexuality": "sexuality",
    "integration": "integration_support",
    "support & integration": "integration_support",
    "languages": "languages",
    "additional support": "accessibility_needs",
    "accessibility": "accessibility_needs",
    "oregon client information form": "regulatory_screening",
    "oha client information form": "regulatory_screening",
    "colorado safety screen": "regulatory_screening",
    "intake packet - safety screen": "regulatory_screening",
    "safety screen": "regulatory_screening",
}

HIGH_STAKES_SECTIONS = {
    "regulatory_screening",
    "medical_history",
    "mental_emotional_health",
    "trauma_history",
    "substance_use",
    "medications",
    "sexuality",
}


def load_section_map(override_path: Optional[Path] = None) -> dict[str, str]:
    """Load the section mapping, optionally overriding with a YAML file."""
    mapping = dict(DEFAULT_SECTION_MAP)
    if override_path and override_path.exists():
        with open(override_path) as f:
            overrides = yaml.safe_load(f) or {}
        mapping.update({k.lower().strip(): v for k, v in overrides.items()})
    return mapping


def resolve_section_key(heading: str, mapping: dict[str, str]) -> Optional[str]:
    """Resolve a section heading to a taxonomy key via exact or prefix match."""
    normalized = heading.lower().strip()

    if normalized in mapping:
        return mapping[normalized]

    for map_key, taxonomy_key in mapping.items():
        if normalized.startswith(map_key) or map_key.startswith(normalized):
            return taxonomy_key

    return None
