"""Unit tests for the deterministic rules engine — Phase 3 acceptance.

These tests construct Screening Profiles directly (no model needed) and verify
that the rules engine catches every hard criterion from the fixture data.
"""

from pathlib import Path

import pytest

from pisa.parser.markdown import parse_file
from pisa.profile.models import (
    CautionCriterion,
    DetectionSpec,
    HardCriterion,
    MedicationClassOfConcern,
    ScreeningProfile,
)
from pisa.rules.engine import run_rules_engine

DEMO_DATA = Path(__file__).parent.parent / "demo-data"
PSILOCYBIN = DEMO_DATA / "psilocybin-group-retreat" / "forms"
SUMMIT = DEMO_DATA / "summit-series" / "forms"


def _psilocybin_profile() -> ScreeningProfile:
    """Construct the psilocybin dataset's screening profile for deterministic testing."""
    return ScreeningProfile(
        hard_criteria=[
            HardCriterion(
                id="A1",
                description="Lithium therapy",
                detection=DetectionSpec(
                    medication_names=["lithium"],
                    keywords=["lithium"],
                    sections=["medications", "medical_history"],
                ),
            ),
            HardCriterion(
                id="A2",
                description="MAOI antidepressants",
                detection=DetectionSpec(
                    medication_names=["phenelzine", "tranylcypromine", "selegiline", "nardil", "parnate"],
                    keywords=["maoi", "phenelzine", "tranylcypromine", "nardil"],
                    sections=["medications", "medical_history"],
                ),
            ),
            HardCriterion(
                id="A3",
                description="Personal history of psychosis",
                detection=DetectionSpec(
                    keywords=["psychosis", "psychotic", "schizophrenia", "schizoaffective", "break from reality"],
                    sections=["mental_emotional_health"],
                ),
            ),
            HardCriterion(
                id="A4",
                description="Bipolar I or manic/hypomanic episode within 5 years",
                detection=DetectionSpec(
                    keywords=["bipolar i", "bipolar 1", "manic episode", "hypomanic episode", "mania"],
                    sections=["mental_emotional_health"],
                ),
            ),
            HardCriterion(
                id="A5",
                description="Suicidal ideation within 12 months",
                detection=DetectionSpec(
                    keywords=["suicidal", "better off without me", "end my life", "kill myself"],
                    sections=["mental_emotional_health"],
                ),
            ),
            HardCriterion(
                id="A6",
                description="Unstable cardiovascular disease",
                detection=DetectionSpec(
                    checklist_fields=["Irregular Heart-rate", "Heart Attack", "Stroke"],
                    keywords=["arrhythmia", "afib", "unstable angina", "uncontrolled hypertension"],
                    sections=["medical_history", "condition_checklist"],
                ),
            ),
            HardCriterion(
                id="A10",
                description="Allergy to mushrooms or fungi",
                detection=DetectionSpec(
                    keywords=["allergic reaction to consuming mushrooms", "allergic to mushrooms"],
                    sections=["substance_use", "medical_history"],
                ),
            ),
        ],
        caution_criteria=[
            CautionCriterion(
                id="C1",
                description="SSRI/SNRI antidepressants",
                detection=DetectionSpec(
                    medication_names=["sertraline", "escitalopram", "fluoxetine", "paroxetine", "venlafaxine", "duloxetine", "citalopram"],
                    keywords=["ssri", "snri"],
                    sections=["medications", "medical_history"],
                ),
            ),
            CautionCriterion(
                id="C3",
                description="Controlled hypertension on medication",
                detection=DetectionSpec(
                    checklist_fields=["High Blood Pressure"],
                    medication_names=["amlodipine", "lisinopril", "losartan", "hydrochlorothiazide", "metoprolol"],
                    sections=["medical_history", "medications"],
                ),
            ),
            CautionCriterion(
                id="C4",
                description="Serotonergic or interaction-prone supplements",
                detection=DetectionSpec(
                    keywords=["st. john's wort", "st john", "passionflower"],
                    sections=["medical_history", "medications", "supplements"],
                ),
            ),
            CautionCriterion(
                id="D2",
                description="Cannabis use >= 4 times/week",
                detection=DetectionSpec(
                    keywords=[],
                    sections=["substance_use"],
                ),
            ),
        ],
    )


