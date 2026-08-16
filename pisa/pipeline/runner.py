"""Analysis pipeline runner.

Executes the 6-step pipeline per applicant:
1. Rules engine (deterministic)
2. Per-section model analysis
3. Comprehensive whole-form pass (full form + all criteria in one call)
4. Synthesis pass (cross-section patterns, deduplication proposals)
5. Merge & dedupe
6. Persist
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from pisa.model.ollama import OllamaProvider, ModelResponseError
from pisa.parser.models import ApplicantRecord, AnswerStatus, ParsedSection
from pisa.parser.section_map import HIGH_STAKES_SECTIONS
from pisa.pipeline.schemas import (
    COMPREHENSIVE_REVIEW_SCHEMA,
    SECTION_ANALYSIS_SCHEMA,
    SYNTHESIS_SCHEMA,
)
from pisa.profile.models import ScreeningProfile
from pisa.rules.engine import run_rules_engine

logger = logging.getLogger(__name__)

SECTION_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "section_analysis_v1.1.0.md"
COMPREHENSIVE_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "comprehensive_review_v1.1.0.md"
SYNTHESIS_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "synthesis_v1.1.0.md"
PROMPT_VERSION = "1.1.0"


class PipelineResult:
    def __init__(self):
        self.run_id: str = str(uuid.uuid4())
        self.started_at: str = datetime.now().isoformat()
        self.completed_at: str = ""
        self.duration_seconds: float = 0.0
        self.status: str = "running"
        self.sections_done: int = 0
        self.sections_total: int = 0
        self.flags: list[dict] = []
        self.section_summaries: dict[str, str] = {}
        self.overall_notes: str = ""
        self.notes: str = ""
        self.model_id: str = ""
        self.profile_hash: str = ""
        self._start_time: float = __import__("time").time()

    def mark_complete(self):
        import time
        self.completed_at = datetime.now().isoformat()
        self.duration_seconds = round(time.time() - self._start_time, 1)

    def to_run_record(self) -> dict:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "trigger": "initial",
            "model_id": self.model_id,
            "prompt_template_version": PROMPT_VERSION,
            "profile_hash": self.profile_hash,
            "status": self.status,
            "progress": {
                "sections_done": self.sections_done,
                "sections_total": self.sections_total,
                "overall_notes": self.overall_notes,
            },
            "notes": self.notes,
        }


class ProgressCallback:
    """Interface for reporting pipeline progress to the UI."""
    def on_section_start(self, section_key: str, index: int, total: int): ...
    def on_section_done(self, section_key: str, index: int, total: int, flags: list[dict] | None = None): ...
    def on_batch_start(self, section_keys: list[str]): ...
    def on_synthesis_start(self): ...
    def on_complete(self, result: PipelineResult): ...
    def on_failure(self, result: PipelineResult, error: str): ...


class NullProgress(ProgressCallback):
    pass


def run_pipeline(
    record: ApplicantRecord,
    profile: ScreeningProfile,
    provider: OllamaProvider,
    progress: Optional[ProgressCallback] = None,
) -> PipelineResult:
    """Run the full analysis pipeline for one applicant."""
    if progress is None:
        progress = NullProgress()

    result = PipelineResult()
    result.model_id = provider._config.model
    result.profile_hash = profile.profile_hash

    # Determine which sections to analyze
    sections_to_analyze = [
        (key, section) for key, section in record.sections.items()
        if section.qa_pairs or section.medications or section.condition_checklist or section.consumption_table
    ]
    result.sections_total = len(sections_to_analyze)

    # Parse quality check: flag if suspiciously few sections/items were extracted
    quality_flags: list[dict] = []
    if len(sections_to_analyze) < 3:
        quality_flags.append({
            "flag_id": str(uuid.uuid4()),
            "applicant_id": record.applicant_id,
            "created_at": datetime.now().isoformat(),
            "source": "rule",
            "level": "yellow",
            "severity": 5,
            "category": "data_quality",
            "title": "Intake form parsing produced few sections",
            "evidence": [{"section": "", "quote": f"Only {len(sections_to_analyze)} sections with content found", "criterion_ref": ""}],
            "rationale": "The intake form may use an unusual format that the parser could not fully extract. Manual review of the original form is recommended.",
            "recommended_followup": ["Review the original intake form for content not captured by the parser"],
            "resolution_criteria": "Confirm all relevant information has been reviewed manually",
            "suggested_lookup": [],
            "hard_flag": False,
            "status": "open",
            "history": [],
        })

    # Step 1: Rules engine
    rule_flags = run_rules_engine(record, profile)
    for rf in rule_flags:
        rf["applicant_id"] = record.applicant_id
        rf.setdefault("status", "open")
        rf.setdefault("history", [])

    # Step 1b: Deterministic deferred/blank flags for high-stakes sections
    for section_key, section in sections_to_analyze:
        relevant_criteria = _get_relevant_criteria(section_key, profile)
        if not relevant_criteria and section_key not in HIGH_STAKES_SECTIONS:
            continue
        deferred_qs = []
        blank_qs = []
        for qa in section.qa_pairs:
            if qa.status == AnswerStatus.deferred:
                deferred_qs.append(qa.question)
            elif qa.status == AnswerStatus.blank:
                blank_qs.append(qa.question)
        if deferred_qs:
            rule_flags.append({
                "flag_id": str(uuid.uuid4()),
                "applicant_id": record.applicant_id,
                "created_at": datetime.now().isoformat(),
                "source": "rule",
                "level": "yellow",
                "severity": 4,
                "category": "deferred_blank",
                "title": f"Deferred answer in high-stakes section: {section_key}",
                "evidence": [{"section": section_key, "quote": q, "criterion_ref": ""} for q in deferred_qs],
                "rationale": "Deferred answers in sections with hard or caution criteria require explicit follow-up.",
                "recommended_followup": [f"Ask the applicant to provide their response to: {q}" for q in deferred_qs],
                "resolution_criteria": "Applicant provides a substantive answer",
                "suggested_lookup": [],
                "hard_flag": False,
                "status": "open",
                "history": [],
            })
        if blank_qs:
            rule_flags.append({
                "flag_id": str(uuid.uuid4()),
                "applicant_id": record.applicant_id,
                "created_at": datetime.now().isoformat(),
                "source": "rule",
                "level": "yellow",
                "severity": 3,
                "category": "deferred_blank",
                "title": f"Blank answer in high-stakes section: {section_key}",
                "evidence": [{"section": section_key, "quote": q, "criterion_ref": ""} for q in blank_qs],
                "rationale": "Blank answers in sections with hard or caution criteria require explicit follow-up.",
                "recommended_followup": [f"Ask the applicant to provide their response to: {q}" for q in blank_qs],
                "resolution_criteria": "Applicant provides a substantive answer",
                "suggested_lookup": [],
                "hard_flag": False,
                "status": "open",
                "history": [],
            })

    # Step 2: Per-section model analysis
    section_prompt_template = SECTION_PROMPT_PATH.read_text(encoding="utf-8")
    all_model_flags: list[dict] = []

    # Partition sections into skip / batch / individual
    skip_sections: list[tuple[str, ParsedSection]] = []
    batch_sections: list[tuple[str, ParsedSection]] = []
    individual_sections: list[tuple[str, ParsedSection]] = []

    for section_key, section in sections_to_analyze:
        item_count = _count_section_items(section)
        relevant_criteria = _get_relevant_criteria(section_key, profile)
        num_criteria = len(relevant_criteria)

        if num_criteria == 0 and section_key not in HIGH_STAKES_SECTIONS:
            skip_sections.append((section_key, section))
        elif num_criteria >= 5 and item_count >= 10:
            individual_sections.append((section_key, section))
        else:
            batch_sections.append((section_key, section))

    # Track progress: total model calls = individual sections + 1 batch (if any)
    total_calls = len(individual_sections) + (1 if batch_sections else 0)
    call_index = 0

    # For skipped sections, emit a minimal summary without a model call
    for section_key, section in skip_sections:
        result.section_summaries[section_key] = "No relevant criteria; skipped model analysis."
        result.sections_done += 1

    # Run individual (heavy) sections as before
    for section_key, section in individual_sections:
        progress.on_section_start(section_key, call_index, total_calls)
        try:
            section_result = _analyze_section(
                provider=provider,
                section_key=section_key,
                section=section,
                profile=profile,
                record=record,
                prompt_template=section_prompt_template,
            )
            result.section_summaries[section_key] = section_result.get("section_summary", "")
            for flag in section_result.get("flags", []):
                flag["source"] = "model"
                flag["flag_id"] = str(uuid.uuid4())
                flag["applicant_id"] = record.applicant_id
                flag["created_at"] = datetime.now().isoformat()
                flag["status"] = "open"
                flag["history"] = []
                all_model_flags.append(flag)
        except ModelResponseError as e:
            logger.warning(f"Section {section_key} analysis failed: {e}")
            result.notes += f"Section {section_key} analysis failed: {e}\n"
            # Emit a data_quality flag
            all_model_flags.append({
                "flag_id": str(uuid.uuid4()),
                "applicant_id": record.applicant_id,
                "created_at": datetime.now().isoformat(),
                "source": "model",
                "level": "yellow",
                "severity": 3,
                "category": "data_quality",
                "title": f"Model analysis incomplete for section: {section_key}",
                "evidence": [{"section": section_key, "quote": str(e)[:200], "criterion_ref": ""}],
                "rationale": "The model failed to produce a valid analysis for this section. Manual review required.",
                "recommended_followup": ["Manually review this section"],
                "resolution_criteria": "Re-run analysis or manual review",
                "suggested_lookup": [],
                "hard_flag": False,
                "status": "open",
                "history": [],
            })
        except Exception as e:
            logger.error(f"Unexpected error analyzing section {section_key}: {e}")
            result.status = "incomplete"
            result.notes += f"Fatal error in section {section_key}: {e}\n"
            result.flags = quality_flags + _merge_and_dedupe(rule_flags, all_model_flags, [])
            progress.on_failure(result, str(e))
            return result

        call_index += 1
        result.sections_done += 1
        progress.on_section_done(section_key, call_index - 1, total_calls, flags=rule_flags + all_model_flags)

    # Run batched (small) sections as ONE combined call
    if batch_sections:
        batch_keys = [key for key, _ in batch_sections]
        progress.on_batch_start(batch_keys)
        try:
            batch_result = _analyze_batched_sections(
                provider=provider,
                sections=batch_sections,
                profile=profile,
                record=record,
                prompt_template=section_prompt_template,
            )
            for section_key in batch_keys:
                section_data = batch_result.get(section_key, {})
                result.section_summaries[section_key] = section_data.get("section_summary", "")
                for flag in section_data.get("flags", []):
                    flag["source"] = "model"
                    flag["flag_id"] = str(uuid.uuid4())
                    flag["applicant_id"] = record.applicant_id
                    flag["created_at"] = datetime.now().isoformat()
                    flag["status"] = "open"
                    flag["history"] = []
                    all_model_flags.append(flag)
        except ModelResponseError as e:
            logger.warning(f"Batched sections analysis failed: {e}")
            result.notes += f"Batched sections {batch_keys} analysis failed: {e}\n"
            for section_key in batch_keys:
                all_model_flags.append({
                    "flag_id": str(uuid.uuid4()),
                    "applicant_id": record.applicant_id,
                    "created_at": datetime.now().isoformat(),
                    "source": "model",
                    "level": "yellow",
                    "severity": 3,
                    "category": "data_quality",
                    "title": f"Model analysis incomplete for section: {section_key}",
                    "evidence": [{"section": section_key, "quote": str(e)[:200], "criterion_ref": ""}],
                    "rationale": "The model failed to produce a valid analysis for this section (batched). Manual review required.",
                    "recommended_followup": ["Manually review this section"],
                    "resolution_criteria": "Re-run analysis or manual review",
                    "suggested_lookup": [],
                    "hard_flag": False,
                    "status": "open",
                    "history": [],
                })
        except Exception as e:
            logger.error(f"Unexpected error analyzing batched sections {batch_keys}: {e}")
            result.status = "incomplete"
            result.notes += f"Fatal error in batched sections {batch_keys}: {e}\n"
            result.flags = quality_flags + _merge_and_dedupe(rule_flags, all_model_flags, [])
            progress.on_failure(result, str(e))
            return result

        result.sections_done += len(batch_sections)
        for section_key in batch_keys:
            progress.on_section_done(section_key, call_index, total_calls, flags=rule_flags + all_model_flags)
        call_index += 1

    # Step 3: Comprehensive whole-form pass
    try:
        comprehensive_flags, comprehensive_impression = _run_comprehensive_pass(
            provider=provider,
            record=record,
            profile=profile,
        )
        if comprehensive_impression:
            # Kept on the run record rather than in section_summaries: it
            # describes the whole form, not one section.
            result.notes += f"Whole-form impression: {comprehensive_impression}\n"
        for flag in comprehensive_flags:
            flag["source"] = "model"
            flag["flag_id"] = str(uuid.uuid4())
            flag["applicant_id"] = record.applicant_id
            flag["created_at"] = datetime.now().isoformat()
            flag["status"] = "open"
            flag["history"] = []
            all_model_flags.append(flag)
    except ModelResponseError as e:
        logger.warning(f"Comprehensive pass failed: {e}")
        result.notes += f"Comprehensive pass failed: {e}\n"
    except Exception as e:
        logger.warning(f"Comprehensive pass error: {e}")
        result.notes += f"Comprehensive pass error: {e}\n"

    # Step 4: Synthesis pass
    progress.on_synthesis_start()
    try:
        synthesis_result = _run_synthesis(
            provider=provider,
            record=record,
            profile=profile,
            section_summaries=result.section_summaries,
            candidate_flags=rule_flags + all_model_flags,
        )
        result.overall_notes = synthesis_result.get("overall_notes", "")

        # Add cross-section flags
        for flag in synthesis_result.get("cross_section_flags", []):
            flag["source"] = "model"
            flag["flag_id"] = str(uuid.uuid4())
            flag["applicant_id"] = record.applicant_id
            flag["created_at"] = datetime.now().isoformat()
            flag["status"] = "open"
            flag["history"] = []
            all_model_flags.append(flag)

        # Step 5: Merge & dedupe
        merged_flags = _merge_and_dedupe(
            rule_flags=rule_flags,
            model_flags=all_model_flags,
            proposed_merges=synthesis_result.get("proposed_merges", []),
        )
        result.flags = quality_flags + merged_flags

    except ModelResponseError as e:
        logger.warning(f"Synthesis pass failed: {e}")
        result.notes += f"Synthesis failed: {e}\n"
        result.flags = quality_flags + _merge_and_dedupe(rule_flags, all_model_flags, [])
    except Exception as e:
        logger.error(f"Unexpected error in synthesis: {e}")
        result.status = "incomplete"
        result.notes += f"Fatal error in synthesis: {e}\n"
        result.flags = quality_flags + _merge_and_dedupe(rule_flags, all_model_flags, [])
        progress.on_failure(result, str(e))
        return result

    # Step 6: Mark complete
    result.status = "complete"
    result.mark_complete()
    progress.on_complete(result)
    return result


def _count_section_items(section: ParsedSection) -> int:
    """Count the total items in a section (QA pairs + medications + checklist + consumption)."""
    count = len(section.qa_pairs)
    count += len(section.medications)
    count += len(section.condition_checklist)
    count += len(section.consumption_table)
    return count


def _analyze_batched_sections(
    provider: OllamaProvider,
    sections: list[tuple[str, ParsedSection]],
    profile: ScreeningProfile,
    record: ApplicantRecord,
    prompt_template: str,
) -> dict[str, dict]:
    """Run model analysis on multiple small sections in a single call.

    Returns a dict keyed by section_key, each value matching the
    SECTION_ANALYSIS_SCHEMA format (section_summary + flags).
    """
    combined_content = ""
    for section_key, section in sections:
        combined_content += f"--- SECTION: {section_key} ---\n"
        combined_content += _build_section_content(section)
        combined_content += "\n"

    # Build combined criteria
    combined_criteria = ""
    all_criteria = [
        {"id": c.id, "description": c.description, "level": "hard"}
        for c in profile.hard_criteria
    ] + [
        {"id": c.id, "description": c.description, "level": "caution"}
        for c in profile.caution_criteria
    ]
    for section_key, _ in sections:
        relevant_criteria = _get_relevant_criteria(section_key, profile)
        if not relevant_criteria and section_key in HIGH_STAKES_SECTIONS:
            relevant_criteria = all_criteria
        relevant_demands = [
            d for d in profile.program_demands
            if section_key in [s.lower().replace(" ", "_") for s in d.interacts_with]
            or any(section_key.startswith(s.lower().replace(" ", "_")[:5]) for s in d.interacts_with)
        ]
        if relevant_criteria or relevant_demands:
            combined_criteria += f"For section '{section_key}':\n"
            if relevant_criteria:
                for c in relevant_criteria:
                    combined_criteria += f"  - [{c['id']}] {c['description']}\n"
            if relevant_demands:
                for d in relevant_demands:
                    combined_criteria += f"  - [demand:{d.id}] {d.demand}\n"
            combined_criteria += "\n"

    # Ground rules
    ground_rules_text = ""
    if profile.ground_rules:
        ground_rules_text = "Ground rules (always apply):\n"
        for gr in profile.ground_rules:
            ground_rules_text += f"  - {gr.rule}\n"
        ground_rules_text += "\n"

    section_keys_str = ", ".join(key for key, _ in sections)
    prompt = (
        f"{prompt_template}\n\n"
        f"## Multiple sections being analyzed: {section_keys_str}\n\n"
        f"Analyze EACH section below independently. "
        f"For EACH section, provide a section_summary and any flags.\n\n"
        f"{combined_content}\n"
        f"{combined_criteria}"
        f"{ground_rules_text}"
        f"Analyze these sections and respond with the JSON schema above. "
        f"In the section_summary, prefix each section's summary with its key in brackets, "
        f"e.g., '[section_key] summary text'. List flags with their section in the evidence."
    )

    raw_result = provider.analyze(prompt=prompt, response_schema=SECTION_ANALYSIS_SCHEMA, max_tokens=4096)

    # Parse the combined result into per-section results
    results: dict[str, dict] = {}
    section_keys = [key for key, _ in sections]

    # Initialize empty results for each section
    for key in section_keys:
        results[key] = {"section_summary": "", "flags": []}

    # Distribute the summary — split by section key markers
    combined_summary = raw_result.get("section_summary", "")
    for key in section_keys:
        marker = f"[{key}]"
        if marker in combined_summary:
            start = combined_summary.index(marker) + len(marker)
            # Find end: next marker or end of string
            end = len(combined_summary)
            for other_key in section_keys:
                other_marker = f"[{other_key}]"
                if other_key != key and other_marker in combined_summary:
                    other_start = combined_summary.index(other_marker)
                    if other_start > start and other_start < end:
                        end = other_start
            results[key]["section_summary"] = combined_summary[start:end].strip()
        elif len(section_keys) == 1:
            # Only one section in batch — just assign the whole summary
            results[key]["section_summary"] = combined_summary

    # Distribute flags by section evidence
    for flag in raw_result.get("flags", []):
        assigned = False
        for ev in flag.get("evidence", []):
            ev_section = ev.get("section", "")
            for key in section_keys:
                if key == ev_section or key in ev_section or ev_section in key:
                    results[key]["flags"].append(flag)
                    assigned = True
                    break
            if assigned:
                break
        if not assigned and section_keys:
            # Default to first section if we cannot determine assignment
            results[section_keys[0]]["flags"].append(flag)

    return results


def _build_section_content(section: ParsedSection) -> str:
    """Build the text content of a section for prompt inclusion."""
    qa_text = ""
    for qa in section.qa_pairs:
        status_note = ""
        if qa.status == AnswerStatus.deferred:
            status_note = " [DEFERRED — applicant requested to discuss in person]"
        elif qa.status == AnswerStatus.blank:
            status_note = " [BLANK — no answer provided]"
        qa_text += f"Q: {qa.question}\nA: {qa.answer}{status_note}\n\n"

    if section.medications:
        qa_text += "Medications listed:\n"
        for med in section.medications:
            qa_text += f"  - {med.medication} {med.dosage} (for: {med.indication}, since: {med.since})\n"
        qa_text += "\n"

    if section.condition_checklist:
        checked = [e.condition for e in section.condition_checklist if e.checked]
        if checked:
            qa_text += f"Conditions checked YES: {', '.join(checked)}\n\n"

    if section.consumption_table:
        qa_text += "Consumption:\n"
        for c in section.consumption_table:
            qa_text += f"  - {c.substance}: {c.amount}\n"
        qa_text += "\n"

    return qa_text


def _analyze_section(
    provider: OllamaProvider,
    section_key: str,
    section: ParsedSection,
    profile: ScreeningProfile,
    record: ApplicantRecord,
    prompt_template: str,
) -> dict:
    """Run model analysis on a single section."""
    # Build section content
    qa_text = ""
    for qa in section.qa_pairs:
        status_note = ""
        if qa.status == AnswerStatus.deferred:
            status_note = " [DEFERRED — applicant requested to discuss in person]"
        elif qa.status == AnswerStatus.blank:
            status_note = " [BLANK — no answer provided]"
        qa_text += f"Q: {qa.question}\nA: {qa.answer}{status_note}\n\n"

    if section.medications:
        qa_text += "Medications listed:\n"
        for med in section.medications:
            qa_text += f"  - {med.medication} {med.dosage} (for: {med.indication}, since: {med.since})\n"
        qa_text += "\n"

    if section.condition_checklist:
        checked = [e.condition for e in section.condition_checklist if e.checked]
        if checked:
            qa_text += f"Conditions checked YES: {', '.join(checked)}\n\n"

    if section.consumption_table:
        qa_text += "Consumption:\n"
        for c in section.consumption_table:
            qa_text += f"  - {c.substance}: {c.amount}\n"
        qa_text += "\n"

    # Build relevant criteria subset. No empty-criteria fallback is needed here:
    # a section only reaches the individual path with 5+ relevant criteria, and
    # the batched path handles the zero-criteria high-stakes case.
    relevant_criteria = _get_relevant_criteria(section_key, profile)

    # Build relevant program demands
    relevant_demands = [
        d for d in profile.program_demands
        if section_key in [s.lower().replace(" ", "_") for s in d.interacts_with]
        or any(section_key.startswith(s.lower().replace(" ", "_")[:5]) for s in d.interacts_with)
    ]

    criteria_text = ""
    if relevant_criteria:
        criteria_text = "Relevant screening criteria:\n"
        for c in relevant_criteria:
            criteria_text += f"  - [{c['id']}] {c['description']}\n"
        criteria_text += "\n"

    if relevant_demands:
        criteria_text += "Program demands relevant to this section:\n"
        for d in relevant_demands:
            criteria_text += f"  - [{d.id}] {d.demand}\n"
        criteria_text += "\n"

    # Ground rules
    ground_rules_text = ""
    if profile.ground_rules:
        ground_rules_text = "Ground rules (always apply):\n"
        for gr in profile.ground_rules:
            ground_rules_text += f"  - {gr.rule}\n"
        ground_rules_text += "\n"

    prompt = (
        f"{prompt_template}\n\n"
        f"## Section being analyzed: {section_key}\n\n"
        f"{qa_text}\n"
        f"{criteria_text}"
        f"{ground_rules_text}"
        f"Analyze this section and respond with the JSON schema above."
    )

    return provider.analyze(prompt=prompt, response_schema=SECTION_ANALYSIS_SCHEMA, max_tokens=4096)


def _get_relevant_criteria(section_key: str, profile: ScreeningProfile) -> list[dict]:
    """Get criteria relevant to a specific section."""
    relevant = []
    for c in profile.hard_criteria:
        if _section_matches(section_key, c.detection.sections):
            relevant.append({"id": c.id, "description": c.description, "level": "hard"})
    for c in profile.caution_criteria:
        if _section_matches(section_key, c.detection.sections):
            relevant.append({"id": c.id, "description": c.description, "level": "caution"})
    return relevant


def _section_matches(section_key: str, target_sections: list[str]) -> bool:
    """Check if a section key matches any of the target section names.

    Resolves profile-authored section names (e.g. "OHA Client Information Form")
    through the section map to taxonomy keys (e.g. "regulatory_screening") so that
    criteria target names written by the profile builder match the parser's keys.
    """
    if not target_sections:
        return True  # No restriction means all sections
    from pisa.parser.section_map import load_section_map, resolve_section_key
    mapping = load_section_map()
    sk = section_key.lower().replace("_", " ")
    for target in target_sections:
        t = target.lower().replace("_", " ")
        if sk.startswith(t[:5]) or t.startswith(sk[:5]) or sk == t:
            return True
        resolved = resolve_section_key(target, mapping)
        if resolved and resolved == section_key:
            return True
    return False


def _run_synthesis(
    provider: OllamaProvider,
    record: ApplicantRecord,
    profile: ScreeningProfile,
    section_summaries: dict[str, str],
    candidate_flags: list[dict],
) -> dict:
    """Run the synthesis pass over all section summaries and candidate flags."""
    synthesis_prompt_template = SYNTHESIS_PROMPT_PATH.read_text(encoding="utf-8")

    # Build summaries text
    summaries_text = "## Section summaries:\n\n"
    for key, summary in section_summaries.items():
        summaries_text += f"**{key}:** {summary}\n\n"

    # Build candidate flags text
    flags_text = "## Candidate flags from rules engine and section analysis:\n\n"
    for flag in candidate_flags:
        source = flag.get("source", "unknown")
        level = flag.get("level", "?")
        title = flag.get("title", "?")
        evidence_quotes = "; ".join(e.get("quote", "")[:80] for e in flag.get("evidence", []))
        flags_text += f"- [{level.upper()}] ({source}) {title} — Evidence: {evidence_quotes[:150]}\n"
    flags_text += "\n"

    # Deferred/blank answers
    deferred_text = "## Deferred and blank answers:\n\n"
    has_deferred = False
    for key, section in record.sections.items():
        for qa in section.qa_pairs:
            if qa.status == AnswerStatus.deferred:
                deferred_text += f"- [{key}] DEFERRED: \"{qa.question}\"\n"
                has_deferred = True
            elif qa.status == AnswerStatus.blank:
                deferred_text += f"- [{key}] BLANK: \"{qa.question}\"\n"
                has_deferred = True
    if not has_deferred:
        deferred_text += "(None)\n"
    deferred_text += "\n"

    # Program demands for cross-reference
    demands_text = "## Program demands:\n\n"
    for d in profile.program_demands:
        demands_text += f"- [{d.id}] {d.demand}\n"
    demands_text += "\n"

    prompt = (
        f"{synthesis_prompt_template}\n\n"
        f"## Applicant: {record.display_name}\n\n"
        f"{summaries_text}"
        f"{flags_text}"
        f"{deferred_text}"
        f"{demands_text}"
        f"Perform your synthesis and respond with the JSON schema above."
    )

    return provider.analyze(prompt=prompt, response_schema=SYNTHESIS_SCHEMA, max_tokens=4096, temperature=0.3)


def _run_comprehensive_pass(
    provider: OllamaProvider,
    record: ApplicantRecord,
    profile: ScreeningProfile,
) -> tuple[list[dict], str]:
    """Run a comprehensive whole-form review with all criteria visible at once.

    This gives the model the full intake form and all criteria in a single call,
    allowing it to catch cross-section patterns, implicit criterion matches, and
    connections that the per-section analysis might miss.

    Returns the candidate flags and the model's overall impression.
    """
    prompt_template = COMPREHENSIVE_PROMPT_PATH.read_text(encoding="utf-8")

    # Build the full form content
    form_text = f"## Complete Intake Form — {record.display_name}\n\n"
    for section_key, section in record.sections.items():
        form_text += f"### {section_key}\n\n"
        for qa in section.qa_pairs:
            status_note = ""
            if qa.status == AnswerStatus.deferred:
                status_note = " [DEFERRED]"
            elif qa.status == AnswerStatus.blank:
                status_note = " [BLANK]"
            form_text += f"**{qa.question}**\n{qa.answer}{status_note}\n\n"
        if section.medications:
            form_text += "**Medications:**\n"
            for med in section.medications:
                form_text += f"- {med.medication} {med.dosage} (for: {med.indication}, since: {med.since})\n"
            form_text += "\n"
        if section.condition_checklist:
            checked = [e.condition for e in section.condition_checklist if e.checked]
            if checked:
                form_text += f"**Conditions checked:** {', '.join(checked)}\n\n"
        if section.consumption_table:
            form_text += "**Consumption:**\n"
            for c in section.consumption_table:
                form_text += f"- {c.substance}: {c.amount}\n"
            form_text += "\n"

    # Build full criteria text
    criteria_text = "## All Screening Criteria\n\n"
    criteria_text += "### Hard criteria (exclusionary or highest-severity):\n"
    for c in profile.hard_criteria:
        criteria_text += f"- **[{c.id}]** {c.description}"
        if c.basis:
            criteria_text += f" (basis: {c.basis})"
        if c.citation:
            criteria_text += f" [{c.citation}]"
        criteria_text += "\n"
    criteria_text += "\n### Caution criteria:\n"
    for c in profile.caution_criteria:
        criteria_text += f"- **[{c.id}]** {c.description}"
        if c.default_level == "red":
            criteria_text += " [RED — serious but resolvable]"
        if c.basis:
            criteria_text += f" (basis: {c.basis})"
        if c.citation:
            criteria_text += f" [{c.citation}]"
        if c.resolution_pathway:
            criteria_text += f" — Resolution: {c.resolution_pathway}"
        criteria_text += "\n"
    criteria_text += "\n"

    # Program demands
    demands_text = ""
    if profile.program_demands:
        demands_text = "## Program Demands\n\n"
        for d in profile.program_demands:
            demands_text += f"- **[{d.id}]** {d.demand} (interacts with: {', '.join(d.interacts_with)})\n"
        demands_text += "\n"

    # Ground rules
    ground_rules_text = ""
    if profile.ground_rules:
        ground_rules_text = "## Ground Rules\n\n"
        for gr in profile.ground_rules:
            ground_rules_text += f"- {gr.rule}\n"
        ground_rules_text += "\n"

    prompt = (
        f"{prompt_template}\n\n"
        f"{form_text}"
        f"{criteria_text}"
        f"{demands_text}"
        f"{ground_rules_text}"
        f"Review this complete form against all criteria and respond with the JSON schema above."
    )

    result = provider.analyze(
        prompt=prompt,
        response_schema=COMPREHENSIVE_REVIEW_SCHEMA,
        max_tokens=4096,
        temperature=0.2,
    )
    return result.get("flags", []), result.get("overall_impression", "")


def _apply_subsumption(rule_flags: list[dict]) -> list[dict]:
    """Remove rule flags that are subsumed by a more specific flag on the same evidence.

    When two flags share the same medication evidence (same medication name in quotes),
    the higher-severity or more-specific flag subsumes the lower one. This prevents
    e.g. R-3 (lithium) and R-4 (generic psychotropic) from both appearing for lithium.
    """
    if len(rule_flags) <= 1:
        return rule_flags

    def _extract_medications(flag: dict) -> set[str]:
        meds = set()
        for ev in flag.get("evidence", []):
            quote = ev.get("quote", "").lower()
            if quote.startswith("medication:"):
                med_name = quote.split("(")[0].replace("medication:", "").strip()
                meds.add(med_name)
        return meds

    subsumed: set[int] = set()
    for i, flag_a in enumerate(rule_flags):
        if i in subsumed:
            continue
        meds_a = _extract_medications(flag_a)
        if not meds_a:
            continue
        for j in range(i + 1, len(rule_flags)):
            if j in subsumed:
                continue
            flag_b = rule_flags[j]
            shared = meds_a & _extract_medications(flag_b)
            if not shared:
                continue

            if _strictness_key(flag_a) >= _strictness_key(flag_b):
                keeper, loser, loser_idx = flag_a, flag_b, j
            else:
                keeper, loser, loser_idx = flag_b, flag_a, i

            # A hard criterion is never subsumed. Its disposition is that no
            # follow-up resolves it, and that is not recoverable from whichever
            # flag would replace it.
            if loser.get("hard_flag"):
                continue

            # Fold rather than drop: the loser's evidence, follow-ups and
            # resolution criteria are part of the reviewer's record, and its
            # criterion is kept in the history entry so the audit trail still
            # shows which rule fired.
            _merge_into(keeper, loser)
            keeper.setdefault("history", []).append({
                "action": "subsumed",
                "subsumed_title": loser.get("title"),
                "subsumed_criterion": ",".join(sorted(_get_criterion_refs(loser))),
                "subsumed_citation": loser.get("citation", ""),
                "shared_medication": ",".join(sorted(shared)),
                "timestamp": datetime.now().isoformat(),
            })
            subsumed.add(loser_idx)
            if loser_idx == i:
                break

    return [f for i, f in enumerate(rule_flags) if i not in subsumed]


def _merge_and_dedupe(
    rule_flags: list[dict],
    model_flags: list[dict],
    proposed_merges: list[dict],
) -> list[dict]:
    """Merge and deduplicate flags. Conservatism: highest level wins."""
    all_flags = []

    # Subsumption: when two rule flags share the same medication evidence,
    # the more specific (higher severity) one subsumes the generic one.
    # E.g., R-3 (lithium specifically) subsumes R-4 (generic psychotropic)
    # when both fired on the same medication.
    rule_flags = _apply_subsumption(rule_flags)

    # Rule flags always survive untouched
    for flag in rule_flags:
        flag.setdefault("flag_id", str(uuid.uuid4()))
        flag.setdefault("status", "open")
        flag.setdefault("history", [])
        all_flags.append(flag)

    # Add model flags, checking for duplicates against rule flags. Every
    # criterion_ref comparison below goes through _get_criterion_refs so the
    # merge decision and _merge_into agree on whether "[R-3]" and "R-3" are the
    # same criterion.
    rule_criteria = set()
    for rf in rule_flags:
        rule_criteria |= _get_criterion_refs(rf)

    for mf in model_flags:
        # Skip if this is a duplicate of a rule flag (same criterion, same section)
        model_criteria = _get_criterion_refs(mf)
        if model_criteria and model_criteria.issubset(rule_criteria):
            matching_rule = None
            for rf in rule_flags:
                if _get_criterion_refs(rf) & model_criteria:
                    matching_rule = rf
                    break
            if matching_rule:
                _merge_into(matching_rule, mf)
                continue

        # Deduplicate model flags against each other by title similarity or shared criteria
        existing_match = None
        mf_title = mf.get("title", "").strip().lower()
        mf_category = mf.get("category", "")
        for ef in all_flags:
            ef_title = ef.get("title", "").strip().lower()
            # Match by title overlap
            if ef_title and mf_title and (ef_title == mf_title or _titles_overlap(ef_title, mf_title)):
                existing_match = ef
                break
            # Match by shared criterion_ref + same category (same concern, different wording)
            if mf_category and ef.get("category") == mf_category and model_criteria:
                if _get_criterion_refs(ef) & model_criteria:
                    existing_match = ef
                    break

        if existing_match:
            _merge_into(existing_match, mf)
        else:
            all_flags.append(mf)

    # Apply proposed merges — match by criterion_ref first, fall back to fuzzy title
    if proposed_merges:
        for merge in proposed_merges:
            primary_title = merge.get("primary_title", "")
            merge_titles = merge.get("merge_titles", [])
            primary = _find_flag_by_ref_or_title(all_flags, primary_title)
            to_remove = []
            for mt in merge_titles:
                match = _find_flag_by_ref_or_title(all_flags, mt)
                if not match or match is primary:
                    continue
                # The synthesis model may not consolidate away a deterministic
                # flag. Its hard_flag disposition, basis and citation come from
                # the criteria document, and title matching here is fuzzy enough
                # that one bad proposal would otherwise delete a rule flag.
                if match.get("source") == "rule":
                    logger.info(
                        "Refused proposed merge of rule flag %r into %r",
                        match.get("title"), primary_title,
                    )
                    continue
                to_remove.append(match)

            if primary and to_remove:
                for rm_flag in to_remove:
                    _merge_into(primary, rm_flag)
                    primary.setdefault("history", []).append({
                        "action": "merged",
                        "merged_from": rm_flag.get("title"),
                        "from_level": rm_flag.get("level", "?"),
                        "to_level": primary.get("level", "?"),
                        "timestamp": datetime.now().isoformat(),
                    })
                all_flags = [f for f in all_flags if f not in to_remove]

    # Auto-merge: consolidate flags that share the same criterion_ref regardless
    # of model merge proposals. Groups by criterion_ref and merges into the
    # highest-severity flag in each group.
    all_flags = _auto_merge_by_criterion(all_flags)

    # Cap green flags to avoid noise — keep only the top 3 by severity
    greens = [f for f in all_flags if f.get("level") == "green"]
    if len(greens) > 3:
        greens.sort(key=lambda f: f.get("severity", 0), reverse=True)
        discard = set(id(f) for f in greens[3:])
        all_flags = [f for f in all_flags if id(f) not in discard]

    return all_flags


def _level_rank(level: str) -> int:
    return {"green": 0, "yellow": 1, "red": 2}.get(level, 0)


def _strictness_key(flag: dict) -> tuple[int, int, int]:
    """Sort key for "which of these two flags is stricter". Higher wins.

    A hard flag outranks any soft flag, then level, then severity. Every
    consolidation path uses this one comparator so the same pair of flags always
    resolves to the same winner, and so a hard exclusion is never displaced by a
    resolvable flag that happens to carry a higher severity number.
    """
    return (
        1 if flag.get("hard_flag") else 0,
        _level_rank(flag.get("level", "green")),
        flag.get("severity", 0),
    )


def _titles_overlap(a: str, b: str) -> bool:
    """Check if two flag titles are substantially similar."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return False
    intersection = words_a & words_b
    smaller = min(len(words_a), len(words_b))
    return len(intersection) / smaller >= 0.7


