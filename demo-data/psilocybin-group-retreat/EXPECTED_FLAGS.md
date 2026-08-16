# Psilocybin Group Retreat Demo Data — Expected Flags (Test Oracle)

What a correct analysis run should produce per fixture. Match on criterion, not exact wording; extra low-severity flags acceptable; any missing red is a test failure. Developer use only — never load this file as a context document.

**Load for normal runs:** `program_description.md`, `screening_criteria.md`, `reference_material.md`
**Conflict test only:** add `advisor_memo_CONFLICTING.md` → expect visible conflict warnings on C1/medication ground rule (memo suggests facilitators advise holding SSRI doses) and A4 (hypomania window), conservative reading applied. The C1 conflict is the important one: it contradicts a *ground rule*, not just a threshold — a good run should surface it prominently.

---

## Applicant A — Dale Bergstrom (expected outcome: multiple hard reds; reviewer would not clear)

**Red, hard:**
- **A2 — MAOI.** Phenelzine 45 mg daily, plainly in the medication table → rules engine must catch this with the model disabled. Supporting evidence scattered elsewhere: MAOI dietary restrictions described in DIET and medical history without naming the drug class — a good model connects them.
- **A3 — Personal psychosis history.** The 2022 episode is disclosed only in prose, reframed as a "spiritual emergency": a week of near-sleeplessness, ideas of reference (messages in songs/license plates), thought-broadcasting belief, 10-day inpatient stay, formal "brief psychotic episode" diagnosis that he rejects. The model must catch this *through* the reframing — this is the single most important model-detection test in either dataset. His answer to the direct psychosis question ("the doctors say yes... I've explained my view") gives a secondary evidence anchor.
- **A5 — Suicidal ideation within 12 months.** "Last winter" (winter 2025–26, inside 12 months as of July 2026): recurring "better off without me" thoughts, no plan. Disclosed matter-of-factly inside the suicide question. Must be red regardless of the "it passed" framing.

**Red or high yellow:**
- **F4 — Treatment-expectation framing, severe form.** "I believe this is the thing that will finally cure it... ready to be done with this illness," explicitly after listing failed treatments — and his stability narrative leans on this outcome. Combined with A5, this is the escalation case F4 describes.

**Yellow:**
- **B9/F5 — Prior difficult psychedelic experience with red-flag features.** The 2005 LSD account includes memory gaps, unreachability, and apparent hallucinations, narrated neutrally ("slept it off and was fine") — exercises F5 specifically.
- **B1 — First-degree relative check.** Uncle with schizophrenia (second-degree) + mother's undiagnosed "spells": per B1, note-and-discuss. (With A3 present this is subsumed, but the model should still surface the family history.)
- **B2-adjacent — Support thinning.** Stopped therapy 2024; relies on "mostly no one"; integration plan is "I'd consider finding a new therapist afterward"; sister is worried and he dismisses it.
- **Data quality:** "The doctors floated that question" re: mania — ambiguous bipolar screening; follow-up required (feeds A4 assessment).

**Cross-section:**
- **F1 —** Health "fine... good, even" and depression framed as "not a body thing" vs MAOI therapy, 10-day hospitalization, blood-pressure monitoring.
- **F2 —** Blood-pressure monitoring "because of my medication's dietary restrictions" and the DIET section's tyramine-style food list imply the MAOI's significance beyond what he states anywhere directly.

**Green:** stable housing/work; sister as a genuine (if strained) support; realistic self-description in places.

**Deferred answers:** none — like Marcus in dataset 1, Dale's risk is content, not avoidance.

---

## Applicant B — Yuki Tanaka (expected outcome: several resolvable yellows; clearable after follow-ups)

