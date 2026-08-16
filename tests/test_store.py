"""Tests for pisa.store.db — CRUD operations, cascading deletes, follow-up workflow."""

import json
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from pisa.store.db import (
    get_connection, init_db, save_applicant, list_applicants, get_applicant,
    purge_applicant, save_flags, get_flags, get_flag_summary,
    save_pipeline_run, get_pipeline_runs, update_review_state,
    save_followup, get_followups, update_flag_status, downgrade_flag,
)
from pisa.parser.models import ApplicantRecord, Identity, ParsedSection


@pytest.fixture
def db_conn(tmp_path):
    """Create a fresh in-memory-like SQLite DB for each test."""
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    init_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def sample_record():
    return ApplicantRecord(
        applicant_id="test-001",
        display_name="Test Person",
        created_at=datetime.now().isoformat(),
        raw_form_path="test.md",
        identity=Identity(name="Test Person", dob="1990-01-01"),
        sections={"medical": ParsedSection(name="Medical History", taxonomy_key="medical")},
        unmapped_content="",
    )


class TestApplicantCRUD:
    def test_save_and_list(self, db_conn, sample_record):
        save_applicant(db_conn, sample_record, dataset="test-ds")
        apps = list_applicants(db_conn)
        assert len(apps) == 1
        assert apps[0]["display_name"] == "Test Person"
        assert apps[0]["dataset"] == "test-ds"

    def test_get_applicant(self, db_conn, sample_record):
        save_applicant(db_conn, sample_record, dataset="test-ds")
        app = get_applicant(db_conn, "test-001")
        assert app is not None
        assert app["display_name"] == "Test Person"
        assert json.loads(app["sections_json"])

    def test_get_nonexistent(self, db_conn):
        assert get_applicant(db_conn, "nope") is None

    def test_list_by_dataset(self, db_conn, sample_record):
        save_applicant(db_conn, sample_record, dataset="ds-a")
        r2 = ApplicantRecord(
            applicant_id="test-002",
            display_name="Other",
            created_at=datetime.now().isoformat(),
            raw_form_path="",
            identity=Identity(),
            sections={},
            unmapped_content="",
        )
        save_applicant(db_conn, r2, dataset="ds-b")
        assert len(list_applicants(db_conn, dataset="ds-a")) == 1
        assert len(list_applicants(db_conn, dataset="ds-b")) == 1
        assert len(list_applicants(db_conn)) == 2

    def test_purge_cascades(self, db_conn, sample_record):
        save_applicant(db_conn, sample_record, dataset="x")
        flag = _make_flag("test-001")
        save_flags(db_conn, [flag])
        fu = _make_followup("test-001", [flag["flag_id"]])
        save_followup(db_conn, fu)

        assert len(get_flags(db_conn, "test-001")) == 1
        assert len(get_followups(db_conn, "test-001")) == 1

        purge_applicant(db_conn, "test-001")
        assert get_applicant(db_conn, "test-001") is None
        assert len(get_flags(db_conn, "test-001")) == 0
        assert len(get_followups(db_conn, "test-001")) == 0


class TestFlags:
    def test_save_and_get(self, db_conn, sample_record):
        save_applicant(db_conn, sample_record)
        flags = [_make_flag("test-001", level="red", severity=8),
                 _make_flag("test-001", level="yellow", severity=4)]
        save_flags(db_conn, flags)
        result = get_flags(db_conn, "test-001")
        assert len(result) == 2
        assert result[0]["level"] == "red"  # sorted by level then severity

    def test_basis_and_citation_round_trip(self, db_conn, sample_record):
        """The regulatory/house chip needs these to survive persistence."""
        save_applicant(db_conn, sample_record)
        save_flags(db_conn, [_make_flag("test-001", level="red",
                                        basis="regulatory",
                                        citation="OAR 333-333-5050(3)(a)")])
        got = get_flags(db_conn, "test-001")[0]
        assert got["basis"] == "regulatory"
        assert got["citation"] == "OAR 333-333-5050(3)(a)"

    def test_flag_without_basis_reads_back_empty(self, db_conn, sample_record):
        save_applicant(db_conn, sample_record)
        save_flags(db_conn, [_make_flag("test-001")])
        got = get_flags(db_conn, "test-001")[0]
        assert got["basis"] == ""
        assert got["citation"] == ""

    def test_flag_summary(self, db_conn, sample_record):
        save_applicant(db_conn, sample_record)
        flags = [
            _make_flag("test-001", level="red"),
            _make_flag("test-001", level="red"),
            _make_flag("test-001", level="yellow"),
            _make_flag("test-001", level="green"),
        ]
        save_flags(db_conn, flags)
        summary = get_flag_summary(db_conn, "test-001")
        assert summary == {"red": 2, "yellow": 1, "green": 1}

    def test_update_flag_status(self, db_conn, sample_record):
        save_applicant(db_conn, sample_record)
        flag = _make_flag("test-001")
        save_flags(db_conn, [flag])

        update_flag_status(db_conn, flag["flag_id"], "acknowledged", {"action": "ack", "by": "reviewer"})
        flags = get_flags(db_conn, "test-001")
        assert flags[0]["status"] == "acknowledged"
        assert len(flags[0]["history"]) == 1

    def test_downgrade_flag(self, db_conn, sample_record):
        save_applicant(db_conn, sample_record)
        flag = _make_flag("test-001", level="yellow")
        save_flags(db_conn, [flag])

        downgrade_flag(db_conn, flag["flag_id"], "green", "Prescriber letter received")
        flags = get_flags(db_conn, "test-001")
        assert flags[0]["level"] == "green"
        assert flags[0]["status"] == "open"
        assert flags[0]["history"][0]["action"] == "downgraded"
        assert flags[0]["history"][0]["from_level"] == "yellow"


