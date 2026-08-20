---
name: bulk-import-create-concepts
description: Stage, review and package the creation of many OCL concepts at once, with an optional CIEL rulebook. Use whenever the user wants to create/add multiple concepts in an OpenConceptLab source — "create these 30 concepts", "add this list to CIEL", "bulk import concepts", "generate a bulk import file", "create concepts with CIEL validation". Produces a CSV for human review first, then a timestamped zipped JSONL bulk-import file for the user to upload themselves. Does NOT upload, retire or delete anything.
---

# Bulk import: create concepts

Turns a list of concepts the user describes into an OCL bulk-import file, with a
mandatory human review gate in between.

**The deliverable is a file.** This skill never uploads it, never writes to OCL, and
needs no credentials to do its job. The user uploads the ZIP themselves through the OCL
import page. Do not offer to upload it, and do not write a script that does.

Everything needed to build a correct file lives in this skill directory:

- **`reference/ocl-bulk-import.md`** — the OCL contract: line format, mandatory fields,
  validation rules, error messages, vocabularies, size limits, manual upload.
- **`reference/ciel-concept-rules.md`** — CIEL's own house rules, used by the `ciel`
  profile: the mandatory self mapping, CIEL defaults, and the FR/CE rule coverage.
- **`reference/concept-classification.md`** — how to choose `concept_class` and
  `datatype` from a concept's name and description.
- **`reference/ciel-extras.md`** — the extras keys CIEL/CIEL actually uses, with the
  JSON types the live data carries.

Read them when a detail is unclear; do not guess and do not rely on other repositories
being present.

## Profiles

The batch declares which rulebook applies:

| `profile` | Applies |
| --- | --- |
| `generic` (default) | OCL's importer contract + the source's validation schema (`None` or `OpenMRS`) |
| `ciel` | all of the above, plus CIEL's in-concept rules, CIEL's defaults, and the automatic `SAME-AS` self mapping |

Use `ciel` whenever the destination is a CIEL-governed source — normally
`CIEL/CIEL`. Ask if it is not obvious; do not infer it from the org name alone.

Every concept gets the mandatory `SAME-AS` self mapping automatically, nested in the
concept line the same way the CIEL editor posts it. Concepts without an `id` use the
`__parent_concept` sentinel, so ids remain optional.

> [!IMPORTANT]
> Nested mappings **do** import. https://github.com/OpenConceptLab/ocl_issues/issues/2683
> is fixed and live — verified end to end against OCL `2.3.201-846796dc` on 2026-08-20:
> a concept line's `mappings` are created, cross-line `to_concept_code` references resolve
> regardless of line order, and `"to_concept": "__parent_concept"` self-maps a concept
> whose mnemonic the source assigned.
>
> What did *not* change is the reporting. OCL's import summary counts **concept lines
> only**, so `Created: N` is silent about mappings — and a mapping whose target does not
> exist is accepted and stored as a bare `to_concept_code` with no resolved target, no
> error. Tell the user this every time a batch carries mappings: after importing, check
> the source's mapping count against the CSV before treating the batch as done.

`validation.py` raises `nested-mappings-verify-after-import` on any batch carrying
mappings, so that reminder also reaches the review CSV.

## Scope

| In scope | Out of scope |
| --- | --- |
| Creating new concepts in one existing source | Uploading anything, or any write to OCL |
| Names, descriptions, extras, parent hierarchy, mappings | Updating existing concepts |
| CIEL house rules via the `ciel` profile | Retiring / deleting concepts |
| CSV review → zipped JSONL (split into parts if huge) | Creating the org/source itself |
| | Mapping-only batches (no concepts) |

`__action: DELETE` is the only action OCL honours on a concept line, and it **retires**
rather than deletes. It never belongs in a creation batch — this skill's schema has no
field for it. If the user asks to remove concepts, stop and say this skill does not do
that.

## The flow

Run these in order. Steps 1 and 5 are gates: do not walk past them alone.

