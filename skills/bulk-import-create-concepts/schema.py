"""Pydantic schema for an OCL bulk *concept creation* batch.

Mirrors what OCL's JSONL bulk importer actually accepts, plus the vocabularies
enforced by the OpenMRS custom validation schema. Both are documented in
`reference/ocl-bulk-import.md`, which is the authority for this module.

This module only models *structure*. Semantic / cross-row / repo-level rules
live in `validation.py`.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

# --------------------------------------------------------------------------- #
# Vocabularies: the name strings of the concepts in the OCL lookup sources
# (Classes / Datatypes / NameTypes / DescriptionTypes under org OCL).
# Full lists and rationale: reference/ocl-bulk-import.md section 5.
# --------------------------------------------------------------------------- #

# Accepted *name* strings in OCL/Classes. The OpenMRS validator also accepts the
# dash form of each (it retries with '-' replaced by ' '), except the two that
# contain a slash.
CONCEPT_CLASSES: frozenset[str] = frozenset({
    "Aggregate Measurement", "Anatomy", "ConvSet", "Diagnosis", "Dose Form Group",
    "Drug", "Drug form", "Finding", "Frequency", "Health Care Monitoring Topics",
    "Indicator", "InteractSet", "LabSet", "MedSet", "Medical supply", "Misc",
    "Misc Order", "Organism", "Pharmacologic Drug Class", "Procedure", "Program",
    "Question", "Radiology/Imaging Procedure", "Specimen", "State", "Symptom",
    "Symptom/Finding", "Test", "Units of Measure", "Workflow",
})

# Accepted *name* strings in OCL/Datatypes (includes HL7 synonyms).
DATATYPES: frozenset[str] = frozenset({
    "BIT", "Boolean", "CWE", "Coded", "Complex", "DT", "Date", "Datetime",
    "Document", "ED", "N/A", "NM", "None", "Numeric", "RP", "Rule", "SN", "ST",
    "Structured Numeric", "TM", "TS", "Text", "Time", "ZZ",
})

# OCL recognises FSN leniently (any casing/spacing variant of
# "fullyspecified"), but SHORT / INDEX_TERM are matched *strictly*.
FULLY_SPECIFIED_ALIASES: frozenset[str] = frozenset({"FULLY_SPECIFIED", "Fully Specified"})
SHORT_ALIASES: frozenset[str] = frozenset({"SHORT", "Short"})
INDEX_TERM_ALIASES: frozenset[str] = frozenset({"INDEX_TERM", "Index Term"})
# 'SYNONYM' is CIEL/OpenMRS vocabulary for "no type at all". OCL's OpenMRS
# validator rejects a literal "SYNONYM", so it is accepted here and emitted as
# an *absent* name_type. See reference/ciel-concept-rules.md.
SYNONYM = "SYNONYM"
NAME_TYPES: frozenset[str] = (
    FULLY_SPECIFIED_ALIASES | SHORT_ALIASES | INDEX_TERM_ALIASES
    | frozenset({"None", SYNONYM})
)
DESCRIPTION_TYPES: frozenset[str] = frozenset({"Definition", "None"})

# Concepts whose own class is a lookup class bypass OpenMRS attribute validation.
LOOKUP_CONCEPT_CLASSES: frozenset[str] = frozenset({
    "Concept Class", "Datatype", "NameType", "DescriptionType", "MapType", "Locale",
})

OPENMRS_EXTERNAL_ID_MAX = 36
MAX_LOCALES_LIMIT = 500

# The mnemonic pattern OCL enforces, applied *after* URL-encoding, which is
# why '%' is allowed.
CONCEPT_ID_RE = re.compile(r"^[a-zA-Z0-9\-\.\_\@\+\%\s]+$")

ValidationSchema = Literal["None", "OpenMRS"]
OwnerType = Literal["Organization", "User"]
# Which rulebook to apply on top of the OCL/OpenMRS baseline.
Profile = Literal["generic", "ciel"]

# Last-resort values when nothing else determined the field. Reaching these is
# a review finding, not a normal outcome: a concept_class of Misc or a datatype
# of N/A should be a decision someone made, never something that just happened.
FALLBACK_CONCEPT_CLASS = "Misc"
FALLBACK_DATATYPE = "N/A"

# Where a field's value came from. Surfaced in the CSV so a reviewer can tell a
# deliberate 'Misc' from an unclassified one.
FieldOrigin = Literal["explicit", "batch-default", "fallback"]
# Namespace for deriving stable external ids. Fixed so that the CSV the user
# approves and the ZIP built afterwards carry identical values.
EXTERNAL_ID_NAMESPACE = uuid.UUID("6f2b1d64-0f3e-5a7c-9c1a-1f6b2d4e8a30")


def is_fully_specified(name_type: str | None) -> bool:
    """Match OCL's lenient FSN detection."""
    if not name_type:
        return False
    return name_type.replace(" ", "").replace("-", "").replace("_", "").lower() == "fullyspecified"


