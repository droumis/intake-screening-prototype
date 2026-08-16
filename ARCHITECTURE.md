# PISA Architecture

Visual overview of the system's data flow and component relationships.

PISA is an unvalidated prototype and must not be used to screen anyone. The diagrams below describe how the code is wired, not verified behavior; see [README.md](README.md#status-and-scope).

---

## Pipeline Flow

The screening pipeline processes one applicant at a time through 6 sequential steps. The rules engine is deterministic and model-independent; steps 2-4 use the local LLM with progressively increasing temperature.

```mermaid
flowchart TD
    subgraph INPUTS["Inputs"]
        FORM[/"Intake Form (.md)"/]
        PROFILE[/"Screening Profile<br/>(hard + caution criteria,<br/>program demands, ground rules)"/]
    end

    subgraph PIPELINE["Analysis Pipeline"]
        direction TB
        S1["<b>Step 1: Rules Engine</b><br/>Deterministic keyword, medication,<br/>checklist matching<br/><i>temp: N/A (no model)</i>"]
        S2["<b>Step 2: Per-Section Model</b><br/>Each section vs relevant criteria<br/><i>temp: 0.1 (conservative)</i>"]
        S3["<b>Step 3: Comprehensive Pass</b><br/>Full form + all criteria in one call<br/>Cross-section patterns<br/><i>temp: 0.2 (moderate)</i>"]
        S4["<b>Step 4: Synthesis</b><br/>All candidate flags + summaries<br/>Merge proposals, cross-section flags<br/><i>temp: 0.3 (liberal)</i>"]
        S5["<b>Step 5: Merge & Dedupe</b><br/>Subsumption, criterion-ref merge,<br/>proposed merges, auto-consolidation<br/><i>temp: N/A (code only)</i>"]
        S6["<b>Step 6: Persist</b><br/>Flags + run record → SQLite"]

        S1 --> S2 --> S3 --> S4 --> S5 --> S6
    end

    FORM --> S1
    PROFILE --> S1
    FORM --> S2
    PROFILE --> S2
    FORM --> S3
    PROFILE --> S3

    S1 -->|rule flags| S4
    S2 -->|model flags + summaries| S4
    S3 -->|comprehensive flags| S4
    S4 -->|merge proposals<br/>+ cross-section flags| S5

    subgraph OUTPUT["Output"]
        FLAGS[("Deduplicated Flags<br/>(red / yellow / green)")]
        NOTES["Overall Notes"]
        RUN["Pipeline Run Record"]
    end

    S6 --> FLAGS
    S6 --> NOTES
    S6 --> RUN
```

---

## System Architecture

```mermaid
flowchart LR
    subgraph UI["Panel UI (browser)"]
        SETUP["Setup View<br/>Profile building & approval"]
        LIST["Applicant List<br/>Table + Run All"]
        DETAIL["Applicant Detail<br/>Flags, Form, Follow-ups, Timeline"]
        SIDEBAR["Sidebar<br/>Program selector, Flag minimap"]
    end

    subgraph CORE["Core"]
        PARSER["Markdown Parser<br/>→ ApplicantRecord"]
        BUILDER["Profile Builder<br/>Context docs → ScreeningProfile"]
        ENGINE["Rules Engine<br/>Deterministic matching"]
        RUNNER["Pipeline Runner<br/>6-step orchestration"]
        QUEUE["Pipeline Queue<br/>Background thread"]
    end

    subgraph INFRA["Infrastructure"]
        OLLAMA["Ollama<br/>Local LLM (qwen3:30b-a3b)"]
        SQLITE[("SQLite<br/>applicants, flags,<br/>followups, runs")]
        CACHE[(".profile_cache/<br/>JSON profiles")]
        FS[/"Filesystem<br/>demo-data/*/forms/<br/>demo-data/*/context/"/]
    end

    SIDEBAR -->|program switch| SETUP
    SIDEBAR -->|program switch| LIST
    LIST -->|select applicant| DETAIL
    LIST -->|Run All| QUEUE
    DETAIL -->|Run Screening| QUEUE

    SETUP -->|Build Profile| BUILDER
    BUILDER -->|extract| OLLAMA
    BUILDER -->|save| CACHE

    QUEUE --> RUNNER
    RUNNER --> ENGINE
    RUNNER -->|per-section, comprehensive, synthesis| OLLAMA
    RUNNER -->|persist| SQLITE

    PARSER -->|parse forms| FS
    BUILDER -->|read context docs| FS

    DETAIL -->|read flags| SQLITE
    LIST -->|read applicants| SQLITE
    SETUP -->|load profile| CACHE
```

---

## Rules Engine Detail

The deterministic layer matches what the profile spelled out, without model involvement. Its recall is bounded by the profile's keyword and medication lists, so this is a floor on model variance rather than a completeness claim.

```mermaid
flowchart TD
    RECORD["ApplicantRecord<br/>(parsed sections)"]
    PROFILE2["ScreeningProfile<br/>(hard + caution criteria)"]

    subgraph CHECKS["Detection Checks (per criterion)"]
        CL["Checklist Fields<br/>Checked conditions"]
        MED["Medication Names<br/>+ Drug Class Expansion<br/>(DRUG_CLASS_MAP)"]
        KW["Keyword Search<br/>+ Word Boundary Matching<br/>+ Negation Detection<br/>+ Whole-form rescan<br/>(hard criteria only)"]
    end

    subgraph RESOLVE["Section Resolution"]
        SM["Section Map<br/>Profile names → taxonomy keys"]
    end

    RECORD --> CHECKS
    PROFILE2 --> CHECKS
    PROFILE2 --> RESOLVE
    RESOLVE --> CHECKS

    CHECKS -->|evidence items| FLAG_BUILD["Flag Builder<br/>criterion_id, level, basis,<br/>citation, resolution_pathway"]
    FLAG_BUILD --> RULE_FLAGS[/"Rule Flags<br/>(deterministic, never downgraded<br/>by the model)"/]
```

---

## Merge & Deduplication Flow

Step 5 consolidates flags from all sources into a non-redundant set. Every consolidation path uses one comparator, `_strictness_key`, which ranks a hard flag above any soft flag, then level, then severity. Consolidation may raise a flag's severity and never lowers it.

```mermaid
flowchart TD
    RF["Rule Flags"]
    MF["Model Flags<br/>(per-section + comprehensive)"]
    SF["Synthesis Flags<br/>(cross-section + merge proposals)"]

    SUB["Subsumption<br/>Same medication evidence →<br/>fold weaker into stricter<br/>(hard flags never subsumed)"]
    RF --> SUB

    subgraph DEDUP["Deduplication"]
        D1["Rule flags are anchors:<br/>model output can add to them,<br/>never delete or downgrade them"]
        D2["Model flags deduped<br/>against rule flags<br/>(shared criterion_ref)"]
        D3["Model flags deduped<br/>against each other<br/>(title overlap OR criterion_ref + category)"]
    end

    SUB --> D1
    MF --> D2
    MF --> D3

    PM["Proposed Merges<br/>(from synthesis)<br/>rule-flag victims refused"]
    SF --> PM

    REF_MATCH["Criterion-Ref Matching<br/>Extract ID from title → match<br/>against normalized criterion_refs<br/>Fallback: fuzzy title match"]
    PM --> REF_MATCH

    AUTO["Auto-Merge by Criterion<br/>Group flags sharing a<br/>criterion_ref → consolidate into<br/>the strictest primary"]

    DEDUP --> AUTO
    REF_MATCH --> AUTO

    AUTO --> FINAL[/"Final Flag Set<br/>Deduplicated, consolidated"/]
```

Three invariants hold across this step, each covered by tests in `tests/test_pipeline.py`:

1. A rule flag is never deleted by model output. A synthesis merge proposal naming a rule flag as a victim is refused and logged.
2. `hard_flag` propagates on merge and is never lost, and a hard flag never acquires `resolution_criteria`. That is what keeps an unresolvable exclusion from turning into a resolvable red.
3. `basis` and `citation` are never inherited across criteria, since they describe the criterion that produced the flag.

---

## Profile Lifecycle

```mermaid
sequenceDiagram
    participant User
    participant Setup as Setup View
    participant Builder as Profile Builder
    participant Ollama
    participant Cache as .profile_cache/

    User->>Setup: Select program
    Setup->>Cache: Check for cached profile (by content hash)
    alt Cache hit
        Cache-->>Setup: Load cached profile
        Setup-->>User: Show profile (Use Cached)
    else Cache miss
        User->>Setup: Click "Build Profile"
        Setup->>Builder: Extract from context docs
        Builder->>Ollama: Send docs + extraction prompt
        Ollama-->>Builder: Structured profile JSON
        Builder->>Builder: Validate + detect conflicts
        Builder->>Cache: Save profile (keyed by hash)
        Builder-->>Setup: Return profile
        Setup-->>User: Show profile for review
    end
    User->>Setup: Click "Approve"
    Setup->>Cache: Mark approved=true
    Note over User,Cache: Screening now unblocked
```

---

## Data Flow During Screening

```mermaid
sequenceDiagram
    participant User
    participant UI as Detail View
    participant Queue as Pipeline Queue
    participant Runner
    participant Engine as Rules Engine
    participant Ollama
    participant DB as SQLite

    User->>UI: Click "Run Screening"
    UI->>Queue: Enqueue (record, profile, callback)
    Queue->>Runner: run_pipeline()

    Runner->>Engine: Step 1: run_rules_engine(record, profile)
    Engine-->>Runner: rule_flags[]

    loop Per section (batch/individual)
        Runner->>Ollama: Step 2: analyze section
        Ollama-->>Runner: section flags + summary
    end

    Runner->>Ollama: Step 3: comprehensive pass (full form)
    Ollama-->>Runner: comprehensive_flags[]

    Runner->>Ollama: Step 4: synthesis (all candidates)
    Ollama-->>Runner: cross_section_flags + proposed_merges + notes

    Runner->>Runner: Step 5: merge & dedupe
    Runner->>DB: Step 6: persist flags + run record

    Runner-->>Queue: PipelineResult
    Queue-->>UI: on_complete callback
    UI-->>User: Show flags + summary
```
