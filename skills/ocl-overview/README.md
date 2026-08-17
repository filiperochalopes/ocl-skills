# ocl-overview

Structured, read-only summaries of an OpenConceptLab organization or source, built by
sequencing the `ocl` CLI's read commands.

`SKILL.md` is the agent-facing procedure. This file is the human-facing reference.

## Prerequisite

The [OCL CLI](https://github.com/OpenConceptLab/ocl-cli), installed and logged in:

```bash
ocl whoami
```

If that fails, run `ocl login`. Everything here depends on it, and nothing here handles
tokens itself — the CLI owns the credential.

## Use

```bash
python overview.py CIEL                    # organization
python overview.py CIEL CIEL               # source
python overview.py CIEL CIEL --versions 10
python overview.py CIEL CIEL --json
python overview.py someuser REPO --user    # user-owned repository
```

### Source output

```
# CIEL/CIEL
- Session: filipelopes on OCL Online Production Server
- CIEL — Interface Terminology, access View
- Content: 55,644 active concepts, 273,749 active mappings
- Versions: 52 | latest release: v2026-07-20 | updated 2026-07-06

## Validation profile
- Schema: OpenMRS  <- the strict OpenMRS rule set applies
- Default locale: en
- Supported locales: en, am, ar, ...
- Concept mnemonics: sequential (OCL assigns ids)
- Match algorithms: llm, es

## Recent versions
| version | released | created |

## For a bulk-import batch
{ ...ready-to-paste target block... }
```

The trailing block is the `target` for `bulk-import-create-concepts`, so the profile
that decides which validation rules apply is read from the source rather than guessed.

## Read-only by construction

`overview.py` routes every CLI call through one function that checks the subcommand
against an allowlist:

```python
READ_COMMANDS = {("whoami",), ("org","get"), ("org","repos"), ("org","members"),
                 ("repo","get"), ("repo","versions")}
```

Anything else raises before a process is spawned. The script cannot create, update,
retire or delete, regardless of how it is called.

## Why the session check is not optional

`ocl whoami` reports the **server** as well as the user. The same org and source names
exist on production and on staging, so a summary without the server named is ambiguous
in exactly the situations where it matters most. The script prints it in every header.

## Beyond org and source

The script covers the two summary shapes. For concept-level questions, use the CLI
directly — `SKILL.md` has the table. The one worth knowing:

```bash
ocl concept get CIEL CIEL 116128 --include-mappings
```

which is how you confirm, after a bulk upload, that a concept arrived **and** kept its
mappings. That distinction matters: OCL's importer reports success per concept line
while silently discarding a line's mappings.
