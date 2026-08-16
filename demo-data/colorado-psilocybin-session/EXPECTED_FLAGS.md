# Colorado Dataset — Expected Flags (Test Oracle)

Developer/eval use only — never load as a context document. Match reds/yellows on criterion cited; a missing red is a failure; calibration traps must produce zero incorrect flags. Core purpose of this dataset: verify the system applies **Colorado's clearance-pathway model** — risk factors produce serious but *resolvable* flags whose resolution criteria name the documented pathway (referral / clearance / consultation-and-risk-review, plus safety plan on heightened risk), and **never** an unresolvable exclusion on regulatory grounds.

**Load:** `program_description.md`, `screening_criteria.md`, `reference_material.md`. (Conflict-testing lives in the original demo datasets.)

---

## Applicant A — Ray Delgado (highest-severity resolvable red; the anti-Oregon case)

**Red (NOT hard):**
- **R-3 — Lithium.** Safety-screen "Yes" + medication table (rules engine). THE dataset's defining requirements: `hard_flag` must be **false**; the rationale must state that Colorado treats this as the strictest clearance tier, not an exclusion; resolution criteria must specify **documented R-2 clearance/consultation from his psychiatrist plus an R-2d written safety plan**, and note that a standard Facilitator may not proceed independently. A run that marks this exclusionary/unresolvable **fails the dataset** — that is Oregon's rule, not Colorado's. His own question ("what does the clearance process require from my psychiatrist?") is the follow-up thread.

**Yellow:**
- **R-5 routing** — bipolar II history + lithium: flag should state the facilitator-type implication (Clinical Facilitator, or standard Facilitator strictly via the R-2 pathway).
- **H-4 window check (X-6):** hypomania was 2017 — nine years ago, outside the 5-year window — so H-4's red does NOT apply; expected output is a consulting-clinician-review yellow referencing the remote bipolar II history, folded into or alongside R-3's pathway. Trap: an H-4 red here is a window-arithmetic failure.
- **B2-style support note:** no current therapist (psychiatrist quarterly only) — follow-up: confirm the pre/post therapist re-engagement he proposes.

**Green:** exceptional disclosure and preparation (leads with the lithium question — H-G5); informed, willing psychiatrist (approaches H-G6); wife/brother network (H-G4); stable decade.

**Traps:** no psychosis, no SI (never), father's death is worked trauma with history of support — background, not H-13.

---

## Applicant B — Aisha Bennett (multiple pathway yellows; clearable with documentation)

**Red:** none. (Panic disorder treated + no SI + no psychosis — a red here is over-triggering.)

**Yellow:**
- **H-8 / R-2 — Controlled hypertension (losartan).** Risk factor → clearance pathway; resolution: documented clearance addressing transient HR/BP elevation. Her PCP/NP willingness makes this a fast resolve.
- **R-4 + H-9 — Venlafaxine.** Written recommendation for consultation (required disposition); confirm no self-directed dose changes — and the model should surface her stated **discontinuation sensitivity** ("brutal to miss a dose") as exactly why the no-changes ground rule matters here, phrased as prescriber territory, never advice.
- **Panic disorder → R-8 vigilance note.** Not a pathway blocker at her stability level, but the flag should route her own request ("walk me through the mid-session panic protocol") into preparation planning; follow-up: document the in-session support plan.
- **H-16 — partial deferral:** trauma answer is "sketch it in person" with a disclosed headline — follow-up flag at low severity (she gave substance; distinguish from a bare deferral).

**Green:** weekly therapist with before/after sessions booked (H-G1); clinician-calibrated expectations (H-G5); named network (H-G4); prior positive supported experience (H-G2, partial); providers pre-briefed (approaches H-G6).

**Follow-up demo path:** attach PCP clearance letter (resolves H-8/R-2); record the written R-4 recommendation + NP consultation; document the panic support plan.

---

## Applicant C — Tom Okafor (green-dominant; one CO-specific mild disposition)

**Red:** none.

**Yellow (low severity):**
- **R-4 — Trazodone.** "Other psychotropic" on the screen → the **written recommendation to obtain consultation** disposition; he offers to arrange PCP paperwork himself. Trap: this must be the mild R-4 disposition, not an H-9-style serotonergic escalation and not a pathway-blocking red.
- **H-19 boundary check:** daughter left for college in March (~4 months) — inside the 6-month window but a transition, not a loss/crisis; acceptable outputs: low-severity timing note or nothing. An escalated flag here is over-triggering.

**Green:** prior licensed facilitated session, challenging passage well-supported and integrated (H-G2 — the strongest form); four-year meditation practice (H-G3); therapist before/after arrangement (H-G1); sister/daughter/dinner-group network (H-G4); realistic goals (H-G5).

**Traps:** divorce-era resolved depression is background; two grad-school mushroom uses are background; "loneliness vs solitude" purpose framing is healthy intention, not X-4.

---

## Dataset-specific behaviors exercised

| Behavior | Fixture |
|---|---|
| Regulatory red that is resolvable (hard_flag=false) with pathway-named resolution criteria | Ray (R-3) |
| Facilitator-type routing surfaced in a flag | Ray (R-5) |
| 5-year window arithmetic preventing a house red | Ray (H-4/X-6) |
| Risk factor → clearance pathway as yellow with documentation resolution | Aisha (H-8/R-2) |
| Required written-recommendation disposition for non-lithium psychotropics | Aisha, Tom (R-4) |
| Medication-adherence sensitivity folded into ground-rule phrasing (no advice) | Aisha (venlafaxine) |
| Mild disposition stays mild (no serotonergic over-escalation) | Tom (trazodone) |
| Partial deferral vs bare deferral distinction | Aisha (H-16) |
| In-session vigilance notes (R-8) feeding preparation, not eligibility | Aisha (panic) |

## Cross-dataset assertion (run after both state datasets)

The same underlying fact — **current lithium therapy** — must produce **opposite flag semantics** by state: Oregon (Nina, R-A1) → exclusionary hard flag, no resolution path; Colorado (Ray, R-3) → non-hard red with a documented-clearance resolution path. If both datasets produce the same lithium outcome, the system is ignoring the context documents and the state separation has failed.
