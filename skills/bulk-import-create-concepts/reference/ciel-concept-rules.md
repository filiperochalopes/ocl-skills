# CIEL concept rules — the `ciel` profile

What CIEL requires of a newly created concept, beyond what OCL and the OpenMRS
validation schema already enforce. `ciel_rules.py` implements the in-concept subset of
this document; `reference/ocl-bulk-import.md` covers the OCL baseline underneath it.

Rule identifiers are CIEL's own (`FR-xx` formal rules, `CE-xx` concept-editor rules),
so a finding here can be matched one-to-one against a finding in CIEL Lab.

Verified against CIEL Lab as of 2026-08.

---

## 1. The self mapping

**Every active CIEL concept must carry exactly one `SAME-AS` mapping pointing at its own
code, inside CIEL itself.** Not to an external terminology — CIEL → CIEL.

```json
{"type":"Mapping","owner":"CIEL","owner_type":"Organization","source":"CIEL",
 "map_type":"SAME-AS",
 "from_concept_url":"/orgs/CIEL/sources/CIEL/concepts/900101/",
 "to_source_url":"/orgs/CIEL/sources/CIEL/",
 "to_concept_code":"900101",
 "external_id":"<uuid>","retired":false}
```

The `ciel` profile adds this line automatically for every concept. Do not write it by
hand; if you do, it is de-duplicated and reported as redundant (FR-13, warning).

### Emitted nested — and why that is currently blocked

The skill emits mappings **nested inside the concept line**, matching what the CIEL
editor posts. A concept without an `id` carries `"to_concept": "__parent_concept"`
instead of `to_concept_code`, and OCL resolves it after assigning the mnemonic — which
is why ids stay optional under this profile.

> [!IMPORTANT]
> This depends on the fix for https://github.com/OpenConceptLab/ocl_issues/issues/2683. Today OCL's bulk
> importer drops the `mappings` key silently and the import still reports success.

Two facts explain the gap.

1. **A concept line cannot carry mappings.** The bulk concept importer filters every
   line through an allowlist of exactly twelve fields — `id, external_id, concept_class,
   datatype, names, descriptions, retired, extras, parent_concept_urls, update_comment,
   comment, retire_reason` — with `{k: v for k, v in self.data.items() if k in
   self.allowed_fields}`. A `mappings` key is **dropped silently, with no error**: the
   concepts import fine and the mappings simply never exist. Mappings must therefore be
   their own `{"type":"Mapping"}` lines, ordered after the concepts they reference.
2. **A standalone mapping line needs `from_concept_url`**, which needs the concept's id.
   Its importer accepts only `to_source_url` / `to_concept_code` / `to_concept_url` —
   there is no `to_concept` field, so the `__parent_concept` sentinel cannot be used on
   a `{"type":"Mapping"}` line either.

### This is an allowlist gap, not an architectural limit

Worth stating precisely, because it is the kind of thing that gets fixed upstream and
would delete this whole constraint.

The sentinel machinery **is** present on the bulk path and sits one function call away.
`ConceptImporter.process()` calls `Concept.persist_new(data=persist_data, ...)`, and
`persist_new` opens with:

```python
mappings_payload = data.pop('mappings_payload', None) or data.pop('mappings', None) or []
...
if mappings_payload:
    mappings_result, has_mapping_errors = concept.create_mappings(mappings_payload)
```

`create_mappings` calls `_create_mapping_from_self`, which is exactly where
`"to_concept": "__parent_concept"` is swapped for the freshly assigned concept URI —
the same code the CIEL editor's single-concept POST relies on.

In other words `persist_new` would accept nested mappings today; they never reach it
because `mappings` is missing from `ConceptImporter.allowed_fields`. Adding that one
entry would let a bulk file carry the self mapping inline and let OCL assign the ids,
removing the explicit-id requirement entirely.

### Verified against a running server

Not inferred from the source — run end to end against OCL API 2.3.201-dev on 2026-08-16.

