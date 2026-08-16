"""Tests for pisa.pipeline — runner structure, loud failure, result format."""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from pisa.pipeline.runner import PipelineResult, run_pipeline, ProgressCallback
from pisa.parser.models import (
    ApplicantRecord, Identity, ParsedSection, QAPair, MedicationEntry, AnswerStatus,
)
from pisa.profile.models import (
    ScreeningProfile, HardCriterion, CautionCriterion, DetectionSpec,
    ProgramDemand, GroundRule,
)


@pytest.fixture
def minimal_profile():
    return ScreeningProfile(
        profile_hash="test",
        hard_criteria=[HardCriterion(
            id="A1",
            description="Lithium therapy",
            source_excerpt="test",
            detection=DetectionSpec(
                keywords=["lithium"],
                sections=["medications"],
                checklist_fields=[],
                medication_names=["lithium"],
            ),
        )],
        caution_criteria=[CautionCriterion(
            id="C1",
            description="Controlled hypertension",
            source_excerpt="test",
            detection=DetectionSpec(
                keywords=["hypertension", "blood pressure"],
                sections=["medical"],
                checklist_fields=["high blood pressure"],
                medication_names=[],
            ),
        )],
        medication_classes_of_concern=[],
        program_demands=[ProgramDemand(id="PD1", demand="48-hour fast", interacts_with=["medical"])],
        positive_indicators=[],
        ground_rules=[GroundRule(rule="Never advise medication changes.")],
    )


@pytest.fixture
def sample_record():
    return ApplicantRecord(
        applicant_id="test-pipeline-001",
        display_name="Pipeline Test",
        created_at="2026-07-01T00:00:00",
        raw_form_path="test.md",
        identity=Identity(name="Pipeline Test"),
        sections={
            "medications": ParsedSection(
                name="Medications",
                taxonomy_key="medications",
                medications=[MedicationEntry(
                    medication="lithium carbonate",
                    dosage="900mg daily",
                    indication="bipolar II",
                    since="2020",
                )],
            ),
            "medical_history": ParsedSection(
                name="Medical History",
                taxonomy_key="medical_history",
                qa_pairs=[QAPair(
                    question="Describe your general health",
                    answer="Good overall, nothing significant",
                    status=AnswerStatus.answered,
                )],
            ),
        },
        unmapped_content="",
    )


class TestPipelineResult:
    def test_result_structure(self):
        result = PipelineResult()
        assert result.status == "running"
        assert result.flags == []
        assert result.run_id
        assert result.started_at

    def test_to_run_record(self):
        result = PipelineResult()
        result.status = "complete"
        result.model_id = "qwen3:30b-a3b"
        record = result.to_run_record()
        assert record["run_id"] == result.run_id
        assert record["status"] == "complete"
        assert record["model_id"] == "qwen3:30b-a3b"


class TestRulesEngineInPipeline:
    def test_rules_run_without_model(self, sample_record, minimal_profile):
        """Rules engine produces flags even when model is unavailable."""
        mock_provider = MagicMock()
        mock_provider._config = MagicMock()
        mock_provider._config.model = "test-model"
        mock_provider.analyze.side_effect = RuntimeError("Model unavailable")

        result = run_pipeline(sample_record, minimal_profile, mock_provider)

        # Pipeline should be incomplete (model failed) but rule flags should exist
        assert result.status == "incomplete"
        rule_flags = [f for f in result.flags if f.get("source") == "rule"]
        assert len(rule_flags) >= 1
        assert any("lithium" in f.get("title", "").lower() for f in rule_flags)

    def test_rules_engine_catches_lithium(self, sample_record, minimal_profile):
        """The deterministic rules engine catches medication-table hard criteria."""
        from pisa.rules.engine import run_rules_engine
        flags = run_rules_engine(sample_record, minimal_profile)
        assert len(flags) >= 1
        assert flags[0]["level"] == "red"
        assert flags[0]["source"] == "rule"


