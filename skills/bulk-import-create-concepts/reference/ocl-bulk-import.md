# OCL bulk import — the contract this skill targets

Everything the skill needs to know about how the OCL API ingests a bulk-import file
and how it validates concepts. This document is the authority for this repository:
`schema.py` and `validation.py` implement what is written here, and nothing in the
workflow depends on reading the server source or any other project.

Verified against the OCL API server as of 2026-08.

---

## 1. What the importer accepts

The skill never calls this endpoint — it writes a file the user uploads themselves
(section 8). The constraints below are what make the generated file acceptable.

| Aspect | Rule |
| --- | --- |
| Body | exactly one of `data` (raw text), `file` (multipart), `file_url`. More than one → `Invalid input.` |
| `update_if_exists` | must literally be `'true'` or `'false'`; default `'true'`. Anything else → 400 |
| Empty content | 400 `No content to import` |
| Re-submitting an identical import | 409 `The same import has been already queued` |
| Accepted formats | JSONL, CSV, an OCL source-version export, or a ZIP wrapping one of those |
| Format detection | **by file extension**, so the upload must literally end in `.zip` |
| ZIP contents | **exactly one member**, else `Zip file must contain exactly one file.` |
| Size | practical upload ceiling ~95 MiB per request; server-side upload buffer caps are 200 MB total / 25 MB in-memory |

`update_if_exists` is the setting that separates a creation batch from an update
batch. For this skill's output it must be **off / false**, so that ids which already
exist are reported as `exists` instead of silently overwriting live concepts.

Multi-part uploads must go **in order**, into the same import queue.

---

## 2. File format

One standalone JSON object per line. No wrapping array, no trailing commas. A single
malformed line aborts the whole import.

Every line **must** carry `type`; it is matched case-insensitively. Recognised values:
`Organization`, `Source`, `Source Version`, `Collection`, `Collection Version`,
`Concept`, `Mapping`, `Reference`.

Ownership is carried **per line** by the trio `owner` / `owner_type` / `source`. The
endpoint's own `owner` body field is *not* applied to JSONL lines — it only feeds the
export converter. Getting the trio wrong on the line means concepts created somewhere
unintended.

`owner_type` is lowercased and compared against the exact singulars `organization`
and `user`. **`org`, `orgs` and `users` do not match.** Use `Organization` or `User`.

The parent source is resolved as the **HEAD** version of
`{owner_type}/{owner}/sources/{source}`. If it does not exist the line fails with
`{'source': 'Not Found'}` — the importer will not create it for you.

### Concept line

```json
{"type":"Concept","id":"1234","owner":"CIEL","owner_type":"Organization","source":"CIEL",
 "concept_class":"Diagnosis","datatype":"N/A","retired":false,
 "names":[{"name":"Malaria","locale":"en","locale_preferred":true,"name_type":"FULLY_SPECIFIED"}],
 "descriptions":[{"description":"A mosquito-borne disease","locale":"en","description_type":"Definition"}],
 "external_id":"abc-123","extras":{}}
```

Fields the concept importer accepts — **everything else is silently dropped, with no
error**, which is why this skill's pydantic models reject unknown fields instead:

```
id, external_id, concept_class, datatype, names, descriptions, retired, extras,
parent_concept_urls, update_comment, comment, retire_reason
```

Mandatory at the importer's own gate: **`concept_class` only**. That gate checks key
*presence*, not truthiness, so `"concept_class": null` passes it and fails later.

`datatype` is not checked by that gate but the column is non-nullable and non-blank,
so a missing datatype fails Django's `full_clean` with `This field cannot be blank.`
**Always send it explicitly** — `"N/A"` when not applicable.

`id` is optional. When absent, OCL assigns a mnemonic (from the source's sequence if
`autoid_concept_mnemonic` is set, otherwise an internal fallback). Two consequences:
an id-less line can never be matched by `update_if_exists`, so every re-run creates a
duplicate; and version-grouping during chunking degrades.

`id` is URL-encoded if not already encoded, and must then match
`[a-zA-Z0-9\-\._@+%\s]+`.

### Name and description sub-objects

| Name field | Required | Notes |
| --- | --- | --- |
| `name` | yes | non-null, non-blank |
| `locale` | yes | non-null, non-blank |
| `locale_preferred` | no (default `false`) | |
| `name_type` | no | falls back to `type` when absent or literally `"ConceptName"` |
| `external_id` | no | auto-filled with a UUID when the source configures it |
| `retired`, `retire_reason` | no | |

Descriptions are identical, except the text key is `description` (falling back to
`name`) and the type key is `description_type` (falling back to `type`, ignoring the
literal `"ConceptDescription"`). Descriptions are entirely optional.

A `checksum` key on a name/description is accepted and discarded.

### Processing order

