"""Unit tests for the markdown form parser — Phase 1 acceptance."""

from pathlib import Path

import pytest

from pisa.parser.markdown import parse_file, parse_markdown_form, detect_answer_status
from pisa.parser.models import AnswerStatus

DEMO_DATA = Path(__file__).parent.parent / "demo-data"
PSILOCYBIN = DEMO_DATA / "psilocybin-group-retreat" / "forms"
SUMMIT = DEMO_DATA / "summit-series" / "forms"
FIXTURES = Path(__file__).parent / "fixtures"
ALT_FORMAT = FIXTURES / "alt_format_intake.md"


# -- Identity parsing --


class TestIdentityParsing:
    def test_dale_identity(self):
        record = parse_file(PSILOCYBIN / "applicant_A_dale_bergstrom.md")
        assert record.display_name == "Dale Bergstrom"
        assert record.identity.age == "44"
        assert record.identity.pronouns == "he/him"
        assert record.identity.occupation == "Architect"
        assert record.identity.date == "2026-07-05"

    def test_yuki_identity(self):
        record = parse_file(PSILOCYBIN / "applicant_B_yuki_tanaka.md")
        assert record.display_name == "Yuki Tanaka"
        assert record.identity.age == "36"
        assert record.identity.pronouns == "she/her"

    def test_marcus_identity(self):
        record = parse_file(SUMMIT / "applicant_A_marcus_webb.md")
        assert record.display_name == "Marcus Webb"
        assert record.identity.age == "47"
        assert record.identity.occupation == "VP of Sales, enterprise software"

    def test_tomas_identity(self):
        record = parse_file(SUMMIT / "applicant_C_tomas_herrera.md")
        assert record.display_name == "Tomás Herrera"
        assert record.identity.age == "52"


# -- Section parsing --


class TestSectionParsing:
    def test_all_fixtures_parse_without_unmapped(self):
        """All 6 fixtures should map all content to known sections."""
        for path in sorted(DEMO_DATA.rglob("forms/applicant_*.md")):
            record = parse_file(path)
            assert record.unmapped_content == "", f"{path.name} has unmapped content"

    def test_section_count(self):
        """Each fixture should produce a reasonable number of sections."""
        for path in sorted(DEMO_DATA.rglob("forms/applicant_*.md")):
            record = parse_file(path)
            assert len(record.sections) >= 10, f"{path.name} has too few sections"

    def test_dale_has_medical_history(self):
        record = parse_file(PSILOCYBIN / "applicant_A_dale_bergstrom.md")
        assert "medical_history" in record.sections
        med_section = record.sections["medical_history"]
        assert len(med_section.qa_pairs) > 5

    def test_marcus_has_separate_medications_section(self):
        """Summit series forms have MEDICATIONS as a separate ## heading."""
        record = parse_file(SUMMIT / "applicant_A_marcus_webb.md")
        assert "medications" in record.sections


# -- Medication parsing --


class TestMedicationParsing:
    def test_dale_phenelzine(self):
        record = parse_file(PSILOCYBIN / "applicant_A_dale_bergstrom.md")
        med_section = record.sections["medical_history"]
        assert len(med_section.medications) == 1
        med = med_section.medications[0]
        assert "Phenelzine" in med.medication or "phenelzine" in med.medication.lower()
        assert "45" in med.dosage
        assert med.since == "2024"

    def test_yuki_two_medications(self):
        record = parse_file(PSILOCYBIN / "applicant_B_yuki_tanaka.md")
        med_section = record.sections["medical_history"]
        assert len(med_section.medications) == 2
        med_names = [m.medication.lower() for m in med_section.medications]
        assert any("amlodipine" in n for n in med_names)
        assert any("sertraline" in n for n in med_names)

    def test_marcus_lithium(self):
        record = parse_file(SUMMIT / "applicant_A_marcus_webb.md")
        med_section = record.sections["medications"]
        med_names = [m.medication.lower() for m in med_section.medications]
        assert any("lithium" in n for n in med_names)

    def test_owen_no_medications(self):
        record = parse_file(PSILOCYBIN / "applicant_C_owen_marsh.md")
        med_section = record.sections["medical_history"]
        assert len(med_section.medications) == 0

    def test_tomas_inhaler(self):
        record = parse_file(SUMMIT / "applicant_C_tomas_herrera.md")
        med_section = record.sections["medications"]
        assert len(med_section.medications) == 1
        assert "albuterol" in med_section.medications[0].medication.lower()


# -- Condition checklist --