def _summit_profile() -> ScreeningProfile:
    """Construct the summit dataset's screening profile for deterministic testing."""
    return ScreeningProfile(
        hard_criteria=[
            HardCriterion(
                id="A1",
                description="Lithium therapy",
                detection=DetectionSpec(
                    medication_names=["lithium"],
                    keywords=["lithium"],
                    sections=["medications", "medical_history"],
                ),
            ),
            HardCriterion(
                id="A2",
                description="Psychotic disorder or psychotic episode at any time",
                detection=DetectionSpec(
                    keywords=["psychosis", "psychotic", "schizophrenia", "break from reality"],
                    sections=["mental_emotional_health"],
                ),
            ),
            HardCriterion(
                id="A3",
                description="Bipolar I or manic/hypomanic episode within 5 years",
                detection=DetectionSpec(
                    keywords=["bipolar", "manic episode", "hypomanic episode", "hypomanic", "mania"],
                    sections=["mental_emotional_health"],
                ),
            ),
            HardCriterion(
                id="A8",
                description="History of an eating disorder",
                detection=DetectionSpec(
                    keywords=["anorexia", "bulimia", "binge eating", "eating disorder", "disordered eating"],
                    sections=["diet", "mental_emotional_health"],
                ),
            ),
            HardCriterion(
                id="A9",
                description="Suicidal ideation within 12 months",
                detection=DetectionSpec(
                    keywords=["suicidal", "better off without me", "end my life"],
                    sections=["mental_emotional_health"],
                ),
            ),
        ],
        caution_criteria=[
            CautionCriterion(
                id="C1",
                description="Controlled hypertension on medication",
                detection=DetectionSpec(
                    checklist_fields=["High Blood Pressure"],
                    medication_names=["lisinopril", "amlodipine", "losartan", "hydrochlorothiazide"],
                    sections=["medications", "medical_history"],
                ),
            ),
            CautionCriterion(
                id="C3",
                description="SSRI/SNRI antidepressants",
                detection=DetectionSpec(
                    medication_names=["sertraline", "escitalopram", "fluoxetine", "venlafaxine"],
                    keywords=["ssri", "snri"],
                    sections=["medications", "medical_history"],
                ),
            ),
            CautionCriterion(
                id="C5",
                description="Asthma",
                detection=DetectionSpec(
                    checklist_fields=["Asthma"],
                    medication_names=["albuterol", "salbutamol"],
                    keywords=["asthma", "inhaler"],
                    sections=["medical_history", "medications"],
                ),
            ),
            CautionCriterion(
                id="C6",
                description="Interaction-prone supplements (St. John's Wort, grapefruit, passionflower)",
                detection=DetectionSpec(
                    keywords=["st. john's wort", "st john", "grapefruit", "passionflower"],
                    sections=["medications", "medical_history", "substance_use"],
                ),
            ),
            CautionCriterion(
                id="C10",
                description="High caffeine dependence (>= 4/day)",
                detection=DetectionSpec(
                    keywords=[],
                    sections=["substance_use"],
                ),
            ),
        ],
    )


# -- Phase 3 acceptance: hard criteria detected with model disabled --