def _merge_into(target: dict, source: dict):
    """Merge source flag's info into target. The stricter value always wins.

    Merging may raise the target's severity but must never soften it. `hard_flag`
    propagates on, a hard flag never acquires a resolution pathway, and
    `basis`/`citation` are left alone because they describe the target's own
    criterion and cannot be inherited from another one.
    """
    if _level_rank(source.get("level", "green")) > _level_rank(target.get("level", "green")):
        target["level"] = source["level"]
    target["severity"] = max(target.get("severity", 1), source.get("severity", 1))
    # A hard disposition survives any merge. Set this before touching
    # resolution_criteria below, so an incoming hard flag also closes off the
    # resolution path on the target.
    if source.get("hard_flag"):
        target["hard_flag"] = True
    # Union evidence
    existing_evidence = target.setdefault("evidence", [])
    for ev in source.get("evidence", []):
        if ev not in existing_evidence:
            existing_evidence.append(ev)
    # Union followups only when criterion refs overlap (§8.4 — prevents cross-substance bleed)
    target_crefs = _get_criterion_refs(target)
    source_crefs = _get_criterion_refs(source)
    if target_crefs & source_crefs or not target_crefs or not source_crefs:
        existing_fu = target.setdefault("recommended_followup", [])
        for fq in source.get("recommended_followup", []):
            if fq not in existing_fu:
                existing_fu.append(fq)
    # Fill rationale if missing
    if source.get("rationale") and not target.get("rationale"):
        target["rationale"] = source["rationale"]
    # A hard flag has no resolution pathway by definition, so never graft one on:
    # that is what turns an exclusion into a resolvable red.
    if (
        source.get("resolution_criteria")
        and not target.get("resolution_criteria")
        and not target.get("hard_flag")
    ):
        target["resolution_criteria"] = source["resolution_criteria"]
    if source.get("suggested_lookup"):
        existing = target.setdefault("suggested_lookup", [])
        target["suggested_lookup"] = list(set(existing + source["suggested_lookup"]))


