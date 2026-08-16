# Demo Data — Expected Flags (Test Oracle)

This file tells you what a correct analysis run should produce for each fixture. Use it to evaluate the pipeline: every listed red and yellow should appear (matching on criterion, not exact wording); extra low-severity flags are acceptable; a missing red is a test failure. This file is for the developer only — never load it as a context document.

**Load for normal runs:** `program_description.md`, `screening_criteria.md`, `reference_material.md`
**Load only for the conflict-detection test:** add `advisor_memo_CONFLICTING.md` → expect visible conflict warnings on C1 (hypertension clearance) and A3 (hypomania window), with the conservative reading applied.

---

## Applicant A — Marcus Webb (expected outcome: multiple hard reds; reviewer would likely not clear)

**Red, hard:**
- **A1 — Lithium therapy.** Medication table: lithium carbonate 900 mg daily. Evidence also in "abnormal findings" (quarterly levels) and side effects (tremor, thirst — both dehydration-relevant). Rationale must cite the 48h fast + exertion dehydration risk.
- **A3 — Hypomanic episode within 5 years.** Spring 2023 episode, explicitly named by his psychiatrist, with 3-day psychiatric hospitalization. Well inside the 5-year window.

**Red or high yellow:**
- **F4 — Expectation that the program treats a clinical condition.** Purpose section: "hoping this week fixes what two years of therapy hasn't... done with the mood stuff." Combined with a bipolar II diagnosis, this is a serious framing problem, not just enthusiasm.

**Yellow:**
- **B3-adjacent / defense-in-depth:** Bipolar II diagnosis disclosed; even absent the A3 window, prescriber letter would be required. (Model may fold this into the A3 flag; acceptable.)
- **C6 — Grapefruit daily + atorvastatin.** Direct, well-known interaction; reference doc covers it.
- **D1-adjacent — Alcohol.** 10–12 drinks/week, nightly pattern, wife has raised it, and "the wine" listed as a coping mechanism. Below the D1 threshold but the *daily* pattern plus abrupt required abstinence warrants follow-up.
- **B1-adjacent — Support thinning.** Stopped therapy in 2025; psychiatrist not told program details; integration plan is "I figured I'd restart." Follow-up: reconnect care before any program.
- **C10 — Caffeine** 3/day: minor, taper-plan follow-up.

**Cross-section (synthesis pass must catch at least the first):**
- **F1 — "Excellent" health + "nothing significant"** vs lithium, hospitalization, statin, borderline blood pressure.
- **F2 — "Borderline" untreated blood pressure** mentioned narratively but High Blood Pressure unchecked in the checklist; needs clarification against A4.

**Green:**
- E3: stable marriage/family support; altitude experience (skiing).

**Deferred answers:** none (Marcus answers everything — his risk is content, not avoidance).

---

## Applicant B — Priya Raman (expected outcome: several resolvable yellows; clearable after follow-ups)

**Red:** none expected. (A9 check: passive ideation was 2021, >12 months, disclosed, therapist-managed → correctly a follow-up note, not a red. If the model reds this, it's over-triggering; if it ignores it entirely, it's under-reading. Expected: yellow.)

**Yellow:**
- **C1 — Controlled hypertension on lisinopril.** Requires written physician clearance covering altitude, cold immersion, and the fast. Resolution: physician letter.
- **C3 + C6 — Sertraline + St. John's Wort tea.** The combination is the point: serotonergic load plus interaction potential, and she reports medication sensitivity. Resolution: confirm discontinuing St. John's Wort and prescriber awareness of the fast. Also C9-adjacent: she notes sertraline is worse without food → prescriber plan for the 48h fast.
- **B6 — Deferred trauma answers.** "Let's discuss this in person" on trauma and abuse questions, plus trust question referencing the same material. Must generate a follow-up flag; must NOT be treated as "no trauma." Note her strengths here: weekly therapist, post-program session booked.
- **B2 — Past depersonalization episodes.** 3–4 episodes, 2021–2022, stress + sleep-deprivation triggered, none since. Follow-up required because the program deliberately combines stress, fasting, and disrupted sleep. Resolution: intake conversation + therapist input.
- **Passive ideation 2021** (see above): follow-up confirmation with therapist context.
- **C10 — Caffeine 4–5/day.** Meets the threshold; taper plan follow-up.
- **B7-adjacent — Recent grief.** Grandmother (her "anchor") died late 2025, self-described as still feeling it. Slightly outside 6 months; judgment-call yellow or green-noted; follow-up on timing is reasonable.
- **Lightheadedness when skipping meals** (Personal section, fears): minor but fast-relevant; roll into C1/C3 follow-up.

**Green:**
- E1: weekly therapy, post-program session already booked.
- E3: named support network (Dana, therapist, running group).
- E2 (partial): Inca Trail altitude experience; intermittent fasting familiarity.
- E5: realistic goals ("I don't expect a week to answer that"), self-aware fear of group work.

**Follow-up workflow demo:** resolve C1 by attaching a physician clearance letter as a follow-up; resolve C3/C6 with "confirmed stopping St. John's Wort 2 weeks prior; PCP consulted." Both should downgrade on re-evaluation with reviewer confirmation.

---

## Applicant C — Tomás Herrera (expected outcome: green-dominant; clearable after two small follow-ups)

**Red:** none.

**Yellow:**
- **C5 — Asthma, cold/exercise triggered.** He names cold air as a trigger and the program includes cold-water immersion — the model should connect these specifically, not just flag "asthma." Resolution: inhaler-on-person plan (he already proposes it) + follow-up on immersion history.
- **D2 — Cannabis 4 nights/week for sleep.** Meets the D2 threshold exactly. He asks for a taper plan himself. Follow-up: taper timeline; note cessation-related sleep disruption compounding altitude sleep effects (reference doc).
- **Data quality — blank answer.** "Anything else about family?" left blank. Low-severity informational flag; not deferred-phrased, so distinguish `blank` from `deferred` handling here.

**Green (the point of this fixture — the model must produce positives, not only problems):**
- E2: three supervised multi-day fasts (72h max, recent), regular exertion above 9,000 ft, 4-year cold practice.
- E1/E3: nine-year men's group with post-program meeting scheduled; therapist available for tune-ups; wife, brother.
- E4 (partial): physician reviewed the program's activity description and gave verbal clearance — follow-up converts to written letter.
- E5: notably realistic expectations ("useful roughly in proportion to that").

---

## Pipeline behaviors the fixtures exercise

| Design requirement | Exercised by |
|---|---|
| Rules engine catches checklist/medication hard criteria with model disabled | A: lithium in med table (A1) |
| Model catches narrative-only hard criteria | A: hypomania described in prose, no checklist field (A3) |
| Synthesis pass cross-section contradiction | A: F1, F2 |
| Deferred ≠ no | B: trauma/abuse "let's talk" (B6) |
| Blank ≠ deferred | C: blank family question |
| Combination reasoning (two safe things, unsafe together) | B: sertraline + St. John's Wort |
| Program-demand cross-reference | C: cold-triggered asthma × cold immersion; B: lisinopril × fast × altitude |
| Green/positive indicators produced | C throughout; B support network |
| Calibration / no flag inflation | C: divorce-era resolved depression should be background, not a flag pile |
| Follow-up → downgrade with audit | B: physician letter resolving C1 |
| Conflict detection | advisor memo vs criteria v2.3 |
