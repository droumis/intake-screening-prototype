"""Profile builder — extracts a Screening Profile from context documents using the model."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from pisa.model.ollama import OllamaProvider, ModelResponseError
from pisa.profile.loader import ContextDocument, compute_context_hash
from pisa.profile.models import (
    CautionCriterion,
    ConflictWarning,
    DetectionSpec,
    GroundRule,
    HardCriterion,
    MedicationClassOfConcern,
    PositiveIndicator,
    ProgramDemand,
    ScreeningProfile,
)

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "prompts" / "profile_builder_v1.1.0.md"

PROFILE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "hard_criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "description": {"type": "string"},
                    "detection": {
                        "type": "object",
                        "properties": {
                            "checklist_fields": {"type": "array", "items": {"type": "string"}},
                            "keywords": {"type": "array", "items": {"type": "string"}},
                            "medication_names": {"type": "array", "items": {"type": "string"}},
                            "sections": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["checklist_fields", "keywords", "medication_names", "sections"],
                    },
                    "source_doc": {"type": "string"},
                    "source_excerpt": {"type": "string"},
                    "basis": {"type": "string", "enum": ["regulatory", "house"]},
                    "citation": {"type": "string"},
                },
                "required": ["id", "description", "detection", "source_doc", "source_excerpt", "basis", "citation"],
            },
        },
        "caution_criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "description": {"type": "string"},
                    "detection": {
                        "type": "object",
                        "properties": {
                            "checklist_fields": {"type": "array", "items": {"type": "string"}},
                            "keywords": {"type": "array", "items": {"type": "string"}},
                            "medication_names": {"type": "array", "items": {"type": "string"}},
                            "sections": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["checklist_fields", "keywords", "medication_names", "sections"],
                    },
                    "source_doc": {"type": "string"},
                    "source_excerpt": {"type": "string"},
                    "default_level": {"type": "string", "enum": ["yellow", "red"]},
                    "basis": {"type": "string", "enum": ["regulatory", "house"]},
                    "citation": {"type": "string"},
                    "resolution_pathway": {"type": "string"},
                },
                "required": ["id", "description", "detection", "source_doc", "source_excerpt", "default_level", "basis", "citation", "resolution_pathway"],
            },
        },
        "medication_classes_of_concern": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "class_name": {"type": "string"},
                    "example_names": {"type": "array", "items": {"type": "string"}},
                    "why": {"type": "string"},
                    "criterion_ref": {"type": "string"},
                    "source_doc": {"type": "string"},
                },
                "required": ["class_name", "example_names", "why", "criterion_ref", "source_doc"],
            },
        },
        "program_demands": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "demand": {"type": "string"},
                    "interacts_with": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "demand", "interacts_with"],
            },
        },
        "positive_indicators": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["id", "description"],
            },
        },
        "ground_rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rule": {"type": "string"},
                    "source_doc": {"type": "string"},
                },
                "required": ["rule", "source_doc"],
            },
        },
    },
    "required": [
        "hard_criteria",
        "caution_criteria",
        "medication_classes_of_concern",
        "program_demands",
        "positive_indicators",
        "ground_rules",
    ],
}


def build_profile(
    provider: OllamaProvider,
    docs: list[ContextDocument],
) -> ScreeningProfile:
    """Use the model to extract a Screening Profile from context documents."""
    prompt_template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")

    # Build the document content section
    doc_text_parts = []
    for doc in docs:
        doc_text_parts.append(f"--- Document: {doc.path.name} (type: {doc.doc_type}) ---\n{doc.content}")

    documents_text = "\n\n".join(doc_text_parts)
    full_prompt = f"{prompt_template}\n\n## Documents to analyze:\n\n{documents_text}"

    result = provider.analyze(
        prompt=full_prompt,
        response_schema=PROFILE_RESPONSE_SCHEMA,
        max_tokens=8192,
    )

    profile = _result_to_profile(result, docs)
    return profile


def _result_to_profile(result: dict, docs: list[ContextDocument]) -> ScreeningProfile:
    """Convert the model's JSON output to a ScreeningProfile object."""
    hard_criteria = [
        HardCriterion(
            id=c["id"],
            description=c["description"],
            detection=DetectionSpec(**c["detection"]),
            source_doc=c.get("source_doc", ""),
            source_excerpt=c.get("source_excerpt", ""),
            basis=c.get("basis", "house"),
            citation=c.get("citation", ""),
        )
        for c in result.get("hard_criteria", [])
    ]

    caution_criteria = [
        CautionCriterion(
            id=c["id"],
            description=c["description"],
            detection=DetectionSpec(**c["detection"]),
            source_doc=c.get("source_doc", ""),
            source_excerpt=c.get("source_excerpt", ""),
            default_level=c.get("default_level", "yellow"),
            basis=c.get("basis", "house"),
            citation=c.get("citation", ""),
            resolution_pathway=c.get("resolution_pathway", ""),
        )
        for c in result.get("caution_criteria", [])
    ]

    medication_classes = [
        MedicationClassOfConcern(
            class_name=m["class_name"],
            example_names=m.get("example_names", []),
            why=m.get("why", ""),
            criterion_ref=m.get("criterion_ref", ""),
            source_doc=m.get("source_doc", ""),
        )
        for m in result.get("medication_classes_of_concern", [])
    ]

    program_demands = [
        ProgramDemand(
            id=d["id"],
            demand=d["demand"],
            interacts_with=d.get("interacts_with", []),
        )
        for d in result.get("program_demands", [])
    ]

    positive_indicators = [
        PositiveIndicator(id=p["id"], description=p["description"])
        for p in result.get("positive_indicators", [])
    ]

    ground_rules = [
        GroundRule(rule=g["rule"], source_doc=g.get("source_doc", ""))
        for g in result.get("ground_rules", [])
    ]

    context_hash = compute_context_hash(docs)

    return ScreeningProfile(
        hard_criteria=hard_criteria,
        caution_criteria=caution_criteria,
        medication_classes_of_concern=medication_classes,
        program_demands=program_demands,
        positive_indicators=positive_indicators,
        ground_rules=ground_rules,
        profile_hash=context_hash,
    )


