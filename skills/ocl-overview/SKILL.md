---
name: ocl-overview
description: Answer questions about what is in an OpenConceptLab organization or source with a structured, read-only summary — content counts, validation profile, locales, autoid settings, repositories and version history. Use when the user asks "what's in CIEL", "summarise this org/source", "which version is current", "what locales does it support", "is this source OpenMRS-validated", or before staging a bulk import against a source. Read-only; never writes to OCL.
---

# OCL overview

Answers "what is this org/source, and what state is it in?" in one pass, using the `ocl`
CLI's read commands, so the user does not get five separate lookups and a guess.

Strictly read-only. `overview.py` runs only commands on an allowlist and refuses
anything else, so it cannot write to OCL even if instructed to.

## Always check the session first

```bash
ocl whoami
```

This is not a formality: it reports the **server** as well as the user, and "CIEL on
production" and "CIEL on staging" are different answers to the same question. If the
command fails, stop and ask the user to run `ocl login`. Never pass a token on the
command line and never work around an unauthenticated CLI.

`overview.py` does this automatically and prints the session in its header. State the
server in your reply whenever the answer describes live content.

## Use

```bash
python overview.py CIEL              # organization: profile + every repository
python overview.py CIEL CIEL         # source: content, validation profile, versions
python overview.py CIEL CIEL --json  # same data, machine-readable
python overview.py someuser REPO --user   # user-owned repository
```

`--versions N` changes how many versions are listed (default 5).

## What to report back

Lead with what the user asked. Then, unprompted, surface the things that change what
they can do next:

- **Validation schema.** `OpenMRS` means fifteen extra rules apply to any concept
  created there. This is the single most consequential field.
- **Content scale.** Active concepts and mappings — a source with 55,000 concepts is a
  different proposition from one with 40.
- **Version state.** Latest released version and how recent it is. A source whose HEAD
  has moved well past its last release is mid-cycle.
- **Autoid.** Whether OCL assigns concept mnemonics, which decides whether a batch has
  to supply ids.
- **Supported locales**, when the user is adding translations.

Do not dump every field. The JSON is there when someone needs the rest.

## Sequencing beyond the script

The script covers org and source. For anything deeper, keep using read commands and say
which you ran:

| Question | Command |
| --- | --- |
| Does this concept exist, and does it have its mappings? | `ocl concept get OWNER SOURCE ID --include-mappings` |
| What is in here about X? | `ocl concept search X --owner OWNER --repo SOURCE` |
| Which concepts match these terms? | `ocl concept match "term" --target-source SOURCE` |
| What changed on this concept? | `ocl concept versions OWNER SOURCE ID` |
| How did that import go? | `ocl task list` / `ocl task get TASK_ID` |
| What does this concept pull in? | `ocl cascade OWNER SOURCE ID` |
| Who can edit this org? | `ocl org members ORG` |

## Feeding a bulk import

A source overview ends with a ready-to-paste `target` block for
`bulk-import-create-concepts`, carrying the four fields that decide which rules apply:
`validation_schema`, `default_locale`, `supported_locales`, `autoid_concept_mnemonic`.

Use it rather than asking the user to read them off the OCL web UI. Confirming the
destination with them is still required — this fills in the profile, not the decision.

## Verifying an import

After the user uploads a bulk file, do not trust the task summary alone: OCL reports
`created` per concept line and says nothing about mappings that were dropped.

```bash
ocl concept get OWNER SOURCE ID --include-mappings
```

Check a sample of the ids from the approved CSV, and specifically confirm the mappings
are present. See `../bulk-import-create-concepts/reference/ocl-bulk-import.md`.

## Boundaries

Read-only. If the user asks this skill to change something, route them by scale, per the
repository rules in `CLAUDE.md`: more than one concept or mapping means a bulk import
file with a CSV review; a single isolated one may go through the CLI after an explicit
confirmation showing the structured before/after.
