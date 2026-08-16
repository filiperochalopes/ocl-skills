---
name: bulk-import-create-concepts
description: Stage, review and package the creation of many OCL concepts at once. Use whenever the user wants to create/add multiple concepts in an OpenConceptLab source (CIEL or any org/user source) — "create these 30 concepts", "add this list to CIEL", "bulk import concepts", "generate a bulk import file". Produces a CSV for human review first, then a timestamped zipped JSONL bulk-import file for the user to upload themselves. Does NOT upload, retire or delete anything.
---

# Bulk import: create concepts

Turns a list of concepts the user describes into an OCL bulk-import file, with a
mandatory human review gate in between.

**The deliverable is a file.** This skill never uploads it, never writes to OCL, and
needs no credentials to do its job. The user uploads the ZIP themselves through the OCL
import page. Do not offer to upload it, and do not write a script that does.

Everything needed to build a correct file lives in this skill directory. The full
import contract — line format, mandatory fields, validation rules, error messages,
vocabularies, size limits, and how the user uploads the result — is in
**`reference/ocl-bulk-import.md`**. Read it when a detail is unclear; do not guess and
do not rely on other repositories being present.

## Scope

| In scope | Out of scope |
| --- | --- |
| Creating new concepts in one existing source | Uploading anything, or any write to OCL |
| Names, descriptions, extras, parent hierarchy | Updating existing concepts |
| CSV review → zipped JSONL (split into parts if huge) | Retiring / deleting concepts |
| | Creating the org/source itself |
| | Mapping-only batches |

`__action: DELETE` is the only action OCL honours on a concept line, and it **retires**
rather than deletes. It never belongs in a creation batch — this skill's schema has no
field for it. If the user asks to remove concepts, stop and say this skill does not do
that.

## The flow

Run these in order. Steps 1 and 4 are gates: do not walk past them alone.

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
The user can read them off the source's page in OCL. If they would rather not look them
up, there is an optional read-only lookup that fetches them:

```bash
python validation.py batch.json --probe
```

`--probe` issues GET requests only and is never required. It needs a token only for a
private source. Everything else in this skill works fully offline.

### 2. Draft the batch JSON

One file per request, matching `schema.py::ConceptBatch`. See
`examples/batch.example.json`.

```json
{
  "slug": "malaria-rdt-panel",
  "request": "Create 3 malaria rapid-test concepts requested by the CIEL curator",
  "target": {
    "owner": "CIEL", "owner_type": "Organization", "source": "CIEL",
    "validation_schema": "OpenMRS", "default_locale": "en",
    "supported_locales": ["en", "pt"], "autoid_concept_mnemonic": "sequential"
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
  `update_if_exists` can never match the line, so a re-run creates duplicates.

### 3. Validate

```bash
python validation.py batch.json --json
```

Fix every `error`. Read every `warning` out loud to the user rather than swallowing it
— OCL returns the offending line in its `others` bucket **without the error message**,
so anything not caught here is expensive to diagnose after the upload.

### 4. Generate the CSV and get approval — before any zip

```bash
python build.py csv batch.json --out-dir output
```

Writes `output/<stem>.csv` and prints the `stem`. Show the user the path and a summary
(row count, per-status counts, the target source and its validation schema).
**Wait for explicit approval.** Do not produce the zip in the same turn as the CSV.

If they ask for changes, edit the batch JSON and regenerate the CSV. The stem carries a
new timestamp each run, which is intentional — each review round is its own artifact.

### 5. Pack the approved batch and hand it over

```bash
python build.py pack batch.json --out-dir output --stem <stem from step 4>
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

Two limits to be honest about: uniqueness against concepts **already in the source**
(OCL's rules R8/R9) and ids already taken can only be checked with `--probe`. Offline,
the batch is checked against itself. Say so when it matters, rather than implying the
file is guaranteed to import cleanly.

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
| `schema.py` | Pydantic models, vocabularies, artifact naming (`<slug>_<owner>_<source>_<yyyymmdd_hhii>`) |
| `validation.py` | Rule replay; optional read-only source lookup; CLI report |
| `build.py` | `csv` (review) and `pack` (zipped JSONL, auto-split) stages |
| `examples/batch.example.json` | Minimal working batch |
| `README.md` | Human-facing docs |