class TestConditionChecklist:
    def test_yuki_high_blood_pressure_checked(self):
        record = parse_file(PSILOCYBIN / "applicant_B_yuki_tanaka.md")
        med_section = record.sections["medical_history"]
        checked = [e.condition for e in med_section.condition_checklist if e.checked]
        assert "High Blood Pressure" in checked

    def test_dale_nothing_checked(self):
        record = parse_file(PSILOCYBIN / "applicant_A_dale_bergstrom.md")
        med_section = record.sections["medical_history"]
        checked = [e.condition for e in med_section.condition_checklist if e.checked]
        assert checked == []

    def test_tomas_asthma_checked(self):
        record = parse_file(SUMMIT / "applicant_C_tomas_herrera.md")
        med_section = record.sections["medical_history"]
        checked = [e.condition for e in med_section.condition_checklist if e.checked]
        assert "Asthma" in checked

    def test_priya_high_blood_pressure_checked(self):
        record = parse_file(SUMMIT / "applicant_B_priya_raman.md")
        med_section = record.sections["medical_history"]
        checked = [e.condition for e in med_section.condition_checklist if e.checked]
        assert "High Blood Pressure" in checked


# -- Consumption tables --


class TestConsumptionTable:
    def test_marcus_alcohol(self):
        record = parse_file(SUMMIT / "applicant_A_marcus_webb.md")
        sub_section = record.sections["substance_use"]
        alcohol = [c for c in sub_section.consumption_table if "alcohol" in c.substance.lower()]
        assert len(alcohol) == 1
        assert "10" in alcohol[0].amount or "12" in alcohol[0].amount

    def test_owen_cannabis(self):
        record = parse_file(PSILOCYBIN / "applicant_C_owen_marsh.md")
        sub_section = record.sections["substance_use"]
        cannabis = [c for c in sub_section.consumption_table if "cannabis" in c.substance.lower()]
        assert len(cannabis) == 1
        assert "5" in cannabis[0].amount

    def test_tomas_cannabis_4(self):
        record = parse_file(SUMMIT / "applicant_C_tomas_herrera.md")
        sub_section = record.sections["substance_use"]
        cannabis = [c for c in sub_section.consumption_table if "cannabis" in c.substance.lower()]
        assert len(cannabis) == 1
        assert "4" in cannabis[0].amount


# -- Deferred answer detection --


class TestDeferredDetection:
    def test_yuki_trauma_deferred(self):
        record = parse_file(PSILOCYBIN / "applicant_B_yuki_tanaka.md")
        mh = record.sections["mental_emotional_health"]
        trauma_qa = [q for q in mh.qa_pairs if "trauma" in q.question.lower()]
        assert len(trauma_qa) >= 1
        assert trauma_qa[0].status == AnswerStatus.deferred

    def test_yuki_sexuality_deferred(self):
        record = parse_file(PSILOCYBIN / "applicant_B_yuki_tanaka.md")
        sex = record.sections["sexuality"]
        assert all(q.status == AnswerStatus.deferred for q in sex.qa_pairs)

    def test_priya_trauma_deferred(self):
        record = parse_file(SUMMIT / "applicant_B_priya_raman.md")
        mh = record.sections["mental_emotional_health"]
        trauma_qa = [q for q in mh.qa_pairs if "trauma" in q.question.lower()]
        assert len(trauma_qa) >= 1
        assert trauma_qa[0].status == AnswerStatus.deferred

    def test_priya_integration_not_deferred(self):
        """Priya's long answer mentioning 'rather cover... live' is NOT deferred."""
        record = parse_file(SUMMIT / "applicant_B_priya_raman.md")
        integ = record.sections["integration_support"]
        last_qa = [q for q in integ.qa_pairs if "anything else" in q.question.lower()]
        assert len(last_qa) == 1
        assert last_qa[0].status == AnswerStatus.answered

    def test_dale_no_deferred(self):
        """Dale answers everything — risk is content, not avoidance."""
        record = parse_file(PSILOCYBIN / "applicant_A_dale_bergstrom.md")
        for section in record.sections.values():
            for qa in section.qa_pairs:
                assert qa.status != AnswerStatus.deferred, (
                    f"Dale should have no deferred answers, got: {qa.question}"
                )


# -- Blank answer detection --


