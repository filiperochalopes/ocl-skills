# bulk-import-create-concepts

Stage, review and package the creation of many OpenConceptLab concepts at once.

> [!IMPORTANT]
> Concepts created with **nested mappings depend on the fix for https://github.com/OpenConceptLab/ocl_issues/issues/2683**.
> OCL's bulk importer currently drops a concept line's `mappings` key silently: the
> import reports success and the mappings never exist. This skill emits the nested form
> on purpose, matching what the CIEL editor posts, so that batches are correct the day
> the fix lands. Until then, verify mappings after every import, or create them
> separately.

Curators need to stage a batch of new concepts, see what would be created, and catch
invalid rows *before* anything is imported — with the same defaults and validation as
single-concept creation, whether driven by a human or an agent.

**The deliverable is a file.** Nothing here uploads it or writes to OCL in any way.
The user uploads the ZIP themselves on OCL's Imports page, which keeps the decision to
modify a live terminology where it belongs. Generating and validating a batch needs no
credentials at all.

`SKILL.md` is the agent-facing procedure. This file is the human-facing reference.
Two documents under `reference/` hold the domain knowledge, and the skill is
self-contained — nothing here requires another repository or an external document:

- `reference/ocl-bulk-import.md` — how OCL itself behaves: the JSONL line format,
  mandatory fields, every validation rule with its exact server message, the lookup
  vocabularies, `__action` semantics, result buckets and upload limits.
- `reference/ciel-concept-rules.md` — CIEL's house rules: the mandatory self mapping,
  CIEL's creation defaults, and which FR/CE rules are covered, delegated or skipped.

## Profiles

| `profile` | Applies |
| --- | --- |
| `generic` (default) | OCL's importer contract plus the source's validation schema |
| `ciel` | the above, plus CIEL's in-concept rules, defaults, and the automatic `SAME-AS` self mapping |

Under `ciel`, the mandatory `SAME-AS` self mapping is added to every concept
automatically. Concepts without an `id` use the `__parent_concept` sentinel, which OCL
resolves once it assigns the mnemonic — so ids stay optional, exactly as in the CIEL
editor. Subject to the notice above. See `reference/ciel-concept-rules.md` section 1.

## The two artifacts

Every run produces at most two files under `output/`, sharing one stem:

```
<slug>_<owner>_<source>_<yyyymmdd_hhii>.csv     # review sheet  — always
<slug>_<owner>_<source>_<yyyymmdd_hhii>.zip     # bulk import   — only after approval
```

The CSV always comes first. The zip is never produced in the same step as the CSV, and
never while validation errors remain. Each zip contains exactly one member — the JSONL
with the same stem — because OCL rejects archives with more than one file. A batch too
large for a single upload is split into `<stem>.partNNofMM.zip`, to be posted in order
under one import queue id.

## Quick start

```bash
cd skills/bulk-import-create-concepts
pip install -r requirements.txt

python validation.py examples/batch.example.json
python build.py csv  examples/batch.example.json --out-dir ../../output
# ... user reviews the CSV and approves ...
python build.py pack examples/batch.example.json --out-dir ../../output \
  --stem malaria_rdt_panel_ciel_ciel_20260815_1432
```

Then upload the ZIP yourself on OCL's **Imports** page, with **"Update existing" off**.
Walkthrough: `reference/ocl-bulk-import.md` section 8.

## Batch file

A single JSON document (`schema.py::ConceptBatch`):

| Field | Notes |
| --- | --- |
| `slug` | Short description of the request; slugified into the file names |
| `request` | Verbatim summary of what the user asked for — provenance for the review |
| `target` | `owner`, `owner_type` (`Organization`/`User`), `source`, plus the source's validation profile: `validation_schema`, `default_locale`, `supported_locales`, `autoid_concept_mnemonic` |
| `defaults` | `concept_class`, `datatype` (default `N/A`), `locale` — applied to rows that omit them |
| `profile` | `generic` (default) or `ciel` |
| `concepts[]` | `id`, `external_id`, `concept_class`, `datatype`, `names[]`, `descriptions[]`, `mappings[]`, `extras`, `parent_concept_urls[]`, `hierarchy_meaning`, `note` |

`note` is review-only metadata; it appears in the CSV and is stripped from the JSONL.

There is deliberately **no** `retired` and **no** `__action` field. In OCL,
`__action: DELETE` on a concept line retires the concept — a different intent that
belongs in a different flow.

## Validation layers

0. **Profile** — when the batch declares `profile: "ciel"`, `ciel_rules.py` layers
   CIEL's in-concept rules (FR-11/12/13/15/19/23/24/25, CE-01..CE-04) on top, keeping
   CIEL's own rule identifiers so findings match CIEL Lab.
1. **Structural** — pydantic (`schema.py`). Unknown fields are rejected outright,
   because OCL's importer drops them silently and you would never learn about a typo.
2. **Semantic** — `validation.py` replays the always-on rules and, when the target
   source runs the OpenMRS schema, R1–R15; plus cross-row checks (duplicate ids,
   duplicate FSNs/preferred names within the batch, unresolvable parents).
3. **Repository** — *optional and read-only*. `--probe` fetches the live source's
   validation profile and flags ids that already exist and FSNs that would collide.
   GETs only; a token is needed solely for a private source.

Layers 1 and 2 are the normal path and run fully offline. They matter because OCL puts
validation failures in its `others` bucket and echoes back the offending line **without
the error message** — anything not caught before the upload has to be diagnosed by hand.

What offline validation cannot see: whether an id is already taken in the source, and
whether a name collides with a concept already there. Those are the two checks that
need `--probe`. Without it, the batch is validated thoroughly against itself and the
rulebook, but a clean report is not a guarantee that the import will be conflict-free.

Under the CIEL profile, three of CIEL's own rules are out of reach by design — FR-18
(sentence case, which needs a 769 KB genus/eponym dataset), FR-21 (unit canonicalisation)
and FR-22 (mappings to retired codes). `ciel_rules.unimplemented_rules()` returns the
current list with reasons, so the gap can be stated rather than assumed away.

## Why the target and its profile are confirmed every time

`owner_type` is compared against the exact lowercase singulars `organization` / `user`.
`org`, `orgs` and `users` do not match. Each JSONL line carries its own
`owner`/`owner_type`/`source` trio, and the import form's own owner field does not
override them — so a wrong destination means concepts silently created in the wrong
place.

The validation profile is confirmed for the same reason: a source running the OpenMRS
schema is validated against fifteen extra rules, and assuming the wrong one produces a
file that passes review and then fails at import.

## Layout

```
SKILL.md                          agent procedure
README.md                         this file
reference/ocl-bulk-import.md      the OCL import contract
reference/ciel-concept-rules.md   CIEL's house rules
schema.py                         pydantic models, vocabularies, artifact naming
validation.py                     rule replay, optional probes, CLI report
ciel_rules.py                     the ciel profile's in-concept rules
build.py                          csv and pack stages
examples/batch.example.json       minimal working batch (generic)
examples/batch.ciel.example.json  working batch with the CIEL profile
requirements.txt
```