### 1. Confirm the destination and its profile — always, every time

Never infer the target from context, a previous run, or a default. Ask explicitly:

- **owner_type** — `Organization` or `User` (exact singular; OCL compares against the
  lowercase singulars, so `org`/`orgs`/`users` silently fail to resolve)
- **owner** — e.g. `CIEL`, `OpenMRS-OCL-Squad`
- **source** — e.g. `CIEL`

Then the source's validation profile, because it decides which rules apply:

- **validation_schema** — `OpenMRS` or `None`. CIEL is `OpenMRS`, which is far
  stricter. Getting this wrong means validating against the wrong rule set.
- **default_locale** and **supported_locales**
- **autoid_concept_mnemonic** — if set, `id` may be omitted

All four go in the batch file's `target` block, so the reviewer sees what was assumed.

The quickest way to fill them in is the `ocl-overview` skill, which ends its source
summary with a ready-to-paste `target` block:

```bash
ocl whoami                                          # confirm user AND server first
python ../ocl-overview/overview.py CIEL CIEL
```

Failing that, the user can read them off the source's page in OCL, or this skill has its
own optional read-only lookup:

```bash
python validation.py batch.json --probe
```

Both are reads. `--probe` needs a token only for a private source, and everything else
in this skill works fully offline.

Confirming the destination with the user is still required either way — a lookup fills
in the profile, it does not make the decision.

### 2. Classify every concept — do not let defaults decide

`concept_class` and `datatype` are meaning, not metadata. Work each concept out from its
name and description using `reference/concept-classification.md`, and put the reasoning
in that concept's `note` so the reviewer can check the judgement instead of re-deriving
it.

The short version: `concept_class` answers *what kind of thing is this* (a `Test` and a
`Diagnosis` are different animals); `datatype` only means anything for question-like
concepts, and is `N/A` for everything else — diagnoses, findings, anatomy, drugs, sets.

`Misc` and `N/A` are legitimate answers when they are chosen. They are not legitimate as
something that happened because nobody looked. A value that merely fell through is
reported as `concept-class-unclassified` / `datatype-unclassified` and appears in the
CSV as `Misc (UNCLASSIFIED)`, which is the reviewer's cue that a row was never
classified. Setting the same value explicitly clears the warning — that is the point:
the record shows a decision was made.

Batch-level `defaults` count as a decision too, so use them when a batch really is
homogeneous ("these forty rows are all `Test` / `Coded`") rather than repeating a value
forty times. Do not use them to paper over a mixed batch.

When you are unsure on a handful of rows, ask. When you are unsure across a large batch,
classify with your best judgement, write the doubt into `note`, and name those rows in
the handover.

### 3. Draft the batch JSON

One file per request, matching `schema.py::ConceptBatch`. See
`examples/batch.example.json`.

```json
{
  "slug": "malaria-rdt-panel",
  "request": "Create 3 malaria rapid-test concepts requested by the CIEL curator",
  "profile": "ciel",
  "target": {
    "owner": "CIEL", "owner_type": "Organization", "source": "CIEL",
    "validation_schema": "OpenMRS", "default_locale": "en",
    "supported_locales": ["en", "pt"]
  },
  "defaults": {"concept_class": "Test", "datatype": "Coded", "locale": "en"},
  "concepts": [ ... ]
}
```

Defaults that match single-concept creation:

- `datatype` — `"N/A"` when not applicable. Never leave it blank: OCL's importer treats
  only `concept_class` as mandatory, so a missing datatype survives the importer's own
  gate and then fails the non-blank column check.
- names — first name is `FULLY_SPECIFIED`, `locale_preferred: true`, in the source's
  `default_locale`.
- `id` — supply one unless the source has `autoid_concept_mnemonic`. Without an id,
  `update_if_exists` can never match the line, so a re-run creates duplicates. Under the
  `ciel` profile an id is always required.

