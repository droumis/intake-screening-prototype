# PISA User Guide

A step-by-step guide to driving the Participant Intake Screening Assistant against its fabricated demo programs.

**Scope.** PISA is an unvalidated prototype. It is not a medical device, not clinical decision support, and not medical or legal advice. It has no authentication, no encryption at rest, and no audit log, so do not enter real participant information into it. Every applicant and organization in `demo-data/` is invented. See [README.md](README.md#status-and-scope).

**How it is put together.** A deterministic rules engine runs first on the criteria the profile spelled out explicitly: medications, checklist fields, keywords. Three model passes then run on top of it, looking for what keyword matching cannot reach, such as contradictions between a form answer and a narrative, reframed disclosures, and connections across sections. Every flag shows its provenance (rule or model) and its basis (regulatory or house policy), so a reviewer can tell a deterministic match from an inference. Inference runs locally through Ollama.

[DESIGN.md](DESIGN.md) covers the rationale: why screening profiles exist, why the two state datasets resolve the same medication in opposite ways, what the rules engine does and does not catch, and where local inference stops being a privacy story.

---

## Getting Started

### Prerequisites

1. **Ollama** installed and running locally (system-level install)
2. **Model pulled:** `ollama pull qwen3:30b-a3b` (~19 GB download, requires 32 GB unified memory on Apple Silicon)
3. **pixi** installed for environment management

### Launching the App

```bash
pixi install        # first time only
pixi run app        # opens browser at localhost:5006
```

The app opens with two tabs: **Setup** and **Review**. A **sidebar** on the left contains the global program selector and flag minimap, and a fixed footer carries the scope warning.

---

## Sidebar

The sidebar is always visible and contains:

- **Program selector** — Switches the active program globally (affects both Setup and Review tabs)
- **Flag Minimap** — When an applicant is selected, shows a compact list of their flags (colored dot + criterion badge + truncated title). Provides at-a-glance severity overview.

A fixed page footer, visible on every tab, reads: "Unvalidated prototype — demo data only. Do not enter real participant information. Not a medical device, not medical or legal advice. All decisions are made by the human reviewer."

---

## Tab 1: Setup

Setup must be completed before any screening can run. Three numbered cards guide you through model connection, document selection, and profile building.

### Card 1: Model Connection

A status banner shows whether Ollama is reachable and the configured model is available.

| Status | Meaning | Action |
|---|---|---|
| ✓ "Model ready: qwen3:30b-a3b" | Everything working | None needed |
| ⚠ "Model not found" | Ollama running but model not pulled | Run `ollama pull qwen3:30b-a3b` |
| ✕ "Ollama server not reachable" | Ollama not running | Start Ollama |

**Re-check button** — Manually re-runs the health check (useful after starting Ollama or pulling the model).

Below the status: a compact config line showing provider, model, temperature, and context window size.

---

### Dataset Selection

The **global program selector** is in the sidebar. Each program has its own context documents (criteria, program description, reference material) and participant intake forms.

Selecting a program:
- Refreshes the context document list in Setup
- Filters the participant list in Review to show only that program's applicants
- Checks for a cached Screening Profile for that program
- Clears the current applicant detail view and flag minimap, so you always see a clean state for the new program

Four demo programs ship, all fabricated, each with 3 invented applicants:
- `psilocybin-group-retreat` — group retreat with fasting, cold-water immersion, group psychological work (Dale, Yuki, Owen)
- `summit-series` — high-altitude expedition with strenuous physical demands (Marcus, Priya, Tomas)
- `oregon-psilocybin-session` — Oregon-style regulatory floor plus stricter house standards (Nina, Marisol, Desmond). In this dataset three criteria are exclusionary (lithium within 30 days, current suicidal ideation, psychosis history) and the rest route to consultation or a written plan.
- `colorado-psilocybin-session` — Colorado-style clearance-pathway model (Ray, Aisha, Tom). In this dataset no criterion is categorically exclusionary; risk factors trigger documented clearance pathways, and lithium is resolvable through the R-2 pathway.

**Regulatory vs house distinction:** the state datasets carry a `basis` field on each criterion.
- **Regulatory** criteria represent a legal obligation, so the disposition is whatever the rule requires. Flag cards show a filled "regulatory" chip with the citation as tooltip.
- **House** criteria are the center's own clinical standards, deliberately stricter. Flag cards show an outlined "house" chip.

A reviewer can then see at a glance whether "cannot proceed" is law or policy.

**Note:** the state datasets paraphrase OAR 333-333 and 4 CCR 755-1 to build two programs that disagree about lithium. The paraphrases were written for this project, are not accurate legal summaries, are not maintained against amendments, and are not legal advice. See [demo-data/README.md](demo-data/README.md).

---

### Context Documents

Context documents are the plain-language source material that defines what the screening system checks for. They live in `<program>/context/` as markdown files and are authored by the program's clinical director or regulatory lead, with no code or schema knowledge required. The system reads them and extracts a structured Screening Profile.

**Why multiple documents?** Each document type serves a different role in the extraction:

| Document type | Purpose | Example content |
|---|---|---|
| `screening_criteria` | The authority — defines every criterion, its disposition, detection hints, and resolution pathway | "R-A1. Lithium within 30 days. A 'yes' means the client may not participate." |
| `program_description` | What the program demands of participants — informs program-demand cross-checks | "A sustained non-ordinary state lasting several hours; transient elevated heart rate and blood pressure; several hours without food." |
| `reference_material` | Clinical background and regulatory citations — gives the model context for why criteria exist | "Lithium + classical psychedelics: case literature associates the combination with seizures and severe adverse events." |

Splitting these out means you can update one without rebuilding everything: edit the criteria when rules change, update the program description when logistics change, or add reference material when new clinical guidance arrives.

**Editing context documents:** Open any `.md` file in a text editor. The screening criteria document matters most, since it defines what the system flags. Structure it however makes sense: part 1 / part 2 splits, regulatory vs house sections, criterion IDs with descriptions. The profile builder extracts structured criteria from natural language; it doesn't require a rigid format. When you save changes, the content hash changes and the UI marks the cached profile as stale. Rebuild and re-approve to pick up the edits.

**Example excerpt (Oregon screening_criteria.md):**
```
### R-A. Participation precluded by rule (EXCLUSIONARY)
- **R-A1. Lithium within the last 30 days** (Form Q 3(a)). A "yes" means
  the client may not participate in an administration session. Note the
  30-day window: recent discontinuation still inside 30 days is a "yes."
```

**Example excerpt (Colorado screening_criteria.md):**
```
### R-2. Risk factors → clearance pathways (Rule 2.2)
If the safety screen identifies a risk factor, the facilitator may not
independently provide services. Services may proceed only when documented:
- R-2a. A referral from a licensed medical or behavioral health provider; or
- R-2b. Medical clearance from the participant's treating provider; or
- R-2c. A documented consultation and risk review.
```

These two excerpts show why the same system needs per-program profiles: Oregon's lithium criterion produces an exclusionary hard flag; Colorado's produces a resolvable red flag with a clearance pathway. The documents say different things, and the profile builder faithfully extracts each disposition.

**In the UI:** A checkbox list of all files found in `<program>/context/`. Each entry shows:
- Filename
- Detected type (program description, screening criteria, reference material)
- Character count
- `[test-only]` label for CONFLICTING files

**Selecting/deselecting documents** controls which documents feed into the Screening Profile. By default, all non-CONFLICTING documents are selected. You can include CONFLICTING files to test the conflict-detection system.

---

### Profile Cache

If a previously built profile exists for the currently selected documents (matched by content hash):

- A green banner appears: "Cached profile found (approved/unapproved)"
- **Use Cached button** — Loads the cached profile without re-running the model

If no cache exists:
- An info banner appears: "No cached profile for this program"

---

### Build Profile

**Build Profile button** — Starts the model-driven extraction process (~3-5 minutes). A spinner appears while running. The model reads all selected context documents and extracts:

- Hard criteria (exclusionary conditions)
- Caution criteria (require follow-up)
- Medication classes of concern
- Program demands
- Positive indicators
- Ground rules

While building, you can switch to the Review tab; the build continues in the background.

**When building completes:**
- A success banner appears
- The derived profile is displayed with expandable sections:
  - Hard Criteria table (ID, Description, Source Excerpt)
  - Caution Criteria table (ID, Description)
  - Ground Rules list
- Conflict warnings appear as orange (criteria conflict) or red (ground-rule conflict) alert blocks

**If building fails:**
- A red error banner appears with the failure message
- Common cause: Ollama stopped mid-generation

---

### Approve Profile

**Approve Profile button** — Marks the profile as approved and saves it to cache. Until approved:
- The profile displays a yellow "Awaiting approval" status
- Screening runs are blocked (attempting to run shows a warning)

After approval:
- The profile shows green "Approved" status
- Screening is unblocked for all applicants in this program

**The profile only needs to be rebuilt if context documents change.** If you modify a screening criteria document, the hash changes and the cached profile becomes stale, so you'll need to rebuild and re-approve.

---

## Tab 2: Review

The Review tab is the primary workspace. It has two regions: the applicant list (top) and the applicant detail (bottom, appears after selection).

---

### Applicant List

A table showing applicants for the selected program:

| Column | Meaning |
|---|---|
| Name | Display name (extracted from intake form identity table) |
| State | Current review state (colored chip). During screening, shows "⟳ screening" or "queued" |
| Flags | Flag counts as colored cluster (e.g., `2R · 1Y · 3G`) |
| Acknowledged | Acknowledged/total count (turns green when all flags reviewed) |
| Last Screened | Humanized timestamp (e.g., "today 14:30", "2d ago") |
| Duration | How long the last run took |

Table cells are read-only (not editable by clicking). **Click any row** to select that applicant and load their detail view below.

---

### Refresh Button

Re-scans all `<data_dir>/<program>/forms/` directories for new `.md` files. Any files not already in the database are automatically imported:
- The file is parsed (identity extracted for display name, sections mapped)
- A new applicant record is created in the database
- The table updates to show the new entry

**This is how new applicants enter the system** — place a `.md` intake form in the appropriate `forms/` directory and click Refresh.

---

### Run All Button

Queues every applicant in the table for screening. Runs execute serially (one at a time) in the background. Requires an approved profile for the program.

**During a Run All:**
- Each applicant's State cell shows "queued" (grey) or "⟳ screening" (blue) as their turn comes
- A progress bar appears above the table: `2/4 done...`
- As each applicant finishes, their row updates immediately (State, Flags, Acknowledged, Last Screened, Duration)
- When all complete, the progress bar disappears and a summary appears

### Stop Screening (⋮ Menu)

Click the **⋮** overflow menu in the toolbar and select "Stop screening" to cancel all pending and active runs. The currently running analysis will finish its current model call but no further applicants will be processed. All table cells revert to their actual state.

---

## Applicant Detail View

Appears below the list after clicking a row. Shows the full screening results and interaction controls in a sticky header + tabbed detail layout.

---

### Header Area (Sticky)

The header stays visible as you scroll through flag details:

- **Applicant name** (large heading)
- **Demographic line** — age, pronouns, occupation (extracted from identity table)
- **Dataset chip** + **Review State chip** (colored) + state selector dropdown
- **Run Screening** button + overflow menu (⋮) containing Stop Screening and Purge

#### Review States

| State | Meaning |
|---|---|
| `unreviewed` | Initial state; no human has looked at this yet |
| `in_review` | A screening has run; reviewer is examining flags |
| `followup_pending` | Waiting for applicant response to follow-up questions |
| `cleared` | All concerns resolved; applicant cleared for program |
| `not_cleared` | Applicant will not proceed |
| `deferred` | Decision postponed pending more information |

**Clearance warning:** If you set the state to "cleared" while open red/yellow flags remain, a yellow notice appears listing the unacknowledged flags. The state change still applies, because you are the reviewer and have final authority.

**Auto-transition:** When a screening run completes, if the state is `unreviewed`, it automatically moves to `in_review`.

**Timeline logging:** Every state change is recorded in the Timeline tab with the reviewer name and timestamp.

---

### Run Screening Button

Starts the analysis pipeline for this applicant. Requires:
- An approved Screening Profile for the applicant's program
- Ollama running and model available

**The screening pipeline runs 6 steps:**

1. **Rules engine** — deterministic keyword/medication/checklist matching against the profile's criteria
2. **Per-section model analysis** — each form section is reviewed against the criteria relevant to it
3. **Comprehensive whole-form pass** — the entire form + all criteria are sent in one model call to catch cross-section patterns and anything the per-section pass might miss
4. **Synthesis** — cross-section correlation, merge proposals, and overall notes
5. **Merge & deduplicate** — criterion-ref based consolidation of flags from all prior steps
6. **Persist to database** — final flags and run metadata are written

**What you see when you click it:**

1. The button area is replaced by a progress display:
   - Blue info alert: "Running screening for [Name]..."
   - A **determinate progress bar** (fills as sections complete: `sections_done / sections_total`)
   - A text line showing current pipeline stage

2. Progress updates appear in real time:
   - "Analyzing section 1/5: Medical History..."
   - "Section 1/5 done: Medical History"
   - "Analyzing batch: Diet, Sleep, Languages..."
   - "Running comprehensive review... Analyzing full form against all criteria."
   - "Running synthesis pass... Correlating findings across sections."

3. As sections complete, flags appear incrementally:
   - A "Flags found so far: N" counter
   - Each flag shown as a chip row (level badge + title)

4. When complete:
   - The progress display is replaced by a "Last run: complete in Xs" banner
   - An **overall screening summary** card appears with "AI summary · advisory only" header and "Generated by [model] · [date]" footer
   - The full flag list renders in the Flags tab
   - The review state auto-transitions to `in_review` (if it was `unreviewed`)
   - The applicant list table refreshes
   - The sidebar flag minimap updates

**If the run fails:**
- A red error alert appears: "Pipeline failed: [error message]"
- Common causes: Ollama stopped, model returned invalid JSON after retries, network timeout
- The final deduplicated flag set from completed sections is preserved

---

### Stop Screening (Overflow Menu)

Click the **⋮** overflow menu next to Run Screening and select "Stop screening" to cancel the active run for this applicant. A yellow "Screening interrupted" alert appears and the table cell reverts to the actual state.

### Purge (Overflow Menu)

Click the **⋮** overflow menu next to Run Screening and select "Purge applicant data." A **confirmation dialog** appears requiring you to type the applicant's first name before the delete button enables.

Purge permanently deletes:
- The applicant record
- All their flags
- All their follow-ups
- All their pipeline run records

After purge:
- The detail view clears
- The applicant list refreshes
- The applicant reappears on next Refresh **if their `.md` file still exists** in the forms directory (re-imported as a fresh record with a new ID and no screening history)

**To permanently remove an applicant:** delete their `.md` file from the forms directory, then purge.

---

### Last Run Status

Below the action buttons, an alert shows the most recent pipeline run:

| Status | Display | Meaning |
|---|---|---|
| `complete` | Green: "Last run: complete in 62s (2026-07-22T14:30)" | Successful full run |
| `incomplete` | Red: "Last run: incomplete (2026-07-22T14:30)" | Pipeline failed partway through |
| No runs | Blue: "No analysis run yet" | Never been screened |

If the run has notes (e.g., "Section X analysis failed"), they appear in a separate yellow alert below.

---

### Flags Tab

The primary review surface. Shows all flags organized by status.

**Header controls:**
- Count chips showing totals by level (Red 2, Yellow 3) and status (Open 5, Resolved 1)
- **Expand all / Collapse all** buttons

**Open flags** appear first. **Resolved flags** are grouped in a collapsed "Resolved (N)" card at the bottom.

Each flag is a collapsible card with a **4px colored left border** (red/amber/green):

**Card header:** Title text + `[HARD]` suffix for hard-flag reds. Red/yellow start expanded; green starts collapsed.

**Inside each card:**

- **Chip row:** Level chip (RED/YELLOW/GREEN filled), HARD chip (if applicable), provenance chip (rule/model), **basis chip** (regulatory/house — regulatory is filled, house is outlined; tooltip shows the rule citation), status chip (if not open), section name chips. The basis chip only appears when the criterion carries a basis, so flags stored before `basis` and `citation` were persisted show no chip until the applicant is screened again.
- **Rationale** — plain-language explanation of why this matters (shown first)
- **Evidence** — verbatim quotes as styled blockquotes with criterion badges (`R-A1`, `H-3` in monospace chip) and section attribution
- **Suggested lookup** — rendered as small neutral chips (e.g., "lithium + fasting interaction", "MAOI dietary restrictions")
- **Recommended follow-up** — warm, non-clinical questions the reviewer could ask
- **Resolution criteria** — displayed in a styled tinted box: "Clears when: [condition]". For regulatory pathway criteria (e.g., Colorado R-3), this names the specific documented pathway (referral / clearance / consultation + safety plan), not generic "follow up"

**Follow-up indicator:** When a flag has linked follow-ups, a 💬 badge with count appears in the card header (visible even when collapsed). Inside the card, a collapsible "Follow-ups (N)" section shows all linked follow-ups with timestamps and content.

**Per-flag actions (open flags only):**

- **Follow-up button** — Opens an inline drawer with:
  - Suggested questions from the model (click to insert into note field)
  - Reviewer note field
  - Applicant response field
  - **Level selector** — shows red/yellow/green, defaults to the flag's current level. Only changes level if you select something different.
  - Save persists the follow-up, updates the flag card's border color and header badge in-place, and shows the new follow-up in the inline history.

- **Acknowledge button** (green outlined) — Instant one-click action. No form required. The flag card:
  - Collapses and dims (opacity 0.6)
  - Gets an "acknowledged ✓" badge in the header
  - Is replaced by a "Reopen" button
  - The acknowledged count updates in the table immediately

- **Level button** — Opens a drawer with:
  - **Level picker** — choose any target level directly (not just one step up/down). E.g., you can go red→green in one action.
  - **Reason field** (required) — explains why the change is being made
  - Updates the card's border color in-place on confirm

**Reopen button (acknowledged flags only):** Restores the flag to open state with full action buttons. Logged in the timeline.

**Reviewer Flags section:** Below system flags, a separate section lets you manually create flags with a title, level, category, and rationale. Reviewer flags follow the same acknowledge/reopen pattern as system flags.

---

### Follow-ups Tab

Shows the history of follow-up interactions and a form for adding general notes.

#### Existing Follow-ups

Each card has an **informative header** showing the date, a preview of the reviewer note, and whether it resolved flags — e.g., `"2026-07-15 — Asked about lithium timeline... [resolved]"`. Expand to see:
- Reviewer note (what was asked)
- Applicant response (what they said)
- Linked flag titles
- Whether flag levels were changed

#### General Note Form

For non-flag-specific observations (collapsed by default):

| Field | Purpose |
|---|---|
| **Link to flags** (MultiChoice) | Optionally associate with open flags |
| **General note** | Logistics, observations, anything not tied to a specific flag action |
| **Save Note** button | Persists the record |

**Note:** The primary way to record flag-specific follow-ups is via the **Follow-up button** on each flag card (in the Flags tab). The general note form here is for observations that don't fit a specific flag.

### Timeline Tab

A merged, time-ordered audit trail of all activity for this applicant:
- Pipeline runs (status, duration, model)
- Flag creations (level + title)
- Flag level changes (from → to, reason, actor)
- Acknowledgements and reopens (actor)
- Review state transitions (from → to, actor)
- Follow-up recordings (linked flag count, resolution status)

Events are sorted newest-first. Each entry shows a timestamp and summary line. Actor names come from the reviewer name configured in Setup.

---

### Form Tab

Collapsible cards for each parsed section of the intake form. Lets the reviewer see the original verbatim Q&A without leaving the app.

Each section card contains:
- **Q&A pairs** — question in bold, answer below. Deferred answers marked *(DEFERRED)*, blank answers marked *(BLANK)*
- **Medications table** — if the section contains a medication list
- **Conditions checked** — if the section contains a checklist with YES entries
- **Consumption table** — substance use quantities

All sections start collapsed; click the card header to expand.

---

## How New Information Enters the System

### New Applicants (Intake Forms)

1. Place a `.md` file in `demo-data/<dataset>/forms/`
2. Click **Refresh** in the Review tab (or restart the app)
3. The file is parsed: identity table extracted for display name, sections mapped to taxonomy keys
4. A new database record is created with status `unreviewed`
5. The applicant appears in the table

**File naming:** Any `.md` file works. The display name comes from the identity table inside the file (the `Name:` field), not the filename. If no name is found, the filename stem is used.

**Form formatting flexibility:** Forms can use either `## Section Heading` style or `**BOLD SECTION HEADING**` style for sections. Questions can be bold-formatted (`**Question?**`) or plain text. Condition checklists can be 2-column or 4-column tables. The parser handles all combinations automatically.

### New Context Documents (Program Materials)

To add or modify the criteria a program screens against:

1. Create or edit a `.md` file in `demo-data/<program-name>/context/`
2. Include a `**Document type:** screening_criteria` (or `program_description` / `reference_material`) metadata line near the top so the system detects its role
3. Write criteria in natural language, using IDs, descriptions, and disposition language the profile builder can extract (see the shipped examples)
4. Go to Setup tab and select the program; the new or changed document appears in the checkbox list
5. Rebuild the profile (the existing cache is stale, since the document hash changed)
6. Review the extracted profile, then approve it

You can iterate quickly: edit the document, rebuild, check if the profile extracts what you intended, adjust wording if not. The model's extraction is what you're reviewing at the approval step: did it understand your criteria correctly?

### Follow-up Information

1. Select the applicant in the Review tab
2. Scroll to the Follow-ups section
3. Fill in the follow-up form (link flags, add notes and response)
4. Click Save Follow-up

---

## Workflow: Complete Screening Lifecycle

### First-Time Setup

1. Launch app (`pixi run app`)
2. Go to **Setup** tab
3. Verify model health (green status)
4. Select program
5. Review context documents (ensure all relevant ones are checked)
6. Click **Build Profile** (wait ~3-5 minutes)
7. Review the derived criteria, demands, and ground rules
8. Click **Approve Profile**

### Screening an Applicant

1. Go to **Review** tab
2. Click **Refresh** (ensures all forms are discovered)
3. Select an applicant from the dropdown
4. Click **Run Screening**
5. Watch progress: sections completing, flags appearing
6. When done: review the flag list

### Reviewing Flags

For each flag (top to bottom, most severe first):

- **Red (hard):** This is an explicitly stated exclusionary criterion. Read the evidence and rationale. Decide whether to:
  - Accept it as-is (applicant likely not cleared)
  - Investigate further (maybe the checklist item was a past benign event)
  - Record a follow-up to gather more information
  - **Acknowledge** it (keeps the level, marks as reviewed, unblocks clearance)

- **Red (not hard):** Serious concern that isn't automatically exclusionary. Same review process but more latitude for resolution.

- **Yellow:** Ambiguity or moderate concern. Every yellow has recommended follow-up questions and resolution criteria. The typical path:
  1. Click **Follow-up** on the flag card
  2. Ask the applicant the suggested question(s) and record their response
  3. Set the level to "green" if the response satisfies the resolution criteria, or "no change" to just document the conversation

- **Green:** Noted information, no action needed. Often positive indicators (strong support network, relevant experience). Provides the reviewer a balanced picture.

### Resolving and Clearing

1. Work through all red and yellow flags via follow-ups or acknowledgments
2. As concerns are resolved, use the Level button to change flags to green
3. Acknowledged flags stay at their level but are marked as reviewed
4. When all flags are acknowledged, the Acknowledged column turns green
5. You can change Review State to `cleared` at any time. If open red/yellow flags remain, a warning appears but the state change still applies (you have final authority)

### Re-Screening

If new information comes in or you want a fresh analysis:
1. Click **Run Screening** again
2. New flags are added (existing flags are preserved via INSERT OR REPLACE)
3. Duplicate flags are automatically merged when they reference the same criterion (criterion-ref matching), share evidence about the same concern, or have substantially similar titles (70% word overlap)

### Purging and Starting Over

To completely reset an applicant's screening:
1. Click **Purge** — removes all records
2. Click **Refresh** — re-imports the form file as a fresh entry
3. Run screening again from scratch

---

## Branching Outcomes by Applicant Archetype

### Archetype A: Hard Red (e.g., Dale, Marcus)

Pipeline produces at least one red flag with `hard_flag: true` from the rules engine (criterion matched deterministically). The model may add additional reds/yellows. Typical outcome path:
- Reviewer sees hard red flag with criterion citation
- Either: gather documentation showing the condition is resolved → follow-up → potentially resolve
- Or: flag stands, applicant is `not_cleared`

### Archetype B: Resolvable Yellow (e.g., Yuki, Priya)

Pipeline produces yellow flags requiring follow-up. No hard reds. Typical outcome path:
- Reviewer contacts applicant with recommended follow-up questions
- Records response in follow-up form
- If response satisfies resolution criteria → resolve flag → eventually `cleared`
- If response reveals new concerns → flag may escalate or new flags appear on re-screen

### Archetype C: Green-Dominant (e.g., Owen, Tomas)

Pipeline produces mostly green flags (positive indicators) with perhaps minor yellows. Typical outcome path:
- Quick review confirms no real concerns
- Minor yellows resolved via brief follow-up
- Applicant is `cleared`

---

## Error States and Recovery

| Situation | What You See | What To Do |
|---|---|---|
| Ollama not running | Red banner in Setup: "server not reachable" | Start Ollama, click Re-check |
| Model not pulled | Yellow banner: "Model not found" | Run `ollama pull qwen3:30b-a3b`, click Re-check |
| No approved profile | Warning when clicking Run Screening | Go to Setup, build and approve a profile |
| Pipeline fails mid-run | Red alert: "Pipeline failed: [error]" | Check Ollama is still running, retry |
| Partial results after failure | Some flags visible, run marked "incomplete" | Flags from completed sections are preserved; re-run for full analysis |
| Applicant "not found" after purge | Error alert when selecting | Click Refresh to re-import from filesystem |
| Stale profile after doc changes | Analysis uses old criteria | Rebuild profile in Setup (new hash won't match cached) |
| Parse quality warning | Yellow "data_quality" flag after screening | Fewer than 3 sections were detected — the form may use an unrecognized format. Check that section headings use `## Title` or `**Title**` format |
| Applicant screens with no flags and 16s runtime | No flags appear, run marked complete | The parser found no content to analyze. Purge the record, verify the form format, click Refresh, and re-screen |

---

## Keyboard and Interaction Summary

| Element | Location | Action |
|---|---|---|
| Program selector | Sidebar | Switches active program globally |
| Re-check button | Setup > Card 1 | Re-runs Ollama health check |
| Document checkboxes | Setup > Card 2 | Include/exclude docs from profile building |
| Use Cached button | Setup > Card 3 | Loads previously built profile |
| Build Profile button | Setup > Card 3 | Starts model extraction (~3-5 min) |
| Approve Profile button | Setup > Card 3 | Unlocks screening for this program |
| Refresh button | Review > List toolbar | Re-scans filesystem for new forms |
| Run All button | Review > List toolbar | Queues all applicants for screening |
| ⋮ Menu > Stop screening | Review > List toolbar | Cancels all pending/active runs |
| Table row click | Review > List | Selects applicant, loads detail view |
| Review State selector | Review > Detail header | Changes applicant's review state (logged to timeline) |
| Run Screening button | Review > Detail header | Starts pipeline for selected applicant |
| ⋮ Menu > Stop screening | Review > Detail header | Cancels active screening run |
| ⋮ Menu > Purge | Review > Detail header | Opens purge confirmation dialog |
| Expand all / Collapse all | Review > Detail > Flags tab | Toggle all flag cards open/closed |
| Follow-up button | Review > Detail > Flag card | Opens inline follow-up drawer |
| Acknowledge button | Review > Detail > Flag card | Instant acknowledge (no form) |
| Level button | Review > Detail > Flag card | Opens level change drawer |
| Reopen button | Review > Detail > Acknowledged flag | Restores flag to open state |
| Level selector | Review > Detail > Follow-up drawer | Set flag level after recording follow-up |
| Add Flag button | Review > Detail > Reviewer Flags | Opens manual flag creation form |
| Detail tabs | Review > Detail | Switch between Flags / Form / Follow-ups / Timeline |
| Flag minimap | Sidebar | At-a-glance flag overview (updates on acknowledge/reopen) |
| Reviewer name | Setup > Top card | Sets name associated with all timeline actions |
