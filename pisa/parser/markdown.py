"""Markdown form parser.

Parses fixture-format markdown intake forms into ApplicantRecord structures.
Handles: identity tables, ## section headings, **Question?** answers,
medication tables, condition checklists, consumption tables, and
deferred/blank answer detection.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from pisa.parser.models import (
    AnswerStatus,
    ApplicantRecord,
    ConditionChecklistEntry,
    ConsumptionEntry,
    Identity,
    MedicationEntry,
    ParsedSection,
    QAPair,
)
from pisa.parser.section_map import load_section_map, resolve_section_key

SECTION_HEADING_RE = re.compile(r"^\*\*([^*]+)\*\*\s*$")

DEFERRED_PATTERNS = [
    r"let'?s discuss",
    r"let'?s talk",
    r"prefer to (talk|discuss)",
    r"rather (discuss|talk|cover).*(in person|live|at the intake|at intake|one-on-one)",
    r"in person,?\s*please",
    r"at the intake",
    r"one-on-one",
]
DEFERRED_RE = re.compile("|".join(DEFERRED_PATTERNS), re.IGNORECASE)


def detect_answer_status(question: str, answer: str) -> AnswerStatus:
    """Determine if an answer is answered, blank, or deferred.

    A deferred answer is one where the primary content is a request to discuss
    later, not a substantive answer that mentions discussing something in person
    as part of a longer reply.
    """
    stripped = answer.strip()
    if not stripped:
        return AnswerStatus.blank
    if DEFERRED_RE.search(stripped):
        # Only mark as deferred if the answer is short (primarily a deferral)
        # Long answers that happen to mention "let's discuss" are substantive
        if len(stripped) < 120:
            return AnswerStatus.deferred
    return AnswerStatus.answered


def parse_identity_table(lines: list[str]) -> tuple[Identity, int]:
    """Parse the identity table at the top of the form. Returns identity and line count consumed."""
    identity = Identity()
    consumed = 0

    table_lines = []
    in_table = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("|") and not in_table:
            in_table = True
            table_lines.append(stripped)
            consumed = i + 1
        elif in_table and stripped.startswith("|"):
            table_lines.append(stripped)
            consumed = i + 1
        elif in_table and (stripped.startswith("|---") or stripped == ""):
            consumed = i + 1
            if stripped == "":
                break
        elif in_table:
            break

    text = "\n".join(table_lines)

    name_match = re.search(r"Name:\s*([^|]+)", text)
    if name_match:
        identity.name = name_match.group(1).strip()

    date_match = re.search(r"Date:\s*([^|]+)", text)
    if date_match:
        identity.date = date_match.group(1).strip()

    age_match = re.search(r"\*?\*?Age:?\*?\*?\s*(\d+)", text)
    if age_match:
        identity.age = age_match.group(1).strip()

    pron_match = re.search(r"Pronouns[^:]*:\*?\*?\s*([^|]+)", text)
    if pron_match:
        identity.pronouns = pron_match.group(1).strip()

    bd_match = re.search(r"Birthdate:?\*?\*?\s*([^|]+)", text)
    if bd_match:
        identity.birthdate = bd_match.group(1).strip()

    occ_match = re.search(r"Occupation:?\*?\*?\s*([^|]+)", text)
    if occ_match:
        identity.occupation = occ_match.group(1).strip()

    email_match = re.search(r"Email:?\*?\*?\s*([^|]+)", text)
    if email_match:
        identity.email = email_match.group(1).strip()

    addr_match = re.search(r"Address:?\*?\*?\s*([^|]+)", text)
    if addr_match:
        identity.address = addr_match.group(1).strip()

    phone_match = re.search(r"Phone:?\*?\*?\s*([^|]+)", text)
    if phone_match:
        identity.phone = phone_match.group(1).strip()

    return identity, consumed


def parse_medication_table(lines: list[str]) -> list[MedicationEntry]:
    """Parse a markdown table of medications."""
    meds = []
    for line in lines:
        if _is_separator_line(line) or not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 1:
            name = cells[0].strip()
            if not name or name.lower() in ("medication", "none", "n/a"):
                continue
            meds.append(MedicationEntry(
                medication=name,
                dosage=cells[1].strip() if len(cells) > 1 else "",
                indication=cells[2].strip() if len(cells) > 2 else "",
                since=cells[3].strip() if len(cells) > 3 else "",
            ))
    return meds


def parse_condition_checklist(lines: list[str]) -> list[ConditionChecklistEntry]:
    """Parse a condition checklist table (condition | yes/blank pairs)."""
    entries = []
    for line in lines:
        if _is_separator_line(line) or not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        # Cells come in pairs: condition name, value
        i = 0
        while i < len(cells) - 1:
            condition = cells[i].strip().strip("*")
            value = cells[i + 1].strip().lower()
            if condition and condition not in ("", "---"):
                entries.append(ConditionChecklistEntry(
                    condition=condition,
                    checked=value in ("yes", "x", "✓", "✔"),
                ))
            i += 2
    return entries


def parse_consumption_table(lines: list[str]) -> list[ConsumptionEntry]:
    """Parse a consumption/amount table."""
    entries = []
    for line in lines:
        if _is_separator_line(line) or not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2:
            substance = cells[0].strip()
            amount = cells[1].strip()
            if substance and substance.lower() not in ("amount", "substance", ""):
                entries.append(ConsumptionEntry(substance=substance, amount=amount))
    return entries


def _is_table_line(line: str) -> bool:
    return line.strip().startswith("|")


def _is_separator_line(line: str) -> bool:
    return bool(re.match(r"^\|[-|:\s]+\|$", line.strip()))


def _collect_table_block(lines: list[str], start: int) -> tuple[list[str], int]:
    """Collect consecutive table lines starting at `start`. Returns lines and end index."""
    table_lines = []
    i = start
    while i < len(lines) and _is_table_line(lines[i]):
        table_lines.append(lines[i])
        i += 1
    return table_lines, i


def _detect_table_type(table_lines: list[str], preceding_question: str) -> str:
    """Heuristic to determine what kind of table this is."""
    text = "\n".join(table_lines).lower()
    pq = preceding_question.lower()

    if "medication" in pq or "prescription" in pq:
        return "medication"
    if "condition checklist" in pq or "checklist" in pq or "following conditions" in pq:
        return "condition_checklist"
    if "amount" in text and ("cigarette" in text or "alcohol" in text or "cannabis" in text or "caffeine" in text):
        return "consumption"
    if "dosage" in text or "for what" in text or "since when" in text:
        return "medication"

    # Detect Q/A-style regulatory screening tables (Question | Answer or Screen item | Answer)
    header_line = next((l for l in table_lines if not _is_separator_line(l)), "")
    header_cells = [c.strip().lower() for c in header_line.strip().strip("|").split("|")]
    if len(header_cells) == 2 and any(
        h in header_cells[0] for h in ("question", "screen item")
    ):
        return "qa_table"

    # Check for condition-style: paired cells with yes/blank
    first_data = [l for l in table_lines if not _is_separator_line(l)]
    if first_data:
        cells = [c.strip() for c in first_data[0].strip().strip("|").split("|")]
        if len(cells) >= 2:
            non_empty = [c for c in cells if c and c.lower() not in ("yes", "x", "")]
            empty_or_yes = [c for c in cells if c.lower() in ("yes", "x", "✓", "") or not c]
            if len(empty_or_yes) >= len(cells) // 2:
                return "condition_checklist"

    return "generic"


def parse_qa_table(lines: list[str]) -> list[QAPair]:
    """Parse a two-column Q/A table (Question | Answer) into QAPair list."""
    pairs = []
    for line in lines:
        if _is_separator_line(line) or not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        question = cells[0].strip().strip("*")
        answer = cells[1].strip()
        # Skip the header row
        if question.lower() in ("question", "screen item", ""):
            continue
        status = detect_answer_status(question, answer)
        pairs.append(QAPair(question=question, answer=answer, status=status))
    return pairs


def parse_markdown_form(text: str, section_map_override: Optional[Path] = None) -> ApplicantRecord:
    """Parse a markdown intake form into an ApplicantRecord."""
    mapping = load_section_map(section_map_override)
    lines = text.split("\n")

    # Skip the title (# heading)
    start = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("# "):
            start = i + 1
            break

    # Parse identity table
    identity, id_consumed = parse_identity_table(lines[start:])
    start += id_consumed

    # Now parse sections
    sections: dict[str, ParsedSection] = {}
    unmapped_parts: list[str] = []
    current_section_heading: Optional[str] = None
    current_section_lines: list[str] = []

    def flush_section():
        nonlocal current_section_heading, current_section_lines
        if current_section_heading is None:
            return
        key = resolve_section_key(current_section_heading, mapping)
        if key is None:
            unmapped_parts.append(f"## {current_section_heading}\n" + "\n".join(current_section_lines))
        else:
            section = _parse_section_content(key, current_section_heading, current_section_lines, mapping)
            if key in sections:
                # Merge into existing section
                sections[key].qa_pairs.extend(section.qa_pairs)
                sections[key].medications.extend(section.medications)
                sections[key].condition_checklist.extend(section.condition_checklist)
                sections[key].consumption_table.extend(section.consumption_table)
                sections[key].raw_text += "\n" + section.raw_text
            else:
                sections[key] = section
        current_section_heading = None
        current_section_lines = []

    for i in range(start, len(lines)):
        line = lines[i]
        if line.strip().startswith("## "):
            flush_section()
            current_section_heading = line.strip().lstrip("#").strip()
            current_section_lines = []
        else:
            # Detect standalone bold lines that match a section key
            # (e.g., "**Medical History**" or "**SUBSTANCE USE**")
            # Exclude bold lines ending with ':' — those are sub-headings/labels
            bold_match = SECTION_HEADING_RE.match(line.strip())
            if bold_match:
                candidate = bold_match.group(1).strip()
                if not candidate.endswith(":") and resolve_section_key(candidate, mapping) is not None:
                    flush_section()
                    current_section_heading = candidate
                    current_section_lines = []
                    continue
            current_section_lines.append(line)

    flush_section()

    return ApplicantRecord(
        display_name=identity.name,
        identity=identity,
        sections=sections,
        unmapped_content="\n\n".join(unmapped_parts) if unmapped_parts else "",
    )


def _parse_section_content(
    taxonomy_key: str,
    heading: str,
    lines: list[str],
    mapping: dict[str, str],
) -> ParsedSection:
    """Parse the content lines of a section into structured data."""
    qa_pairs: list[QAPair] = []
    medications: list[MedicationEntry] = []
    condition_checklist: list[ConditionChecklistEntry] = []
    consumption_table: list[ConsumptionEntry] = []

    raw_text = "\n".join(lines)
    i = 0
    current_question: Optional[str] = None
    current_answer_lines: list[str] = []
    last_question_for_table: str = ""

    def flush_qa():
        nonlocal current_question, current_answer_lines
        if current_question is not None:
            answer = "\n".join(current_answer_lines).strip()
            status = detect_answer_status(current_question, answer)
            qa_pairs.append(QAPair(question=current_question, answer=answer, status=status))
        current_question = None
        current_answer_lines = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Detect bold question pattern: **Question text**
        q_match = re.match(r"^\*\*(.+?)\*\*\s*(.*)", stripped)

        if _is_table_line(stripped) and not _is_separator_line(stripped):
            # Collect full table block
            table_lines, end_i = _collect_table_block(lines, i)
            table_type = _detect_table_type(table_lines, last_question_for_table)

            if table_type == "medication":
                # Drop the preceding label if it was just a table header
                if current_question and not "\n".join(current_answer_lines).strip():
                    current_question = None
                    current_answer_lines = []
                else:
                    flush_qa()
                medications.extend(parse_medication_table(table_lines))
            elif table_type == "condition_checklist":
                if current_question and not "\n".join(current_answer_lines).strip():
                    current_question = None
                    current_answer_lines = []
                else:
                    flush_qa()
                condition_checklist.extend(parse_condition_checklist(table_lines))
            elif table_type == "consumption":
                if current_question and not "\n".join(current_answer_lines).strip():
                    current_question = None
                    current_answer_lines = []
                else:
                    flush_qa()
                consumption_table.extend(parse_consumption_table(table_lines))
            elif table_type == "qa_table":
                flush_qa()
                qa_pairs.extend(parse_qa_table(table_lines))
            else:
                # Keep as part of the current answer
                for tl in table_lines:
                    current_answer_lines.append(tl)
            i = end_i
            continue

        if _is_separator_line(stripped):
            i += 1
            continue

        if q_match:
            flush_qa()
            current_question = q_match.group(1).strip().rstrip(":")
            last_question_for_table = current_question
            inline_answer = q_match.group(2).strip()
            current_answer_lines = [inline_answer] if inline_answer else []
            i += 1
            continue

        # Non-question, non-table line: part of the current answer or a new question
        if current_question is not None:
            # Check if this line is a new question. Heuristics:
            # - Contains a '?' or ends with ':' (with optional trailing spaces)
            # - The whole line looks like a standalone question (not mid-answer text)
            # - Previous answer already has content (blank-line separated)
            line_has_question_mark = "?" in stripped
            line_ends_colon = stripped.rstrip().endswith(":")
            prev_has_content = bool("\n".join(current_answer_lines).strip())
            if prev_has_content and (line_has_question_mark or line_ends_colon):
                kv_match = re.match(r"^([^:?]+[?:])\s*(.*)", stripped)
                if kv_match:
                    remainder = kv_match.group(2).strip()
                    # The remainder is still part of the question if it's empty,
                    # a parenthetical, a trailing qualifier/instruction, or itself a question
                    remainder_is_qualifier = (
                        not remainder
                        or remainder.startswith("(")
                        or remainder.lower().startswith("if ")
                        or remainder.lower().startswith("please ")
                        or remainder.lower().startswith("have you ")
                        or remainder.endswith("?")
                        or remainder.endswith(":")
                    )
                    if remainder_is_qualifier:
                        flush_qa()
                        current_question = stripped.rstrip()
                        last_question_for_table = current_question
                        current_answer_lines = []
                        i += 1
                        continue
            current_answer_lines.append(stripped)
        elif stripped:
            # Standalone text without a bold question — treat as implicit Q&A
            # Check if it looks like "Key: Value" or "Key?" pattern
            kv_match = re.match(r"^([^:?]+[?:])\s*(.*)", stripped)
            if kv_match:
                flush_qa()
                answer_part = kv_match.group(2).strip()
                # If the remainder looks like more question text (contains ?,
                # ends with ? or :, or is a qualifier/instruction), treat
                # the entire line as the question
                remainder_is_question = (
                    not answer_part
                    or answer_part.endswith("?")
                    or answer_part.endswith(":")
                    or "?" in answer_part
                    or answer_part.lower().startswith("if ")
                    or answer_part.lower().startswith("please ")
                    or answer_part.lower().startswith("have you ")
                    or answer_part.startswith("(")
                )
                if remainder_is_question:
                    current_question = stripped.rstrip()
                    current_answer_lines = []
                else:
                    current_question = kv_match.group(1).rstrip(":").strip()
                    current_answer_lines = [answer_part] if answer_part else []
                last_question_for_table = current_question
            else:
                current_answer_lines.append(stripped)

        i += 1

    flush_qa()

    return ParsedSection(
        name=heading,
        taxonomy_key=taxonomy_key,
        qa_pairs=qa_pairs,
        medications=medications,
        condition_checklist=condition_checklist,
        consumption_table=consumption_table,
        raw_text=raw_text,
    )


def parse_file(path: Path, section_map_override: Optional[Path] = None) -> ApplicantRecord:
    """Parse a file from disk. Supports .md and .txt."""
    text = path.read_text(encoding="utf-8")
    record = parse_markdown_form(text, section_map_override)
    record.raw_form_path = str(path)
    if not record.display_name:
        record.display_name = path.stem
    return record
