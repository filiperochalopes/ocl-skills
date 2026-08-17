# CIEL concept extras — the observed vocabulary

`extras` is an open JSON object: OCL accepts any key and stores it verbatim, without
coercing types. That freedom makes typos invisible, so the `ciel` profile checks keys
against the vocabulary CIEL/CIEL actually uses and warns on anything else.

Warnings, never hard errors — a genuinely new key is legitimate. The point is that a new
key should be a decision, not a slip.

## How this list was produced

Sampled from the live source with the read-only CLI on 2026-08-16, across ~2,500
concepts drawn from general paging plus targeted probes by datatype (`Numeric`) and by
class (`LabSet`, `MedSet`, `ConvSet`, `Drug`, `Test`, `Symptom`, `Frequency`,
`Question`):

```bash
ocl -j concept search --owner CIEL --repo CIEL --verbose --limit 100 --page N
```

Counts below are occurrences in that sample, not in the whole 55,644-concept source.
Refresh the same way if the vocabulary drifts.

Keys fall into two groups, and the distinction matters: most were **observed** in the
data, while a few are **declared** by CIEL for new content and have no occurrences yet.
Declared keys are marked as such rather than folded into the counts.

## Numeric metadata

Only meaningful when `datatype` is `Numeric`. Drives CE-02 and CE-03.

| key | type in live data | n | notes |
| --- | --- | --- | --- |
| `units` | string | 315 | e.g. `"10^3/ul"`, `"mg/dL"`. Required for a `Numeric` `Test` (CE-03) |
| `allow_decimal` | boolean | 503 | real JSON `true`/`false`, not a string |
| `low_absolute` | number | 397 | usually float, occasionally int |
| `hi_absolute` | number | 232 | |
| `hi_normal` | number | 60 | |
| `low_normal` | number | 56 | |
| `low_critical` | number | 2 | |
| `hi_critical` | number | 1 | |

The `hi_*` keys also have `high_*` aliases (`high_absolute`, `high_critical`,
`high_normal`), which the CIEL editor reads. Both forms are accepted here; prefer `hi_*`,
which is what the data uses.

### `allow_decimal` vs `precise` — a live discrepancy

These are two names for the same flag, and the two systems disagree:

- **The data** uses `allow_decimal`: 503 occurrences in the sample, **zero** `precise`.
- **CIEL Lab writes `precise`.** `NUMERIC_FIELD_MAP` in the concept editor maps
  `precise → precise`, and the save path writes both `allowDecimal` and `precise` into
  its internal model but only `precise` reaches extras.
- **CIEL Lab reads `precise` only.** `extractNumericExtras` reads `extras.precise` and
  never looks at `extras.allow_decimal`; it then back-fills `allowDecimal` from
  `precise` when the former is undefined.

Read together, that means the editor does not see the decimal flag on the concepts that
carry `allow_decimal` — the majority of them. Worth raising with the CIEL Lab team; it
is their bug to confirm, not something this skill should paper over.

Both keys are in the vocabulary so neither is flagged as unknown. When writing new
concepts, prefer `allow_decimal` to match the existing data, and say so if the user
expects the editor to reflect it.

## Governance flags

| key | type | notes |
| --- | --- | --- |
| `clinical` | boolean | **Declared by CIEL, not yet present in the live data** — zero occurrences in the sample |

A real JSON `true` / `false`, like `allow_decimal` — not the string `"true"`. A string
value is reported as `extras-unexpected-type`, which catches both the obvious
`"false"` and the sloppier `"yes"` in one rule.

Booleans are the right call here: OCL stores extras verbatim, so a string would force
every consumer to normalise casing and truthy spellings before comparing, and one that
forgot would silently read `"false"` as truthy.

Because the key is new, expect it to be absent on existing concepts. Read code should
treat a missing `clinical` as "not set" rather than assuming a default.

## Sets

| key | type in live data | n | notes |
| --- | --- | --- | --- |
| `is_set` | integer `1` | 208 | not a boolean in the data; `1` means set. Drives CE-04 |

## Description metadata

A key family rather than a fixed key, matching:

```
^\s*(Definition|Description|Caption|Reference)\s*\([^)]+\)\s*$
```

for example `Definition(4f2c-…)`. The parenthesised part is the description's
`external_id`, so the extra annotates one specific description. Recognised by the
pattern and never reported as unknown. Rare in the sample.

## Reserved — never put these in extras

| key | why |
| --- | --- |
| `retired_reason`, `retire_reason` | OCL owns `retire_reason` as a real column; the CIEL editor explicitly deletes this key from extras before saving |

Reported as an **error**, not a warning: a retire reason hidden in extras is invisible
to everything that reads the real field.

## Not part of the CIEL/CIEL vocabulary

Seen on other CIEL-owned sources, not on CIEL/CIEL itself, so they are flagged as
unknown here — correctly, because a concept in CIEL/CIEL carrying them is probably a
copy-paste from the wrong pipeline:

- ICD-11 lookup sources: `isLeaf`, `IsPostcoordinated`, `Foundation URI`,
  `Linearization URI`, `DepthInKind`, `IsResidual`, `BrowserLink`, `ChapterNo`, `BlockId`
- OMOP mapping provenance: `omop_relationship_id`, `omop_concept_id_1`,
  `omop_concept_id_2`, `omop_valid_start_date`, `source_of_truth`

## What the checks do

| finding | severity | when |
| --- | --- | --- |
| `extras-reserved-key` | error | a key OCL owns as a column |
| `extras-unknown-key` | warning | not in the vocabulary and not description metadata |
| `extras-unexpected-type` | warning | known key carrying a different JSON type than the live data |
| `extras-string-boolean` | warning | any value is the string `"true"` / `"false"` |
| `extras-key-whitespace` | error | leading or trailing whitespace in a key |

`extras-string-boolean` is generic rather than CIEL-specific, because the trap is OCL's:
it stores extras verbatim, so `"false"` and `false` are different values and a consumer
testing for a boolean will not match the string. Under the `ciel` profile it is
suppressed for any key the vocabulary types, because `extras-unexpected-type` reports
the same defect and names the expected type — one finding per defect, not two.

The boolean-ish keys, for reference:

| key | correct form | wrong form |
| --- | --- | --- |
| `allow_decimal` | JSON `true` / `false` | `"true"` |
| `clinical` | JSON `true` / `false` | `"true"`, `"yes"` |
| `is_set` | integer `1` | `"1"`, `true` |

`is_set` is the odd one out, and that is the data's doing, not a choice made here.