class TestPsilocybinHardCriteria:
    """Dale Bergstrom: rules engine must catch A2 (MAOI) from the medication table."""

    def test_dale_a2_maoi_detected(self):
        record = parse_file(PSILOCYBIN / "applicant_A_dale_bergstrom.md")
        profile = _psilocybin_profile()
        flags = run_rules_engine(record, profile)

        red_flags = [f for f in flags if f["level"] == "red"]
        a2_flags = [f for f in red_flags if "A2" in f["title"]]

        assert len(a2_flags) >= 1, "Rules engine must catch A2 (MAOI: Phenelzine)"
        flag = a2_flags[0]
        assert flag["hard_flag"] is True
        assert any("Phenelzine" in ev["quote"] or "phenelzine" in ev["quote"].lower()
                   for ev in flag["evidence"])

    def test_dale_a5_suicidal_ideation_detected(self):
        """Dale's 'better off without me' disclosure must trigger A5."""
        record = parse_file(PSILOCYBIN / "applicant_A_dale_bergstrom.md")
        profile = _psilocybin_profile()
        flags = run_rules_engine(record, profile)
        a5_flags = [f for f in flags if "A5" in f["title"]]
        assert len(a5_flags) >= 1, "Rules engine must catch A5 (suicidal ideation: 'better off without me')"
        assert a5_flags[0]["hard_flag"] is True

    def test_dale_no_false_a6(self):
        """Dale has no checked cardiovascular conditions — should not trigger A6."""
        record = parse_file(PSILOCYBIN / "applicant_A_dale_bergstrom.md")
        profile = _psilocybin_profile()
        flags = run_rules_engine(record, profile)
        a6_flags = [f for f in flags if "A6" in f["title"]]
        assert len(a6_flags) == 0

    def test_yuki_no_hard_reds(self):
        """Yuki should have no hard red flags from rules engine."""
        record = parse_file(PSILOCYBIN / "applicant_B_yuki_tanaka.md")
        profile = _psilocybin_profile()
        flags = run_rules_engine(record, profile)
        hard_reds = [f for f in flags if f["level"] == "red" and f["hard_flag"]]
        assert len(hard_reds) == 0

    def test_yuki_c1_ssri_detected(self):
        """Yuki's sertraline should trigger C1 (SSRI)."""
        record = parse_file(PSILOCYBIN / "applicant_B_yuki_tanaka.md")
        profile = _psilocybin_profile()
        flags = run_rules_engine(record, profile)
        c1_flags = [f for f in flags if "C1" in f["title"]]
        assert len(c1_flags) >= 1

    def test_yuki_c3_hypertension_detected(self):
        """Yuki's High Blood Pressure checklist item should trigger C3."""
        record = parse_file(PSILOCYBIN / "applicant_B_yuki_tanaka.md")
        profile = _psilocybin_profile()
        flags = run_rules_engine(record, profile)
        c3_flags = [f for f in flags if "C3" in f["title"]]
        assert len(c3_flags) >= 1

    def test_yuki_c4_passionflower_detected(self):
        """Yuki's passionflower use should trigger C4."""
        record = parse_file(PSILOCYBIN / "applicant_B_yuki_tanaka.md")
        profile = _psilocybin_profile()
        flags = run_rules_engine(record, profile)
        c4_flags = [f for f in flags if "C4" in f["title"]]
        assert len(c4_flags) >= 1

    def test_owen_no_hard_reds(self):
        """Owen should have no hard red flags."""
        record = parse_file(PSILOCYBIN / "applicant_C_owen_marsh.md")
        profile = _psilocybin_profile()
        flags = run_rules_engine(record, profile)
        hard_reds = [f for f in flags if f["level"] == "red" and f["hard_flag"]]
        assert len(hard_reds) == 0