Regardless of position in the file, OCL processes all Organizations, then Sources,
then Collections, then everything else in file order, splitting whenever the child
type changes. Concept chunks are sorted by `id` so all versions of one concept stay
together. Parent-child hierarchy (`parent_concept_urls`) is deferred and reconciled at
the end, restricted to concepts the importing user may edit.

---

## 3. `__action`

Only one value is honoured: **`DELETE`**, matched case-insensitively.

| Value | Effect |
| --- | --- |
| `DELETE` / `delete` (any casing) | routes to the delete path |
| absent, `""`, `null`, **or any other string** | ignored — the line is imported normally |

`CREATE`, `UPDATE`, `CREATE_OR_UPDATE`, `NEW`, `RETIRE`, `SKIP` are **not implemented**.
Sending `"__action": "SKIP"` still imports the line. Create-vs-update is controlled
solely by the `update_if_exists` query param.

What `DELETE` does, per type:

| Type | Effect |
| --- | --- |
| Concept | **retires** — not a hard delete |
| Mapping | **retires** |
| Organization / Source / Collection | hard delete |
| Source Version / Collection Version | no delete path; the line is ignored and the version is (re)created |

A concept delete line still needs `concept_class`, because it passes through the same
validity gate.

One inconsistency worth knowing: the safeguard that disables parallel chunking when a
file contains deletes compares against exact-uppercase `'DELETE'`, while the dispatcher
lowercases. Lowercase `"delete"` deletes but skips the ordering safeguard.

**This skill never emits `__action`.** Creation batches and retirement batches are
separate flows precisely because the failure mode of mixing them is silent.

---

## 4. Validation rules

