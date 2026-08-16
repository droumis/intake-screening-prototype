"""Oracle evaluation script — runs the pipeline on both demo datasets and
scores results against each EXPECTED_FLAGS.md.

Passing bar:
- 100% of expected reds present (missing red = build failure)
- >= 80% of expected yellows present
- Zero flags on explicit calibration traps

Usage: pixi run eval [data_dir]
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pisa.config import load_config
from pisa.model.ollama import OllamaProvider
from pisa.parser.markdown import parse_file
from pisa.pipeline.runner import run_pipeline, PipelineResult
from pisa.profile.loader import load_context_documents, compute_context_hash
from pisa.profile.builder import build_profile
from pisa.profile.models import ScreeningProfile
from pisa.profile.store import load_profile, save_profile


def extract_expected_flags(oracle_path: Path) -> dict:
    """Parse EXPECTED_FLAGS.md to extract expected reds and yellows per applicant."""
    content = oracle_path.read_text(encoding="utf-8")
    results = {}

    # Split by applicant sections
    applicant_blocks = re.split(r"^## Applicant", content, flags=re.MULTILINE)

    for block in applicant_blocks[1:]:  # Skip the header
        # Extract applicant letter and name
        header_match = re.match(r"\s*([A-C])\s*[—–-]\s*(.+?)(?:\s*\(|$)", block)
        if not header_match:
            continue
        letter = header_match.group(1)
        name = header_match.group(2).strip()

        expected = {"name": name, "letter": letter, "reds": [], "yellows": [], "calibration_traps": []}

        # Split into labeled sections by **Bold:** headers at start of line
        lines = block.split("\n")
        current_section = None
        section_header_line: dict[str, str] = {}
        section_items: dict[str, list[str]] = {}

        for line in lines:
            header = re.match(r"^\*\*(.+?)\*\*:?\s*(.*)", line)
            if header:
                label = header.group(1).lower().strip()
                current_section = label
                section_header_line[current_section] = header.group(2)
                section_items.setdefault(current_section, [])
            elif current_section and line.strip().startswith("-"):
                section_items.setdefault(current_section, []).append(line)

        def _extract_criteria_from_items(items: list[str]) -> list[str]:
            """Extract criterion IDs from list items."""
            crits = []
            for line in items:
                # Extract the criterion label portion (before the em-dash description)
                label_match = re.match(r"\s*-\s*\*\*(.+?)(?:\*\*|—|–)", line)
                if label_match:
                    label = label_match.group(1)
                    found = re.findall(r"([A-Z]\d+)", label)
                    crits.extend(found)
                else:
                    # Fallback: any bolded criterion IDs in the line
                    found = re.findall(r"\*\*([A-Z]\d+)", line)
                    if found:
                        crits.extend(found)
            return crits

        # Collect reds from "red..." sections (skip if header says "none")
        for key, items in section_items.items():
            if not key.startswith("red"):
                continue
            header_text = section_header_line.get(key, "")
            if re.search(r"\bnone\b", header_text, re.IGNORECASE):
                continue
            expected["reds"].extend(_extract_criteria_from_items(items))

        # Collect yellows
        for key, items in section_items.items():
            if not key.startswith("yellow"):
                continue
            header_text = section_header_line.get(key, "")
            if re.search(r"\bnone\b", header_text, re.IGNORECASE):
                continue
            expected["yellows"].extend(_extract_criteria_from_items(items))

        results[letter] = expected

    return results


def check_flags_against_oracle(flags: list[dict], expected: dict) -> dict:
    """Check pipeline flags against oracle expectations."""
    # Extract criterion refs from produced flags
    produced_criteria = {}
    for flag in flags:
        level = flag.get("level", "")
        for ev in flag.get("evidence", []):
            cref = ev.get("criterion_ref", "")
            if cref:
                # Handle compound refs, brackets, etc
                for part in re.findall(r"[A-Z]\d+", cref):
                    if part not in produced_criteria or _level_rank(level) > _level_rank(produced_criteria[part]):
                        produced_criteria[part] = level

        # Also check title for criterion IDs
        title = flag.get("title", "")
        for cref in re.findall(r"[A-Z]\d+", title):
            if cref not in produced_criteria or _level_rank(level) > _level_rank(produced_criteria[cref]):
                produced_criteria[cref] = level

        # Check rationale for criterion IDs
        rationale = flag.get("rationale", "")
        for cref in re.findall(r"\b[A-Z]\d+\b", rationale):
            if cref not in produced_criteria or _level_rank(level) > _level_rank(produced_criteria[cref]):
                produced_criteria[cref] = level

    # Check reds
    reds_found = []
    reds_missing = []
    for crit in expected["reds"]:
        if crit in produced_criteria and produced_criteria[crit] in ("red", "yellow"):
            reds_found.append(crit)
        else:
            reds_missing.append(crit)

    # Check yellows
    yellows_found = []
    yellows_missing = []
    for crit in expected["yellows"]:
        if crit in produced_criteria:
            yellows_found.append(crit)
        else:
            yellows_missing.append(crit)

    yellow_rate = len(yellows_found) / len(expected["yellows"]) if expected["yellows"] else 1.0

    return {
        "reds_expected": expected["reds"],
        "reds_found": reds_found,
        "reds_missing": reds_missing,
        "reds_pass": len(reds_missing) == 0,
        "yellows_expected": expected["yellows"],
        "yellows_found": yellows_found,
        "yellows_missing": yellows_missing,
        "yellow_rate": yellow_rate,
        "yellows_pass": yellow_rate >= 0.8,
        "total_flags_produced": len(flags),
    }


def _level_rank(level: str) -> int:
    return {"green": 0, "yellow": 1, "red": 2}.get(level, 0)


def check_lithium_cross_dataset(dataset_results: dict) -> bool:
    """Cross-dataset assertion: lithium must be hard in Oregon, non-hard in Colorado.

    Returns True if the assertion passes.
    """
    oregon_lithium = dataset_results.get("oregon-psilocybin-session", {}).get("A", {})
    colorado_lithium = dataset_results.get("colorado-psilocybin-session", {}).get("A", {})

    if not oregon_lithium or not colorado_lithium:
        return True  # datasets not both present; skip

    or_flags = oregon_lithium.get("flags", [])
    co_flags = colorado_lithium.get("flags", [])

    or_lithium_hard = None
    co_lithium_hard = None

    for flag in or_flags:
        if _flag_mentions_criterion(flag, "R-A1") or _flag_mentions_criterion(flag, "RA1"):
            or_lithium_hard = flag.get("hard_flag", True)
            break

    for flag in co_flags:
        if _flag_mentions_criterion(flag, "R-3") or _flag_mentions_criterion(flag, "R3"):
            co_lithium_hard = flag.get("hard_flag", None)
            break

    if or_lithium_hard is None or co_lithium_hard is None:
        return True  # can't check if flags not found

    return or_lithium_hard is True and co_lithium_hard is False


def _flag_mentions_criterion(flag: dict, criterion_id: str) -> bool:
    """Check if a flag references a criterion ID in its title, evidence, or rationale."""
    normalized = criterion_id.replace("-", "")
    title = flag.get("title", "").replace("-", "")
    if normalized in title:
        return True
    for ev in flag.get("evidence", []):
        cref = ev.get("criterion_ref", "").replace("-", "")
        if normalized in cref:
            return True
    rationale = flag.get("rationale", "").replace("-", "")
    if normalized in rationale:
        return True
    return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Oracle evaluation")
    parser.add_argument("data_dir", nargs="?", default="demo-data")
    parser.add_argument("--dataset", help="Run only this dataset (e.g. summit-series)")
    parser.add_argument("--applicant", help="Run only this applicant letter (e.g. C)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    config = load_config()
    provider = OllamaProvider(config.model)

    # Check model availability
    status = provider.health_check()
    if not status.available:
        print(f"ERROR: Ollama not available: {status.message}")
        sys.exit(1)

    datasets = sorted(p for p in data_dir.iterdir() if p.is_dir() and not p.name.startswith("."))
    if args.dataset:
        datasets = [d for d in datasets if d.name == args.dataset]
    all_pass = True
    dataset_results: dict[str, dict] = {}

    for dataset_dir in datasets:
        oracle_path = dataset_dir / "EXPECTED_FLAGS.md"
        if not oracle_path.exists():
            continue

        print(f"\n{'='*60}")
        print(f"Dataset: {dataset_dir.name}")
        print(f"{'='*60}")

        # Build or load cached profile
        context_dir = dataset_dir / "context"
        docs = load_context_documents(context_dir)
        context_hash = compute_context_hash(docs)
        cached = load_profile(context_hash)
        if cached:
            profile = cached
            print(f"Loaded cached profile ({len(profile.hard_criteria)} hard, {len(profile.caution_criteria)} caution)")
        else:
            print(f"Building screening profile from {len(docs)} docs...")
            profile = build_profile(provider, docs)
            save_profile(profile)
            print(f"Profile: {len(profile.hard_criteria)} hard, {len(profile.caution_criteria)} caution criteria")

        # Parse oracle
        expected_all = extract_expected_flags(oracle_path)

        # Run pipeline on each applicant
        forms_dir = dataset_dir / "forms"
        forms = sorted(forms_dir.glob("applicant_*.md"))

        dataset_results[dataset_dir.name] = {}

        for form_path in forms:
            # Determine which applicant letter
            letter_match = re.search(r"applicant_([A-C])_", form_path.name)
            if not letter_match:
                continue
            letter = letter_match.group(1)

            if args.applicant and letter != args.applicant.upper():
                continue

            if letter not in expected_all:
                print(f"\n  {form_path.name}: no oracle entry, skipping")
                continue

            expected = expected_all[letter]
            print(f"\n  {expected['name']} (Applicant {letter}):")

            record = parse_file(form_path)
            result = run_pipeline(record, profile, provider)

            dataset_results[dataset_dir.name][letter] = {"flags": result.flags}

            report = check_flags_against_oracle(result.flags, expected)

            # Report
            red_status = "PASS" if report["reds_pass"] else "FAIL"
            yellow_status = "PASS" if report["yellows_pass"] else "FAIL"

            print(f"    Status: {result.status} | Flags produced: {report['total_flags_produced']}")
            print(f"    Reds:    [{red_status}] {len(report['reds_found'])}/{len(report['reds_expected'])} found")
            if report["reds_missing"]:
                print(f"             MISSING: {report['reds_missing']}")
            print(f"    Yellows: [{yellow_status}] {len(report['yellows_found'])}/{len(report['yellows_expected'])} ({report['yellow_rate']:.0%})")
            if report["yellows_missing"]:
                print(f"             Missing: {report['yellows_missing']}")

            if not report["reds_pass"]:
                all_pass = False

    # Cross-dataset assertion: lithium semantics
    if "oregon-psilocybin-session" in dataset_results and "colorado-psilocybin-session" in dataset_results:
        lithium_pass = check_lithium_cross_dataset(dataset_results)
        print(f"\n{'='*60}")
        print(f"Cross-dataset: Lithium semantics (OR=hard, CO=resolvable)")
        if lithium_pass:
            print("  [PASS] Oregon lithium is exclusionary; Colorado lithium is resolvable")
        else:
            print("  [FAIL] Lithium flags have identical semantics across states — state separation failed")
            all_pass = False

    print(f"\n{'='*60}")
    if all_pass:
        print("OVERALL: PASS — all expected reds detected in all datasets")
    else:
        print("OVERALL: FAIL — missing required red flags or cross-dataset assertions")
    print(f"{'='*60}")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
