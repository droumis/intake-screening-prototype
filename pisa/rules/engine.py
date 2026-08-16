"""Deterministic rules engine.

Matches the approved Screening Profile's hard_criteria and caution_criteria
detection specs against a parsed ApplicantRecord. This layer alone must catch
every explicitly stated hard contraindication even with the model disabled.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pisa.parser.models import ApplicantRecord, AnswerStatus, ParsedSection
from pisa.profile.models import (
    CautionCriterion,
    DetectionSpec,
    HardCriterion,
    ScreeningProfile,
)


def _normalize(text: str) -> str:
    return text.lower().strip()


def _keyword_in_text(keyword: str, text: str) -> bool:
    """Check if keyword appears in text with word-boundary awareness.

    Short keywords (<=3 chars) require word boundaries to avoid substring noise
    (e.g. "21" matching "2021"). Longer keywords use substring matching.
    """
    kw = _normalize(keyword)
    txt = _normalize(text)
    if len(kw) <= 3:
        return bool(re.search(r'\b' + re.escape(kw) + r'\b', txt))
    return kw in txt


def _check_checklist_fields(section: ParsedSection, fields: list[str]) -> list[str]:
    """Check if any checklist fields are marked as checked. Returns matched field names."""
    matches = []
    for entry in section.condition_checklist:
        if entry.checked:
            for field in fields:
                if _normalize(field) in _normalize(entry.condition):
                    matches.append(entry.condition)
    return matches


NEGATION_PATTERNS = [
    r"\bno\b",
    r"\bnot\b",
    r"\bnever\b",
    r"\bnone\b",
    r"\bno,\b",
]
NEGATION_RE = re.compile("|".join(NEGATION_PATTERNS), re.IGNORECASE)


def _is_negated_context(text: str, keyword: str) -> bool:
    """Check if a keyword appears in a negating context.

    Only returns True for short, clearly negative answers where the entire
    response is a denial. For longer answers, the keyword is not suppressed
    because negation in one clause doesn't negate disclosures in another.
    """
    text_lower = text.lower().strip()
    kw_lower = keyword.lower()

    # Only suppress for short answers (under ~80 chars) that are clearly denials
    # This catches "No", "No, never", "None", "Not suicidal" but not
    # multi-sentence answers that start with "No attempts" then disclose things.
    if len(text_lower) < 80 and re.match(r"^(no|never|none|not)\b", text_lower):
        return True

    # For the specific keyword appearing right after "not" in a short clause
    pos = text_lower.find(kw_lower)
    if pos == -1:
        return False

    # Check the immediate prefix (within 5 chars) for "not "
    immediate_prefix = text_lower[max(0, pos - 5):pos].strip()
    if immediate_prefix.endswith("not"):
        # "not suicidal" is a clear negation
        return True

    return False


def _check_keywords(section: ParsedSection, keywords: list[str]) -> list[dict]:
    """Search section text for keywords. Returns list of {keyword, quote} dicts.

    Skips matches where the keyword appears in a clearly negated context
    (e.g., "No, never" or "not suicidal").

    For Q/A pairs where the answer is affirmative ("yes"), also checks the
    question text for keyword matches — this catches regulatory screening
    tables where the criterion term appears in the question.
    """
    matches = []
    all_text_parts = []
    for qa in section.qa_pairs:
        if qa.answer:
            all_text_parts.append((qa.question, qa.answer))

    for question, answer in all_text_parts:
        answer_lower = _normalize(answer)
        for keyword in keywords:
            if _keyword_in_text(keyword, answer):
                if _is_negated_context(answer, keyword):
                    continue
                quote = answer[:200] if len(answer) <= 200 else answer[:200] + "..."
                matches.append({"keyword": keyword, "quote": quote, "question": question})
            elif _keyword_in_text(keyword, question):
                # Keyword in question — check if answer is affirmative
                answer_start = answer_lower.lstrip("*").strip()[:10]
                if answer_start.startswith("yes"):
                    quote = f"{question}: {answer}"
                    quote = quote[:200] if len(quote) <= 200 else quote[:200] + "..."
                    matches.append({"keyword": keyword, "quote": quote, "question": question})
    return matches


DRUG_CLASS_MAP: dict[str, list[str]] = {
    "ssris": ["sertraline", "fluoxetine", "paroxetine", "citalopram", "escitalopram", "fluvoxamine"],
    "snris": ["venlafaxine", "desvenlafaxine", "duloxetine", "levomilnacipran", "milnacipran"],
    "maois": ["phenelzine", "tranylcypromine", "isocarboxazid", "selegiline", "moclobemide"],
    "lithium": ["lithium carbonate", "lithium citrate"],
    "antipsychotics": [
        "quetiapine", "olanzapine", "risperidone", "aripiprazole", "clozapine",
        "haloperidol", "chlorpromazine", "ziprasidone", "paliperidone", "lurasidone",
        "cariprazine", "brexpiprazole",
    ],
    "mood stabilizers": ["valproate", "valproic acid", "divalproex", "carbamazepine", "lamotrigine", "lithium"],
    "stimulants": ["methylphenidate", "amphetamine", "dextroamphetamine", "lisdexamfetamine", "modafinil"],
    "sedatives": ["trazodone", "zolpidem", "eszopiclone", "suvorexant", "lemborexant", "doxepin"],
    "benzodiazepines": ["alprazolam", "lorazepam", "clonazepam", "diazepam", "temazepam"],
}


def _expand_medication_targets(medication_names: list[str]) -> list[str]:
    """Expand drug class names to include individual drug names."""
    expanded = list(medication_names)
    for target in medication_names:
        class_key = _normalize(target)
        if class_key in DRUG_CLASS_MAP:
            expanded.extend(DRUG_CLASS_MAP[class_key])
    return expanded


def _check_medication_names(record: ApplicantRecord, medication_names: list[str]) -> list[dict]:
    """Search all medication tables for specific medication names."""
    expanded_targets = _expand_medication_targets(medication_names)
    matches = []
    for section_key, section in record.sections.items():
        for med in section.medications:
            med_name_lower = _normalize(med.medication)
            for target in expanded_targets:
                if _normalize(target) in med_name_lower:
                    matches.append({
                        "medication": med.medication,
                        "dosage": med.dosage,
                        "indication": med.indication,
                        "section": section_key,
                        "matched_name": target,
                    })
                    break
    return matches


def _build_flag(
    criterion_id: str,
    criterion_desc: str,
    level: str,
    evidence: list[dict],
    source: str = "rule",
    hard_flag: bool = False,
    basis: str = "",
    citation: str = "",
    resolution_pathway: str = "",
) -> dict:
    """Build a flag dict in the standard schema."""
    flag = {
        "flag_id": str(uuid.uuid4()),
        "created_at": datetime.now().isoformat(),
        "source": source,
        "level": level,
        "severity": 9 if level == "red" else 5,
        "category": _infer_category(criterion_id),
        "title": f"[{criterion_id}] {criterion_desc[:80]}",
        "evidence": evidence,
        "rationale": "",
        "recommended_followup": [],
        "resolution_criteria": resolution_pathway if resolution_pathway else "",
        "suggested_lookup": [],
        "hard_flag": hard_flag,
        "basis": basis,
        "citation": citation,
        "status": "open",
        "history": [],
    }
    return flag


def _infer_category(criterion_id: str) -> str:
    """Infer flag category from criterion ID prefix."""
    prefix = criterion_id[0].upper() if criterion_id else ""
    if prefix == "A":
        # Could be medical, medication, or psychological
        return "medical"
    elif prefix == "B":
        return "psychological"
    elif prefix == "C":
        return "medication"
    elif prefix == "D":
        return "substance"
    elif prefix == "E":
        return "support_network"
    elif prefix == "F":
        return "medical"
    return "medical"


def _scan_keywords(
    record: ApplicantRecord, section_keys: list[str], keywords: list[str]
) -> list[dict]:
    """Scan the given sections for any of the keywords, tagging each match with its section."""
    matches = []
    for section_key in section_keys:
        section = record.sections.get(section_key)
        if not section:
            continue
        for match in _check_keywords(section, keywords):
            match["section"] = section_key
            matches.append(match)
    return matches


def _resolve_target_sections(
    detection_sections: list[str], record: ApplicantRecord
) -> list[str]:
    """Resolve profile-authored section names to record taxonomy keys.

    If detection_sections is empty, returns all record section keys (no restriction).
    Otherwise resolves each name through the section map, falling back to record keys
    if unresolved.
    """
    if not detection_sections:
        return list(record.sections.keys())
    from pisa.parser.section_map import load_section_map, resolve_section_key
    mapping = load_section_map()
    resolved = []
    for name in detection_sections:
        if name in record.sections:
            resolved.append(name)
        else:
            taxonomy_key = resolve_section_key(name, mapping)
            if taxonomy_key and taxonomy_key in record.sections:
                resolved.append(taxonomy_key)
            else:
                resolved.append(name)
    return resolved


def run_rules_engine(record: ApplicantRecord, profile: ScreeningProfile) -> list[dict]:
    """Run the deterministic rules engine against an applicant record.

    Returns a list of flag dicts (§4 schema) for all matched criteria.
    """
    flags = []

    # Check hard criteria
    for criterion in profile.hard_criteria:
        criterion_flags = _check_criterion(
            record, criterion, level="red", hard_flag=True,
            basis=criterion.basis, citation=criterion.citation,
        )
        flags.extend(criterion_flags)

    # Check caution criteria — respect default_level (may be "red" for pathway criteria)
    for criterion in profile.caution_criteria:
        level = criterion.default_level
        hard_flag = False
        criterion_flags = _check_criterion(
            record, criterion, level=level, hard_flag=hard_flag,
            basis=criterion.basis, citation=criterion.citation,
            resolution_pathway=criterion.resolution_pathway,
        )
        flags.extend(criterion_flags)

    return flags


def _check_criterion(
    record: ApplicantRecord,
    criterion: HardCriterion | CautionCriterion,
    level: str,
    hard_flag: bool,
    basis: str = "",
    citation: str = "",
    resolution_pathway: str = "",
) -> list[dict]:
    """Check a single criterion against the record. Returns flags if matched."""
    detection = criterion.detection
    evidence_items = []
    weak_keyword_match = False
    matched_outside_target: list[str] = []

    # 1. Check checklist fields
    if detection.checklist_fields:
        for section_key in _resolve_target_sections(detection.sections, record):
            section = record.sections.get(section_key)
            if not section:
                continue
            checklist_matches = _check_checklist_fields(section, detection.checklist_fields)
            for match in checklist_matches:
                evidence_items.append({
                    "section": section_key,
                    "quote": f"Condition checklist: '{match}' marked YES",
                    "criterion_ref": criterion.id,
                })

    # 2. Check medication names
    if detection.medication_names:
        med_matches = _check_medication_names(record, detection.medication_names)
        for match in med_matches:
            evidence_items.append({
                "section": match["section"],
                "quote": (
                    f"Medication: {match['medication']} {match['dosage']} "
                    f"(for: {match['indication']})"
                ),
                "criterion_ref": criterion.id,
            })

    # 3. Check keywords in relevant sections
    if detection.keywords:
        target_sections = _resolve_target_sections(detection.sections, record)
        all_kw_matches = _scan_keywords(record, target_sections, detection.keywords)

        # A hard criterion that finds nothing in the sections it targets rescans
        # the rest of the form. Those targets are a guess made by the model that
        # wrote the profile, and the guess is load-bearing: Oregon's lithium
        # question sits in the regulatory screening block rather than the
        # medication list, and the applicant's medication table reads "None
        # currently", so a criterion pointed at "medications" stayed silent on an
        # explicit "Yes". Flagging with a caveat beats missing an exclusion.
        if hard_flag and not all_kw_matches:
            searched = set(target_sections)
            wider = [k for k in record.sections if k not in searched]
            all_kw_matches = _scan_keywords(record, wider, detection.keywords)
            if all_kw_matches:
                matched_outside_target = sorted({m["section"] for m in all_kw_matches})

        # A single keyword match is always enough to fire. Gating on keyword
        # count produced false negatives on exclusionary criteria: a criterion
        # with keywords ["psychosis", "psychotic", "hallucination", "delusion"]
        # would stay silent on a narrative that only used one of them. A missed
        # red is the worst outcome this layer can produce, so weak matches are
        # surfaced at lower confidence instead of being dropped.
        distinct_keywords = {m["keyword"].lower() for m in all_kw_matches}
        has_specific_match = any(" " in kw or len(kw) > 10 for kw in distinct_keywords)
        if all_kw_matches:
            # Evidence is ordered most-specific first (multi-word phrases, then
            # longer keywords) so the reviewer reads the quote that actually
            # substantiates the criterion first. Nothing is filtered out: pruning
            # by keyword length used to discard the substantiating quote whenever
            # a longer keyword matched somewhere irrelevant.
            evidence_source = sorted(
                all_kw_matches,
                key=lambda m: (" " in m["keyword"], len(m["keyword"])),
                reverse=True,
            )
            for match in evidence_source:
                evidence_items.append({
                    "section": match["section"],
                    "quote": match["quote"],
                    "criterion_ref": criterion.id,
                })
            # Only one general single-word keyword fired. Still flagged, but the
            # reviewer is told so, because this is the shape of a false positive.
            if not has_specific_match and len(distinct_keywords) < 2:
                weak_keyword_match = True

    # Deduplicate evidence by quote
    seen_quotes = set()
    unique_evidence = []
    for ev in evidence_items:
        key = (ev["section"], ev["quote"][:100])
        if key not in seen_quotes:
            seen_quotes.add(key)
            unique_evidence.append(ev)

    if unique_evidence:
        # Window check: if matched answer contains a time reference, note it
        window_note = ""
        if hasattr(criterion, 'detection') and detection.keywords:
            _number_words = "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
            time_patterns = re.compile(
                r"\b((\d+|" + _number_words + r")\s*(weeks?|days?|months?|years?)\s*ago|in\s*\d{4}|last\s*(winter|spring|summer|fall|year|month|week)|\d{4})\b",
                re.IGNORECASE,
            )
            for ev in unique_evidence:
                quote = ev.get("quote", "")
                if time_patterns.search(quote):
                    window_note = "the answer contains a time reference, so verify the window"
                    break

        flag = _build_flag(
            criterion_id=criterion.id,
            criterion_desc=criterion.description,
            level=level,
            evidence=unique_evidence,
            hard_flag=hard_flag,
            basis=basis,
            citation=citation,
            resolution_pathway=resolution_pathway,
        )
        # Both caveats go in the rationale because that is what the flag card
        # renders and what the database stores. A separate field would not reach
        # the reviewer.
        caveats = []
        if matched_outside_target:
            caveats.append(
                "found in "
                + ", ".join(matched_outside_target)
                + " rather than the section this criterion targets, so confirm the "
                "profile's section mapping"
            )
        if weak_keyword_match:
            caveats.append(
                "matched on a single general keyword, so check the quoted text "
                "before treating this as a real match"
            )
        if window_note:
            caveats.append(window_note)
        if caveats:
            flag["rationale"] = "Deterministic match: " + "; ".join(caveats) + "."
        return [flag]

    return []