class TestBlankDetection:
    def test_owen_guilt_blank(self):
        """Owen's guilt/shame question is left entirely blank."""
        record = parse_file(PSILOCYBIN / "applicant_C_owen_marsh.md")
        personal = record.sections["personal"]
        guilt_qa = [q for q in personal.qa_pairs if "guilt" in q.question.lower() or "shame" in q.question.lower()]
        assert len(guilt_qa) == 1
        assert guilt_qa[0].status == AnswerStatus.blank

    def test_tomas_family_blank(self):
        """Tomás's 'Anything else about family?' is left blank."""
        record = parse_file(SUMMIT / "applicant_C_tomas_herrera.md")
        mh = record.sections["mental_emotional_health"]
        family_qa = [q for q in mh.qa_pairs if "anything else about family" in q.question.lower()]
        assert len(family_qa) == 1
        assert family_qa[0].status == AnswerStatus.blank

    def test_blank_is_not_deferred(self):
        """Blank answers must not be classified as deferred."""
        record = parse_file(PSILOCYBIN / "applicant_C_owen_marsh.md")
        personal = record.sections["personal"]
        guilt_qa = [q for q in personal.qa_pairs if "guilt" in q.question.lower()]
        assert guilt_qa[0].status == AnswerStatus.blank
        assert guilt_qa[0].status != AnswerStatus.deferred


# -- Answer status detection unit tests --


class TestAnswerStatusDetection:
    def test_blank(self):
        assert detect_answer_status("Q?", "") == AnswerStatus.blank
        assert detect_answer_status("Q?", "   ") == AnswerStatus.blank

    def test_deferred_short(self):
        assert detect_answer_status("Q?", "Let's discuss this in person.") == AnswerStatus.deferred
        assert detect_answer_status("Q?", "let's talk") == AnswerStatus.deferred
        assert detect_answer_status("Q?", "Let's talk about this at the intake meeting.") == AnswerStatus.deferred

    def test_long_answer_with_deferred_phrase_is_answered(self):
        long_answer = (
            "I'd like to talk through how the fast interacts with my medications, "
            "and I'd rather cover the trauma questions live than in writing."
        )
        assert detect_answer_status("Q?", long_answer) == AnswerStatus.answered

    def test_substantive_answer(self):
        assert detect_answer_status("Q?", "No") == AnswerStatus.answered
        assert detect_answer_status("Q?", "Yes, I have high blood pressure.") == AnswerStatus.answered


# -- Alternative form layout (no title, bold headings, plain-text questions, 2-col checklist) --


class TestAltFormatLayout:
    """Tests for the second supported form layout.

    Fixture: no `#` title, bold standalone section headings, several questions per
    plain-text line, a two-column condition checklist, and a consumption table.
    """

    def test_alt_identity(self):
        record = parse_file(ALT_FORMAT)
        assert record.display_name == "Wren Halloway"
        assert record.identity.age == "41"
        assert record.identity.pronouns == "they/them"

    def test_alt_section_count(self):
        record = parse_file(ALT_FORMAT)
        assert len(record.sections) >= 10

    def test_alt_multi_question_line_merges(self):
        """Multi-sentence questions on one line should not split into Q/A."""
        record = parse_file(ALT_FORMAT)
        purpose = record.sections["purpose_goals"]
        assert len(purpose.qa_pairs) == 1
        q = purpose.qa_pairs[0].question
        assert "goals" in q.lower()
        assert "seeking" in q.lower()
        assert purpose.qa_pairs[0].answer.startswith("Mostly I want to slow down")

    def test_alt_psychedelic_history_questions(self):
        """First question in psychedelic history merges the full multi-? line."""
        record = parse_file(ALT_FORMAT)
        hist = record.sections["relevant_experience_history"]
        first_q = hist.qa_pairs[0].question
        assert "psychedelics" in first_q.lower()
        assert "recreational" in first_q.lower() or "ceremonial" in first_q.lower()
        assert hist.qa_pairs[0].answer.startswith("Twice, both a long time ago")

    def test_alt_condition_checklist_2col(self):
        """2-column condition checklist parses correctly (all blank = none checked)."""
        record = parse_file(ALT_FORMAT)
        med = record.sections["medical_history"]
        assert len(med.condition_checklist) >= 10
        checked = [e.condition for e in med.condition_checklist if e.checked]
        assert checked == []

    def test_alt_no_medications(self):
        record = parse_file(ALT_FORMAT)
        med = record.sections["medical_history"]
        assert len(med.medications) == 0

    def test_alt_consumption_table(self):
        record = parse_file(ALT_FORMAT)
        sub = record.sections["substance_use"]
        caffeine = [c for c in sub.consumption_table if "caffeine" in c.substance.lower()]
        assert len(caffeine) == 1
        assert "tea" in caffeine[0].amount.lower()

    def test_alt_no_unmapped(self):
        record = parse_file(ALT_FORMAT)
        assert record.unmapped_content == ""