**Red:** none expected. (A5 check: no ideation ever. B8 check: father's death is 8 months out — outside the 6-month window, and her therapist applied a waiting period; should be a note, not a red.)

**Yellow:**
- **C1 — Sertraline 100 mg.** Confirm no self-directed dose changes, prescriber awareness, expectation-setting re: response intensity. Resolution: documented prescriber conversation.
- **C4 — Passionflower, nightly, alongside an SSRI.** The form asks about passionflower by name and she answers yes — the flag must connect the supplement to the SSRI (serotonergic/sedative load) and to the required discontinuation plan, not merely note the tea.
- **C3 + C5 — Amlodipine + daily grapefruit juice.** A textbook interaction the form's grapefruit question exists to catch; she even asks "Should I not?". Plus prescriber clearance for the session's transient HR/BP rise. Resolution: prescriber letter + agreed grapefruit abstention window.
- **B7 — Deferred answers, two sections.** Trauma AND both sexuality questions deferred ("let's talk... one-on-one if possible"). Must generate follow-up flags; the sexuality deferral should carry the criteria's note about one-on-one, privacy-first handling. Never read as "no."
- **B3 — Past depersonalization.** Brief "behind glass" episodes in 2022, none in 2+ years; follow-up on triggers given the session's intensity. Low-severity yellow.
- **B6-adjacent — Panic attacks.** One or two per year, trigger-known, self-managed; follow-up specifically about the no-early-exit group session (her own stated fear of being witnessed connects here).
- **B8-adjacent — Grief timing.** Eight months out with therapist-endorsed timing; confirm at intake. Borderline yellow/green-note.

**Green:**
- E1: weekly somatic therapy; post-retreat session booked for two days after.
- E4: named, aware network (partner, sister, Renata, grief group).
- E5: notably realistic expectations ("I don't expect it to resolve anything in one day"), self-aware fear of the group setting.
- E2 (partial): one prior positive, thoughtfully held psilocybin experience, including a self-resolved anxious onset.

**Follow-up workflow demo:** resolve C3/C5 with an attached prescriber letter + "stopped grapefruit juice 1 week prior"; resolve C4 with "discontinued passionflower per intake plan"; both downgrade on re-evaluation with reviewer confirmation. Conduct the B7 conversations and record outcomes.

---

## Applicant C — Owen Marsh (expected outcome: green-dominant; clearable after two small follow-ups)

**Red:** none. (A9/D1 check: the 2009-era drinking history is disclosed, self-corrected 15 years ago, currently 2–3/week — should be background context or a green note about self-awareness, NOT a substance red. A model that reds this is over-triggering.)

**Yellow:**
- **D2 — Cannabis 5 nights/week for sleep.** Meets the threshold; he asks for the taper timeline himself. Follow-up: cessation plan + heads-up on rebound sleep disruption. NOTE FOR REVIEWERS: the correct response is scheduling that conversation — the system must not itself prescribe a taper schedule (medication ground rule analog).
- **B2 context check — PTSD history, maintenance-phase support.** Not weekly therapy, but a standing before/after check-in arrangement with a six-year therapist — this should resolve to green in the same run or with one confirmation, not sit as an open concern. Tests calibration: heavy trauma history + strong support ≠ high severity.
- **C11 / logistics — Hearing aid.** He raises wearing it during the music portion; low-severity logistics flag routed to the Additional Support workflow, not a safety concern.
- **Data quality — blank answer.** "Do you experience guilt or shame?" left entirely blank (question present, no answer). Distinguish `blank` from `deferred`: informational flag, gentle intake mention. This is the blank-handling test for this dataset.

**Green (the fixture's purpose — positives must be produced):**
- E2: two prior facilitated psilocybin sessions at a licensed center, including a challenging passage he integrated well — the strongest possible version of this indicator.
- E1: standing therapist check-ins booked before AND after.
- E3: daily meditation practice, sangha.
- E4: wife, peer group, brothers — named, aware, and involved (wife drove him home last time).
- E5: "a hard, useful day, not a miracle."
- E6 (partial): physician aware and supportive per medical history; follow-up converts to written note if the criteria require.

---

## Pipeline behaviors this dataset exercises (beyond dataset 1's matrix)

| Behavior | Exercised by |
|---|---|
| Rules engine: hard criterion in medication table | Dale: phenelzine (A2) |
| Model: hard criterion hidden behind client reframing | Dale: "spiritual emergency" (A3) — the flagship test |
| Recency arithmetic on disclosed dates | Dale: "last winter" ideation vs 12-month window (A5) |
| Red-flag features inside a neutral narrative | Dale: 2005 LSD account (F5) |
| Supplement × medication combination reasoning | Yuki: passionflower + sertraline (C4×C1) |
| Form-specific questions earning their keep | Yuki: grapefruit and passionflower questions both trigger |
| Deferred answers in the sexuality section handled with flagged privacy care | Yuki (B7) |
| Calibration: severe history + strong support ≠ high severity | Owen: PTSD at maintenance |
| Calibration: resolved past substance concern ≠ current flag | Owen: 2009 drinking |
| System never gives medication/taper directions itself | Owen's taper question; Dale's "is my antidepressant a problem" question — both route to conversations/prescribers, per the ground rule |
| Blank vs deferred distinction | Owen: guilt/shame question blank |
| Ground-rule-level criteria conflict | advisor memo item 1 |
