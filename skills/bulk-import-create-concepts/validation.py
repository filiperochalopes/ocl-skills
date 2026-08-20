"""Pre-flight validation for an OCL bulk concept-creation batch.

Replays, client-side, the rules OCL applies at import time so that failures
surface in the CSV review sheet instead of in the `others` bucket of an import
task (where OCL echoes the offending line back *without* the error message).
The rules being replayed are written down in `reference/ocl-bulk-import.md`.

Three layers:

0. profile     -- when the batch declares profile "ciel", `ciel_rules.py` adds
                  CIEL's own in-concept rules (FR-xx / CE-xx) on top
1. structural  -- `schema.py` (pydantic)
2. semantic    -- the always-on rules plus, when the source runs the OpenMRS
                  schema, R1-R15; plus cross-row checks inside the batch
3. repository  -- OPTIONAL read-only probes against the target source (`--probe`)

Layers 1 and 2 are the normal path and need no network and no credentials.
Layer 3 is a convenience that only ever issues GETs: it fills in the source's
validation profile and flags ids that are already taken. Nothing in this module
writes to OCL — uploading the generated file is the user's own manual step.

Usage:
    python validation.py batch.json                 # offline, the default
    python validation.py batch.json --probe         # + read-only source lookup
    python validation.py batch.json --json          # machine-readable report
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal
from urllib.parse import quote

import ciel_rules
from schema import (
    CONCEPT_CLASSES,
    DATATYPES,
    LOOKUP_CONCEPT_CLASSES,
    OPENMRS_EXTERNAL_ID_MAX,
    ConceptBatch,
    ConceptDraft,
    ImportTarget,
)

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class Issue:
    severity: Severity
    rule: str
    message: str
    row: int | None = None  # 1-based index into batch.concepts; None = batch-level
    concept_id: str | None = None

    def __str__(self) -> str:
        where = f"row {self.row}" if self.row else "batch"
        if self.concept_id:
            where += f" ({self.concept_id})"
        return f"[{self.severity.upper():7}] {where} {self.rule}: {self.message}"


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)

    def add(self, severity: Severity, rule: str, message: str, *, row: int | None = None,
            concept_id: str | None = None) -> None:
        self.issues.append(Issue(severity, rule, message, row, concept_id))

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def for_row(self, row: int) -> list[Issue]:
        return [i for i in self.issues if i.row == row]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [
                {"severity": i.severity, "rule": i.rule, "message": i.message,
                 "row": i.row, "concept_id": i.concept_id}
                for i in self.issues
            ],
        }


# --------------------------------------------------------------------------- #
# Layer 2a: per-concept rules
# --------------------------------------------------------------------------- #


def _class_accepted(concept_class: str) -> bool:
    # OpenMRS validator retries with '-' replaced by ' '.
    return concept_class in CONCEPT_CLASSES or concept_class.replace("-", " ") in CONCEPT_CLASSES


def validate_concept(concept: ConceptDraft, row: int, target: ImportTarget, report: Report,
                     profile: str = "generic") -> None:
    cid = concept.id
    openmrs = target.validation_schema == "OpenMRS"

    # --- always-on rules (apply under every validation schema) -------------- #
    if not concept.concept_class:
        report.add("error", "concept_class-required",
                   "concept_class is the only mandatory field for the OCL concept importer and is missing",
                   row=row, concept_id=cid)
    if not concept.datatype:
        report.add("error", "datatype-required",
                   "datatype is blank; Django full_clean rejects it. Use 'N/A' when not applicable",
                   row=row, concept_id=cid)
    if not concept.names:
        report.add("error", "names-required", "A concept must have at least one name", row=row, concept_id=cid)
    for desc in concept.descriptions:
        if not desc.description.strip():
            report.add("error", "description-empty", "Concept description cannot be empty",
                       row=row, concept_id=cid)

    # --- classification ----------------------------------------------------- #
    # A fallback here means nobody decided. 'Misc' and 'N/A' are legitimate
    # answers, but they have to be chosen, not defaulted into.
    if concept.concept_class_origin == "fallback":
        report.add("warning", "concept-class-unclassified",
                   f"concept_class was not set and fell back to {concept.concept_class!r}. Classify it "
                   "from the concept's name and description (see reference/concept-classification.md); "
                   "if Misc really is right, set it explicitly and say why in `note`",
                   row=row, concept_id=cid)
    if concept.datatype_origin == "fallback":
        report.add("warning", "datatype-unclassified",
                   f"datatype was not set and fell back to {concept.datatype!r}. Question-like concepts "
                   "(Test, Question) need a real datatype; for everything else N/A is correct but should "
                   "be stated explicitly", row=row, concept_id=cid)

    if not cid and not target.autoid_concept_mnemonic:
        report.add("warning", "id-missing",
                   "no id and the source has no autoid_concept_mnemonic: OCL will fall back to an internal "
                   "sequence/UUID and update_if_exists can never match this line",
                   row=row, concept_id=cid)

    # --- extras --------------------------------------------------------------- #
    # OCL stores extras as JSON and does not coerce, so "false" and false are two
    # different values to anything reading them back. CIEL itself uses string
    # booleans in places, so this is advisory, not a rule.
    # Keys the CIEL vocabulary types are left to ciel_rules, which reports the
    # same defect as extras-unexpected-type with the expected type named.
    typed_elsewhere = set(ciel_rules.KNOWN_EXTRA_KEYS) if profile == "ciel" else set()
    for key, value in concept.extras.items():
        if (isinstance(value, str) and value.strip().lower() in {"true", "false"}
                and key not in typed_elsewhere):
            report.add("warning", "extras-string-boolean",
                       f"extras[{key!r}] is the string {value!r}, not the boolean {value.strip().lower()}. "
                       "OCL stores extras as JSON verbatim, so a consumer testing for a boolean will not "
                       "match. Confirm which the target expects — some CIEL extras are string booleans",
                       row=row, concept_id=cid)
        if key != key.strip():
            report.add("error", "extras-key-whitespace",
                       f"extras key {key!r} has leading or trailing whitespace",
                       row=row, concept_id=cid)

    # --- vocabularies ------------------------------------------------------- #
    # Checked even under the 'None' schema: OCL will not reject them there, but a
    # class/datatype outside the lookup sources is almost always a typo.
    is_lookup = concept.concept_class in LOOKUP_CONCEPT_CLASSES
    if concept.concept_class and not is_lookup and not _class_accepted(concept.concept_class):
        report.add("error" if openmrs else "warning", "concept-class-invalid",
                   f"Invalid concept class {concept.concept_class!r}; not in OCL/Classes",
                   row=row, concept_id=cid)
    if concept.datatype and not is_lookup and concept.datatype not in DATATYPES:
        report.add("error" if openmrs else "warning", "datatype-invalid",
                   f"Invalid data type {concept.datatype!r}; not in OCL/Datatypes",
                   row=row, concept_id=cid)

    # --- locales ------------------------------------------------------------ #
    supported = set(target.supported_locales or [])
    for name in concept.names:
        if supported and name.locale not in supported:
            report.add("warning", "name-locale",
                       f"locale {name.locale!r} is not in the source's supported_locales "
                       f"({sorted(supported)}); OCL also accepts anything in OCL/Locales",
                       row=row, concept_id=cid)
    for desc in concept.descriptions:
        if supported and desc.locale not in supported:
            report.add("warning", "description-locale",
                       f"description locale {desc.locale!r} is not in the source's supported_locales",
                       row=row, concept_id=cid)

    # --- OpenMRS-only rules -------------------------------------------------- #
    if not openmrs:
        return

    if concept.external_id and len(concept.external_id) > OPENMRS_EXTERNAL_ID_MAX:
        report.add("error", "external-id-length",
                   f"Concept External ID cannot be more than {OPENMRS_EXTERNAL_ID_MAX} characters",
                   row=row, concept_id=cid)
    for name in concept.names:
        if name.external_id and len(name.external_id) > OPENMRS_EXTERNAL_ID_MAX:
            report.add("error", "name-external-id-length",
                       f"Concept name's External ID cannot be more than {OPENMRS_EXTERNAL_ID_MAX} characters",
                       row=row, concept_id=cid)
    for desc in concept.descriptions:
        if desc.external_id and len(desc.external_id) > OPENMRS_EXTERNAL_ID_MAX:
            report.add("error", "description-external-id-length",
                       f"Concept description's External ID cannot be more than "
                       f"{OPENMRS_EXTERNAL_ID_MAX} characters",
                       row=row, concept_id=cid)

    fsns = [n for n in concept.names if n.is_fsn]
    if not fsns:
        report.add("error", "at-least-one-fsn", "A concept must have at least one fully specified name",
                   row=row, concept_id=cid)

    per_locale_fsn: dict[str, int] = defaultdict(int)
    per_locale_preferred: dict[str, int] = defaultdict(int)
    per_locale_short: dict[str, int] = defaultdict(int)
    seen_non_short: set[tuple[str, str]] = set()

    for name in concept.names:
        if name.is_fsn:
            per_locale_fsn[name.locale] += 1
        if name.locale_preferred:
            per_locale_preferred[name.locale] += 1
        if name.is_short:
            per_locale_short[name.locale] += 1
            if name.locale_preferred:
                report.add("error", "short-name-preferred",
                           f"A short name cannot be marked as locale preferred: {name.name}",
                           row=row, concept_id=cid)
        else:
            key = (name.locale, name.name)
            if key in seen_non_short:
                report.add("error", "names-unique",
                           f"All names except short names must be unique for a concept and locale: "
                           f"{name.name} (locale: {name.locale})",
                           row=row, concept_id=cid)
            seen_non_short.add(key)
        if name.is_index_term and name.locale_preferred:
            report.add("error", "index-term-preferred",
                       f"An index term cannot be marked as locale preferred: {name.name}",
                       row=row, concept_id=cid)

    for locale, count in per_locale_fsn.items():
        if count > 1:
            report.add("error", "one-fsn-per-locale",
                       f"A concept may not have more than one fully specified name in any locale "
                       f"(locale: {locale})", row=row, concept_id=cid)
    for locale, count in per_locale_preferred.items():
        if count > 1:
            report.add("error", "one-preferred-per-locale",
                       f"A concept may not have more than one preferred name (per locale) (locale: {locale})",
                       row=row, concept_id=cid)
    for locale, count in per_locale_short.items():
        if count > 1:
            report.add("error", "one-short-per-locale",
                       f"A concept cannot have more than one short name in a locale (locale: {locale})",
                       row=row, concept_id=cid)

    if concept.names and not concept.descriptions:
        report.add("warning", "no-descriptions",
                   "no descriptions: OCL skips its locale validation entirely for such concepts, so an "
                   "unsupported name locale will slip through here and only surface later",
                   row=row, concept_id=cid)


# --------------------------------------------------------------------------- #
# Layer 2b: cross-row rules inside the batch
# --------------------------------------------------------------------------- #


def validate_batch_uniqueness(batch: ConceptBatch, report: Report) -> None:
    openmrs = batch.target.validation_schema == "OpenMRS"

    by_id: dict[str, list[int]] = defaultdict(list)
    fsn_index: dict[tuple[str, str], list[int]] = defaultdict(list)
    preferred_index: dict[tuple[str, str], list[int]] = defaultdict(list)

    for row, concept in enumerate(batch.concepts, start=1):
        if concept.id:
            by_id[concept.id].append(row)
        for name in concept.names:
            if name.is_fsn:
                fsn_index[(name.locale, name.name)].append(row)
            if name.locale_preferred and not name.is_short and not name.is_index_term:
                preferred_index[(name.locale, name.name)].append(row)

    for concept_id, rows in by_id.items():
        if len(rows) > 1:
            report.add("error", "duplicate-id-in-batch",
                       f"Concept ID must be unique within a source; {concept_id!r} appears on rows {rows}",
                       concept_id=concept_id)

    if openmrs:
        for (locale, name), rows in fsn_index.items():
            if len(rows) > 1:
                report.add("error", "duplicate-fsn-in-batch",
                           f"Concept fully specified name must be unique for same source and locale: "
                           f"{name} (locale: {locale}) on rows {rows}")
        for (locale, name), rows in preferred_index.items():
            if len(rows) > 1:
                report.add("error", "duplicate-preferred-in-batch",
                           f"Concept preferred name must be unique for same source and locale: "
                           f"{name} (locale: {locale}) on rows {rows}")

    # Parent hierarchy references must resolve: either to the target source's
    # existing content (only checkable with --probe) or another concept in this batch.
    known = {concept.id for concept in batch.concepts if concept.id}
    for row, concept in enumerate(batch.concepts, start=1):
        for url in concept.parent_concept_urls:
            if not url.startswith("/"):
                report.add("error", "parent-url-format",
                           f"parent_concept_url {url!r} must be a relative OCL URL like "
                           f"{batch.target.concept_url('1234')}", row=row, concept_id=concept.id)
            elif url.startswith(batch.target.source_url):
                referenced = url[len(batch.target.source_url) + len("concepts/"):].strip("/")
                if referenced not in known:
                    report.add("warning", "parent-not-in-batch",
                               f"parent concept {referenced!r} is not in this batch; it must already exist "
                               f"in {batch.target.source_url}", row=row, concept_id=concept.id)


# --------------------------------------------------------------------------- #
# Layer 3: OPTIONAL read-only repository probes
#
# Everything below is opt-in (`--probe`) and issues GET requests only. A token is
# needed solely to read private sources; without one the offline path still works,
# with the caller supplying the source profile in the batch file instead.
# --------------------------------------------------------------------------- #


def _api_base(target: ImportTarget) -> str:
    return target.api_url.rstrip("/").replace("://app.", "://api.")


def resolve_target(target: ImportTarget, token: str | None = None) -> tuple[ImportTarget, Report]:
    """Read the live source and fill in schema/locales/autoid. Never guesses, never writes."""
    import requests  # imported lazily so offline validation needs no network stack

    report = Report()
    token = token or os.getenv("OCL_API_TOKEN") or os.getenv("OCL_TOKEN") or os.getenv("OCL_API_KEY")
    headers = {"Authorization": f"Token {token}"} if token else {}
    url = f"{_api_base(target)}{target.source_url}"

    response = requests.get(url, headers=headers, timeout=60)
    if response.status_code == 404:
        report.add("error", "source-not-found",
                   f"{target.source_url} does not exist (or is private and the token cannot see it). This "
                   "skill never creates the org/source implicitly — confirm the destination with the user.")
        return target, report
    if response.status_code in (401, 403):
        report.add("error", "source-forbidden",
                   f"{response.status_code} on {url}. Set a valid OCL_API_TOKEN with access to "
                   f"{target.source_url}; private sources cannot be resolved anonymously.")
        return target, report
    response.raise_for_status()
    payload = response.json()

    resolved = target.model_copy(update={
        "validation_schema": payload.get("custom_validation_schema") or "None",
        "default_locale": payload.get("default_locale") or target.default_locale,
        "supported_locales": payload.get("supported_locales") or target.supported_locales,
        "autoid_concept_mnemonic": payload.get("autoid_concept_mnemonic"),
    })
    report.add("warning", "target-resolved",
               f"{target.source_url} -> validation_schema={resolved.validation_schema}, "
               f"default_locale={resolved.default_locale}, supported_locales={resolved.supported_locales}, "
               f"autoid_concept_mnemonic={resolved.autoid_concept_mnemonic}")
    return resolved, report


def validate_against_source(batch: ConceptBatch, report: Report, token: str | None = None) -> None:
    """Flag rows that would be *updates* or that collide with existing names.

    Best effort and read-only: a network hiccup downgrades to a warning rather
    than blocking the review step.
    """
    import requests

    token = token or os.getenv("OCL_API_TOKEN") or os.getenv("OCL_TOKEN") or os.getenv("OCL_API_KEY")
    headers = {"Authorization": f"Token {token}"} if token else {}
    base = _api_base(batch.target)
    session = requests.Session()

    for row, concept in enumerate(batch.concepts, start=1):
        if not concept.id:
            continue
        url = f"{base}{batch.target.concept_url(quote(concept.id, safe=''))}"
        try:
            response = session.get(url, headers=headers, timeout=30)
        except requests.RequestException as exc:
            report.add("warning", "probe-failed", f"could not probe {url}: {exc}",
                       row=row, concept_id=concept.id)
            continue
        if response.status_code == 200:
            report.add("error", "concept-already-exists",
                       f"Concept ID must be unique within a source: {concept.id!r} already exists in "
                       f"{batch.target.source_url}. This skill only creates concepts — updating existing "
                       "ones is a separate flow.", row=row, concept_id=concept.id)

    if batch.target.validation_schema != "OpenMRS":
        return

    # FSN collisions against the live source (OpenMRS rule R8/R9).
    for row, concept in enumerate(batch.concepts, start=1):
        for name in (n for n in concept.names if n.is_fsn):
            params = {"q": name.name, "exact_match": "on", "limit": 25, "includeSearchMeta": "false"}
            try:
                response = session.get(f"{base}{batch.target.source_url}concepts/",
                                       params=params, headers=headers, timeout=30)
                results = response.json() if response.ok else []
            except (requests.RequestException, ValueError) as exc:
                report.add("warning", "probe-failed",
                           f"could not search existing names for {name.name!r}: {exc}",
                           row=row, concept_id=concept.id)
                continue
            for hit in results if isinstance(results, list) else []:
                for existing in hit.get("names") or []:
                    if existing.get("name") == name.name and existing.get("locale") == name.locale:
                        report.add("error", "fsn-collision-in-source",
                                   f"Concept fully specified name must be unique for same source and locale: "
                                   f"{name.name} (locale: {name.locale}) — already used by "
                                   f"{hit.get('id')}", row=row, concept_id=concept.id)


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #


def load_batch(path: str | Path) -> ConceptBatch:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return ConceptBatch.model_validate(data)


def validate(batch: ConceptBatch, *, probe: bool = False, token: str | None = None) -> tuple[ConceptBatch, Report]:
    report = Report()
    if probe:
        resolved, target_report = resolve_target(batch.target, token)
        report.issues.extend(target_report.issues)
        if target_report.errors:
            return batch, report
        batch = batch.model_copy(update={"target": resolved})

    for row, concept in enumerate(batch.concepts, start=1):
        validate_concept(concept, row, batch.target, report, batch.profile)
    validate_batch_uniqueness(batch, report)
    ciel_rules.validate(batch, report)
    if any(batch.mappings_for(concept) for concept in batch.concepts):
        report.add("warning", "nested-mappings-verify-after-import",
                   "this batch carries nested mappings. They do import (ocl_issues#2683 landed; "
                   "verified against OCL 2.3.201-846796dc), but OCL's import summary counts only "
                   "concept lines — a dropped or rejected mapping is invisible in 'Created: N'. "
                   "Check the mappings on a sample of ids after importing")

    if probe:
        validate_against_source(batch, report, token)
    return batch, report


def _print(report: Report, issues: Iterable[Issue] | None = None) -> None:
    for issue in issues if issues is not None else report.issues:
        print(issue, file=sys.stderr if issue.severity == "error" else sys.stdout)
    print(f"\n{len(report.errors)} error(s), {len(report.warnings)} warning(s)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("batch", help="Path to the batch JSON file")
    parser.add_argument("--probe", action="store_true",
                        help="Optional read-only lookup of the live source: validation profile, "
                             "already-taken ids, FSN collisions. Issues GETs only")
    parser.add_argument("--token", default=None,
                        help="OCL API token, only needed with --probe on a private source "
                             "(defaults to $OCL_API_TOKEN)")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit the report as JSON")
    args = parser.parse_args(argv)

    batch = load_batch(args.batch)
    _, report = validate(batch, probe=args.probe, token=args.token)

    if args.as_json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        _print(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
