"""Unit tests for the profile loader and conflict detection — Phase 2."""

from pathlib import Path

import pytest

from pisa.profile.loader import load_context_documents, compute_context_hash, detect_doc_type
from pisa.profile.models import ScreeningProfile
from pisa.profile.builder import detect_conflicts

DEMO_DATA = Path(__file__).parent.parent / "demo-data"
PSILOCYBIN_CONTEXT = DEMO_DATA / "psilocybin-group-retreat" / "context"
SUMMIT_CONTEXT = DEMO_DATA / "summit-series" / "context"


class TestContextDocLoader:
    def test_loads_three_docs_without_conflicting(self):
        docs = load_context_documents(PSILOCYBIN_CONTEXT)
        assert len(docs) == 3
        types = {d.doc_type for d in docs}
        assert "program_description" in types
        assert "screening_criteria" in types
        assert "reference_material" in types

    def test_loads_four_docs_with_conflicting(self):
        docs = load_context_documents(PSILOCYBIN_CONTEXT, include_conflicting=True)
        assert len(docs) == 4

    def test_doc_type_detection(self):
        assert detect_doc_type("**Document type:** program_description", "foo.md") == "program_description"
        assert detect_doc_type("**Document type:** screening_criteria", "bar.md") == "screening_criteria"
        assert detect_doc_type("no type here", "reference_material.md") == "reference_material"

    def test_hash_changes_with_content(self):
        docs1 = load_context_documents(PSILOCYBIN_CONTEXT)
        docs2 = load_context_documents(SUMMIT_CONTEXT)
        hash1 = compute_context_hash(docs1)
        hash2 = compute_context_hash(docs2)
        assert hash1 != hash2

    def test_hash_stable(self):
        docs = load_context_documents(PSILOCYBIN_CONTEXT)
        assert compute_context_hash(docs) == compute_context_hash(docs)


class TestConflictDetection:
    def test_psilocybin_conflicting_doc_produces_conflicts(self):
        docs = load_context_documents(PSILOCYBIN_CONTEXT, include_conflicting=True)
        profile = ScreeningProfile()
        conflicts = detect_conflicts(profile, docs)
        assert len(conflicts) >= 2

        # Must have a ground-rule conflict (medication changes)
        ground_rule_conflicts = [c for c in conflicts if c.is_ground_rule_conflict]
        assert len(ground_rule_conflicts) >= 1

        # Must have a criteria conflict (hypomania window)
        criteria_conflicts = [c for c in conflicts if not c.is_ground_rule_conflict]
        assert len(criteria_conflicts) >= 1

    def test_summit_conflicting_doc_produces_conflicts(self):
        docs = load_context_documents(SUMMIT_CONTEXT, include_conflicting=True)
        profile = ScreeningProfile()
        conflicts = detect_conflicts(profile, docs)
        assert len(conflicts) >= 2

        # C1 (hypertension) conflict
        c1_conflicts = [c for c in conflicts if "C1" in c.criteria_involved]
        assert len(c1_conflicts) >= 1

        # A3 (hypomania) conflict
        a3_conflicts = [c for c in conflicts if "A3" in c.criteria_involved]
        assert len(a3_conflicts) >= 1

    def test_no_conflicts_without_conflicting_doc(self):
        docs = load_context_documents(PSILOCYBIN_CONTEXT, include_conflicting=False)
        profile = ScreeningProfile()
        conflicts = detect_conflicts(profile, docs)
        assert len(conflicts) == 0

    def test_conflicts_have_conservative_reading(self):
        docs = load_context_documents(SUMMIT_CONTEXT, include_conflicting=True)
        profile = ScreeningProfile()
        conflicts = detect_conflicts(profile, docs)
        for c in conflicts:
            assert c.conservative_reading, f"Conflict {c.criteria_involved} missing conservative reading"
            assert c.source_docs, f"Conflict {c.criteria_involved} missing source docs"
