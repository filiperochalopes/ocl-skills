# ocl-skills

Agent skills for working with [OpenConceptLab](https://openconceptlab.org), with
explicit, repeatable flows instead of ad-hoc scripting.

Each skill is **self-contained**: it carries the knowledge it needs about how the OCL
API behaves, so it works in an environment where this repository is the only thing
available. No skill depends on another project being checked out, on a wiki, or on an
issue tracker.

| File | Role |
| --- | --- |
| `SKILL.md` | The agent-facing procedure, with YAML frontmatter (`name`, `description`) |
| `README.md` | Human-facing reference |
| `reference/*.md` | The OCL and terminology-owner behaviour the skill relies on, written down |
| `schema.py` | Pydantic models for the skill's input/output contract |
| `validation.py` | Client-side replay of the rules OCL enforces server-side |

## Skills

| Skill | Purpose |
| --- | --- |
| [`bulk-import-create-concepts`](skills/bulk-import-create-concepts/) | Stage many new concepts, review them as CSV, then emit a timestamped zipped bulk-import JSONL. Profiles: `generic` (OCL/OpenMRS) and `ciel` (CIEL house rules, incl. the mandatory self mapping) |

Planned, deliberately kept separate because they carry different risk:

- `bulk-retire-concepts` — `__action: DELETE` on concept lines (retires, not deletes)
- `bulk-import-mappings` — mapping-only batches
- `bulk-update-concepts` — batches meant to be imported with "Update existing" on

Each would produce a file for manual upload, like this one. Automating the upload itself
is a separate question, and not one any of these skills answers.

## House rules these skills follow

1. **Confirm the destination every time.** `owner_type` + `owner` + `source`, plus the
   source's validation profile, asked explicitly and recorded in the batch file the user
   reviews. Never inferred, never remembered from a previous run.
2. **CSV before ZIP.** The user reviews a flat CSV and approves it before any import
   artifact is produced.
3. **Every artifact is zipped and timestamped**, named
   `<slug>_<owner>_<source>_<yyyymmdd_hhii>.zip`, with exactly one member inside.
4. **Validate client-side before generating anything.** OCL reports validation failures
   by echoing the offending line back without the error message, so a rule caught at
   review costs seconds and a rule caught at import costs a manual diff.
5. **Create, update and retire are different skills.** In OCL a concept line with
   `__action: DELETE` retires the concept; mixing that into a creation batch is how
   accidents happen.
6. **The deliverable is a file; the user uploads it.** No skill here writes to OCL.
   Generating and validating a batch requires no credentials. Where a live lookup genuinely
   helps it is opt-in, read-only, and the flow works without it.
7. **Write down what the server does.** Anything a skill relies on about OCL's
   behaviour belongs in that skill's `reference/`, not in a comment pointing elsewhere.
8. **A terminology's house rules are a profile, not a fork.** CIEL, and any other owner
   with its own rulebook, is a `profile` layered on the shared flow — so the review gate,
   the artifact conventions and the OCL contract stay in one place.

## Using these with Claude Code

Point Claude Code at the folder, e.g.:

```bash
ln -s "$PWD/skills" .claude/skills
```

## Setup

```bash
pip install -r skills/bulk-import-create-concepts/requirements.txt
```

That is all that is needed. No credentials, no API configuration: the skills produce
files, and the user uploads them through OCL's web interface.

The one optional exception is `validation.py --probe`, a read-only lookup that fills in
a source's validation profile and flags ids that are already taken. It issues GETs only
and needs `OCL_API_TOKEN` (or `OCL_TOKEN` / `OCL_API_KEY`) solely for a private source.
Every flow works without it.

Never commit tokens or generated artifacts containing patient-identifiable data.
`output/` is gitignored.