class TestSummitHardCriteria:
    """Marcus Webb: rules engine must catch A1 (Lithium) from the medication table."""

    def test_marcus_a1_lithium_detected(self):
        record = parse_file(SUMMIT / "applicant_A_marcus_webb.md")
        profile = _summit_profile()
        flags = run_rules_engine(record, profile)

        red_flags = [f for f in flags if f["level"] == "red"]
        a1_flags = [f for f in red_flags if "A1" in f["title"]]

        assert len(a1_flags) >= 1, "Rules engine must catch A1 (Lithium)"
        flag = a1_flags[0]
        assert flag["hard_flag"] is True
        assert any("lithium" in ev["quote"].lower() or "Lithium" in ev["quote"]
                   for ev in flag["evidence"])

    def test_marcus_a3_hypomanic_detected(self):
        """Marcus's hypomanic episode text should trigger A3."""
        record = parse_file(SUMMIT / "applicant_A_marcus_webb.md")
        profile = _summit_profile()
        flags = run_rules_engine(record, profile)
        a3_flags = [f for f in flags if "A3" in f["title"]]
        assert len(a3_flags) >= 1

    def test_priya_no_hard_reds(self):
        """Priya should have no hard red flags."""
        record = parse_file(SUMMIT / "applicant_B_priya_raman.md")
        profile = _summit_profile()
        flags = run_rules_engine(record, profile)
        hard_reds = [f for f in flags if f["level"] == "red" and f["hard_flag"]]
        assert len(hard_reds) == 0

    def test_priya_c1_hypertension_detected(self):
        """Priya's High Blood Pressure checklist should trigger C1."""
        record = parse_file(SUMMIT / "applicant_B_priya_raman.md")
        profile = _summit_profile()
        flags = run_rules_engine(record, profile)
        c1_flags = [f for f in flags if "C1" in f["title"]]
        assert len(c1_flags) >= 1

    def test_priya_c3_ssri_detected(self):
        """Priya's sertraline should trigger C3 (SSRI)."""
        record = parse_file(SUMMIT / "applicant_B_priya_raman.md")
        profile = _summit_profile()
        flags = run_rules_engine(record, profile)
        c3_flags = [f for f in flags if "C3" in f["title"]]
        assert len(c3_flags) >= 1

    def test_priya_c6_st_johns_wort_detected(self):
        """Priya's St. John's Wort use should trigger C6."""
        record = parse_file(SUMMIT / "applicant_B_priya_raman.md")
        profile = _summit_profile()
        flags = run_rules_engine(record, profile)
        c6_flags = [f for f in flags if "C6" in f["title"]]
        assert len(c6_flags) >= 1

    def test_tomas_c5_asthma_detected(self):
        """Tomás's asthma checklist item should trigger C5."""
        record = parse_file(SUMMIT / "applicant_C_tomas_herrera.md")
        profile = _summit_profile()
        flags = run_rules_engine(record, profile)
        c5_flags = [f for f in flags if "C5" in f["title"]]
        assert len(c5_flags) >= 1

    def test_tomas_no_hard_reds(self):
        """Tomás should have no hard red flags."""
        record = parse_file(SUMMIT / "applicant_C_tomas_herrera.md")
        profile = _summit_profile()
        flags = run_rules_engine(record, profile)
        hard_reds = [f for f in flags if f["level"] == "red" and f["hard_flag"]]
        assert len(hard_reds) == 0


class TestCalibration:
    """Ensure the rules engine doesn't over-flag (calibration traps from oracle)."""

    def test_owen_past_drinking_not_flagged_as_red(self):
        """Owen's 2009-era resolved drinking must NOT produce a substance red."""
        record = parse_file(PSILOCYBIN / "applicant_C_owen_marsh.md")
        profile = _psilocybin_profile()
        flags = run_rules_engine(record, profile)
        substance_reds = [f for f in flags if f["level"] == "red" and f["category"] == "substance"]
        assert len(substance_reds) == 0

    def test_tomas_divorce_depression_not_flagged(self):
        """Tomás's resolved 2016 depression should NOT trigger current flags."""
        record = parse_file(SUMMIT / "applicant_C_tomas_herrera.md")
        profile = _summit_profile()
        flags = run_rules_engine(record, profile)
        # Should only have asthma-related caution, nothing psychological
        psych_flags = [f for f in flags if f["category"] == "psychological"]
        assert len(psych_flags) == 0


# -- Section targeting: a hard criterion must not miss an explicit disclosure --

OREGON = DEMO_DATA / "oregon-psilocybin-session" / "forms"