class TestFollowups:
    def test_save_and_get(self, db_conn, sample_record):
        save_applicant(db_conn, sample_record)
        flag = _make_flag("test-001")
        save_flags(db_conn, [flag])

        fu = _make_followup("test-001", [flag["flag_id"]])
        save_followup(db_conn, fu)

        followups = get_followups(db_conn, "test-001")
        assert len(followups) == 1
        assert followups[0]["reviewer_note"] == "Please confirm prescriber awareness."
        assert flag["flag_id"] in followups[0]["linked_flag_ids"]

    def test_followup_resolve_workflow(self, db_conn, sample_record):
        save_applicant(db_conn, sample_record)
        flag = _make_flag("test-001", level="yellow")
        save_flags(db_conn, [flag])

        # Create follow-up with resolution
        fu = _make_followup("test-001", [flag["flag_id"]])
        fu["applicant_response"] = "Prescriber confirmed."
        fu["triggered_reeval"] = True
        save_followup(db_conn, fu)
        downgrade_flag(db_conn, flag["flag_id"], "green", "Resolved via follow-up")

        flags = get_flags(db_conn, "test-001")
        assert flags[0]["level"] == "green"
        assert flags[0]["status"] == "open"


class TestPipelineRuns:
    def test_save_and_get(self, db_conn, sample_record):
        save_applicant(db_conn, sample_record)
        run = {
            "run_id": str(uuid.uuid4()),
            "started_at": datetime.now().isoformat(),
            "trigger": "initial",
            "model_id": "qwen3:30b-a3b",
            "prompt_template_version": "1.0.0",
            "profile_hash": "abc123",
            "status": "complete",
            "progress": {"sections_done": 10, "sections_total": 10},
            "notes": "",
        }
        save_pipeline_run(db_conn, run, "test-001")
        runs = get_pipeline_runs(db_conn, "test-001")
        assert len(runs) == 1
        assert runs[0]["status"] == "complete"
        assert runs[0]["progress"]["sections_done"] == 10


class TestReviewState:
    def test_update(self, db_conn, sample_record):
        save_applicant(db_conn, sample_record)
        update_review_state(db_conn, "test-001", "in_review")
        app = get_applicant(db_conn, "test-001")
        assert app["review_state"] == "in_review"


def _make_flag(applicant_id: str, level: str = "yellow", severity: int = 5,
               basis: str = "", citation: str = "") -> dict:
    return {
        "flag_id": str(uuid.uuid4()),
        "applicant_id": applicant_id,
        "created_at": datetime.now().isoformat(),
        "source": "rule",
        "level": level,
        "severity": severity,
        "category": "medication",
        "title": f"Test flag ({level})",
        "evidence": [{"section": "meds", "quote": "test", "criterion_ref": "C1"}],
        "rationale": "Test rationale",
        "recommended_followup": ["Confirm with prescriber"],
        "resolution_criteria": "Written confirmation",
        "suggested_lookup": [],
        "hard_flag": level == "red",
        "basis": basis,
        "citation": citation,
        "status": "open",
        "history": [],
    }


def _make_followup(applicant_id: str, flag_ids: list) -> dict:
    return {
        "followup_id": str(uuid.uuid4()),
        "applicant_id": applicant_id,
        "linked_flag_ids": flag_ids,
        "reviewer_note": "Please confirm prescriber awareness.",
        "applicant_response": "",
        "created_at": datetime.now().isoformat(),
        "triggered_reeval": False,
    }


class TestSchemaMigration:
    def test_adds_basis_and_citation_to_an_existing_db(self, tmp_path):
        """A database created before basis/citation must migrate, not break."""
        import sqlite3
        from pisa.store.db import get_connection, init_db, save_flags, get_flags

        db = tmp_path / "old.db"
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        # The pre-migration flags table, without basis/citation.
        conn.executescript("""
            CREATE TABLE applicants (applicant_id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
                dataset TEXT DEFAULT '', created_at TEXT, raw_form_path TEXT, identity_json TEXT,
                sections_json TEXT, unmapped_content TEXT, review_state TEXT DEFAULT 'unreviewed');
            CREATE TABLE flags (flag_id TEXT PRIMARY KEY, applicant_id TEXT NOT NULL,
                created_at TEXT NOT NULL, source TEXT NOT NULL, level TEXT NOT NULL,
                severity INTEGER DEFAULT 1, category TEXT, title TEXT NOT NULL,
                evidence_json TEXT, rationale TEXT, recommended_followup_json TEXT,
                resolution_criteria TEXT, suggested_lookup_json TEXT, hard_flag INTEGER DEFAULT 0,
                status TEXT DEFAULT 'open', history_json TEXT DEFAULT '[]');
            INSERT INTO applicants (applicant_id, display_name) VALUES ('a1', 'Legacy');
            INSERT INTO flags (flag_id, applicant_id, created_at, source, level, title)
                VALUES ('f1', 'a1', '2026-01-01', 'rule', 'red', 'Legacy flag');
        """)
        conn.commit()
        conn.close()

        conn = get_connection(db)
        init_db(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(flags)")}
        assert {"basis", "citation"} <= cols

        # The pre-existing row survives with empty values, and new writes work.
        legacy = get_flags(conn, "a1")
        assert len(legacy) == 1
        assert legacy[0]["basis"] == ""
        save_flags(conn, [_make_flag("a1", level="red", basis="house", citation="H-2")])
        assert any(f["basis"] == "house" for f in get_flags(conn, "a1"))
        conn.close()