def is_short(name_type: str | None) -> bool:
    return name_type in SHORT_ALIASES


def is_index_term(name_type: str | None) -> bool:
    return name_type in INDEX_TERM_ALIASES


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #


class ConceptName(BaseModel):
    """One entry of a concept's `names` array."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(min_length=1)
    locale: str = Field(min_length=2)
    locale_preferred: bool = False
    name_type: str | None = "FULLY_SPECIFIED"
    external_id: str | None = None

    @field_validator("name", "locale")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("name_type")
    @classmethod
    def _known_name_type(cls, value: str | None) -> str | None:
        if value is None or value in NAME_TYPES or is_fully_specified(value):
            return value
        raise ValueError(
            f"unknown name_type {value!r}; expected one of {sorted(NAME_TYPES)} "
            "(SHORT / INDEX_TERM are matched case-sensitively by OCL)"
        )

    def to_payload(self) -> dict[str, Any]:
        """OCL wire form. A SYNONYM is the *absence* of a name_type."""
        payload = {k: v for k, v in self.model_dump().items() if v is not None}
        if payload.get("name_type") == SYNONYM:
            payload.pop("name_type")
        return payload

    @property
    def is_fsn(self) -> bool:
        return is_fully_specified(self.name_type)

    @property
    def is_short(self) -> bool:
        return is_short(self.name_type)

    @property
    def is_index_term(self) -> bool:
        return is_index_term(self.name_type)


class ConceptDescription(BaseModel):
    """One entry of a concept's `descriptions` array."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1)
    locale: str = Field(min_length=2)
    locale_preferred: bool = False
    description_type: str | None = "Definition"
    external_id: str | None = None

    @field_validator("description", "locale")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("description_type")
    @classmethod
    def _known_description_type(cls, value: str | None) -> str | None:
        if value is None or value in DESCRIPTION_TYPES:
            return value
        raise ValueError(f"unknown description_type {value!r}; expected one of {sorted(DESCRIPTION_TYPES)}")


# The sentinel CIEL Lab uses for a self mapping on a concept whose id OCL has
# not assigned yet. Resolved server-side by Concept._create_mapping_from_self.
PARENT_CONCEPT_SENTINEL = "__parent_concept"


class ConceptMapping(BaseModel):
    """A mapping emitted nested inside the concept line.

    Nested mappings import correctly since ocl_issues#2683; OCL's import summary
    still counts only concept lines, so verify them afterwards (see README.md).
    """

    model_config = ConfigDict(extra="forbid")

    map_type: str = Field(min_length=1)
    to_source_url: str | None = None
    to_concept_code: str | None = None
    to_concept_url: str | None = None
    to_concept_name: str | None = None
    to_concept: str | None = None
    external_id: str | None = None
    sort_weight: float | None = None
    extras: dict[str, Any] = Field(default_factory=dict)

    @field_validator("map_type")
    @classmethod
    def _normalize_map_type(cls, value: str) -> str:
        return value.strip().replace("_", "-").replace(" ", "-").upper()

    @model_validator(mode="after")
    def _needs_a_target(self) -> "ConceptMapping":
        if self.to_concept or self.to_concept_url:
            return self
        if not (self.to_source_url and self.to_concept_code):
            raise ValueError(
                "a mapping needs to_concept_url, or to_concept, or both to_source_url "
                "and to_concept_code"
            )
        return self

    def to_payload(self) -> dict[str, Any]:
        """The nested wire form, matching what the CIEL editor posts."""
        payload: dict[str, Any] = {"map_type": self.map_type, "retired": False}
        if self.external_id:
            payload["external_id"] = self.external_id
        if self.to_concept_url:
            payload["to_concept_url"] = self.to_concept_url
        else:
            if self.to_source_url:
                payload["to_source_url"] = self.to_source_url
            if self.to_concept_code:
                payload["to_concept_code"] = self.to_concept_code
            elif self.to_concept:
                payload["to_concept"] = self.to_concept
        if self.to_concept_name:
            payload["to_concept_name"] = self.to_concept_name
        if self.sort_weight is not None:
            payload["sort_weight"] = self.sort_weight
        if self.extras:
            payload["extras"] = self.extras
        return payload

    @property
    def is_same_as(self) -> bool:
        return self.map_type == "SAME-AS"

    def target_key(self) -> tuple[str, str]:
        """(source, code) as CIEL's duplicate rules compare them."""
        source = (self.to_source_url or "").strip().rstrip("/").rsplit("/", 1)[-1].lower()
        code = (self.to_concept_code or self.to_concept or self.to_concept_url or "").strip().upper()
        return source, code