class TestLoudFailure:
    def test_model_crash_produces_incomplete(self, sample_record, minimal_profile):
        """A model crash mid-pipeline must produce status=incomplete with notes."""
        mock_provider = MagicMock()
        mock_provider._config = MagicMock()
        mock_provider._config.model = "test-model"
        mock_provider.analyze.side_effect = RuntimeError("Connection refused")

        result = run_pipeline(sample_record, minimal_profile, mock_provider)
        assert result.status == "incomplete"
        assert "Fatal error" in result.notes or "Connection refused" in result.notes

    def test_incomplete_preserves_rule_flags(self, sample_record, minimal_profile):
        """Even on model failure, rule-engine flags survive in the result."""
        mock_provider = MagicMock()
        mock_provider._config = MagicMock()
        mock_provider._config.model = "test-model"
        mock_provider.analyze.side_effect = RuntimeError("timeout")

        result = run_pipeline(sample_record, minimal_profile, mock_provider)
        rule_flags = [f for f in result.flags if f.get("source") == "rule"]
        assert len(rule_flags) >= 1


class TestDeferredBlankFlags:
    def test_deferred_in_high_stakes_section_emits_flag(self, minimal_profile):
        """Deferred answers in sections with criteria emit deterministic yellow flags."""
        record = ApplicantRecord(
            applicant_id="test-deferred-001",
            display_name="Deferred Test",
            created_at="2026-07-01T00:00:00",
            raw_form_path="test.md",
            identity=Identity(name="Deferred Test"),
            sections={
                "medical_history": ParsedSection(
                    name="Medical History",
                    taxonomy_key="medical_history",
                    qa_pairs=[
                        QAPair(question="Do you have trauma?", answer="Let's discuss in person", status=AnswerStatus.deferred),
                        QAPair(question="General health?", answer="Good", status=AnswerStatus.answered),
                    ],
                ),
            },
            unmapped_content="",
        )
        mock_provider = MagicMock()
        mock_provider._config = MagicMock()
        mock_provider._config.model = "test-model"
        mock_provider.analyze.side_effect = RuntimeError("skip model")

        result = run_pipeline(record, minimal_profile, mock_provider)
        deferred_flags = [f for f in result.flags if f.get("category") == "deferred_blank"]
        assert len(deferred_flags) >= 1
        assert deferred_flags[0]["level"] == "yellow"
        assert "deferred" in deferred_flags[0]["title"].lower()

    def test_blank_in_high_stakes_section_emits_flag(self, minimal_profile):
        """Blank answers in sections with criteria emit deterministic yellow flags."""
        record = ApplicantRecord(
            applicant_id="test-blank-001",
            display_name="Blank Test",
            created_at="2026-07-01T00:00:00",
            raw_form_path="test.md",
            identity=Identity(name="Blank Test"),
            sections={
                "medical_history": ParsedSection(
                    name="Medical History",
                    taxonomy_key="medical_history",
                    qa_pairs=[
                        QAPair(question="Any conditions?", answer="", status=AnswerStatus.blank),
                    ],
                ),
            },
            unmapped_content="",
        )
        mock_provider = MagicMock()
        mock_provider._config = MagicMock()
        mock_provider._config.model = "test-model"
        mock_provider.analyze.side_effect = RuntimeError("skip model")

        result = run_pipeline(record, minimal_profile, mock_provider)
        blank_flags = [f for f in result.flags if f.get("category") == "deferred_blank"]
        assert len(blank_flags) >= 1
        assert "blank" in blank_flags[0]["title"].lower()

    def test_no_flag_for_section_without_criteria(self, minimal_profile):
        """Sections with no relevant criteria don't get deferred/blank flags."""
        record = ApplicantRecord(
            applicant_id="test-nocrit-001",
            display_name="No Crit Test",
            created_at="2026-07-01T00:00:00",
            raw_form_path="test.md",
            identity=Identity(name="No Crit Test"),
            sections={
                "languages": ParsedSection(
                    name="Languages",
                    taxonomy_key="languages",
                    qa_pairs=[
                        QAPair(question="What languages?", answer="", status=AnswerStatus.blank),
                    ],
                ),
            },
            unmapped_content="",
        )
        mock_provider = MagicMock()
        mock_provider._config = MagicMock()
        mock_provider._config.model = "test-model"
        mock_provider.analyze.side_effect = RuntimeError("skip model")

        result = run_pipeline(record, minimal_profile, mock_provider)
        deferred_flags = [f for f in result.flags if f.get("category") == "deferred_blank"]
        assert len(deferred_flags) == 0


