"""Guardrail tests — verify safety invariants hold across the system.

These test the static/deterministic guarantees, not model output (which is
tested via the oracle eval script).
"""

import re

import pytest
from pathlib import Path


# Guardrail 9: System never proposes medication changes
MEDICATION_CHANGE_PHRASES = [
    "stop taking", "discontinue your", "reduce your dose",
    "taper off", "increase your", "switch from", "wean off",
    "hold your medication", "skip your dose", "stop your",
    "we recommend discontinuing", "you should stop",
]

# Guardrail: No admit/deny language
ADMIT_DENY_PHRASES = [
    "we are unable to accept",
    "you are not eligible",
    "your application has been denied",
    "we cannot admit",
    "you have been accepted",
    "congratulations on your admission",
    "you are cleared to participate",
    "we are pleased to accept",
]


class TestPromptGuardrails:
    """Verify prompt templates don't contain forbidden language."""

    @pytest.fixture
    def prompt_files(self):
        prompts_dir = Path(__file__).parent.parent / "prompts"
        return list(prompts_dir.glob("*.md"))

    def test_prompts_exist(self, prompt_files):
        assert len(prompt_files) >= 3

    def test_no_medication_advice_in_prompts(self, prompt_files):
        for path in prompt_files:
            content = path.read_text().lower()
            for phrase in MEDICATION_CHANGE_PHRASES:
                assert phrase not in content, (
                    f"Prompt {path.name} contains medication change language: '{phrase}'"
                )

    def test_no_admit_deny_in_prompts(self, prompt_files):
        for path in prompt_files:
            content = path.read_text().lower()
            for phrase in ADMIT_DENY_PHRASES:
                assert phrase not in content, (
                    f"Prompt {path.name} contains admit/deny language: '{phrase}'"
                )

    def test_prompts_contain_medication_guardrail(self, prompt_files):
        """Every analysis prompt must instruct the model not to advise medication changes."""
        analysis_prompts = [p for p in prompt_files if "analysis" in p.name or "synthesis" in p.name]
        for path in analysis_prompts:
            content = path.read_text().lower()
            assert "medication" in content and ("never" in content or "not" in content), (
                f"Prompt {path.name} lacks explicit medication-change guardrail instruction"
            )


class TestRulesEngineGuardrails:
    """Verify the rules engine output doesn't contain forbidden language."""

    def test_rule_flag_titles_no_admit_deny(self):
        from pisa.parser.markdown import parse_file
        from pisa.rules.engine import run_rules_engine
        from pisa.profile.models import ScreeningProfile, HardCriterion, DetectionSpec

        # Build a minimal profile with one hard criterion
        profile = ScreeningProfile(
            profile_hash="test",
            hard_criteria=[HardCriterion(
                id="A1",
                description="Test criterion",
                source_excerpt="test",
                detection=DetectionSpec(
                    keywords=["lithium"],
                    sections=["medications"],
                    checklist_fields=[],
                    medication_names=["lithium"],
                ),
            )],
            caution_criteria=[],
            medication_classes_of_concern=[],
            program_demands=[],
            positive_indicators=[],
            ground_rules=[],
        )

        # Parse a fixture that triggers the rule
        fixtures = list(Path("demo-data").rglob("applicant_A_marcus_webb.md"))
        if not fixtures:
            pytest.skip("Demo data not available")

        record = parse_file(fixtures[0])
        flags = run_rules_engine(record, profile)

        for flag in flags:
            title = flag.get("title", "").lower()
            rationale = flag.get("rationale", "").lower()
            for phrase in ADMIT_DENY_PHRASES:
                assert phrase not in title, f"Flag title contains admit/deny: {title}"
                assert phrase not in rationale, f"Flag rationale contains admit/deny: {rationale}"
            for phrase in MEDICATION_CHANGE_PHRASES:
                assert phrase not in title, f"Flag title contains med-change advice: {title}"
                assert phrase not in rationale, f"Flag rationale contains med-change advice: {rationale}"


class TestProfileBuilderGuardrails:
    """Verify profile builder conflict detection catches medication-change advice."""

    def test_conflict_detection_catches_ssri_hold(self):
        from pisa.profile.builder import detect_conflicts
        from pisa.profile.models import (
            ScreeningProfile, GroundRule, ConflictWarning,
        )
        from pisa.profile.loader import ContextDocument

        profile = ScreeningProfile(
            profile_hash="test",
            hard_criteria=[],
            caution_criteria=[],
            medication_classes_of_concern=[],
            program_demands=[],
            positive_indicators=[],
            ground_rules=[GroundRule(rule="Never advise medication changes.")],
        )

        # Simulate a conflicting document (filename must contain CONFLICTING)
        doc = ContextDocument(
            path=Path("advisor_memo_CONFLICTING.md"),
            doc_type="reference_material",
            content="Facilitators should advise holding SSRI doses during the session for safety.",
        )

        conflicts = detect_conflicts(profile, [doc])
        assert len(conflicts) >= 1
        assert any(c.is_ground_rule_conflict for c in conflicts)


class TestBlankVsDeferred:
    """Verify the parser correctly distinguishes blank from deferred answers."""

    def test_blank_not_deferred(self):
        from pisa.parser.markdown import detect_answer_status
        from pisa.parser.models import AnswerStatus

        assert detect_answer_status("Any question?", "") == AnswerStatus.blank
        assert detect_answer_status("Any question?", "   ") == AnswerStatus.blank

    def test_deferred_not_blank(self):
        from pisa.parser.markdown import detect_answer_status
        from pisa.parser.models import AnswerStatus

        assert detect_answer_status("Q?", "Let's discuss in person") == AnswerStatus.deferred
        assert detect_answer_status("Q?", "I'd rather talk about this live") == AnswerStatus.deferred

    def test_long_answer_with_deferred_phrase_is_answered(self):
        from pisa.parser.markdown import detect_answer_status
        from pisa.parser.models import AnswerStatus

        long_answer = (
            "I'd like to talk through some of this in more detail. There's a lot "
            "of context from my twenties that I think would be helpful to share, and "
            "I'd rather cover the trauma questions live with someone who can ask follow-ups."
        )
        assert detect_answer_status("Q?", long_answer) == AnswerStatus.answered