Under the `ciel` profile, additionally: a missing `external_id` is derived as a stable
UUID, and `"name_type": "SYNONYM"` is accepted and emitted as an absent type (OCL
rejects the literal string). `examples/batch.ciel.example.json` is a working CIEL batch.

### 3b. Extras

`extras` is an open JSON object on every concept — whatever the user asks for goes in.
Two ways to set it:

```json
"defaults": {"extras": {"clinical": "false", "source_of_truth": "curator-request"}},
"concepts": [{"id": "7102", "extras": {"clinical": "true"}}]
```

Batch `defaults.extras` is merged into every concept; a key the concept sets itself
wins, so a batch-wide flag can still be overridden row by row. All JSON types survive
verbatim — strings, booleans, numbers, arrays, nested objects.

One trap worth raising with the user: OCL stores extras as JSON **without coercing**, so
`"false"` (string) and `false` (boolean) are different values, and a consumer testing
for a boolean will not match the string. `validation.py` warns with
`extras-string-boolean` whenever a value is the string `"true"` or `"false"`. It is a
warning, not an error, because CIEL genuinely uses string booleans in places
(`IsPostcoordinated: "True"`). Ask which one the target expects rather than guessing.

The merged result appears in the review CSV's `extras` column, so the reviewer sees what
each concept will actually carry.

Under the `ciel` profile the keys are also checked against the vocabulary CIEL/CIEL
actually uses, sampled from the live source — see `reference/ciel-extras.md`:

- `extras-unknown-key` (warning) catches typos like `unitss` or `clincal`
- `extras-unexpected-type` (warning) catches `allow_decimal: "true"` when the data
  stores a real boolean, or `low_absolute: "zero"` where a number belongs
- `extras-reserved-key` (**error**) catches `retired_reason`, which OCL owns as a column

Some keys are load-bearing: the numeric metadata (`units`, `hi_absolute`,
`allow_decimal`, …) drives CE-02/CE-03, and `is_set` drives CE-04.

Mind the boolean-ish keys: `allow_decimal` and `clinical` are real JSON booleans, while
`is_set` is the integer `1` — the last is the live data's doing, not a choice.

`clinical` is stored **only when `false`**: absence means clinical, so a `true` is
redundant and reported as `extras-redundant-default`. Tagging a batch of non-clinical
concepts is a natural use of `defaults.extras`:

```json
"defaults": {"extras": {"clinical": false}}
```

An unknown key is a warning, not a blocker — a genuinely new key is legitimate. Ask the
user to confirm it rather than silently shipping a misspelling.

### 4. Validate

```bash
python validation.py batch.json --json
```

Fix every `error`. Read every `warning` out loud to the user rather than swallowing it
— OCL returns the offending line in its `others` bucket **without the error message**,
so anything not caught here is expensive to diagnose after the upload.

### 5. Generate the CSV and get approval — before any zip

```bash
python build.py csv batch.json --out-dir output
```

Writes `output/<stem>.csv` and prints the `stem`. Show the user the path and a summary
(row count, per-status counts, the target source and its validation schema). Call out
any row still marked `UNCLASSIFIED` explicitly — that is a question for the curator, not
a detail to bury in a count.
**Wait for explicit approval.** Do not produce the zip in the same turn as the CSV.

If they ask for changes, edit the batch JSON and regenerate the CSV. The stem carries a
new timestamp each run, which is intentional — each review round is its own artifact.

### 6. Pack the approved batch and hand it over

```bash
python build.py pack batch.json --out-dir output --stem <stem from step 5>
```

Passing `--stem` pairs the zip with the CSV the user actually approved. Output:

```
output/<slug>_<owner>_<source>_<yyyymmdd_hhii>.zip
```

containing exactly one member, `<same stem>.jsonl`. One member is a hard requirement —
OCL errors with `Zip file must contain exactly one file.` otherwise.

`pack` refuses to run while validation errors remain; `--allow-errors` exists only for
an explicit, stated user override.

Batches too large for a single upload are split automatically into
`<stem>.partNNofMM.zip`, to be uploaded in ascending order into one import queue.