def _lithium_criterion(sections: list[str]) -> DetectionSpec:
    return DetectionSpec(
        keywords=["lithium"],
        sections=sections,
        checklist_fields=[],
        medication_names=["lithium"],
    )


class TestHardCriterionSectionFallback:
    """The Oregon lithium case.

    The applicant answers "Yes" to the lithium question, but that question lives
    in the regulatory screening block and her medication table reads "None
    currently". A profile that points the criterion at "medications" used to
    produce no flag at all, while the dataset's oracle asserts the rules engine
    catches the Yes.
    """

    @pytest.mark.parametrize("sections", [
        ["medications"],              # plausible but wrong section
        ["client_information_form"],  # name that resolves to nothing
        ["regulatory_screening"],     # correct section
        [],                           # unrestricted
    ])
    def test_lithium_fires_whatever_section_the_profile_targets(self, sections):
        record = parse_file(OREGON / "applicant_A_nina_kowalski.md")
        profile = ScreeningProfile(
            profile_hash="t",
            hard_criteria=[HardCriterion(
                id="R-A1",
                description="Lithium within the last 30 days",
                source_excerpt="OAR 333-333-5050(3)(a)",
                detection=_lithium_criterion(sections),
            )],
        )
        flags = run_rules_engine(record, profile)
        assert len(flags) == 1, f"exclusionary criterion missed with sections={sections}"
        assert flags[0]["hard_flag"] is True
        assert flags[0]["level"] == "red"
        assert flags[0]["evidence"], "flag must carry the quote that substantiates it"

    def test_wrong_section_says_so_in_the_rationale(self):
        """A rescued match tells the reviewer the profile's mapping is suspect."""
        record = parse_file(OREGON / "applicant_A_nina_kowalski.md")
        profile = ScreeningProfile(
            profile_hash="t",
            hard_criteria=[HardCriterion(
                id="R-A1", description="Lithium within the last 30 days",
                source_excerpt="x", detection=_lithium_criterion(["medications"]),
            )],
        )
        flag = run_rules_engine(record, profile)[0]
        assert "rather than the section this criterion targets" in flag["rationale"]
        assert "regulatory_screening" in flag["rationale"]

    def test_correct_section_does_not_claim_a_mapping_problem(self):
        record = parse_file(OREGON / "applicant_A_nina_kowalski.md")
        profile = ScreeningProfile(
            profile_hash="t",
            hard_criteria=[HardCriterion(
                id="R-A1", description="Lithium within the last 30 days",
                source_excerpt="x",
                detection=_lithium_criterion(["regulatory_screening"]),
            )],
        )
        flag = run_rules_engine(record, profile)[0]
        assert "rather than the section this criterion targets" not in flag["rationale"]

    def test_caution_criteria_keep_their_narrow_scope(self):
        """The rescan is for exclusions only; widening every criterion would flood
        the reviewer with matches from unrelated sections."""
        record = parse_file(OREGON / "applicant_A_nina_kowalski.md")
        profile = ScreeningProfile(
            profile_hash="t",
            caution_criteria=[CautionCriterion(
                id="C-9", description="Lithium mention", source_excerpt="x",
                default_level="yellow",
                detection=DetectionSpec(keywords=["lithium"], sections=["medications"],
                                        checklist_fields=[], medication_names=[]),
            )],
        )
        assert run_rules_engine(record, profile) == []

    def test_absent_finding_still_produces_no_flag(self):
        """The rescan must not invent a match: a keyword absent from the whole
        form stays absent."""
        record = parse_file(OREGON / "applicant_A_nina_kowalski.md")
        profile = ScreeningProfile(
            profile_hash="t",
            hard_criteria=[HardCriterion(
                id="R-A9", description="Clozapine", source_excerpt="x",
                detection=DetectionSpec(keywords=["clozapine"], sections=["medications"],
                                        checklist_fields=[], medication_names=["clozapine"]),
            )],
        )
        assert run_rules_engine(record, profile) == []