**Bulk import, nested mappings.** One concept line carrying
`"mappings":[{"map_type":"SAME-AS","to_source_url":"...","to_concept":"__parent_concept"}]`:

```
task state: SUCCESS
message:    Processed: 1/1 | Created: 1
concepts in source: 1
mappings in source: 0        <-- silently dropped
```

**The same payload through the REST endpoint CIEL Lab uses**, `POST /concepts/`:

```
http 201
mappings in source: 1        SAME-AS 2 -> 2
```

Same server, same payload shape, opposite result. The REST view has an explicit
translation step the bulk importer never got:

```python
# core/concepts/views.py, ConceptListView.post
data['mappings_payload'] = data.pop('mappings', [])
```

paired with `mappings_payload = ListField(child=JSONField(), write_only=True, ...)`
declared on the serializer. That one line is why CIEL Lab can leave ids to OCL.

**This skill's approach — separate `{"type":"Mapping"}` lines with explicit ids** —
imported from a generated ZIP:

```
task state: SUCCESS
message:    Processed: 2/2 | Created: 2
mappings in source: 1        SAME-AS 5001 -> 5001
```

So: do not put `mappings` on a concept line hoping it will work. The import reports
success while producing concepts with no mappings at all — the failure is invisible at
import time and only surfaces in a later QA pass.

---

## 2. CIEL defaults for a new concept

| Field | Default | Notes |
| --- | --- | --- |
| `concept_class` | `Misc` | CIEL Lab's blank-draft default. **This skill does not adopt it as a silent fallback** — see below |
| `datatype` | `N/A` | same |
| `external_id` | a UUID | CIEL Lab generates a random v4 client-side |
| `id` | assigned by OCL | supported via the `__parent_concept` sentinel — see above |
| `locale` | `en` | |
| First name | `FULLY_SPECIFIED`, `locale_preferred`, `en` | CIEL Lab synthesises this from the Display field when a draft has no names |

### Why the class/datatype defaults are not simply copied

CIEL Lab starts a blank draft at `Misc` / `N/A` because a human is about to fill the
form in and can see the field. A batch file has no such moment: an unclassified row
would sail through validation and become a badly classified concept nobody looked at.

So the values still exist as a last resort, but reaching them is a review finding
(`concept-class-unclassified` / `datatype-unclassified`) and the CSV prints
`Misc (UNCLASSIFIED)`. Setting `Misc` explicitly, or via batch `defaults`, is treated as
a decision and stays silent. See `reference/concept-classification.md`.

### Derived external ids

The profile fills a missing `external_id` with `uuid5(namespace, concept_url)` rather
than a random v4. Deterministic on purpose: the CSV the user approves and the ZIP built
afterwards must carry identical values, and re-running the batch must produce the same
file. Supply `external_id` explicitly to override.

### `SYNONYM` is the absence of a type

CIEL's vocabulary has four name types: `FULLY_SPECIFIED`, `SYNONYM`, `SHORT`,
`INDEX_TERM`. But OCL's OpenMRS validator rejects a literal `"SYNONYM"` with
`Invalid name type`. A synonym must go on the wire with **no `name_type` key at all**.

The batch schema accepts `"name_type": "SYNONYM"` and strips it at emission time, so
authors can write what they mean.

---

## 3. Rule coverage

### 3.1 Implemented here (in-concept, payload-only)

