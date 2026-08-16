"""JSON schemas for pipeline model responses.

These are passed to the provider as the structured-output format and validated
against the response, so a property missing here is a property the model cannot
return, whatever the prompt asks for. `tests/test_prompt_schemas.py` asserts each
prompt's documented schema block matches the constant enforced against it.
"""

EVIDENCE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "section": {"type": "string"},
        "quote": {"type": "string"},
        "criterion_ref": {"type": "string"},
    },
    "required": ["section", "quote", "criterion_ref"],
}

# One flag shape, shared by every pass that emits flags. It was duplicated per
# pass, and the copies drifted: the per-section and synthesis prompts asked for
# `basis` and `citation` while their schemas omitted both, so the model was
# constrained away from ever returning the regulatory-vs-house attribution the
# state datasets exist to demonstrate.
#
# `basis` accepts "" because a program whose criteria carry no regulatory layer
# has no basis to report, and forcing a choice there invites the model to invent
# one.
FLAG_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "level": {"type": "string", "enum": ["green", "yellow", "red"]},
        "severity": {"type": "integer", "minimum": 1, "maximum": 10},
        "category": {"type": "string", "enum": ["medical", "medication", "psychological", "substance", "logistical", "support_network", "data_quality"]},
        "title": {"type": "string"},
        "evidence": {"type": "array", "items": EVIDENCE_ITEM_SCHEMA},
        "rationale": {"type": "string"},
        "recommended_followup": {"type": "array", "items": {"type": "string"}},
        "resolution_criteria": {"type": "string"},
        "suggested_lookup": {"type": "array", "items": {"type": "string"}},
        "hard_flag": {"type": "boolean"},
        "basis": {"type": "string", "enum": ["regulatory", "house", ""]},
        "citation": {"type": "string"},
    },
    "required": [
        "level", "severity", "category", "title", "evidence", "rationale",
        "recommended_followup", "resolution_criteria", "suggested_lookup",
        "hard_flag", "basis", "citation",
    ],
}

SECTION_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "section_summary": {"type": "string"},
        "flags": {"type": "array", "items": FLAG_ITEM_SCHEMA},
    },
    "required": ["section_summary", "flags"],
}

# The comprehensive pass sees the whole form at once, so it reports an overall
# impression rather than a per-section summary.
COMPREHENSIVE_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "overall_impression": {"type": "string"},
        "flags": {"type": "array", "items": FLAG_ITEM_SCHEMA},
    },
    "required": ["overall_impression", "flags"],
}

SYNTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "overall_notes": {"type": "string"},
        "cross_section_flags": {"type": "array", "items": FLAG_ITEM_SCHEMA},
        "proposed_merges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "primary_title": {"type": "string"},
                    "merge_titles": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
                "required": ["primary_title", "merge_titles", "reason"],
            },
        },
    },
    "required": ["overall_notes", "cross_section_flags", "proposed_merges"],
}
