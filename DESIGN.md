# PISA Design Rationale

Why the system works the way it does.

PISA is an unvalidated prototype and must not be used to screen anyone. The rationale below describes design intent, not verified behavior. See [README.md](README.md#status-and-scope) for the full scope note, and [demo-data/README.md](demo-data/README.md) on why the regulatory summaries quoted here are illustrative rather than authoritative.

---

## The problem: screening is high-stakes and context-dependent

Psilocybin facilitators in Oregon and Colorado screen participants against criteria that vary by jurisdiction, program type, and clinical philosophy. The same fact, "this person takes lithium," demands opposite outcomes depending on whose rules apply. As the demo datasets model it:

- **Oregon-style dataset:** lithium within 30 days is treated as a categorical exclusion, with no follow-up that resolves it.
- **Colorado-style dataset:** lithium is the strictest clearance tier. Services may proceed with documented consultation, risk review, and a safety plan.

Both readings are paraphrases written for this project, not legal summaries. What matters architecturally is that they disagree. A tool that hard-codes either disposition is wrong half the time, and a tool that leaves the disposition to the model's parametric knowledge is unreliable: the model may conflate the two states, or apply a generic "lithium is dangerous" heuristic that ignores a documented pathway.

PISA's answer is to make the criteria **explicit, modular, and externally authored** rather than baked into code or model weights.

---

## Why screening profiles exist

A Screening Profile is a structured extraction of a program's context documents: the regulatory rules, house policies, ground rules, detection hints, and resolution pathways that define what the screening should check for. It's the bridge between "here are our documents" and "here's what the system looks at."

**Why not feed the docs to the model every run?**

1. **Determinism.** The rules engine operates on the profile's `DetectionSpec` fields (checklist keywords, medication names, section targets). Those produce the same flags every time, regardless of model temperature or phrasing variation. Model-inferred flags are supplementary. The deterministic layer bounds model variance, within the limits described under Layer 1 below.

2. **Reviewability.** A human can inspect the profile before any screening runs: "Did the system correctly understand that R-A1 is exclusionary? Did it classify Colorado R-3 as a pathway red, not a hard red?" That is the "approve" gate: the reviewer signs off on the interpretation before it drives anything.

3. **Modularity.** Different programs share the same engine but use different profiles. A retreat center in Costa Rica, an Oregon service center, and a Colorado healing center each have their own context documents and thus their own profiles. No code changes required.

4. **Iteration.** When rules change (both Oregon and Colorado are still amending their frameworks), you update the context documents and rebuild the profile. The system re-extracts criteria from the new text. Old cached profiles are invalidated by content hash.

---

## Why local inference, and what that does not cover

PISA runs on Ollama with a local model (default: qwen3:30b-a3b), for three reasons:

- **The form text stays on the machine.** Intake forms contain psychiatric history, medication lists, substance use, trauma narratives, and identifying information. Local inference keeps that text out of a third party's logs.
- **No network dependency.** Reviewing forms the evening before a session should not depend on an internet connection. Ollama runs on the same machine.
- **Reproducibility.** The model is pinned and versioned, so results don't shift because a provider updated weights upstream. A profile built today produces the same interpretation next month.

Local inference decides where the text goes. It says nothing about whether the surrounding system is safe to put real participant information into, and this one is not. PISA has no authentication, so anyone who can reach `localhost:5006` sees every record. `pisa.db` is unencrypted SQLite in the working directory. There is no audit log of who read which applicant, no retention or deletion path, no consent tracking, and no backup or key management story. `pixi run app` serves with `--dev`, and pointing `--address` at anything other than localhost would expose the whole database to the network.

A tool that handles this category of information for real needs all of that, plus a review this prototype has never had. Read the local-inference choice as one necessary piece of a privacy design, not as evidence that the design exists.

The tradeoff is capability: a 30B local model is less capable than frontier cloud models. The deterministic rules engine absorbs some of that gap, since the model doesn't need to catch lithium when the keyword matcher already did.

The full intake form plus all screening criteria fits comfortably in the 16k context window used for the comprehensive pass (~7k tokens total input), so no context-window trade-offs are needed despite running locally. The 30B model's physical 262k limit is far above what's required.

---

## The deterministic + model layered design

The pipeline has a specific architecture to manage the non-determinism of LLM inference. The model runs in three distinct passes (per-section analysis, comprehensive whole-form analysis, and synthesis), each with its own role and temperature, set by how much inference the pass requires.

### Layer 1: Rules engine (deterministic, always runs first)
Every criterion in the profile carries a `DetectionSpec` with explicit keywords, medication names, and checklist fields to search for. When these match, the flag is emitted without any model involvement. This layer:
- Cannot be talked out of a match by the applicant's framing
- Produces identical results across runs
- Fires independently of the model: if `lithium` is in the profile's keyword list and the parser found it in the medication table, R-A1 fires whatever the model concludes

What it does not do is guarantee recall. Its coverage is only as good as four things upstream of it: the profile builder emitting the right keywords for each criterion, the section map resolving the form's headings, the parser having captured the field at all, and the applicant's spelling matching. A form that says `Lithobid` or `Li carbonate` is a test of `DRUG_CLASS_MAP`, not a certainty. Treat this layer as the floor on model variance, not as a safety net.

### Layer 2: Per-section model analysis
The model reads each section against the relevant criteria and produces supplementary flags. It catches things the rules engine cannot: contradictions between a form answer and a narrative disclosure, spiritual reframing of psychotic episodes, implications of medication combinations, timeline inferences. But these flags are:
- Always additive (they cannot suppress or downgrade a rule flag)
- Attributed to "model" provenance so the reviewer knows the confidence level
- Backed by verbatim quotes (the prompt enforces this)

### Layer 2.5: Comprehensive whole-form pass
After individual section analysis, the entire intake form and all screening criteria are sent in a single model call. This addresses a fundamental limitation of per-section analysis: some concerns only emerge when the full form is visible at once. A medication in one section that maps to a criterion tested in a different section; a "No" on a regulatory screening question contradicted by a disclosure three pages later; a timeline that only makes sense when multiple dated references are combined. The per-section pass can't see these because it only receives one section at a time. The comprehensive pass sees everything the human reviewer would see when reading the form front to back.

The temperature is slightly elevated (0.2 vs 0.1 for per-section) because its job requires more inference: connecting information across sections rather than matching keywords in a single answer.

### Layer 4: Synthesis pass
A cross-section analysis that receives candidate flags from three sources: rules, per-section model, and the comprehensive pass. It detects contradictions, patterns, and timeline issues spanning multiple sections. Proposes merges when multiple flags address the same underlying concern. Merge proposals are matched by criterion reference rather than exact title strings, so the model doesn't need to reproduce flag titles verbatim for merges to succeed.

Its temperature is the highest (0.3) because its task is the most associative: comparing flags, detecting redundancy, proposing merges.

### Layer 5: Merge and deduplicate
Rule flags survive untouched. Model flags are deduplicated against each other and merged into rule flags where they share criterion references. The conservatism principle: highest severity always wins.

The model catches what explicit keyword matching cannot: reframing, implication, cross-section patterns. It is never the sole authority on a safety-critical match. The human reviewer sees both layers, knows which flags are deterministic and which are inferred, and makes the final call.

---

## Why the test forms and oracles exist

Each program ships with carefully authored intake forms (the `applicant_*.md` files) and an `EXPECTED_FLAGS.md` oracle. These serve multiple purposes:

### Calibration traps
Forms are designed to test that the system does NOT over-flag. Desmond's fungi allergy in the Oregon dataset must produce a plan-level logistics flag (R-B2, product-type plan) rather than a medical exclusion. Tom's trazodone in the Colorado dataset must be the mild R-4 written-recommendation disposition rather than a serotonergic escalation.

### Semantic precision
Ray's lithium in Colorado must produce `hard_flag: false` with resolution criteria naming the R-2 pathway. Nina's lithium in Oregon must produce `hard_flag: true` with no resolution. Same medication, opposite semantics. The oracle checks this.

### Detection coverage
Nina's psychosis history is answered "No" on the CIF but disclosed in narrative form later (reframed as a sacred experience). The system must catch the contradiction between the form answer and the narrative, and flag R-A3 regardless of her label. This tests the model's ability to evaluate what is described rather than what the applicant calls it.

### Regression protection
When you modify the rules engine, prompt templates, or parser, `pixi run eval` re-runs all datasets and checks:
- 100% of expected reds are present (missing a red = build failure)
- ≥80% of expected yellows are present
- Zero flags on calibration traps
- Cross-dataset assertions hold (lithium semantics differ by state)

---

## Why the regulatory vs. house distinction matters

Facilitators need to know whether a flag represents a legal obligation or a policy choice, because the response is different:

- A **regulatory** flag ("Oregon law says this person cannot participate") leaves no discretion; the facilitator cannot override it on clinical judgment.
- A **house** flag ("our policy declines this pending consulting-clinician review") allows the center to make exceptions through their own processes.

PISA carries `basis` (regulatory/house) and `citation` (rule reference) on every criterion and flag. The UI renders these as distinct chip styles so a reviewer sees the distinction at a glance without reading the full rationale.

---

## Why screening criteria are structured as documents, not config

The context documents (`screening_criteria.md`, `program_description.md`, `reference_material.md`) are authored in natural language rather than YAML or JSON, for four reasons:

1. **Domain experts author them.** A clinical director writes criteria in prose with rule citations. They don't need to learn a schema.
2. **Nuance survives.** "Not exclusionary by rule; see house criterion H-2 for this center's stricter handling" is easy to write in prose, awkward in structured config.
3. **The extraction is the model's job.** The profile builder prompt instructs the LLM to read the documents and produce the structured profile. This leverages what models are good at (structured extraction from natural language) while the resulting profile is what the deterministic engine needs (explicit fields, keyword lists, section targets).
4. **Iteration is fast.** Update the prose, rebuild the profile, re-run eval. No code changes, no schema migrations.

The approval step is where a human verifies that the extraction was faithful. If the model misclassified a criterion, the reviewer catches it before any screening runs.

### Why three document types?

Each document gives the profile builder different information:

- **`screening_criteria`** is the authority. It defines every criterion (with IDs), says what disposition each triggers, and provides detection hints. This is what the rules engine is built from. Example: "R-A1. Lithium within 30 days. A 'yes' means the client may not participate."

- **`program_description`** defines what the program *demands* of participants: physical, psychological, dietary, environmental. These become program-demand cross-checks: a heart condition matters differently for a high-altitude expedition vs. a reclining session. Example: "Transient elevated heart rate and blood pressure; several hours without food; no option to end early."

- **`reference_material`** provides clinical background and regulatory citations that give the model context for *why* criteria exist and how to weigh edge cases. Example: "Lithium + classical psychedelics: case literature associates the combination with seizures." This helps the model's section analysis distinguish "this medication is concerning because..." from "this medication is unremarkable."

Splitting them means a regulatory update (new rule) only requires editing `screening_criteria`; a program logistics change (new venue, longer sessions) only touches `program_description`; new clinical evidence goes into `reference_material`. The profile rebuilds from whatever combination is selected.

---

## Summary of trust boundaries

| Component | Trusted for | Not trusted for |
|---|---|---|
| Context documents | Ground truth criteria, dispositions, pathways | — |
| Profile builder (model) | Structured extraction from docs | Inventing criteria not in the docs |
| Rules engine | Deterministic matching of criteria the profile spelled out | Recall beyond its keyword lists, nuanced interpretation, cross-section patterns |
| Per-section model | Pattern detection, contradiction surfacing, framing analysis | Final decisions, suppressing rule flags |
| Comprehensive pass (model) | Cross-section patterns, implicit connections, timeline reasoning | Same as per-section: final decisions, suppressing rule flags |
| Synthesis model | Comparing flags, detecting redundancy, proposing merges | Final decisions, suppressing rule flags |
| Human reviewer | Final eligibility evaluation, clinical judgment | — |

No component in this table has unilateral authority over an outcome, and the reviewer is the only one that decides anything. That is a design property of the prototype, not a validated safety claim; see the scope note in [README.md](README.md#status-and-scope).