| Rule | Severity | What it checks |
| --- | --- | --- |
| FR-11 | error | active concept has an `external_id` of exactly 36 characters (an OpenMRS UUID) |
| FR-12 | error | no duplicate mapping — same target source + code + map type |
| FR-13 | error | exactly one `SAME-AS` self mapping (auto-added; missing id is an error) |
| FR-15 | error | no HTML-encoded entities (`&[A-Za-z0-9#]+;`) in names or descriptions |
| FR-19 | warning | preferred name contains `and/or`, `and` or `or` — likely two concepts |
| FR-23 | warning | `SAME-AS` to a residual ICD code (ICD-10 `.8`, ICD-11 trailing `Y`), unless the FSN itself says "other" |
| FR-24 | warning | same target source + code reached with more than one map type |
| FR-25 | warning | more than one `SAME-AS` to the same target source |
| CE-01 | error | an English (`en`) `locale_preferred` name exists |
| CE-02 | error | a `Numeric` concept has numeric metadata in extras |
| CE-03 | error | a `Numeric` concept of class `Test` has `extras.units` |
| CE-04 | error | a set class (`LabSet`, `MedSet`, `ConvSet`, `InteractSet`) has at least one `CONCEPT-SET` mapping |

### 3.2 Already covered by the generic OpenMRS layer

These CIEL rules are not re-implemented in `ciel_rules.py`, because `validation.py`
already reports the same defect against the OCL rule of the same meaning. They are
listed so the coverage table is honest, not to imply they go unchecked.

| CIEL rule | Generic rule that covers it |
| --- | --- |
| FR-01 one preferred name per locale | `one-preferred-per-locale` |
| FR-02 no duplicate names per locale | `names-unique` |
| FR-03 one SHORT name per locale | `one-short-per-locale` |
| FR-04 SHORT name not preferred | `short-name-preferred` |
| FR-05 one FSN per locale | `one-fsn-per-locale` |
| FR-06 at least one FSN | `at-least-one-fsn` |
| FR-07 valid name type | rejected by the schema at parse time |

### 3.3 Deliberately NOT implemented

These need more than one concept's payload. `ciel_rules.unimplemented_rules()` returns
this list at runtime so the skill can state the gap rather than imply full coverage.

| Rule | Why it is out of scope |
| --- | --- |
| FR-08 | needs the source version's `supported_locales` — approximated by the generic locale check when the batch supplies them |
| FR-09 | FSN collision with another active concept — needs the whole source |
| FR-10 | preferred synonym duplicated on another concept — needs the whole source |
| FR-18 | sentence-case review — needs CIEL's 769 KB genus/eponym datasets (36 539 genus words, 4 584 eponym fragments) |
| FR-21 | numeric unit recognition/canonicalisation — needs CIEL's unit tables |
| FR-22 | mapping to a retired code — needs an indexed reference terminology |
| FR-26 | another concept `SAME-AS` to the same external code — needs the whole source |

FR-09, FR-10 and FR-26 are partially reachable with `validation.py --probe`, which
searches the live source for name collisions. That is a read-only convenience, not the
same check.

Note that CIEL's own `INTRA_CONCEPT_RULE_IDS` set includes FR-08 and FR-22, which are
*not* payload-only. The classification above follows what the rules actually need, not
that set.

---

## 4. Details worth getting right

**Severity is not cosmetic.** In CIEL Lab, `error` blocks saving a concept and `warning`
does not. The same split applies here: `pack` refuses to build while errors remain, and
warnings are surfaced for the reviewer to judge.

**FR-12 and FR-24 are mutually exclusive per target.** One pass buckets mappings by
`(lowercased source, uppercased code)`. If a single map type repeats in a bucket it is
FR-12; otherwise, if the bucket holds more than one entry, it is FR-24. Mappings with a
blank source or code are skipped entirely.

**Validation runs against the declared mappings, emission de-duplicates.** A mapping
written twice is an authoring mistake and is reported (FR-12); the emitted JSONL still
contains it once, so a file that does get built is never self-inconsistent.

**Map types are normalised** to uppercase with `_` and spaces turned into `-`, so
`same_as`, `Same As` and `SAME-AS` all compare equal — matching CIEL's
`normalize_relationship`.

**FR-13 compares codes case-sensitively** (trimmed only), while the source key is
compared case-insensitively. That asymmetry is CIEL's, and is preserved here.

**FR-23 has an escape hatch:** a residual mapping is not flagged when the concept's own
FSN contains the word "other", since that is a legitimately residual concept.
