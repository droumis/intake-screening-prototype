"""The schema block in each prompt must match the schema the code enforces.

Every prompt template documents its response shape as a JSON block, and the
provider validates responses against a constant in pisa.pipeline.schemas. When
the two drift, the model is told to return one shape and rejected for returning
it. That happened once already: the comprehensive pass asked for
`overall_impression` while the code enforced `section_summary`.
"""

import json
import re
from pathlib import Path

import pytest

from pisa.pipeline.schemas import (
    COMPREHENSIVE_REVIEW_SCHEMA,
    SECTION_ANALYSIS_SCHEMA,
    SYNTHESIS_SCHEMA,
)

PROMPTS = Path(__file__).parent.parent / "prompts"

# Prompt template -> the schema the pipeline validates its response against.
ENFORCED = [
    ("section_analysis_v1.1.0.md", SECTION_ANALYSIS_SCHEMA),
    ("comprehensive_review_v1.1.0.md", COMPREHENSIVE_REVIEW_SCHEMA),
    ("synthesis_v1.1.0.md", SYNTHESIS_SCHEMA),
]


def _strip_descriptions(node):
    """Drop `description` keys, which document intent for the model and carry no
    validation meaning."""
    if isinstance(node, dict):
        return {k: _strip_descriptions(v) for k, v in node.items() if k != "description"}
    if isinstance(node, list):
        return [_strip_descriptions(v) for v in node]
    return node


def _schema_block(prompt_name: str) -> dict:
    text = (PROMPTS / prompt_name).read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)\n```", text, re.DOTALL)
    assert blocks, f"{prompt_name} has no ```json schema block"
    # The response schema is the last JSON block; earlier ones are examples.
    return json.loads(blocks[-1])


@pytest.mark.parametrize("prompt_name,schema", ENFORCED, ids=[p for p, _ in ENFORCED])
def test_prompt_schema_matches_enforced_schema(prompt_name, schema):
    documented = _strip_descriptions(_schema_block(prompt_name))
    enforced = _strip_descriptions(schema)
    assert documented == enforced, (
        f"{prompt_name} documents a response shape the pipeline will reject. "
        "Update the prompt's json block and the schema constant together."
    )


@pytest.mark.parametrize("prompt_name,schema", ENFORCED, ids=[p for p, _ in ENFORCED])
def test_prompt_schema_block_is_valid_json_schema(prompt_name, schema):
    """A malformed block would still validate above if both sides were wrong."""
    import jsonschema

    jsonschema.Draft7Validator.check_schema(_schema_block(prompt_name))


def test_comprehensive_and_section_schemas_differ_where_intended():
    """The comprehensive pass sees the whole form, so it reports an overall
    impression and can attribute basis/citation. Guards against someone
    "fixing" the drift by pointing both at one schema."""
    assert "overall_impression" in COMPREHENSIVE_REVIEW_SCHEMA["properties"]
    assert "section_summary" in SECTION_ANALYSIS_SCHEMA["properties"]
    comprehensive_flag = COMPREHENSIVE_REVIEW_SCHEMA["properties"]["flags"]["items"]
    assert {"basis", "citation"} <= set(comprehensive_flag["properties"])
    assert {"basis", "citation"} <= set(comprehensive_flag["required"])
