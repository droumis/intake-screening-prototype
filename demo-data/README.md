# Demo data

Everything in this directory is fabricated.

The four programs, the centers that supposedly run them, their screening criteria, their clinical policies, and every applicant and answer were written for this repository as test material. No center named Juniper Ridge, Alder Creek, Bluebird Healing Center, or Summit Series was involved in, consulted about, or is described by any of it. Any resemblance to a real organization is coincidence, and none of these documents represents any real center's policy. Applicant names are invented; contact details use `example.com` addresses, `555` phone numbers, and addresses marked `(fictional)`.

## The regulatory content is illustrative, not authoritative

The Oregon and Colorado datasets paraphrase publicly available rules to create two programs that resolve the same medication in opposite ways. That contrast is the point of the fixtures. The paraphrases were written for this project, are not legal advice, are not accurate summaries of any rule, and are not maintained against amendments. Both states continue to change their frameworks. Anyone with an actual compliance question should read the current rule text and talk to counsel, not read this directory.

The same applies to the criteria in `psilocybin-group-retreat/` and `summit-series/`, which are invented clinical standards attributed to invented organizations.

## Layout

```
<program>/
  context/
    program_description.md   # what the program demands of participants
    screening_criteria.md    # the criteria, IDs, dispositions, detection hints
    reference_material.md    # background the model uses to weigh edge cases
    advisor_memo_CONFLICTING.md   # optional; used only to test conflict detection
  forms/
    applicant_*.md           # completed intake forms
  EXPECTED_FLAGS.md          # test oracle, developer use only
```

`EXPECTED_FLAGS.md` is never loaded as a context document. It records what a correct run should produce, and `pixi run eval` checks runs against it.

## Programs

| Program | What it exercises | Applicants |
|---|---|---|
| `psilocybin-group-retreat` | Center-defined criteria, no regulatory layer. Group format, fasting, remote setting. Includes a conflicting advisor memo. | 3 |
| `summit-series` | Non-psychedelic comparison: high-altitude expedition with heavy physical demands, so the same medical facts carry different weight. Includes a conflicting advisor memo. | 3 |
| `oregon-psilocybin-session` | Regulatory floor plus stricter house criteria, with `basis` and `citation` on each criterion. Lithium is exclusionary here. | 3 |
| `colorado-psilocybin-session` | Clearance-pathway model with no categorical exclusions. Lithium is red but resolvable. | 3 |

Forms are written to test restraint as much as detection. Several contain findings that must produce a logistics or plan-level flag rather than an exclusion, and the oracle fails a run that over-flags them.

## Parser fixtures

`tests/fixtures/alt_format_intake.md` is a synthetic form in a second layout (no title, bold section headings, several questions per line, two-column checklist). It exists for parser tests, has no oracle, and is not part of any program.