class TestProgressCallback:
    def test_callback_interface(self, sample_record, minimal_profile):
        """Progress callbacks fire correctly during a pipeline run."""
        cb = MagicMock(spec=ProgressCallback)
        mock_provider = MagicMock()
        mock_provider._config = MagicMock()
        mock_provider._config.model = "test-model"
        mock_provider.analyze.side_effect = RuntimeError("fail")

        run_pipeline(sample_record, minimal_profile, mock_provider, progress=cb)
        # Small sections get batched — on_batch_start fires instead of on_section_start
        assert cb.on_batch_start.called or cb.on_section_start.called
        assert cb.on_failure.called

    def test_batch_callback_fires_for_small_sections(self, sample_record, minimal_profile):
        """on_batch_start fires when sections are small enough to batch."""
        cb = MagicMock(spec=ProgressCallback)
        mock_provider = MagicMock()
        mock_provider._config = MagicMock()
        mock_provider._config.model = "test-model"
        mock_provider.analyze.return_value = {
            "section_summary": "[medications] ok [medical_history] ok",
            "flags": [],
        }

        run_pipeline(sample_record, minimal_profile, mock_provider, progress=cb)
        assert cb.on_batch_start.called
        batch_keys = cb.on_batch_start.call_args[0][0]
        assert "medications" in batch_keys
        assert "medical_history" in batch_keys


class TestMergeDedupe:
    def test_no_duplicate_titles_after_merge(self):
        """No two open flags should share an identical title after merge."""
        from pisa.pipeline.runner import _merge_and_dedupe
        model_flags = [
            {"flag_id": "a", "title": "Cannabis use frequency exceeds program requirements",
             "level": "yellow", "category": "substance", "severity": 5,
             "evidence": [{"section": "substance_use", "quote": "5x", "criterion_ref": "D2"}],
             "recommended_followup": ["Ask about reduction"], "status": "open", "history": []},
            {"flag_id": "b", "title": "Cannabis use frequency exceeds program requirements",
             "level": "yellow", "category": "substance", "severity": 4,
             "evidence": [{"section": "substance_use", "quote": "2-3x", "criterion_ref": "D2"}],
             "recommended_followup": ["Ask about timeline"], "status": "open", "history": []},
        ]
        result = _merge_and_dedupe([], model_flags, [])
        titles = [f["title"] for f in result]
        assert len(titles) == len(set(titles)), f"Duplicate titles found: {titles}"

    def test_criterion_category_dedup(self):
        """Flags with same category + overlapping criterion_ref merge."""
        from pisa.pipeline.runner import _merge_and_dedupe
        model_flags = [
            {"flag_id": "a", "title": "Cannabis conflicts with D5 abstinence",
             "level": "yellow", "category": "substance", "severity": 5,
             "evidence": [{"section": "substance_use", "quote": "q1", "criterion_ref": "D5"}],
             "recommended_followup": ["q about cannabis"], "status": "open", "history": []},
            {"flag_id": "b", "title": "Cannabis frequency exceeds program requirements",
             "level": "yellow", "category": "substance", "severity": 4,
             "evidence": [{"section": "substance_use", "quote": "q2", "criterion_ref": "D5"}],
             "recommended_followup": ["q about frequency"], "status": "open", "history": []},
        ]
        result = _merge_and_dedupe([], model_flags, [])
        assert len(result) == 1

    def test_followup_union_only_with_shared_criteria(self):
        """Follow-ups only merge when criterion refs overlap (§8.4)."""
        from pisa.pipeline.runner import _merge_and_dedupe
        model_flags = [
            {"flag_id": "a", "title": "Substance concern A",
             "level": "yellow", "category": "substance", "severity": 5,
             "evidence": [{"section": "s", "quote": "q1", "criterion_ref": "D1"}],
             "recommended_followup": ["alcohol question"], "status": "open", "history": []},
            {"flag_id": "b", "title": "Substance concern B",
             "level": "yellow", "category": "substance", "severity": 4,
             "evidence": [{"section": "s", "quote": "q2", "criterion_ref": "D2"}],
             "recommended_followup": ["cannabis question"], "status": "open", "history": []},
        ]
        # These should NOT merge (different criterion refs, titles don't overlap 70%)
        result = _merge_and_dedupe([], model_flags, [])
        assert len(result) == 2