def _normalize_ref(ref: str) -> str:
    """Strip brackets from a criterion_ref (e.g., '[R-3]' -> 'R-3')."""
    return ref.strip("[]")


def _get_criterion_refs(flag: dict) -> set[str]:
    """Extract all criterion_ref values from a flag's evidence (normalized)."""
    raw = {ev.get("criterion_ref", "") for ev in flag.get("evidence", [])} - {""}
    return {_normalize_ref(r) for r in raw}


def _find_flag_by_ref_or_title(flags: list[dict], title: str) -> dict | None:
    """Find a flag by criterion ref extracted from a title, or by fuzzy title match.

    Titles are formatted as "[R-4] Description..." — extract the criterion ID and
    match against evidence criterion_refs. Falls back to fuzzy title matching.
    """
    import re
    ref_match = re.match(r"\[?([A-Z]-?\w+)\]?", title.strip())
    target_ref = ref_match.group(1) if ref_match else None

    if target_ref:
        for flag in flags:
            if target_ref in _get_criterion_refs(flag):
                return flag
            flag_title = flag.get("title", "")
            flag_ref = re.match(r"\[([A-Z]-?\w+)\]", flag_title.strip())
            if flag_ref and flag_ref.group(1) == target_ref:
                return flag

    # Fall back to fuzzy title match
    title_lower = title.strip().lower()
    for flag in flags:
        flag_title = flag.get("title", "").strip().lower()
        if flag_title == title_lower:
            return flag
        if _titles_overlap(flag_title, title_lower):
            return flag

    return None


