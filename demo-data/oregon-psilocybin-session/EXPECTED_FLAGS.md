# Oregon Dataset — Expected Flags (Test Oracle)

Developer/eval use only — never load as a context document. Match reds/yellows on criterion cited; a missing red is a failure; calibration traps must produce zero incorrect flags. The core purpose of this dataset: verify the system applies **Oregon's actual dispositions** (three legal exclusions; everything else routes to consultation or plans) and keeps regulatory (R-) and house (H-) bases distinct in flag citations.

**Load:** `program_description.md`, `screening_criteria.md`, `reference_material.md`. (Conflict-testing lives in the original demo datasets.)

---

## Applicant A — Nina Kowalski (multiple hard reds; not clearable)

**Red, hard:**
- **R-A1 — Lithium within 30 days.** CIF Q 3(a) answered **Yes** with "finished tapering ~three weeks ago." Rules engine catches the Yes; the model must apply the **30-day window arithmetic (X-6)**: recently *stopped* is still inside the window, and the rationale must say the prescriber-managed taper does not change the rule's timeframe. Trap: a run that downgrades because "she's off it now" fails.
- **R-A3 — Psychosis history, via form-vs-narrative contradiction (X-5).** CIF Q 3(j) answered **No**, but the mental-health narrative describes a 2019 episode with hallucinated voice, hospital diagnosis of "manic episode with psychotic features," and 8-day psychiatric admission, reframed as sacred. The flag must (a) cite R-A3, (b) surface the **contradiction between the form answer and the narrative** as its own evidence point, and (c) evaluate what is described rather than her label. This is the dataset's flagship model-detection test.

**Red or high yellow:**
- **H-3 — Bipolar/manic history.** 2019 manic episode + bipolar II diagnosis: outside Oregon's form entirely, house-exclusionary — the flag must carry the **H- citation**, not a rule citation (basis-separation test).

**Yellow:**
- **H-2-adjacent context** none (no SI ever — do not flag suicidality; trap).
- **R-B1** — under current care (psychiatrist + therapist): consult-encouraged disposition; largely satisfied by her existing care — low severity, notes that the psychiatrist hasn't discussed session details.
- **X-4 (mild)** — "now that I'm off the mood medication…" framing warrants an expectation conversation; low severity.

**Green:** current therapist and psychiatrist (H-G1); realistic tone (H-G5); strong routines/support.

**Calibration traps:** no pregnancy/allergy/mobility flags (all No); the aunt's probable bipolar is second-degree — note-level at most, not H-11.

---

## Applicant B — Marisol Vega (resolvable yellows; clearable after follow-ups)

**Red:** none. (Deferred trauma/abuse/sexuality answers are NOT reds; psychosis/SI all No.)

**Yellow:**
- **R-B3 — Mid-session medication plan.** CIF 3(d) Yes: sumatriptan as needed. Required outcome: written medication plan (self-administration confirmed or support person identified) + encourage pharmacist/provider consultation. Bonus the model should catch: **sumatriptan is serotonergic and she takes sertraline + St. John's Wort tea** — the three-way serotonergic load belongs in H-6's follow-up, routed to her prescriber (never advice to skip anything).
- **H-6 — Sertraline + St. John's Wort (+ grapefruit).** Discontinuation plan for the tea per intake; grapefruit abstention window; prescriber awareness. Resolution: documented prescriber conversation + supplement plan.
- **R-B1 — Under current care** (PCP, therapist, neurologist): consult-encouraged; largely pre-satisfied by the therapist's involvement — low severity.
- **H-13 — Deferred answers** on trauma, abuse, and sexual-trauma questions: follow-up flags; sexuality deferral carries the one-on-one privacy note; never read as "no."
- **H-16-adjacent:** none (no recent loss — trap: father's long-resolved drinking is background, not a flag).

**Green:** weekly therapist with post-session appointment booked (H-G1); named support network (H-G4); notably realistic first-timer expectations (H-G5).

**Follow-up demo path:** resolve R-B3 with a written med plan + prescriber note; resolve H-6 with "tea discontinued per plan; PCP consulted"; conduct H-13 conversations.

---

## Applicant C — Desmond Cole (green-dominant; two plan-flags that must NOT read as concerns)

**Red:** none.

**Yellow (informational/plan-level — low severity):**
- **R-B2 — Fungi allergy → alternative product encouragement.** CIF 3(c) Yes. THE key Oregon calibration trap: this must be a plan-level flag citing R-B2 with resolution "product-type plan noted," **not** an exclusion and not a high-severity medical concern. A run that reds this fails the dataset.
- **R-B9 — Mobility device → written emergency exit plan.** Cane since knee replacement; he asks for the plan himself. Logistics category.
- **R-B1 — Under current care** (PT, annual physicals): consult-encouraged; his physician already reviewed his plans (approaches H-G6) — minimal severity or fold into green.

**Green:** grief work with ongoing counselor + booked post-session appointment (H-G1); widowers' group + family (H-G4); prior mild psychedelic experience (H-G2, partial); exceptionally realistic goals (H-G5); physician awareness (H-G6).

**Calibration traps:** grief history with strong support must stay green-context, not a trauma yellow (H-8 requires *absent* support — his is exemplary); the 2024 "sad, not done" line is a disclosed negative answer to suicidality, not a flag; 1980s mushroom use is background.

---

## Dataset-specific behaviors exercised

| Behavior | Fixture |
|---|---|
| CIF questions keyed by the rules engine (verbatim question text → R- criteria) | all three |
| 30-day window arithmetic on a "stopped" medication | Nina (R-A1/X-6) |
| Form-answer vs narrative contradiction detection | Nina (R-A3/X-5) |
| Regulatory vs house citation separation | Nina (R-A1 vs H-3) |
| Non-exclusionary state dispositions rendered as plans, not concerns | Desmond (R-B2, R-B9) |
| Serotonergic combination across three sources incl. an as-needed med | Marisol (R-B3 × H-6) |
| Deferred-answer handling incl. sexuality privacy note | Marisol (H-13) |
| Strong-support trauma history stays green-context | Desmond |
