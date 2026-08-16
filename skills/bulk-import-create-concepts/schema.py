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
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
NAME_TYPES: frozenset[str] = (
    FULLY_SPECIFIED_ALIASES | SHORT_ALIASES | INDEX_TERM_ALIASES | frozenset({"None"})
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
    # Free-text provenance for the CSV review sheet; stripped from the JSONL.
    note: str | None = None

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


class ConceptBatch(BaseModel):
    """The staged batch: the single artifact the whole workflow revolves around."""

    model_config = ConfigDict(extra="forbid")

    # Short kebab/snake description of the user's intent. Drives the file names.
    slug: str = Field(min_length=3)
    request: str = Field(min_length=1, description="Verbatim summary of what the user asked for")
    target: ImportTarget
    defaults: BatchDefaults = Field(default_factory=BatchDefaults)
    concepts: list[ConceptDraft] = Field(min_length=1)

    @field_validator("slug")
    @classmethod
    def _slugify(cls, value: str) -> str:
        return slugify(value)

    @model_validator(mode="after")
    def _apply_defaults(self) -> "ConceptBatch":
        for concept in self.concepts:
            if not concept.concept_class:
                concept.concept_class = self.defaults.concept_class
            if not concept.datatype:
                concept.datatype = self.defaults.datatype
        return self

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
            line["names"] = [
                {k: v for k, v in name.model_dump().items() if v is not None}
                for name in concept.names
            ]
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
            line["retired"] = False
            line.update(source_info)
            lines.append(line)
        return lines


# --------------------------------------------------------------------------- #
# Naming helpers
# --------------------------------------------------------------------------- #


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
