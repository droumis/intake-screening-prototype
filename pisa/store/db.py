"""SQLite store for applicant records, flags, and pipeline runs."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from pisa.config import load_config
from pisa.parser.models import ApplicantRecord


def get_db_path() -> Path:
    config = load_config()
    return Path(config.app.db_path)


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
""")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS applicants (
            applicant_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            dataset TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            raw_form_path TEXT,
            identity_json TEXT,
            sections_json TEXT,
            unmapped_content TEXT DEFAULT '',
            review_state TEXT DEFAULT 'unreviewed',
            review_history_json TEXT DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS flags (
            flag_id TEXT PRIMARY KEY,
            applicant_id TEXT NOT NULL REFERENCES applicants(applicant_id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            source TEXT NOT NULL,
            level TEXT NOT NULL,
            severity INTEGER DEFAULT 1,
            category TEXT,
            title TEXT NOT NULL,
            evidence_json TEXT,
            rationale TEXT,
            recommended_followup_json TEXT,
            resolution_criteria TEXT,
            suggested_lookup_json TEXT,
            hard_flag INTEGER DEFAULT 0,
            basis TEXT DEFAULT '',
            citation TEXT DEFAULT '',
            status TEXT DEFAULT 'open',
            history_json TEXT DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS followups (
            followup_id TEXT PRIMARY KEY,
            applicant_id TEXT NOT NULL REFERENCES applicants(applicant_id) ON DELETE CASCADE,
            linked_flag_ids_json TEXT DEFAULT '[]',
            reviewer_note TEXT,
            applicant_response TEXT,
            created_at TEXT NOT NULL,
            triggered_reeval INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS pipeline_runs (
            run_id TEXT PRIMARY KEY,
            applicant_id TEXT NOT NULL REFERENCES applicants(applicant_id) ON DELETE CASCADE,
            started_at TEXT NOT NULL,
            completed_at TEXT DEFAULT '',
            duration_seconds REAL DEFAULT 0,
            trigger TEXT DEFAULT 'initial',
            model_id TEXT,
            prompt_template_version TEXT,
            profile_hash TEXT,
            status TEXT DEFAULT 'queued',
            progress_json TEXT DEFAULT '{}',
            notes TEXT DEFAULT ''
        );
    """)
    # Migrate: add columns if missing (for existing DBs)
    try:
        conn.execute("ALTER TABLE pipeline_runs ADD COLUMN completed_at TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE pipeline_runs ADD COLUMN duration_seconds REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE applicants ADD COLUMN review_history_json TEXT DEFAULT '[]'")
    except sqlite3.OperationalError:
        pass
    # basis/citation were carried through the pipeline but dropped on write, so
    # the regulatory-vs-house chip could never render for a flag read back from
    # the database. Rows written before this migration keep empty values; they
    # repopulate on the next screening run.
    try:
        conn.execute("ALTER TABLE flags ADD COLUMN basis TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE flags ADD COLUMN citation TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    conn.commit()


def save_applicant(conn: sqlite3.Connection, record: ApplicantRecord, dataset: str = "") -> None:
    """Insert or replace an applicant record."""
    sections_data = {
        key: section.model_dump() for key, section in record.sections.items()
    }
    conn.execute(
        """INSERT OR REPLACE INTO applicants
           (applicant_id, display_name, dataset, created_at, raw_form_path,
            identity_json, sections_json, unmapped_content, review_state)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'unreviewed')""",
        (
            record.applicant_id,
            record.display_name,
            dataset,
            record.created_at,
            record.raw_form_path,
            record.identity.model_dump_json(),
            json.dumps(sections_data),
            record.unmapped_content,
        ),
    )
    conn.commit()


def list_applicants(conn: sqlite3.Connection, dataset: Optional[str] = None) -> list[dict]:
    """List all applicants, optionally filtered by dataset."""
    if dataset:
        rows = conn.execute(
            "SELECT applicant_id, display_name, dataset, created_at, review_state FROM applicants WHERE dataset = ?",
            (dataset,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT applicant_id, display_name, dataset, created_at, review_state FROM applicants"
        ).fetchall()
    return [dict(r) for r in rows]


def get_applicant(conn: sqlite3.Connection, applicant_id: str) -> Optional[dict]:
    """Get a full applicant record by ID."""
    row = conn.execute(
        "SELECT * FROM applicants WHERE applicant_id = ?", (applicant_id,)
    ).fetchone()
    return dict(row) if row else None


def purge_applicant(conn: sqlite3.Connection, applicant_id: str) -> None:
    """Delete an applicant and all related data (cascading)."""
    conn.execute("DELETE FROM applicants WHERE applicant_id = ?", (applicant_id,))
    conn.commit()


def save_flags(conn: sqlite3.Connection, flags: list[dict]) -> None:
    """Insert or replace flags for an applicant."""
    for flag in flags:
        conn.execute(
            """INSERT OR REPLACE INTO flags
               (flag_id, applicant_id, created_at, source, level, severity, category,
                title, evidence_json, rationale, recommended_followup_json,
                resolution_criteria, suggested_lookup_json, hard_flag, basis, citation,
                status, history_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                flag["flag_id"],
                flag["applicant_id"],
                flag.get("created_at", ""),
                flag.get("source", ""),
                flag.get("level", ""),
                flag.get("severity", 1),
                flag.get("category", ""),
                flag.get("title", ""),
                json.dumps(flag.get("evidence", [])),
                flag.get("rationale", ""),
                json.dumps(flag.get("recommended_followup", [])),
                flag.get("resolution_criteria", ""),
                json.dumps(flag.get("suggested_lookup", [])),
                1 if flag.get("hard_flag") else 0,
                flag.get("basis", ""),
                flag.get("citation", ""),
                flag.get("status", "open"),
                json.dumps(flag.get("history", [])),
            ),
        )
    conn.commit()


def replace_flags(conn: sqlite3.Connection, applicant_id: str, flags: list[dict]) -> None:
    """Replace all flags for an applicant with the given set (atomic)."""
    conn.execute("DELETE FROM flags WHERE applicant_id = ?", (applicant_id,))
    save_flags(conn, flags)


def get_flags(conn: sqlite3.Connection, applicant_id: str) -> list[dict]:
    """Get all flags for an applicant, ordered by severity desc."""
    rows = conn.execute(
        """SELECT * FROM flags WHERE applicant_id = ?
           ORDER BY CASE level WHEN 'red' THEN 0 WHEN 'yellow' THEN 1 ELSE 2 END,
                    severity DESC""",
        (applicant_id,),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        # `or "[]"` covers NULL columns in rows written by an older schema: a
        # single bad row would otherwise raise and take out the whole flag list.
        d["evidence"] = json.loads(d.pop("evidence_json", None) or "[]")
        d["recommended_followup"] = json.loads(d.pop("recommended_followup_json", None) or "[]")
        d["suggested_lookup"] = json.loads(d.pop("suggested_lookup_json", None) or "[]")
        d["history"] = json.loads(d.pop("history_json", None) or "[]")
        d["hard_flag"] = bool(d["hard_flag"])
        d["basis"] = d.get("basis") or ""
        d["citation"] = d.get("citation") or ""
        result.append(d)
    return result


def get_flag_summary(conn: sqlite3.Connection, applicant_id: str) -> dict:
    """Get flag counts by level for an applicant."""
    rows = conn.execute(
        "SELECT level, COUNT(*) as cnt FROM flags WHERE applicant_id = ? GROUP BY level",
        (applicant_id,),
    ).fetchall()
    return {row["level"]: row["cnt"] for row in rows}


def get_flag_ack_summary(conn: sqlite3.Connection, applicant_id: str) -> dict:
    """Get acknowledged/total counts and manual flag counts for an applicant.

    Total includes ALL flags (system + reviewer). Ack'd means a human has reviewed it.

    Returns: {
        "ack": int,  # acknowledged or resolved count (all sources)
        "total": int,  # total flags (all sources)
        "manual_red": int, "manual_yellow": int, "manual_green": int
    }
    """
    rows = conn.execute(
        "SELECT source, status, level FROM flags WHERE applicant_id = ?",
        (applicant_id,),
    ).fetchall()
    ack = 0
    total = 0
    manual = {"red": 0, "yellow": 0, "green": 0}
    for row in rows:
        total += 1
        if row["status"] in ("acknowledged", "resolved"):
            ack += 1
        if row["source"] == "reviewer":
            manual[row["level"]] = manual.get(row["level"], 0) + 1
    return {
        "ack": ack,
        "total": total,
        "manual_red": manual.get("red", 0),
        "manual_yellow": manual.get("yellow", 0),
        "manual_green": manual.get("green", 0),
    }


def save_pipeline_run(conn: sqlite3.Connection, run: dict, applicant_id: str) -> None:
    """Save a pipeline run record."""
    conn.execute(
        """INSERT OR REPLACE INTO pipeline_runs
           (run_id, applicant_id, started_at, completed_at, duration_seconds,
            trigger, model_id, prompt_template_version, profile_hash, status,
            progress_json, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run["run_id"],
            applicant_id,
            run.get("started_at", ""),
            run.get("completed_at", ""),
            run.get("duration_seconds", 0),
            run.get("trigger", "initial"),
            run.get("model_id", ""),
            run.get("prompt_template_version", ""),
            run.get("profile_hash", ""),
            run.get("status", "queued"),
            json.dumps(run.get("progress", {})),
            run.get("notes", ""),
        ),
    )
    conn.commit()


def get_pipeline_runs(conn: sqlite3.Connection, applicant_id: str) -> list[dict]:
    """Get pipeline runs for an applicant, most recent first."""
    rows = conn.execute(
        "SELECT * FROM pipeline_runs WHERE applicant_id = ? ORDER BY started_at DESC",
        (applicant_id,),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["progress"] = json.loads(d.pop("progress_json", "{}"))
        result.append(d)
    return result


def get_last_screened(conn: sqlite3.Connection) -> dict[str, dict]:
    """Return {applicant_id: {last_run, duration_seconds, status}} for all applicants with runs."""
    rows = conn.execute(
        """SELECT applicant_id, started_at, duration_seconds, status
           FROM pipeline_runs
           WHERE (applicant_id, started_at) IN (
               SELECT applicant_id, MAX(started_at) FROM pipeline_runs GROUP BY applicant_id
           )"""
    ).fetchall()
    return {
        row["applicant_id"]: {
            "last_run": row["started_at"],
            "duration_seconds": row["duration_seconds"] or 0,
            "status": row["status"],
        }
        for row in rows
    }


def update_review_state(conn: sqlite3.Connection, applicant_id: str, state: str,
                        actor: str = "reviewer") -> None:
    """Update an applicant's review state and log the transition."""
    from datetime import datetime
    row = conn.execute(
        "SELECT review_state, review_history_json FROM applicants WHERE applicant_id = ?",
        (applicant_id,),
    ).fetchone()
    if not row:
        return
    old_state = row["review_state"]
    history = json.loads(row["review_history_json"] or "[]")
    history.append({
        "action": "state_change",
        "from_state": old_state,
        "to_state": state,
        "actor": actor,
        "timestamp": datetime.now().isoformat(),
    })
    conn.execute(
        "UPDATE applicants SET review_state = ?, review_history_json = ? WHERE applicant_id = ?",
        (state, json.dumps(history), applicant_id),
    )
    conn.commit()


def get_review_history(conn: sqlite3.Connection, applicant_id: str) -> list[dict]:
    """Get the review state change history for an applicant."""
    row = conn.execute(
        "SELECT review_history_json FROM applicants WHERE applicant_id = ?",
        (applicant_id,),
    ).fetchone()
    if not row:
        return []
    return json.loads(row["review_history_json"] or "[]")


def save_followup(conn: sqlite3.Connection, followup: dict) -> None:
    """Insert a follow-up record."""
    conn.execute(
        """INSERT INTO followups
           (followup_id, applicant_id, linked_flag_ids_json, reviewer_note,
            applicant_response, created_at, triggered_reeval)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            followup["followup_id"],
            followup["applicant_id"],
            json.dumps(followup.get("linked_flag_ids", [])),
            followup.get("reviewer_note", ""),
            followup.get("applicant_response", ""),
            followup.get("created_at", ""),
            1 if followup.get("triggered_reeval") else 0,
        ),
    )
    conn.commit()


def get_followups(conn: sqlite3.Connection, applicant_id: str) -> list[dict]:
    """Get follow-ups for an applicant, most recent first."""
    rows = conn.execute(
        "SELECT * FROM followups WHERE applicant_id = ? ORDER BY created_at DESC",
        (applicant_id,),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["linked_flag_ids"] = json.loads(d.pop("linked_flag_ids_json", "[]"))
        d["triggered_reeval"] = bool(d["triggered_reeval"])
        result.append(d)
    return result


def update_followup(conn: sqlite3.Connection, followup_id: str, reviewer_note: str, applicant_response: str) -> None:
    """Update a follow-up's note and response fields."""
    conn.execute(
        "UPDATE followups SET reviewer_note = ?, applicant_response = ? WHERE followup_id = ?",
        (reviewer_note, applicant_response, followup_id),
    )
    conn.commit()


def delete_followup(conn: sqlite3.Connection, followup_id: str) -> None:
    """Delete a follow-up record."""
    conn.execute("DELETE FROM followups WHERE followup_id = ?", (followup_id,))
    conn.commit()


def update_flag_status(conn: sqlite3.Connection, flag_id: str, status: str, history_entry: dict) -> None:
    """Update a flag's status and append to its history."""
    row = conn.execute("SELECT history_json FROM flags WHERE flag_id = ?", (flag_id,)).fetchone()
    if not row:
        return
    history = json.loads(row["history_json"] or "[]")
    history.append(history_entry)
    conn.execute(
        "UPDATE flags SET status = ?, history_json = ? WHERE flag_id = ?",
        (status, json.dumps(history), flag_id),
    )
    conn.commit()


def downgrade_flag(conn: sqlite3.Connection, flag_id: str, new_level: str, reason: str, actor: str = "reviewer") -> None:
    """Change a flag's level. Marks resolved only when moving to green."""
    from datetime import datetime
    row = conn.execute("SELECT history_json, level FROM flags WHERE flag_id = ?", (flag_id,)).fetchone()
    if not row:
        return
    old_level = row["level"]
    level_rank = {"green": 0, "yellow": 1, "red": 2}
    action = "downgraded" if level_rank.get(new_level, 0) < level_rank.get(old_level, 0) else "escalated"
    history = json.loads(row["history_json"] or "[]")
    history.append({
        "action": action,
        "from_level": old_level,
        "to_level": new_level,
        "reason": reason,
        "actor": actor,
        "timestamp": datetime.now().isoformat(),
    })
    conn.execute(
        "UPDATE flags SET level = ?, history_json = ? WHERE flag_id = ?",
        (new_level, json.dumps(history), flag_id),
    )
    conn.commit()


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    """Get a setting value by key."""
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Set a setting value."""
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value),
    )
    conn.commit()
