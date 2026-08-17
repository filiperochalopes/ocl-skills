# Operating rules for this repository

These apply to **every** skill here and override a skill's own convenience. A skill may
add rules; it may not relax these. Skill-specific rules live in each
`skills/<name>/SKILL.md`.

## 1. Scale decides the mechanism

| What is being changed | How |
| --- | --- |
| **More than one** concept or mapping | Always a bulk import file, always preceded by a CSV review sheet |
| **Exactly one** isolated concept or mapping | The `ocl` CLI, after an explicit confirmation showing the structured before/after |

There is no third option. Do not hand-edit a live repository through a sequence of CLI
writes to avoid producing a file: two changes is a batch.

### Multi-item changes

Produce the artifacts, hand them over, stop. The CSV comes first and the user approves
it before the ZIP exists. The user uploads the ZIP themselves; nothing here uploads.

### Single-item changes

The CLI may write **one** concept or mapping, and only after the user confirms. No
curation spreadsheet is needed for an isolated concept — the confirmation is the review.

Before writing, show:

- the target: server, owner, source, resource id
- the current value of every field being touched
- the proposed value of every field being touched
- anything derived automatically (external ids, self mappings)

Then wait for a clear yes. One approval covers one change; do not carry it forward.

## 2. The CLI is a read tool by default

`ocl` is installed and authenticated. Use it freely for reads — they are safe, fast, and
save the user from looking things up.

Read commands, always allowed:

```
ocl whoami
ocl org get|repos|members|list
ocl repo get|versions|list|extras
ocl concept get|search|names|descriptions|extras|versions|match
ocl mapping get|search|versions
ocl task get|list
ocl cascade
```

Write commands — `create`, `update`, `retire`, `delete`, `add`, `remove`, `extra-set`,
`extra-del`, `version-create`, `import`, `ref add` — are governed by rule 1 and always
need confirmation. `delete` and `retire` are additionally out of scope for any skill
that does not name them explicitly.

## 3. Always verify the session before acting

Start any CLI-backed work with:

```bash
ocl whoami
```

It reports the username **and the server**. Both matter: the same command against
production and against staging are different actions. If it fails, stop and ask the user
to run `ocl login` — never work around an unauthenticated CLI, and never pass a token on
the command line.

State the server in your first substantive message whenever a task touches a live
repository.

## 4. Reads inform, files change

Reading a repository to fill in a batch's `target` profile, to check whether an id is
taken, or to verify an import afterwards is encouraged. Producing the change is still a
file.

After a user reports uploading a bulk file, verify with the CLI rather than trusting the
task summary: OCL reports `created` per line and says nothing about mappings that were
dropped. See `skills/bulk-import-create-concepts/reference/ocl-bulk-import.md`.

## 5. Say what you did not check

Every skill states its own coverage gaps. When a validation layer cannot see something —
cross-concept uniqueness, an external terminology, a rule needing datasets that are not
here — say so plainly instead of letting a clean report imply completeness.