# -- Flag integrity: consolidation must never soften a deterministic flag --


def _rule_flag(criterion, level="red", severity=8, hard=False, **kw):
    """Minimal rule flag. Evidence quotes use the 'Medication:' form the
    subsumption check keys on."""
    flag = {
        "flag_id": criterion,
        "source": "rule",
        "title": f"[{criterion}] {kw.pop('title', 'Concern')}",
        "level": level,
        "severity": severity,
        "category": "medication",
        "hard_flag": hard,
        "evidence": [{
            "section": "medications",
            "quote": kw.pop("quote", "Medication: lithium 600 mg (for: mood)"),
            "criterion_ref": criterion,
        }],
        "rationale": "r",
        "recommended_followup": [],
        "resolution_criteria": "",
        "suggested_lookup": [],
        "status": "open",
        "history": [],
    }
    flag.update(kw)
    return flag


def _model_flag(criterion, level="yellow", severity=5, hard=False, **kw):
    flag = {
        "flag_id": f"m-{criterion}",
        "source": "model",
        "title": f"[{criterion}] {kw.pop('title', 'Model observation')}",
        "level": level,
        "severity": severity,
        "category": "medication",
        "hard_flag": hard,
        "evidence": [{
            "section": "medications",
            "quote": kw.pop("quote", "narrative mention"),
            "criterion_ref": criterion,
        }],
        "rationale": "r",
        "recommended_followup": [],
        "resolution_criteria": "",
        "suggested_lookup": [],
        "status": "open",
        "history": [],
    }
    flag.update(kw)
    return flag


class TestRuleFlagSurvival:
    def test_subsumption_keeps_both_criteria_accounted_for(self):
        """Subsuming a rule flag must fold it in, not drop it silently."""
        from pisa.pipeline.runner import _merge_and_dedupe
        strict = _rule_flag("R-3", level="red", severity=9,
                            recommended_followup=["Confirm prescriber plan"])
        mild = _rule_flag("R-4", level="yellow", severity=4,
                          recommended_followup=["Written recommendation"],
                          resolution_criteria="Documented consultation")
        result = _merge_and_dedupe([strict, mild], [], [])
        survivor = next(f for f in result if "R-3" in f["title"])
        # The dropped criterion's disposition is preserved somewhere the
        # reviewer can see it.
        assert "Written recommendation" in survivor["recommended_followup"]
        subsumed = [h for h in survivor["history"] if h["action"] == "subsumed"]
        assert subsumed and subsumed[0]["subsumed_criterion"] == "R-4"

    def test_hard_rule_flag_is_never_subsumed(self):
        """A hard exclusion outranks a higher-severity resolvable flag."""
        from pisa.pipeline.runner import _merge_and_dedupe
        hard = _rule_flag("R-A1", level="red", severity=6, hard=True)
        soft = _rule_flag("R-9", level="red", severity=10, hard=False)
        result = _merge_and_dedupe([hard, soft], [], [])
        assert any(f.get("hard_flag") and "R-A1" in f["title"] for f in result)

    def test_proposed_merge_cannot_delete_a_rule_flag(self):
        """Synthesis output must not consolidate away a deterministic flag."""
        from pisa.pipeline.runner import _merge_and_dedupe
        rule = _rule_flag("R-A1", hard=True, basis="regulatory",
                          citation="OAR 333-333-5050(3)(a)")
        model = _model_flag("R-A1", level="red", severity=9,
                            resolution_criteria="Prescriber letter confirming taper")
        proposed = [{
            "primary_title": "[R-A1] Model observation",
            "merge_titles": ["[R-A1] Concern"],
            "reason": "same criterion",
        }]
        result = _merge_and_dedupe([rule], [model], proposed)
        survivors = [f for f in result if "R-A1" in f["title"]]
        assert any(f.get("source") == "rule" for f in survivors)
        surviving_rule = next(f for f in survivors if f.get("source") == "rule")
        assert surviving_rule["hard_flag"] is True
        assert surviving_rule["citation"] == "OAR 333-333-5050(3)(a)"