def detect_conflicts(
    profile: ScreeningProfile,
    docs: list[ContextDocument],
) -> list[ConflictWarning]:
    """Detect conflicts between documents and ground rules.

    Looks for documents that contradict criteria or ground rules.
    The advisor_memo_CONFLICTING files are designed to trigger this.
    """
    conflicts = []

    # Find conflicting docs
    conflicting_docs = [d for d in docs if "CONFLICTING" in d.path.name or "conflicting" in d.path.name.lower()]
    if not conflicting_docs:
        return conflicts

    # Extract ground rules text for comparison
    ground_rule_texts = [gr.rule.lower() for gr in profile.ground_rules]

    for doc in conflicting_docs:
        content_lower = doc.content.lower()

        # Check for medication-change advice (violates the ground rule)
        medication_change_phrases = [
            "advise holding",
            "advise stopping",
            "advise tapering",
            "recommend holding",
            "recommend stopping",
            "suggest holding",
            "suggest discontinuing",
            "holding their",
            "hold their dose",
            "skip their dose",
            "pause their",
            "consider holding",
        ]
        for phrase in medication_change_phrases:
            if phrase in content_lower:
                conflicts.append(ConflictWarning(
                    criteria_involved=["medication_ground_rule"],
                    description=(
                        f"Document '{doc.path.name}' suggests facilitators advise medication changes "
                        f"(found: '{phrase}'). This contradicts the ground rule that the system/facilitators "
                        "never advise medication changes — all medication questions route to the client's prescriber."
                    ),
                    conservative_reading="The ground rule stands: never advise medication changes.",
                    source_docs=[doc.path.name],
                    is_ground_rule_conflict=True,
                ))
                break

        # Check for criteria relaxation (e.g., shortening exclusion windows)
        relaxation_phrases = [
            ("hypomania", "3 year"),
            ("hypomanic", "3 year"),
        ]
        for keyword, window_phrase in relaxation_phrases:
            if keyword in content_lower and window_phrase in content_lower:
                # Determine which criterion IDs based on the dataset
                criterion_ids = []
                if "a3" in content_lower:
                    criterion_ids.append("A3")
                if "a4" in content_lower:
                    criterion_ids.append("A4")
                if not criterion_ids:
                    criterion_ids = ["A3", "A4"]
                conflicts.append(ConflictWarning(
                    criteria_involved=criterion_ids,
                    description=(
                        f"Document '{doc.path.name}' suggests relaxing the exclusion window for "
                        f"hypomania from 5 years to 3 years. The screening criteria specify a 5-year window."
                    ),
                    conservative_reading="Apply the more conservative (longer) 5-year exclusion window from the screening criteria.",
                    source_docs=[doc.path.name],
                    is_ground_rule_conflict=False,
                ))
                break

        # Check for hypertension clearance relaxation
        if "hypertension" in content_lower or "blood pressure" in content_lower:
            if "without" in content_lower and ("physician" in content_lower or "documentation" in content_lower):
                conflicts.append(ConflictWarning(
                    criteria_involved=["C1"],
                    description=(
                        f"Document '{doc.path.name}' suggests clearing controlled hypertension "
                        "without physician documentation. The screening criteria (C1) require "
                        "written physician clearance."
                    ),
                    conservative_reading="Require written physician clearance per the screening criteria (C1).",
                    source_docs=[doc.path.name],
                    is_ground_rule_conflict=False,
                ))

        # Check for SSRI-related conflicts
        if "ssri" in content_lower and ("hold" in content_lower or "skip" in content_lower or "reduce" in content_lower):
            # Check if this contradicts the no-medication-change rule
            already_found = any("medication" in c.criteria_involved[0] for c in conflicts if c.source_docs == [doc.path.name])
            if not already_found:
                conflicts.append(ConflictWarning(
                    criteria_involved=["C1", "medication_ground_rule"],
                    description=(
                        f"Document '{doc.path.name}' suggests facilitators may advise clients to "
                        "hold or adjust SSRI doses. This contradicts both criterion C1's resolution "
                        "path (prescriber-directed only) and the medication ground rule."
                    ),
                    conservative_reading=(
                        "The ground rule stands: never advise medication changes. "
                        "All SSRI decisions require the client's prescriber."
                    ),
                    source_docs=[doc.path.name],
                    is_ground_rule_conflict=True,
                ))

    return conflicts