class ConceptDraft(BaseModel):
    """A single concept the user wants created.

    Deliberately *creation-only*: there is no `retired` and no `__action` field.
    Retiring/deleting concepts is a different skill (`bulk-retire-concepts`),
    because `__action: DELETE` on a concept line retires it in OCL.
    """

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    external_id: str | None = None
    concept_class: str | None = None
    datatype: str | None = None
    names: list[ConceptName] = Field(min_length=1)
    descriptions: list[ConceptDescription] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)
    parent_concept_urls: list[str] = Field(default_factory=list)
    hierarchy_meaning: str | None = None
    # Emitted as separate Mapping lines. Under the CIEL profile the SAME-AS self
    # mapping is added automatically and must not be listed here.
    mappings: list[ConceptMapping] = Field(default_factory=list)
    # Free-text provenance for the CSV review sheet; stripped from the JSONL.
    # The right place for *why* this concept_class and datatype were chosen.
    note: str | None = None

    # Set by ConceptBatch when defaults are resolved; see FieldOrigin.
    _concept_class_origin: FieldOrigin = PrivateAttr(default="explicit")
    _datatype_origin: FieldOrigin = PrivateAttr(default="explicit")

    @property
    def concept_class_origin(self) -> FieldOrigin:
        return self._concept_class_origin

    @property
    def datatype_origin(self) -> FieldOrigin:
        return self._datatype_origin

    @field_validator("id")
    @classmethod
    def _valid_mnemonic(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = str(value).strip()
        if not value:
            return None
        if not CONCEPT_ID_RE.match(value):
            raise ValueError(
                f"id {value!r} contains characters OCL rejects; allowed: letters, digits, "
                "space and - . _ @ + %"
            )
        return value

    @model_validator(mode="after")
    def _limits(self) -> "ConceptDraft":
        if len(self.names) > MAX_LOCALES_LIMIT:
            raise ValueError(f"max limit {MAX_LOCALES_LIMIT} of names exceeded")
        if len(self.descriptions) > MAX_LOCALES_LIMIT:
            raise ValueError(f"max limit {MAX_LOCALES_LIMIT} of descriptions exceeded")
        if self.hierarchy_meaning and not self.parent_concept_urls:
            raise ValueError("hierarchy_meaning set without parent_concept_urls")
        return self

    def preferred_name(self) -> ConceptName:
        """Best label for the review CSV: preferred FSN > any FSN > first name."""
        for name in self.names:
            if name.is_fsn and name.locale_preferred:
                return name
        for name in self.names:
            if name.is_fsn:
                return name
        return self.names[0]


class ImportTarget(BaseModel):
    """Where the batch will be created. Must be confirmed with the user.

    The profile fields (validation_schema, default_locale, supported_locales,
    autoid_concept_mnemonic) change which rules apply, so they are part of the
    batch the user reviews rather than something inferred. Read them off the
    source's page in OCL, or let the optional read-only probe fill them in.
    """

    model_config = ConfigDict(extra="forbid")

    owner: str = Field(min_length=1)
    owner_type: OwnerType
    source: str = Field(min_length=1)
    # 'OpenMRS' turns on the strict rule set. CIEL uses it.
    validation_schema: ValidationSchema = "None"
    default_locale: str = "en"
    # Empty means "unknown": locale checks are skipped rather than guessed.
    supported_locales: list[str] = Field(default_factory=list)
    # 'sequential' / 'uuid' when the source assigns mnemonics itself; makes `id` optional.
    autoid_concept_mnemonic: str | None = None
    # Only read by the optional --probe lookup; never used to write anything.
    api_url: str = "https://api.openconceptlab.org"

    @property
    def owner_segment(self) -> str:
        return "orgs" if self.owner_type == "Organization" else "users"

    @property
    def source_url(self) -> str:
        return f"/{self.owner_segment}/{self.owner}/sources/{self.source}/"

    def concept_url(self, concept_id: str) -> str:
        return f"{self.source_url}concepts/{concept_id}/"


class BatchDefaults(BaseModel):
    """Applied to any concept that leaves the field unset."""

    model_config = ConfigDict(extra="forbid")

    concept_class: str | None = None
    datatype: str | None = "N/A"
    locale: str = "en"
    # Merged into every concept's extras. A key the concept sets itself wins,
    # so a batch-wide flag can still be overridden row by row.
    extras: dict[str, Any] = Field(default_factory=dict)


class ConceptBatch(BaseModel):
    """The staged batch: the single artifact the whole workflow revolves around."""

    model_config = ConfigDict(extra="forbid")

    # Short kebab/snake description of the user's intent. Drives the file names.
    slug: str = Field(min_length=3)
    request: str = Field(min_length=1, description="Verbatim summary of what the user asked for")
    # 'ciel' layers CIEL's own in-concept rules and defaults on top of the
    # OCL/OpenMRS baseline, including the mandatory SAME-AS self mapping.
    profile: Profile = "generic"
    target: ImportTarget
    defaults: BatchDefaults = Field(default_factory=BatchDefaults)
    concepts: list[ConceptDraft] = Field(min_length=1)

    @field_validator("slug")
    @classmethod
    def _slugify(cls, value: str) -> str:
        return slugify(value)

    @model_validator(mode="after")
    def _apply_defaults(self) -> "ConceptBatch":
        ciel = self.profile == "ciel"
        # A default the author wrote is a decision; the model's own default is not.
        declared = self.defaults.model_fields_set
        for concept in self.concepts:
            if not concept.concept_class:
                if "concept_class" in declared and self.defaults.concept_class:
                    concept.concept_class = self.defaults.concept_class
                    concept._concept_class_origin = "batch-default"
                else:
                    concept.concept_class = FALLBACK_CONCEPT_CLASS
                    concept._concept_class_origin = "fallback"
            if not concept.datatype:
                if "datatype" in declared and self.defaults.datatype:
                    concept.datatype = self.defaults.datatype
                    concept._datatype_origin = "batch-default"
                else:
                    concept.datatype = FALLBACK_DATATYPE
                    concept._datatype_origin = "fallback"
            if self.defaults.extras:
                # Batch-wide extras, with the concept's own keys taking priority.
                concept.extras = {**self.defaults.extras, **concept.extras}
            if ciel and not concept.external_id and concept.id:
                # Derived, not random: the CSV under review and the ZIP built
                # afterwards must carry the same value, and a re-run must be
                # byte-identical. Supply external_id explicitly to override.
                concept.external_id = str(uuid.uuid5(
                    EXTERNAL_ID_NAMESPACE, self.target.concept_url(concept.id)))
        return self

    def self_mapping(self, concept: ConceptDraft) -> ConceptMapping | None:
        """CIEL's mandatory SAME-AS mapping from a concept to its own code.

        When the concept has no id, the `__parent_concept` sentinel stands in and
        OCL resolves it after assigning the mnemonic — the same thing the CIEL
        editor does, which is why ids are optional under this profile.
        """
        if self.profile != "ciel":
            return None
        seed = self.target.concept_url(concept.id) if concept.id else \
            f"{self.target.source_url}::{concept.preferred_name().name}"
        return ConceptMapping(
            map_type="SAME-AS",
            to_source_url=self.target.source_url,
            to_concept_code=normalize_concept_code(concept.id) if concept.id else None,
            to_concept=None if concept.id else PARENT_CONCEPT_SENTINEL,
            external_id=str(uuid.uuid5(EXTERNAL_ID_NAMESPACE, f"self-map:{seed}")),
        )

    def declared_mappings_for(self, concept: ConceptDraft) -> list[ConceptMapping]:
        """Everything the author wrote, plus the self mapping, WITHOUT dedup.

        Validation runs against this list: a mapping written twice is an
        authoring mistake worth reporting (CIEL's FR-12), not something to
        quietly swallow.
        """
        mappings = list(concept.mappings)
        self_map = self.self_mapping(concept)
        # Appended only when the author has not already written it, so that an
        # explicitly declared self map is reported as redundant (FR-13) rather
        # than as a duplicate mapping (FR-12).
        if self_map and not any(
            m.map_type == self_map.map_type and m.target_key() == self_map.target_key()
            for m in mappings
        ):
            mappings.append(self_map)
        return mappings

    def mappings_for(self, concept: ConceptDraft) -> list[ConceptMapping]:
        """What actually gets emitted: the declared list, de-duplicated on
        (map_type, source, code) the way the CIEL editor does."""
        deduped: dict[tuple[str, str, str], ConceptMapping] = {}
        for mapping in self.declared_mappings_for(concept):
            source, code = mapping.target_key()
            deduped.setdefault((mapping.map_type, source, code), mapping)
        return list(deduped.values())

    def to_jsonl_lines(self) -> list[dict[str, Any]]:
        """Render bulk-import JSONL objects, in OCL dependency order.

        Only concepts are emitted: the target org/source must already exist and
        is verified up front, never created implicitly by this skill.
        """
        source_info = {
            "owner": self.target.owner,
            "owner_type": self.target.owner_type,
            "source": self.target.source,
        }
        lines: list[dict[str, Any]] = []
        for concept in self.concepts:
            line: dict[str, Any] = {"type": "Concept"}
            if concept.id:
                line["id"] = concept.id
            if concept.external_id:
                line["external_id"] = concept.external_id
            line["concept_class"] = concept.concept_class
            line["datatype"] = concept.datatype
            line["names"] = [name.to_payload() for name in concept.names]
            if concept.descriptions:
                line["descriptions"] = [
                    {k: v for k, v in desc.model_dump().items() if v is not None}
                    for desc in concept.descriptions
                ]
            if concept.extras:
                line["extras"] = concept.extras
            if concept.parent_concept_urls:
                line["parent_concept_urls"] = concept.parent_concept_urls
                line["hierarchy_meaning"] = concept.hierarchy_meaning or "grouped-by"
            mappings = [m.to_payload() for m in self.mappings_for(concept)]
            if mappings:
                # Nested, matching the CIEL editor. Blocked upstream today — see
                # the IMPORTANT notice in README.md.
                line["mappings"] = mappings
            line["retired"] = False
            line.update(source_info)
            lines.append(line)
        return lines


# --------------------------------------------------------------------------- #
# Naming helpers
# --------------------------------------------------------------------------- #


def normalize_concept_code(value: str) -> str:
    """Strip a leading `CIEL:` qualifier, as the CIEL editor does."""
    text = (value or "").strip()
    return text.split(":", 1)[1].strip() if text.upper().startswith("CIEL:") else text


def slugify(value: str, max_length: int = 60) -> str:
    """ASCII, lowercase, underscore-separated — safe for file names."""
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", normalized).strip("_").lower()
    return (normalized[:max_length].rstrip("_")) or "batch"


def timestamp(now: datetime | None = None) -> str:
    """`yyyymmdd_hhii` — the convention required for every artifact of this skill."""
    return (now or datetime.now()).strftime("%Y%m%d_%H%M")


def artifact_stem(batch: ConceptBatch, now: datetime | None = None) -> str:
    """e.g. `create_concepts_malaria_labset_CIEL_CIEL_20260815_1432`."""
    return "_".join((
        slugify(batch.slug),
        slugify(batch.target.owner, 24),
        slugify(batch.target.source, 24),
        timestamp(now),
    ))
