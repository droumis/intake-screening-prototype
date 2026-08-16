"""Integrity checks on the shipped demo programs.

These run without a model. They catch the ways demo data rots: a form that stops
parsing after an edit, an oracle that cites a criterion nobody defines any more,
or an applicant letter the eval runner cannot see.
"""

import re
from pathlib import Path

import pytest

from pisa.parser.markdown import parse_file
from pisa.profile.loader import load_context_documents

DEMO_DATA = Path(__file__).parent.parent / "demo-data"
PROGRAMS = sorted(p for p in DEMO_DATA.iterdir() if p.is_dir())
FORMS = sorted(DEMO_DATA.glob("*/forms/*.md"))

# Criterion IDs use two schemes: "R-A1" in the state datasets, "A1" in the
# others. A definition is either bold at the start of its bullet ("**R-3. ...**")
# or a markdown heading ("### R-2. ..." for one that introduces sub-pathways).
_ID = r"[A-Z]{1,2}-[A-Z]?\d{1,2}|[A-Z]\d{1,2}"
ID_DEFINITION = re.compile(rf"(?:\*\*|^#{{1,6}}\s*)({_ID})\b", re.MULTILINE)
ID_REFERENCE = re.compile(rf"\b({_ID})\b")


def _defined_ids(program: Path) -> set[str]:
    criteria = program / "context" / "screening_criteria.md"
    if not criteria.exists():
        return set()
    return set(ID_DEFINITION.findall(criteria.read_text(encoding="utf-8")))


ALL_DEFINED_IDS = set().union(*(_defined_ids(p) for p in PROGRAMS)) if PROGRAMS else set()


def test_programs_are_discovered():
    assert len(PROGRAMS) == 4, [p.name for p in PROGRAMS]


@pytest.mark.parametrize("program", PROGRAMS, ids=lambda p: p.name)
class TestProgramShape:
    def test_has_context_documents(self, program):
        docs = load_context_documents(program / "context")
        types = {d.doc_type for d in docs}
        assert "screening_criteria" in types
        assert "program_description" in types
        assert "unknown" not in types, "a context document's type was not detected"

    def test_has_three_applicants_lettered_a_to_c(self, program):
        """oracle_eval.py matches applicant_([A-C])_, so a D would be skipped."""
        forms = sorted((program / "forms").glob("applicant_*.md"))
        letters = [re.search(r"applicant_([A-Z])_", f.name).group(1) for f in forms]
        assert letters == ["A", "B", "C"], f"{program.name}: {letters}"

    def test_has_an_oracle(self, program):
        assert (program / "EXPECTED_FLAGS.md").exists()

    def test_criteria_document_defines_criteria(self, program):
        assert len(_defined_ids(program)) >= 10


@pytest.mark.parametrize("form", FORMS, ids=lambda f: f"{f.parent.parent.name}/{f.name}")
class TestFormsParse:
    def test_parses_with_a_name_and_sections(self, form):
        record = parse_file(form)
        assert record.display_name and record.display_name != "Unknown"
        # Under 3 sections is what triggers the app's data_quality warning.
        assert len(record.sections) >= 3, f"only parsed {list(record.sections)}"

    def test_no_unmapped_content(self, form):
        """Unmapped content means a heading the section map does not know."""
        record = parse_file(form)
        assert record.unmapped_content == "", record.unmapped_content[:200]

    def test_is_marked_fabricated(self, form):
        """Every form must say it is invented, near the top where it is read."""
        head = form.read_text(encoding="utf-8").split("\n")[:6]
        assert any("Fabricated demo form" in line for line in head), form.name


@pytest.mark.parametrize("program", PROGRAMS, ids=lambda p: p.name)
def test_oracle_only_cites_criteria_that_exist(program):
    """A cited criterion must be defined somewhere in the shipped data.

    Checked against the union across programs rather than per program, because
    the cross-dataset assertion in each state oracle deliberately names the other
    state's criterion.
    """
    oracle = (program / "EXPECTED_FLAGS.md").read_text(encoding="utf-8")
    cited = set(ID_REFERENCE.findall(oracle))
    unknown = sorted(cited - ALL_DEFINED_IDS)
    assert not unknown, f"{program.name} cites undefined criteria: {unknown}"


def test_lithium_resolves_oppositely_across_the_two_state_oracles():
    """The project's headline claim, asserted from the documents themselves.

    The same medication must be exclusionary in one program and resolvable in the
    other, or the datasets no longer demonstrate anything.
    """
    oregon = (DEMO_DATA / "oregon-psilocybin-session" / "context" / "screening_criteria.md").read_text(encoding="utf-8")
    colorado = (DEMO_DATA / "colorado-psilocybin-session" / "context" / "screening_criteria.md").read_text(encoding="utf-8")

    assert "lithium" in oregon.lower()
    assert "lithium" in colorado.lower()
    # Oregon states a categorical exclusion; Colorado states no categorical
    # participant exclusions and routes risk through clearance pathways.
    assert "R-A1" in oregon
    assert re.search(r"no categorical participant exclusions", colorado, re.IGNORECASE)
    assert re.search(r"clearance|pathway", colorado, re.IGNORECASE)