def _auto_merge_by_criterion(flags: list[dict]) -> list[dict]:
    """Merge model flags into rule flags that share the same criterion_ref.

    Strategy:
    - Rule flags are anchors (1 criterion each). They never merge into each other.
    - A model flag with ≤2 distinct criterion_refs merges into the matching rule flag.
    - A model flag with 3+ refs is a cross-cutting observation and stays separate,
      UNLESS all its refs map to the same single rule flag.
    - Model flags that don't match any rule flag merge among themselves only if
      they share a criterion and both have ≤2 refs.
    """
    from collections import defaultdict

    flag_refs: list[set[str]] = [_get_criterion_refs(f) for f in flags]

    # Index rule flags by their criterion ref
    rule_ref_to_idx: dict[str, int] = {}
    for i, f in enumerate(flags):
        if f.get("source") == "rule":
            for ref in flag_refs[i]:
                rule_ref_to_idx[ref] = i

    merged_away: set[int] = set()

    # Phase 1: merge model flags into matching rule flags
    for i, f in enumerate(flags):
        if f.get("source") == "rule" or i in merged_away:
            continue
        refs = flag_refs[i]
        # Find which rule flags this model flag overlaps with
        matching_rule_indices = set()
        for ref in refs:
            if ref in rule_ref_to_idx:
                matching_rule_indices.add(rule_ref_to_idx[ref])
        if not matching_rule_indices:
            continue
        # Only merge if the model flag is focused (≤2 refs), OR all its refs
        # have matching rule flags (it's a synthesis of already-covered criteria)
        all_refs_covered = refs <= set(rule_ref_to_idx.keys())
        if len(refs) <= 2 or all_refs_covered:
            # Merge into the strictest matching rule flag
            target_idx = max(matching_rule_indices, key=lambda idx: _strictness_key(flags[idx]))
            target_flag = flags[target_idx]
            _merge_into(target_flag, f)
            shared = refs & set(rule_ref_to_idx.keys())
            target_flag.setdefault("history", []).append({
                "action": "auto_merged",
                "merged_from": f.get("title"),
                "criterion_ref": ",".join(sorted(shared)),
                "timestamp": datetime.now().isoformat(),
            })
            merged_away.add(i)

    # Phase 2: merge remaining model flags among themselves (≤2 refs only)
    remaining_model: dict[str, list[int]] = defaultdict(list)
    for i, f in enumerate(flags):
        if i in merged_away or f.get("source") == "rule":
            continue
        if len(flag_refs[i]) <= 2:
            for ref in flag_refs[i]:
                remaining_model[ref].append(i)

    for ref, indices in remaining_model.items():
        active = [i for i in indices if i not in merged_away]
        if len(active) <= 1:
            continue
        active.sort(key=lambda i: _strictness_key(flags[i]), reverse=True)
        primary_flag = flags[active[0]]
        for other_idx in active[1:]:
            _merge_into(primary_flag, flags[other_idx])
            primary_flag.setdefault("history", []).append({
                "action": "auto_merged",
                "merged_from": flags[other_idx].get("title"),
                "criterion_ref": ref,
                "timestamp": datetime.now().isoformat(),
            })
            merged_away.add(other_idx)

    return [f for i, f in enumerate(flags) if i not in merged_away]