class TestHardFlagSemantics:
    def test_hard_flag_survives_merge(self):
        """Merging a soft flag into a hard one keeps the hard disposition."""
        from pisa.pipeline.runner import _merge_into
        hard = _rule_flag("R-A1", hard=True)
        soft = _model_flag("R-A1", hard=False)
        _merge_into(hard, soft)
        assert hard["hard_flag"] is True

    def test_hard_flag_propagates_into_soft_target(self):
        from pisa.pipeline.runner import _merge_into
        soft = _model_flag("R-A3", hard=False)
        hard = _model_flag("R-A3", hard=True)
        _merge_into(soft, hard)
        assert soft["hard_flag"] is True

    def test_hard_flag_never_gains_a_resolution_pathway(self):
        """An exclusion has no resolution by definition; merging must not add one."""
        from pisa.pipeline.runner import _merge_into
        hard = _rule_flag("R-A1", hard=True)
        assert hard["resolution_criteria"] == ""
        resolvable = _model_flag("R-A1", resolution_criteria="Prescriber letter")
        _merge_into(hard, resolvable)
        assert hard["resolution_criteria"] == ""

    def test_resolvable_flag_still_accepts_a_pathway(self):
        from pisa.pipeline.runner import _merge_into
        soft = _rule_flag("R-3", hard=False)
        source = _model_flag("R-3", resolution_criteria="Documented consultation")
        _merge_into(soft, source)
        assert soft["resolution_criteria"] == "Documented consultation"

    def test_merge_does_not_inherit_basis_or_citation(self):
        """basis/citation describe the target's own criterion."""
        from pisa.pipeline.runner import _merge_into
        target = _rule_flag("R-A1", basis="regulatory", citation="OAR 333-333")
        source = _model_flag("H-3", basis="house", citation="H-3")
        _merge_into(target, source)
        assert target["basis"] == "regulatory"
        assert target["citation"] == "OAR 333-333"

    def test_auto_merge_primary_is_the_hard_flag(self):
        """A hard flag wins the primary slot over a higher-severity soft flag."""
        from pisa.pipeline.runner import _auto_merge_by_criterion
        soft = _model_flag("R-A3", level="yellow", severity=8, hard=False,
                           basis="house", citation="H-3")
        hard = _model_flag("R-A3", level="red", severity=7, hard=True,
                           basis="regulatory", citation="OAR 333-333")
        result = _auto_merge_by_criterion([soft, hard])
        assert len(result) == 1
        assert result[0]["hard_flag"] is True
        assert result[0]["citation"] == "OAR 333-333"


class TestCriterionRefNormalization:
    def test_bracketed_and_bare_refs_are_the_same_criterion(self):
        """'[R-3]' and 'R-3' must not be treated as different criteria."""
        from pisa.pipeline.runner import _merge_and_dedupe
        rule = _rule_flag("R-3", recommended_followup=["Confirm prescriber plan"])
        model = _model_flag("R-3", recommended_followup=["Ask about timeline"])
        model["evidence"][0]["criterion_ref"] = "[R-3]"
        result = _merge_and_dedupe([rule], [model], [])
        assert len(result) == 1
        # The follow-up union fired, so both stages agreed on the ref.
        assert "Ask about timeline" in result[0]["recommended_followup"]
