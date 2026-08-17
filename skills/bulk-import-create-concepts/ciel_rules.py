"""CIEL's own in-concept rules, layered on top of the OCL/OpenMRS baseline.

Only rules decidable from a single concept's payload are implemented — the
"in concept" subset. CIEL's cross-concept and external-terminology rules
(FR-09, FR-10, FR-26, FR-22, FR-08) need the whole source or an indexed
terminology and are deliberately out of scope; `unimplemented_rules()` names
them so the skill can say so out loud instead of implying full coverage.

Rules keep CIEL's own identifiers (FR-xx / CE-xx) so a finding here can be
matched against a finding in CIEL Lab. `reference/ciel-concept-rules.md` is the
authority for what each one means.

Rules already covered by the generic OpenMRS layer in `validation.py` are not
duplicated here; the mapping between the two is in that same document.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING

from schema import ConceptBatch, ConceptDraft

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters for type checking
    from validation import Report

# FR-15: HTML entities must never reach a name or description.
HTML_ENTITY_RE = re.compile(r"&[A-Za-z0-9#]+;")

# FR-19: a preferred name holding a disjunction is ambiguous. First match wins.
DISJUNCTION_PATTERNS = (
    ("and/or", re.compile(r"\band\/or\b", re.IGNORECASE)),
    ("and", re.compile(r"\band\b", re.IGNORECASE)),
    ("or", re.compile(r"\bor\b", re.IGNORECASE)),
)

# FR-11: an active concept carries an OpenMRS UUID, which is exactly 36 chars.
OPENMRS_UUID_LENGTH = 36

# CE-04: these classes are meaningless without members.
SET_CONCEPT_CLASSES = frozenset({"LabSet", "MedSet", "ConvSet", "InteractSet"})

# CE-02/CE-03: the numeric metadata CIEL keeps in extras. `hi_*` also appears as
# `high_*`, which the CIEL editor reads as an alias.
NUMERIC_EXTRA_KEYS = (
    "units", "hi_absolute", "high_absolute", "low_absolute",
    "hi_critical", "high_critical", "low_critical",
    "hi_normal", "high_normal", "low_normal",
    "allow_decimal", "precise",
)

# The extras vocabulary observed on CIEL/CIEL, with the JSON types the live data
# actually carries. Sampled from the source itself — see
# reference/ciel-extras.md for the counts and how to refresh this.
KNOWN_EXTRA_KEYS: dict[str, tuple[type, ...]] = {
    "units": (str,),
    "hi_absolute": (int, float),
    "high_absolute": (int, float),
    "low_absolute": (int, float),
    "hi_critical": (int, float),
    "high_critical": (int, float),
    "low_critical": (int, float),
    "hi_normal": (int, float),
    "high_normal": (int, float),
    "low_normal": (int, float),
    "allow_decimal": (bool,),
    "precise": (bool,),
    "is_set": (bool, int),
    # Declared by CIEL, not yet present in the live data. A real JSON boolean,
    # like allow_decimal — not the string "true"/"false".
    "clinical": (bool,),
}

# Description metadata, keyed `<Label>(<external_id>)`.
DESCRIPTION_META_RE = re.compile(
    r"^\s*(Definition|Description|Caption|Reference)\s*\([^)]+\)\s*$", re.IGNORECASE)

# Keys that must never be extras: OCL owns them as real columns.
RESERVED_EXTRA_KEYS = frozenset({"retired_reason", "retire_reason"})

# FR-23: a residual ("other"/"unspecified") code should not be a SAME-AS target.
ICD10_RESIDUAL_SUFFIX = ".8"
OTHER_WORD_RE = re.compile(r"\bother\b", re.IGNORECASE)

UNIMPLEMENTED = {
    "FR-08": "locale must be in the source version's supported_locales "
             "(approximated by the generic locale check when supported_locales is supplied)",
    "FR-09": "FSN must not collide with another active concept in the source",
    "FR-10": "preferred synonym must not be duplicated on another active concept",
    "FR-18": "sentence-case review — needs CIEL's 769 KB genus/eponym datasets",
    "FR-21": "numeric unit must be recognised and canonical — needs CIEL's unit tables",
    "FR-22": "mapping must not point at a retired code in an indexed terminology",
    "FR-26": "another active concept must not be SAME-AS to the same external code",
}


def unimplemented_rules() -> dict[str, str]:
    """CIEL rules this module cannot decide from the payload alone."""
    return dict(UNIMPLEMENTED)


def _is_icd10(source: str) -> bool:
    return "icd" in source and "10" in source


def _is_icd11(source: str) -> bool:
    return "icd" in source and "11" in source


def _fsn_says_other(concept: ConceptDraft) -> bool:
    return any(OTHER_WORD_RE.search(name.name) for name in concept.names if name.is_fsn)


def validate_concept(batch: ConceptBatch, concept: ConceptDraft, row: int, report: "Report") -> None:
    cid = concept.id

    # --- FR-11: OpenMRS identifier ------------------------------------------ #
    identifier = (concept.external_id or "").strip()
    if not identifier:
        report.add("error", "FR-11",
                   "an active CIEL concept needs an external_id holding a 36-character OpenMRS UUID; "
                   "leave it unset and the batch derives one, or supply your own",
                   row=row, concept_id=cid)
    elif len(identifier) != OPENMRS_UUID_LENGTH:
        report.add("error", "FR-11",
                   f"external_id must be exactly {OPENMRS_UUID_LENGTH} characters (an OpenMRS UUID); "
                   f"got {len(identifier)}", row=row, concept_id=cid)

    # --- FR-15: HTML entities ------------------------------------------------ #
    for name in concept.names:
        if HTML_ENTITY_RE.search(name.name):
            report.add("error", "FR-15",
                       f"name contains an HTML-encoded entity: {name.name}",
                       row=row, concept_id=cid)
    for desc in concept.descriptions:
        if HTML_ENTITY_RE.search(desc.description):
            report.add("error", "FR-15",
                       f"description contains an HTML-encoded entity: {desc.description}",
                       row=row, concept_id=cid)

    # --- FR-19: ambiguous preferred name ------------------------------------- #
    for name in (n for n in concept.names if n.locale_preferred):
        for label, pattern in DISJUNCTION_PATTERNS:
            if pattern.search(name.name):
                report.add("warning", "FR-19",
                           f"preferred name contains {label!r} and may be ambiguous — consider splitting "
                           f"it into separate concepts: {name.name} (locale: {name.locale})",
                           row=row, concept_id=cid)
                break

    # --- CE-01: an English preferred name ------------------------------------ #
    if not any(n.locale_preferred and n.locale.lower().startswith("en") for n in concept.names):
        report.add("error", "CE-01",
                   "CIEL requires an English (en) locale_preferred name",
                   row=row, concept_id=cid)

    # --- CE-02 / CE-03: numeric metadata ------------------------------------- #
    if (concept.datatype or "").strip().lower() == "numeric":
        if not any(key in concept.extras for key in NUMERIC_EXTRA_KEYS):
            report.add("error", "CE-02",
                       "a Numeric concept needs numeric metadata in extras "
                       f"({', '.join(NUMERIC_EXTRA_KEYS)})", row=row, concept_id=cid)
        elif concept.concept_class == "Test" and not str(concept.extras.get("units", "")).strip():
            report.add("error", "CE-03",
                       "a Numeric concept of class Test needs extras.units",
                       row=row, concept_id=cid)

    # --- extras vocabulary ---------------------------------------------------- #
    for key, value in concept.extras.items():
        if key in RESERVED_EXTRA_KEYS:
            report.add("error", "extras-reserved-key",
                       f"extras[{key!r}] collides with an OCL column; a retire reason belongs in the "
                       "concept's own retire_reason, not in extras",
                       row=row, concept_id=cid)
            continue
        expected = KNOWN_EXTRA_KEYS.get(key)
        if expected is None:
            if not DESCRIPTION_META_RE.match(key):
                report.add("warning", "extras-unknown-key",
                           f"extras[{key!r}] is not in the vocabulary observed on CIEL/CIEL "
                           f"({', '.join(sorted(KNOWN_EXTRA_KEYS))}). Fine if deliberate — confirm it is "
                           "not a typo, and that whatever consumes it expects this name",
                           row=row, concept_id=cid)
            continue
        # bool is a subclass of int; check it first so True never passes as a number.
        actual_ok = (isinstance(value, bool) and bool in expected) or (
            not isinstance(value, bool) and isinstance(value, expected))
        if not actual_ok:
            report.add("warning", "extras-unexpected-type",
                       f"extras[{key!r}] is {type(value).__name__} {value!r}; CIEL/CIEL stores this key as "
                       f"{' or '.join(e.__name__ for e in expected)}",
                       row=row, concept_id=cid)

    # --- mapping rules ------------------------------------------------------- #
    # Validated against the DECLARED list, not the de-duplicated one that gets
    # emitted: a mapping written twice must be reported (FR-12), not swallowed.
    mappings = batch.declared_mappings_for(concept)

    # CE-04: set classes need members.
    is_set = concept.concept_class in SET_CONCEPT_CLASSES or bool(concept.extras.get("is_set"))
    if is_set and not any(m.map_type == "CONCEPT-SET" for m in mappings):
        report.add("error", "CE-04",
                   f"a set concept ({concept.concept_class}) needs at least one CONCEPT-SET member mapping",
                   row=row, concept_id=cid)

    # FR-12 / FR-24: one bucket pass per (source, code), as CIEL does it.
    buckets: dict[tuple[str, str], list[str]] = defaultdict(list)
    for mapping in mappings:
        source, code = mapping.target_key()
        if not source or not code:
            continue
        buckets[(source, code)].append(mapping.map_type)
    for (source, code), map_types in buckets.items():
        repeated = {mt for mt in map_types if map_types.count(mt) > 1}
        if repeated:
            report.add("error", "FR-12",
                       f"duplicate mapping to {source}:{code} with map type {sorted(repeated)}",
                       row=row, concept_id=cid)
        elif len(map_types) > 1:
            report.add("warning", "FR-24",
                       f"{source}:{code} is mapped with more than one map type: {sorted(map_types)}",
                       row=row, concept_id=cid)

    # FR-25: at most one SAME-AS per target source.
    same_as_per_source: dict[str, int] = defaultdict(int)
    for mapping in mappings:
        if mapping.is_same_as:
            same_as_per_source[mapping.target_key()[0]] += 1
    for source, count in same_as_per_source.items():
        if count > 1:
            report.add("warning", "FR-25",
                       f"{count} SAME-AS mappings point at source {source!r}; a concept should have at "
                       "most one SAME-AS per source", row=row, concept_id=cid)

    # FR-23: residual ICD code as SAME-AS.
    if not _fsn_says_other(concept):
        for mapping in mappings:
            if not mapping.is_same_as:
                continue
            source, code = mapping.target_key()
            residual = (
                (_is_icd10(source) and code.endswith(ICD10_RESIDUAL_SUFFIX))
                or (_is_icd11(source) and code.endswith("Y") and "&" not in code and "/" not in code)
            )
            if residual:
                report.add("warning", "FR-23",
                           f"SAME-AS to what looks like a residual ICD code ({source}:{code}); residual "
                           "'other/unspecified' codes are usually NARROWER-THAN, not SAME-AS",
                           row=row, concept_id=cid)

    # --- FR-13: the self mapping --------------------------------------------- #
    # No id is needed: the self mapping falls back to the __parent_concept
    # sentinel, which OCL resolves after assigning the mnemonic.
    declared_self = [
        m for m in concept.mappings
        if m.is_same_as and m.target_key() == batch.self_mapping(concept).target_key()
    ]
    if declared_self:
        report.add("warning", "FR-13",
                   "the SAME-AS self mapping is added automatically under the CIEL profile; the one "
                   "declared here is redundant and was de-duplicated",
                   row=row, concept_id=cid)


def validate(batch: ConceptBatch, report: "Report") -> None:
    """Run the in-concept CIEL rules over the whole batch."""
    if batch.profile != "ciel":
        return
    for row, concept in enumerate(batch.concepts, start=1):
        validate_concept(batch, concept, row, report)