Two validators. The base validator always runs. The OpenMRS validator runs
**in addition** when the target source's `custom_validation_schema` is `OpenMRS`
(CIEL's is). Confirm the schema with the user or read it off the source's page in OCL; never assume it.

Every rule below is skipped for concepts where `retired` is true.

### 4.1 Always on

| Rule | Message |
| --- | --- |
| At least one name | `A concept must have at least one name` |
| No blank description text | `Concept description cannot be empty` |
| ≤500 names | `max limit 500 of names exceeded` |
| ≤500 descriptions | `max limit 500 of descriptions exceeded` |
| Unique id in source | `Concept ID must be unique within a source.` |
| `concept_class`, `datatype` non-blank | Django `This field cannot be blank.` |
| No-op update | `No changes detected. Standard checksum is same as last version.` → reported as `unchanged`, not a failure |

### 4.2 OpenMRS schema only

| # | Rule | Message |
| --- | --- | --- |
| R1 | Concept `external_id` ≤ 36 chars | `Concept External ID cannot be more than 36 characters.` |
| R2 | At most one `locale_preferred` name per locale | `A concept may not have more than one preferred name (per locale)` |
| R3 | All non-short names unique per (locale, text) | `All names except short names must be unique for a concept and locale` |
| R4 | At most one `SHORT` name per locale | `A concept cannot have more than one short name in a locale` |
| R5 | `SHORT` / `INDEX_TERM` cannot be preferred | `A short name cannot be marked as locale preferred` |
| R6 | At most one FSN per locale | `A concept may not have more than one fully specified name in any locale` |
| R7 | At least one FSN overall | `A concept must have at least one fully specified name` |
| R8 | FSN unique in source+locale | `Concept fully specified name must be unique for same source and locale` |
| R9 | Preferred name unique in source+locale | `Concept preferred name must be unique for same source and locale` |
| R10 | `concept_class` in the Classes lookup | `Invalid concept class` |
| R11 | `datatype` in the Datatypes lookup | `Invalid data type` |
| R12 | `name_type` in the NameTypes lookup | `Invalid name type` |
| R13 | `description_type` in the DescriptionTypes lookup | `Invalid description type` |
| R14 | Locales valid | `Invalid name locale` / `Invalid description locale` |
| R15 | Name / description `external_id` ≤ 36 chars | `Concept name's External ID cannot be more than 36 characters.` |

Name-scoped messages get a suffix: `: <name> (locale: <locale>, preferred: yes|no)`.

R8/R9 compare against other concepts in the source that are active, non-retired and
latest-version, excluding SHORT/INDEX_TERM/blank name types.

R10 retries with `-` replaced by ` `, which is why the dashed ids of the lookup
concepts also validate.

R11 treats an absent datatype as the string `"None"` — which *is* a legal value — so a
missing datatype passes R11 and then fails the non-blank column check instead.

R14 uses the source's `supported_locales` **union** the Locales lookup source, so a
locale outside `supported_locales` may still be legal.

### 4.3 Three traps

1. **R14 only runs when the concept has both names *and* descriptions.** A concept with
   names and no descriptions skips locale validation entirely — a bad locale slips in
   at import and surfaces much later.
2. **R10–R14 are skipped entirely** when the concept's own `concept_class` is one of
   `Concept Class`, `Datatype`, `NameType`, `DescriptionType`, `MapType`, `Locale`
   (that is how the lookup sources bootstrap themselves).
3. **FSN detection is lenient, SHORT/INDEX_TERM detection is strict.** Any casing or
   spacing variant normalising to `fullyspecified` counts as an FSN, but only exactly
   `SHORT`/`Short` and `INDEX_TERM`/`Index Term` are recognised. Lowercase `"short"` is
   treated as an ordinary synonym and will then trip R3 or R2.

---

## 5. Vocabularies

Validation compares against the **name strings** of the concepts in the lookup sources
(synonyms included), not their ids. `schema.py` holds these as frozensets and is the
machine-readable copy.

**Concept classes** — `Aggregate Measurement`, `Anatomy`, `ConvSet`, `Diagnosis`,
`Dose Form Group`, `Drug`, `Drug form`, `Finding`, `Frequency`,
`Health Care Monitoring Topics`, `Indicator`, `InteractSet`, `LabSet`, `MedSet`,
`Medical supply`, `Misc`, `Misc Order`, `Organism`, `Pharmacologic Drug Class`,
`Procedure`, `Program`, `Question`, `Radiology/Imaging Procedure`, `Specimen`, `State`,
`Symptom`, `Symptom/Finding`, `Test`, `Units of Measure`, `Workflow`.

Note the two slash forms: the dashed ids `Symptom-Finding` and
`Radiology-Imaging-Procedure` do **not** match, because the dash→space retry produces
`Symptom Finding`, not `Symptom/Finding`. Send the slash form.

**Datatypes** — `BIT`, `Boolean`, `CWE`, `Coded`, `Complex`, `DT`, `Date`, `Datetime`,
`Document`, `ED`, `N/A`, `NM`, `None`, `Numeric`, `RP`, `Rule`, `SN`, `ST`,
`Structured Numeric`, `TM`, `TS`, `Text`, `Time`, `ZZ`.

**Name types** — `Fully Specified` / `FULLY_SPECIFIED`, `Short` / `SHORT`,
`Index Term` / `INDEX_TERM`, `None`.

**Description types** — `Definition`, `None`.

---

## 6. Result buckets

Each line lands in exactly one bucket of the task result:

```
created  updated  unchanged  exists  deleted  invalid
failed   others   unknown    permission_denied  exception
```

| Bucket | Meaning |
| --- | --- |
| `exists` | already present and `update_if_exists=false` |
| `invalid` | mandatory field missing (for concepts: `concept_class`) |
| `unchanged` | identical checksum, no new version created |
| `unknown` | line had no recognised `type` |
| **`others`** | **validation errors land here, not in `failed`** |

The critical limitation: the bucket contains the **original line, without the error
message**. The server does not tell you which rule failed. That is the whole reason
this skill replays the rules client-side before generating anything — a row rejected
at review costs seconds, a row rejected at import costs a manual diff.

---

## 7. Source settings that change behaviour

These belong in the batch file's `target` block so the reviewer can see them. Read
them off the source's page in OCL, or let `validation.py --probe` fetch them.

| Field | Why it matters |
| --- | --- |
| `custom_validation_schema` | `OpenMRS` turns on R1–R15 |
| `default_locale` | the locale the primary FSN should use |
| `supported_locales` | feeds R14 |
| `autoid_concept_mnemonic` | `sequential` / `uuid` — when set, `id` may be omitted |
| `autoid_concept_external_id` | when `uuid`, generated ids are exactly 36 chars, which passes R1 |

---

## 8. How the user uploads the file

The skill's deliverable is the ZIP. Uploading is a deliberate human step, done in the
OCL web application — there is no automated upload anywhere in this repository.

1. Sign in to OCL and open the **Imports** page (from the account menu).
2. Upload the ZIP produced by `build.py pack`.
3. Leave **"Update existing"** / `update_if_exists` **off**. A creation batch should
   never overwrite existing concepts; with it off, an id that already exists is
   reported in the `exists` bucket instead.
4. Submit, and watch the task until it reaches `SUCCESS` or `FAILURE`. A parent task
   can report `SUCCESS` as soon as its children are dispatched, so check the child
   tasks when the counts look short.
5. Read the result buckets (section 6). `created` should equal the row count of the
   approved CSV. Anything in `others`, `invalid` or `failed` needs to come back for a
   new round: fix the batch file, regenerate the CSV, re-approve.

For a multi-part batch, upload the parts **in ascending order** into the same import
queue, waiting for each to finish before starting the next.

Why the counts are worth checking against the CSV: the file the user uploads is the one
they approved, so any gap between `created` and the approved row count is a real
discrepancy, not a rounding difference.