Then hand the file over and stop. Tell the user:

- where the ZIP is, and how many concepts it creates
- the exact destination it targets
- to upload it on OCL's **Imports** page with **"Update existing" off**, so an id that
  already exists is reported rather than overwriting a live concept
- to compare `created` against the approved CSV's row count, and to bring back anything
  landing in `others`, `invalid` or `failed` for a new round

### Verify afterwards — the task summary is not enough

When the user reports the upload is done, check the result with the CLI rather than
trusting `Created: N`. OCL counts concept lines and says nothing about mappings it
dropped, so a batch carrying mappings can report complete success and be missing all of
them (see the IMPORTANT notice above).

```bash
ocl concept get <owner> <source> <id> --include-mappings
```

Sample several ids from the approved CSV, and for a CIEL batch confirm the `SAME-AS`
self mapping is actually there. Report what you checked and what you found.

`reference/ocl-bulk-import.md` section 8 has the full upload walkthrough.

## Rules replayed by `validation.py`

Always on:

- at least one name; no blank description text; `concept_class` present;
  `datatype` non-blank; concept id matches `[a-zA-Z0-9\-\._@+%\s]+`; ≤500 names and
  ≤500 descriptions; ids unique within the batch.

OpenMRS schema only:

- at least one `FULLY_SPECIFIED` name, at most one per locale
- at most one `locale_preferred` name per locale
- `SHORT` and `INDEX_TERM` names cannot be `locale_preferred`; at most one `SHORT` per locale
- all non-short names unique per (locale, text) within the concept
- FSN and preferred name unique across the batch per locale
- `concept_class`, `datatype`, name and description types in their lookup vocabularies
- external ids ≤ 36 characters (concept, each name, each description)

CIEL profile, additionally — the in-concept rules FR-11, FR-12, FR-13, FR-15, FR-19,
FR-23, FR-24, FR-25 and CE-01 through CE-04. Full table in
`reference/ciel-concept-rules.md`.

Be honest about the limits rather than implying the file will import cleanly:

- Uniqueness against concepts **already in the source** (R8/R9, and CIEL's FR-09/FR-10/
  FR-26) and ids already taken need `--probe`. Offline, the batch is checked against
  itself.
- CIEL's FR-18 (sentence case), FR-21 (units) and FR-22 (retired mapping targets) are
  **not** implemented: they need CIEL's datasets or an indexed terminology. Call
  `ciel_rules.unimplemented_rules()` for the current list and say which checks the
  reviewer still owns.

Two traps worth stating to the user when relevant:

1. OCL skips locale validation entirely for concepts with names but **no** descriptions —
   a bad locale slips through at import and only bites later.
2. `SHORT`/`INDEX_TERM` are matched case-sensitively; `"short"` is not recognised as a
   short name and will be validated as an ordinary synonym.

Full rule table, exact server messages and vocabularies: `reference/ocl-bulk-import.md`.

## Files

| File | Role |
| --- | --- |
| `reference/ocl-bulk-import.md` | The OCL import contract — format, rules, messages, vocabularies, limits, manual upload |
| `reference/ciel-concept-rules.md` | CIEL's house rules — self mapping, defaults, FR/CE coverage |
| `reference/concept-classification.md` | Choosing `concept_class` and `datatype`, with worked examples |
| `reference/ciel-extras.md` | The CIEL/CIEL extras vocabulary, sampled from the live source |
| `ciel_rules.py` | The `ciel` profile's in-concept rules |
| `schema.py` | Pydantic models, vocabularies, artifact naming (`<slug>_<owner>_<source>_<yyyymmdd_hhii>`) |
| `validation.py` | Rule replay; optional read-only source lookup; CLI report |
| `build.py` | `csv` (review) and `pack` (zipped JSONL, auto-split) stages |
| `examples/batch.example.json` | Minimal working batch (generic profile) |
| `examples/batch.ciel.example.json` | Working batch with the CIEL profile |
| `README.md` | Human-facing docs |
