# PISA Implementation Reference

This document describes the current implementation of PISA (Participant Intake Screening Assistant) and where it departs from the original design document (v3).

PISA is an unvalidated prototype and must not be used to screen anyone; see [README.md](README.md#status-and-scope).

---

## Architecture Overview

PISA is a pure-Python HoloViz Panel application. It ingests intake forms and program context documents, then surfaces a prioritized list of evidence-linked flags for a human reviewer, who makes every decision. The demo programs and applicants it runs against are fabricated.

```
pisa/
  app.py                 # Entry point — panel serve pisa/app.py
  config.py              # Config loader (config.toml)
  model/
    provider.py          # ModelProvider protocol + ProviderStatus
    ollama.py            # OllamaProvider (local inference via Ollama HTTP API)
  parser/
    models.py            # Pydantic models: ApplicantRecord, ParsedSection, QAPair, etc.
    markdown.py          # Markdown form parser (identity tables, Q&A, medications, checklists)
    section_map.py       # Section heading → taxonomy key mapping (YAML-overridable)
  profile/
    models.py            # ScreeningProfile, HardCriterion, CautionCriterion, etc.
    builder.py           # Profile extraction from context docs via model
    loader.py            # ContextDocument loader, doc_type detection, hash computation
    store.py             # Profile persistence (JSON files in .profile_cache/)
  rules/
    engine.py            # Deterministic criteria matching (checklist fields, keywords, medications)
  pipeline/
    runner.py            # 6-step pipeline: rules → per-section → comprehensive → synthesis → merge → persist
    queue.py             # Serialized background thread execution queue
    schemas.py           # JSON schemas for section_analysis and synthesis responses
  store/
    db.py                # SQLite persistence (applicants, flags, followups, pipeline_runs)
  ui/
    setup_view.py        # View C: model health, context docs, profile approval
    applicant_list_view.py  # View A: filesystem discovery, Tabulator table, Select dropdown
    applicant_detail_view.py  # View B: flags, sections, follow-up workflow, live progress
prompts/
  profile_builder_v1.1.0.md     # extracts basis, citation, default_level, resolution_pathway
  section_analysis_v1.1.0.md   # includes basis/citation in flags, pathway-specific resolution
  comprehensive_review_v1.1.0.md  # whole-form + all criteria in one call for cross-section patterns
  synthesis_v1.1.0.md          # cross-section analysis with basis/citation rules
scripts/
  oracle_eval.py         # Evaluation runner (pixi run eval)
  seed_demo.py           # Seed demo data (pixi run seed)
demo-data/               # 4 fabricated programs (see demo-data/README.md)
  psilocybin-group-retreat/
  summit-series/
  oregon-psilocybin-session/
  colorado-psilocybin-session/
tests/
  fixtures/
    alt_format_intake.md # synthetic second-layout form for parser tests
config.toml              # Runtime configuration
pixi.toml                # Environment and tasks
```

---

## Core Principles — Implementation Status

| Principle | Status |
|---|---|
| 1. Safety first (escalate uncertainty) | Implemented: conservatism rules in merge/dedupe, rules engine matches hard criteria independently of the model. Recall is bounded by the profile's keyword lists, so this is not a completeness claim. |
| 2. Human decides (no decision language) | Implemented: enforced in all three prompt templates, no admit/deny logic in code |
| 3. Deterministic where it matters | Implemented: rules engine is pure-function keyword/checklist matching with unit tests |
| 4. Local inference | Implemented: SQLite and Ollama, no network calls beyond localhost. Not a privacy architecture: no auth, no encryption at rest, no audit of reads, no retention policy. |
| 5. Domain agnosticism | Implemented: 4 demo programs with different criteria and no hardcoded rules |
| 6. Auditability | Implemented: flags have history, PipelineRun records exist, Timeline tab shows merged audit trail (runs, flag changes, follow-ups) |

---

## Configuration

`config.toml` matches the design spec:

```toml
[model]
provider = "ollama"
model = "qwen3:30b-a3b"
temperature = 0.1
num_ctx = 16384
max_retries = 1
base_url = "http://localhost:11434"

[app]
data_dir = "demo-data"
db_path = "pisa.db"
```

---

## ModelProvider

The `ModelProvider` protocol is implemented as specified:

```python
class ModelProvider(Protocol):
    def analyze(self, prompt: str, response_schema: dict, max_tokens: int = 4096, temperature: float | None = None) -> dict: ...
    def health_check(self) -> ProviderStatus: ...
    @property
    def context_limit(self) -> int: ...
```

The `temperature` parameter allows pipeline steps to override the global config temperature. Per-section analysis uses the default (0.1), the comprehensive pass uses 0.2, and synthesis uses 0.3 — progressively more liberal as the task shifts from evidence extraction to associative cross-referencing.

`OllamaProvider` calls Ollama's `/api/generate` with `format: response_schema` for structured output. On validation failure, retries once with the error appended to the prompt; on second failure, raises `ModelResponseError` (callers emit a `data_quality` flag per design).

---

## Inputs

### Intake Forms

Currently supports **markdown only**. `.docx` and `.pdf` parsing (via `python-docx` and `pdfplumber`) are listed as dependencies in `pixi.toml` but the parser module only implements the markdown path.

The parser handles multiple form formatting styles:

- **Section headings:** Both `## Heading` and standalone `**BOLD HEADING**` lines (excluding bold lines ending with `:`, which are sub-headings/labels within a section)
- **Questions:** Both `**Bold question?**` format and plain-text questions (detected via `?` or `:` endings with qualifier heuristics when accumulating answers)
- **Medication tables:** Standard 4-column markdown tables (medication, dosage, indication, since)
- **Condition checklists:** Both 4-column paired format and simple 2-column (condition | yes/blank) format; detection triggers on "condition checklist", "checklist", or "following conditions" in the preceding question
- **Consumption tables:** Substance/amount pairs
- **Q/A tables (regulatory screening):** Two-column `| Question | Answer |` or `| Screen item | Answer |` tables are parsed into QAPair lists (question = col 1, answer = col 2, with deferred/blank detection). Maps headings "Oregon Client Information Form" and "Colorado Safety Screen" to the `regulatory_screening` taxonomy key.
- **Deferred answers:** Regex patterns for "let's discuss" / "prefer to talk" etc.
- **Blank answers:** Empty response detection

The section taxonomy mapping is implemented in `section_map.py` with YAML override support. `HIGH_STAKES_SECTIONS` defines sections that always flag deferred/blank answers regardless of whether a criterion explicitly targets them.

### Context Documents

Loaded from `<data_dir>/<program>/context/`. Each document's type is auto-detected from content metadata or filename. `CONFLICTING` files are excluded from normal loads (included only for conflict detection via `include_conflicting=True`).

### Demo Datasets

Four fabricated programs ship, 3 invented applicants each. See [demo-data/README.md](demo-data/README.md) for the fabrication notice and the caveat on the regulatory paraphrases.

- `psilocybin-group-retreat/` — Dale, Yuki, Owen. Center-defined criteria, no regulatory layer.
- `summit-series/` — Marcus, Priya, Tomas. Non-psychedelic comparison; the same medical facts carry different weight against altitude and exertion.
- `oregon-psilocybin-session/` — Nina, Marisol, Desmond. Oregon-style regulatory floor plus house standards. Tests: exclusionary reds, form-vs-narrative contradiction, CIF Q/A table parsing, 30-day window arithmetic, regulatory/house basis separation.
- `colorado-psilocybin-session/` — Ray, Aisha, Tom. Colorado-style clearance-pathway model. Tests: red-but-resolvable flags (hard_flag=false), pathway-named resolution criteria, facilitator-type routing, 5-year window check.

Each has `context/`, `forms/`, and `EXPECTED_FLAGS.md`.

The oracle eval (`pixi run eval`) includes a **cross-dataset assertion**: lithium must come out hard/exclusionary in the Oregon dataset (R-A1) and non-hard/resolvable in the Colorado dataset (R-3). If both produce the same semantics, dataset separation has failed.

`tests/fixtures/alt_format_intake.md` is a synthetic form in a second layout (no title, bold section headings, several questions per plain-text line, 2-column condition checklist). It exercises the parser's multi-format support, has no oracle, and belongs to no program.

---

## Screening Profile

The `ScreeningProfile` model (schema version 2):
- `hard_criteria` with `DetectionSpec` (checklist_fields, keywords, medication_names, sections), plus `basis` ("regulatory"/"house") and `citation` (rule reference)
- `caution_criteria` with the same detection structure, plus `default_level` ("yellow"/"red"), `basis`, `citation`, and `resolution_pathway`
- `medication_classes_of_concern`
- `program_demands` with `interacts_with`
- `positive_indicators`
- `ground_rules`
- `conflicts` (detected post-build)

**Key semantic:** A caution criterion with `default_level: "red"` produces a red flag with `hard_flag: false` — serious but resolvable via the documented pathway. This models Colorado's clearance-pathway system where lithium is the strictest tier but NOT exclusionary.

The profile builder (v1.1.0 prompt) uses the model to extract the profile from context documents, including basis/citation/pathway fields. Conflict detection (`detect_conflicts`) checks for medication-change advice, criteria relaxation, and SSRI-related conflicts. Profiles are cached to `.profile_cache/` keyed by document-content hash + schema version (old-schema profiles are auto-rebuilt).

The approval flow is implemented: analysis is blocked until a profile is approved.

---

## Rules Engine

Fully deterministic, matching the design's Step 1. Iterates `hard_criteria` and `caution_criteria` detection specs against the structured record:
1. Checklist field matching (checked conditions)
2. Medication name matching (across all sections)
3. Keyword matching in relevant sections with negation detection
4. **Question-keyword matching** for regulatory screening Q/A tables: when a keyword appears in the question text and the answer is affirmative ("Yes..."), the match fires
5. **Window check notes**: when a matched answer contains a relative-time phrase ("three weeks ago", "in 2017"), the flag's rationale notes that the window needs verifying. This is written into the rationale rather than a separate field, because the rationale is what the flag card renders and the database stores.

Caution criteria respect `default_level`: if set to "red", the emitted flag has `level: "red"` but `hard_flag: false`, and inherits `resolution_pathway` into `resolution_criteria`.

Emitted flags carry `basis` and `citation` from the criterion that produced them, enabling the UI to show whether a flag is regulatory or house policy.

Negation detection prevents false positives on clearly negative answers (e.g., "No, never" or "not suicidal"). Keywords in short denial-pattern answers are suppressed; longer multi-sentence answers are not suppressed.

Additional rules engine behaviors:

- **Drug class expansion:** `DRUG_CLASS_MAP` maps class names (SSRIs, SNRIs, MAOIs, etc.) to individual drug names so the rules engine catches specific medications when the profile specifies a class
- **Word-boundary matching:** Keywords ≤3 characters use regex word boundaries to prevent substring noise (e.g., "21" matching inside "2021")
- **A single keyword match fires:** one distinct match is enough. Requiring two produced false negatives on exclusionary criteria, so a match on one general single-word keyword now flags with a caveat in the rationale instead of being suppressed.
- **All matching evidence is kept, ordered most-specific first** (multi-word phrases, then longer keywords). Filtering evidence by keyword length discarded the substantiating quote whenever a longer keyword matched somewhere irrelevant.
- **Whole-form rescan for hard criteria:** a hard criterion that matches nothing in the sections it targets is retried against the rest of the form, and the rationale names where the match was found. Caution criteria keep the narrow scope.
- **Section name resolution:** Profile-authored section names (e.g., "Intake Packet - Safety Screen") are resolved through the section map to taxonomy keys (e.g., "regulatory_screening") so criteria target names match the parser's keys.

---

## Analysis Pipeline

The 6-step pipeline from the design is implemented with one significant optimization departure:

### Step 0 — Parse Quality Validation
If the parser extracts fewer than 3 sections with content, a yellow `data_quality` flag is emitted recommending manual review of the original form. This catches forms with unrecognized formatting or truncated content before the pipeline spends model calls on incomplete data.

### Step 1 — Rules Engine
Unchanged from design. Pure deterministic matching.

### Step 2 — Per-Section Model Analysis

**DEPARTURE: Section Partitioning (Batch/Skip/Individual)**

The design specifies one model call per section. The implementation partitions sections into three tiers to reduce model calls from ~14 to ~5:

- **Skip** — sections with 0 relevant criteria get a canned summary ("No relevant criteria; skipped model analysis") with no model call
- **Batch** — sections with few criteria (< 5) and few items (< 10) are combined into a single model call
- **Individual** — sections with >= 5 criteria AND >= 10 items get their own dedicated model call

The batch call uses section-key markers (`[section_key]`) in the prompt and distributes the combined response back to per-section results by parsing markers in the summary and matching flags by evidence section.

### Step 3 — Comprehensive Whole-Form Pass

Sends the ENTIRE intake form + ALL criteria (hard + caution) + program demands + ground rules in a single model call using the `comprehensive_review_v1.1.0.md` prompt. Temperature: 0.2 (slightly more liberal than per-section's 0.1 to catch less obvious connections).

Purpose: catches cross-section patterns, medication-criterion connections, timeline/window checks, implicit concerns, and positive indicators that per-section analysis misses because it only sees one section at a time. Returns flags in the same schema as per-section analysis. The full form + all criteria is ~7k tokens, well within the 16k context window.

### Step 4 — Synthesis Pass
One model call receiving all section summaries, all candidate flags from ALL THREE prior sources (rules engine, per-section model, AND comprehensive pass), and deferred/blank answers. Temperature: 0.3 (most liberal — its job is associative/creative: connecting flags, proposing merges).

### Step 5 — Merge & Dedupe

Implemented with additional heuristics beyond the design:

- **Title-based deduplication** (70% word overlap threshold) merges model flags that describe the same concern with different wording
- **Criterion-ref deduplication against rule flags** merges model flags whose cited criteria already appear in rule flags
- **Criterion-ref + category deduplication across model flags** merges model flags that share at least one criterion_ref and the same category (catches same concern with completely different titles)
- **Proposed merges** from the synthesis pass are applied (primary keeps highest level/severity, unions evidence and follow-ups)
- **Criterion-ref based merge for proposed merges** — the synthesis pass proposes merges by title, but the code now extracts criterion IDs from titles (e.g., "R-4" from "[R-4] Other psychotropic...") and matches against evidence `criterion_ref` fields. Falls back to fuzzy title matching only when no ref is found.
- **Automatic criterion-ref consolidation** — after processing proposed merges, an `_auto_merge_by_criterion` pass groups ALL flags sharing the same `criterion_ref` and merges them into one flag (preferring rule-sourced as primary, keeping highest severity). This is model-independent and ensures that when multiple pipeline stages flag the same criterion, only one consolidated flag appears.
- Conservatism enforced by one comparator, `_strictness_key`: a hard flag outranks any soft flag, then level, then severity. Model output can add evidence and follow-ups to a rule flag, but cannot delete it, lower its level, or attach a resolution pathway to a hard flag.
- **Atomic flag replacement on completion:** Intermediate flags shown during progress are replaced by the final deduplicated set via `replace_flags()` (DELETE + INSERT) to prevent stale duplicates accumulating across runs

### Step 6 — Persist
Flags, summaries, and PipelineRun records written to SQLite. The `PipelineRun` progress JSON includes `overall_notes` from synthesis, surfaced in the UI as a post-screening summary.

---

## Execution Model

### DEPARTURE: Direct Callbacks Instead of Polling

The design specifies:
> views poll [PipelineRun status] with `pn.state.add_periodic_callback` (~1s)

The implementation uses **direct callbacks via `pn.state.execute`** from the background thread instead:

- `UIProgressCallback` receives progress events (section start/done, batch start, synthesis start, complete, failure)
- Each event dispatches a UI mutation via `pn.state.execute()` for thread-safe updates
- Flags are incrementally persisted and rendered as each section completes (not just at the end)
- No periodic polling is used

This provides more responsive feedback (immediate updates vs 1s poll interval) and simplifies state management.

### Background Queue

`PipelineQueue` is a module-level singleton running a daemon thread. Runs are serialized (one at a time) as specified. The queue consumer calls `run_pipeline()` and invokes the `on_complete` callback when done. Supports cancellation via `cancel()` which clears the queue and signals the worker to stop after the current run completes.

---

## Frontend

### DEPARTURE: panel-material-ui Instead of FastListTemplate

The design specifies:
> A single served Panel application using `pn.template.FastListTemplate`

The implementation uses **`panel-material-ui` (pmui)** with `pmui.Page`:

```python
page = pmui.Page(
    title="PISA — Participant Intake Screening Assistant",
    sidebar=[...],
    main=[pmui.Tabs(("Setup", ...), ("Review", ...))],
    theme_config=THEME,
)
```

Material UI components used throughout: `pmui.Button`, `pmui.Typography`, `pmui.Alert`, `pmui.Chip`, `pmui.Select`, `pmui.Row`, `pmui.Column`, `pmui.Tabs`, `pmui.Divider`, `pmui.LinearProgress`, `pmui.MenuButton`, `pmui.Dialog`, `pmui.Page`.

Standard Panel components still used where pmui equivalents don't support needed features: `pn.widgets.Tabulator`, `pn.widgets.MultiChoice`, `pn.widgets.TextAreaInput`, `pn.widgets.CheckBoxGroup`, `pn.pane.Markdown`, `pn.pane.Alert` (for dynamic `.object` mutation), `pn.pane.HTML`, `pn.Card`.

### DEPARTURE: Filesystem Discovery Instead of Upload

The design specifies:
> Upload area (`pn.widgets.FileDropper`) for new intake forms

The implementation uses **filesystem-based discovery**:

- `_sync_from_filesystem()` scans `<data_dir>/<program>/forms/*.md` for new files
- Auto-imports any `.md` files not already in the database (deduplication by path)
- A "Refresh" button re-scans the filesystem
- No upload widget exists; users place files directly in the program directory

### View A — Applicant List

- **Global program selector** in sidebar — scopes both list and setup views
- Tabulator table with HTML-formatted columns: Name, State (colored chip), Flags (colored cluster: `2R · 1Y`), Acknowledged (ack/total with green when complete), Last Screened (humanized), Duration
- Table cells are non-editable (`disabled=True`) while retaining row-click selection
- Row-click selection via `selectable=1` + `.on_click()` handler
- Refresh button (re-scans filesystem)
- Run All button (queues all applicants in current program) with:
  - Per-applicant progress: "queued" and "⟳ screening" chips in the State column
  - Incremental table updates: Flags, Acknowledged, Last Screened, Duration cells patch in real-time as each applicant completes
  - Global progress bar with done/total counter
- Overflow menu (⋮) with "Stop screening" to cancel all pending/active runs
- Dismissable alert messages (import notifications, completion summaries)

### View B — Applicant Detail

- **Sticky header** (CSS `position: sticky`) with:
  - Applicant name + demographic line (age · pronouns · occupation)
  - Dataset chip + colored review state chip + state selector
  - Run Screening button + overflow MenuButton (Purge with Dialog confirmation + name-typing guard)
- **Clearance gating:** Selecting "cleared" with open red/yellow flags shows a non-blocking warning but allows the transition (reviewer is final authority). State changes are logged to the timeline with actor name.
- **Overall summary** from synthesis, with "AI summary · advisory only" caption and "Generated by [model]" footer
- **Determinate progress bar** (`value = sections_done / sections_total`) during runs with incremental flag display
- **Detail tabs** (pmui.Tabs): Flags / Form / Follow-ups / Timeline
- **Flags tab:**
  - Count chips by level and status (Red 2, Yellow 3, Open 5, Resolved 1)
  - Expand all / Collapse all buttons
  - Open flags grouped first, Resolved in a collapsed card
  - Each flag card: 4px left border in level color, level+HARD+section chips in header
  - Body: rationale first, evidence as blockquotes with criterion badges (`<span class="pisa-criterion-badge">A1</span>`), suggested lookup chips, recommended follow-up bullets, resolution criteria in styled tinted box
  - **Follow-up count indicator:** 💬 badge with count in header chips when a flag has linked follow-ups
  - **Inline follow-up history:** Collapsible "Follow-ups (N)" card nested within each flag body (11px header, max-height 200px scrollable), showing timestamp + note + response for each
  - **Per-flag inline actions:**
    - Follow-up button → drawer with suggested questions, reviewer note, applicant response, level selector (red/yellow/green, defaults to current level — no change if left unchanged). Updates flag card border color, header badge, and follow-up section in-place on save.
    - Acknowledge button (green outlined, instant one-click) → collapses card, dims opacity, adds "acknowledged ✓" badge to header. No form required.
    - Level button → drawer with level picker (any level except current) and required reason field. Updates card border color in-place.
    - Reopen button (on acknowledged flags) → restores card to open state with full action buttons.
  - **Reviewer Flags section:** Separate section with "Add Flag" form (title, level, category, rationale). Both system and reviewer flags follow the same acknowledge/reopen pattern.
- **Form tab:** Collapsible section cards with Q&A, medications, checklists, consumption
- **Follow-ups tab:**
  - Existing follow-ups as cards with informative headers (`"2026-07-15 — Asked about lithium timeline... [resolved]"`)
  - General note form for non-flag-specific observations
- **Timeline tab:** Merged audit trail (runs, flag creations, level changes, acknowledgements, reopens, review state transitions, follow-ups) sorted newest-first with actor attribution

### View C — Program Setup

- Three numbered cards: "1. Model Connection", "2. Context Documents", "3. Screening Profile"
- Model health check with ✓/⚠/✕ symbols and re-check button
- Compact config info line (provider · model · temp · ctx)
- Context document listing with checkbox selection (including test-only CONFLICTING files)
- Profile cache detection ("Use Cached" button)
- Build Profile button (runs on background thread)
- Profile display (criteria counts, collapsible tables for hard/caution criteria, ground rules list)
- Conflict warnings (Alert with appropriate severity)
- Approve Profile button

### Sidebar

- Dataset selector (global scope)
- Flag minimap: live list of flag dots (level color) + criterion badge + truncated title, updates on applicant selection and on flag acknowledge/reopen actions
- Advisory disclaimer at bottom

### Settings

- **Reviewer name** (Setup tab, top card) — auto-saved to `settings` table, associated with all timeline entries (acknowledge, reopen, level changes, state transitions)

### DEPARTURE: Cross-View Communication

The design specifies param-driven state classes. The implementation uses:

- `request_list_refresh = param.Event()` on `ApplicantDetailView` — triggers full table refresh on the list view
- `screening_applicant_id = param.String()` on `ApplicantDetailView` — wired in `app.py` to patch the list table's State cell with "⟳ screening" while a run is active, and refresh on completion
- These events fire after purge, after screening completes, after review state changes, after flag acknowledge/reopen, and after follow-up save

---

## Data Model

### ApplicantRecord (Pydantic)

Matches design closely. Stored in SQLite as JSON blobs for `identity_json` and `sections_json`.

### Flags

Schema matches the design spec. Stored in a normalized `flags` table with JSON columns for evidence, recommended_followup, suggested_lookup, and history.

### PipelineRun

Extends the design with:
- `completed_at` (ISO8601 timestamp)
- `duration_seconds` (float, for table display)

### FollowUp

Matches design. Stored in `followups` table.

---

## Safety Guardrails — Implementation Status

| # | Guardrail | Status |
|---|---|---|
| 1 | Rules engine sole authority for hard criteria | Implemented |
| 2 | Profile must be approved before analysis | Implemented |
| 3 | No admit/deny language | Enforced in prompts; no post-processing strip |
| 4 | Conservative merge: highest level wins | Implemented in `_merge_and_dedupe()` |
| 5 | Deferred/blank on high-stakes sections generate flags | Implemented: deterministic yellow flags emitted in Step 1b for deferred (severity 4) and blank (severity 3) answers in sections with relevant criteria |
| 6 | Failed/incomplete analysis is loud | Implemented: `data_quality` flags emitted, `incomplete` status, UI alert |
| 7 | Human confirmation for flag transitions | Implemented for follow-up workflow; auto-transition from "unreviewed" to "in_review" on run completion is an exception |
| 8 | All data local; per-applicant purge | Implemented |
| 9 | Never proposes medication changes | Enforced in prompts; no output post-processing |

### Guardrail Departures

- **Guardrail 3 (post-processing):** The design says "post-process model output to strip decision phrasing." This is not implemented; reliance is entirely on prompt instructions.
- **Guardrail 9 (post-processing):** Same as guardrail 3 — no output post-processing for medication-change language.

---

## Features Not Yet Implemented

| Design Feature | Status |
|---|---|
| `.docx` / `.pdf` form parsing | Dependencies installed; parser only handles markdown |
| Section-summary left column (View B) | Section summaries exist in pipeline output but not displayed in their own column |
| Evidence cross-links (click evidence → expand section) | Not implemented |
| Copy button for follow-up questions | Not implemented (requires JS clipboard API) |
| Scoped re-evaluation on follow-up | Follow-up capture exists; scoped re-eval (steps 2-4 on linked sections) not implemented |
| Unmapped content generates yellow `data_quality` flag | Unmapped content is stored but no automatic flag is generated. Low section count (< 3) does generate a `data_quality` flag. |
| Output post-processing (strip decision language, medication advice) | Not implemented |
| Simultaneous browser session isolation | Untested; module-level `pipeline_queue` is shared across sessions |
| Typography enforcement (Inter/Source Sans font) | Not implemented (requires web font loading) |

---

## Known Gaps

Where the design's claims outrun what the code can actually promise. These are the honest limits of the prototype, not a backlog.

**Recall is bounded by the profile.** The rules engine can only match what the profile builder extracted into a `DetectionSpec`. If the model writing the profile omits a keyword or misses a medication brand name, the deterministic layer is silent and the only remaining coverage is the model passes. `DRUG_CLASS_MAP` expands common classes, but a form saying `Lithobid` or `Li carbonate` depends on that map having the alias. The layer bounds model variance; it does not bound misses.

**Section targeting is a guess, and hard criteria compensate by widening.** A criterion's `detection.sections` comes from the profile builder, which can point a criterion at the wrong section or at a name the section map does not resolve. Oregon's lithium question lives in the regulatory screening block rather than the medication list, so a criterion aimed at `medications` found nothing on a form that answered "Yes". A hard criterion that matches nothing in its declared sections now rescans the rest of the form and says so in the flag's rationale. Caution criteria keep the narrow scope, since widening every criterion would bury the reviewer in matches from unrelated sections. See `TestHardCriterionSectionFallback` in `tests/test_rules_engine.py`.

**Weak keyword matches are surfaced, not resolved.** A criterion whose only hit is one general single-word keyword still produces a flag, with a caveat in the rationale. That trades false positives for recall on purpose, because a missed red is worse here than an extra one the reviewer dismisses. It does mean flag lists include noise.

**Consolidation preserves severity, not full provenance.** When two flags merge, the survivor carries one `basis` and one `citation`. Merging folds the other flag's evidence, follow-ups, and criterion ID into the survivor and its history, but a reviewer reading only the chip row sees a single basis for a flag that may span a regulatory and a house criterion. The per-evidence `criterion_ref` is where the full picture lives.

**Fuzzy title matching drives merge proposals.** `_find_flag_by_ref_or_title` falls back to a 0.7 word-overlap match when a synthesis proposal carries no criterion ID. Rule flags are protected from being deleted this way, but two distinct model flags with similar titles can still be merged into one.

**Profile approval is a human gate with no verification.** Nothing checks that an approved profile faithfully represents the source documents. If the reviewer approves a misextracted criterion, every run inherits the error. This is the single largest unaddressed risk in the design, and it is a process problem rather than a code problem.

**Nothing post-processes model text.** Prompts forbid decision language and medication advice, and no code enforces it. A model that ignores the instruction produces output that reaches the reviewer verbatim.

**A prompt can only ask for what its schema permits.** Response schemas are passed to the provider as the structured-output format, so a property absent from the schema is a property the model cannot return no matter what the prompt says. Three passes had drifted from their schemas, which is why `basis` and `citation` never reached a flag. `tests/test_prompt_schemas.py` now asserts each prompt's documented JSON block matches the constant enforced against it, and all flag-emitting passes share one `FLAG_ITEM_SCHEMA`.

**The eval is a small fixed corpus.** Four programs, twelve applicants, hand-authored oracles. It catches regressions in the behaviors it encodes and says nothing about generalization.

---

## Performance

The design expected "~15-20 model calls; roughly 2-5 minutes."

With the batching optimization and comprehensive pass:
- A typical applicant now produces ~6 model calls: ~3 individual + 1 batch + 1 comprehensive + 1 synthesis
- The comprehensive pass adds ~15-20 seconds but significantly improves flag coverage for cross-section patterns
- Measured run time: ~60 seconds for Owen (lighter form), expected 2-5 minutes for heavier forms like Dale
- Well within the design's time budget, significantly below the naive 14-call approach

### Temperature Tiers

| Pipeline Step | Temperature | Rationale |
|---|---|---|
| Per-section analysis | 0.1 (default) | Conservative — generating evidence quotes that must be precise |
| Comprehensive pass | 0.2 | Slightly more liberal — finding less obvious cross-section connections |
| Synthesis | 0.3 | Most liberal — associative task (connecting flags, proposing merges) |
| Profile builder | 0.1 (default) | Conservative — structured extraction from documents |

---

## Environment

Tasks:
- `pixi run app` — serve the Panel app
- `pixi run test` — run pytest, including the integration test that needs a live Ollama
- `pixi run test-unit` — everything that does not need a model; what CI runs
- `pixi run eval` — oracle evaluation (requires a model)
- `pixi run seed` — seed demo data

`.github/workflows/test.yml` runs `test-unit` on push and pull request against `main`. CI performs no inference, so the pipeline's model passes are exercised only through mocked providers and the schema tests.

Additional dependency beyond design: `pyyaml` (for section map overrides) and `panel-material-ui` (installed via pip, not in pixi.toml).

---

## Summary of Major Departures

1. **UI framework:** `pmui.Page` with Material UI components instead of `pn.template.FastListTemplate`
2. **Applicant discovery:** Filesystem scanning instead of file upload widget
3. **Pipeline optimization:** Section partitioning (skip/batch/individual) instead of one-call-per-section
4. **Progress reporting:** Direct callbacks via `pn.state.execute` instead of periodic polling
5. **Flag deduplication:** Title-overlap (70% word match), criterion-ref+category overlap heuristics, AND automatic criterion-ref consolidation (model-independent grouping of all flags sharing the same criterion_ref across pipeline stages) added beyond design spec
6. **Incremental flag display:** Flags shown in UI as each section completes for responsiveness; final deduplicated set replaces all on completion
7. **No output post-processing:** Guardrails 3 and 9 rely solely on prompt instructions, not code enforcement
8. **No scoped re-evaluation:** Follow-up capture exists but does not trigger partial pipeline re-runs
9. **Auto review-state transition:** Pipeline completion auto-moves "unreviewed" to "in_review" (design requires manual-only transitions after review begins)
