"""Turn a validated concept batch into the two review artifacts.

Stage 1 (`csv`)  -- a flat review sheet the user reads and approves.
Stage 2 (`pack`) -- the zipped bulk-import JSONL, only after that approval.

Both artifacts share one stem so they can always be paired back up:

    <slug>_<owner>_<source>_<yyyymmdd_hhii>.csv
    <slug>_<owner>_<source>_<yyyymmdd_hhii>.zip   (contains the .jsonl)

Each ZIP holds exactly one member — OCL rejects archives with more. Batches whose
archive would exceed the upload ceiling are split into ordered parts
(`<stem>.part01of03.zip`), to be uploaded in order into one import queue.

This module produces files. It never uploads anything: the user does that
themselves through the OCL import page.

See `reference/ocl-bulk-import.md` for the format and size rules being honoured.

Usage:
    python build.py csv  batch.json [--out-dir output]
    python build.py pack batch.json [--out-dir output] [--stem <shared stem>]
"""

from __future__ import annotations

import argparse
import csv
import json
import zipfile
from pathlib import Path
from typing import Any

from schema import ConceptBatch, artifact_stem
from validation import Report, load_batch, validate

# OCL's bulk-import form rejects uploads larger than this.
OCL_MAX_UPLOAD_BYTES = 99_614_720  # 95 MiB
# Leave headroom so a part measured before the archive is finalised still fits.
SIZE_SAFETY = 0.90

CSV_COLUMNS = [
    "row", "status", "id", "concept_class", "datatype", "external_id",
    "preferred_name", "preferred_locale", "synonyms", "descriptions",
    "parent_concept_urls", "mappings", "extras", "note", "issues",
]


def _sort_key(line: dict[str, Any]) -> tuple[str, str]:
    """Deterministic order: by id, then by first name. Keeps diffs and parts stable."""
    return str(line.get("id") or ""), line["names"][0]["name"]


def _with_origin(value: str | None, origin: str) -> str:
    """Mark unclassified values so a reviewer can spot them at a glance."""
    if not value:
        return ""
    return f"{value} (UNCLASSIFIED)" if origin == "fallback" else value


def build_csv(batch: ConceptBatch, report: Report, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row, concept in enumerate(batch.concepts, start=1):
            issues = report.for_row(row)
            preferred = concept.preferred_name()
            synonyms = [n for n in concept.names if n is not preferred]
            self_map = batch.self_mapping(concept)
            # self_mapping() builds a fresh object each call, so compare by target.
            self_key = (self_map.map_type, self_map.target_key()) if self_map else None
            writer.writerow({
                "row": row,
                "status": "ERROR" if any(i.severity == "error" for i in issues)
                          else ("WARN" if issues else "OK"),
                "id": concept.id or "(auto)",
                "concept_class": _with_origin(concept.concept_class, concept.concept_class_origin),
                "datatype": _with_origin(concept.datatype, concept.datatype_origin),
                "external_id": concept.external_id or "",
                "preferred_name": preferred.name,
                "preferred_locale": preferred.locale,
                "synonyms": " | ".join(
                    f"{n.name} [{n.locale}/{n.name_type or 'None'}"
                    f"{'/preferred' if n.locale_preferred else ''}]" for n in synonyms
                ),
                "descriptions": " | ".join(f"{d.description} [{d.locale}]" for d in concept.descriptions),
                "parent_concept_urls": " | ".join(concept.parent_concept_urls),
                "mappings": " | ".join(
                    f"{m.map_type} -> {m.to_concept_url or ''}"
                    f"{(m.to_source_url or '') + (m.to_concept_code or '')}"
                    f"{' (self, auto)' if (m.map_type, m.target_key()) == self_key else ''}"
                    for m in batch.mappings_for(concept)
                ),
                "extras": json.dumps(concept.extras, ensure_ascii=False) if concept.extras else "",
                "note": concept.note or "",
                "issues": " | ".join(f"{i.rule}: {i.message}" for i in issues),
            })
    return out_path


def render_lines(batch: ConceptBatch) -> list[str]:
    """The JSONL payload, one serialised line per concept."""
    return [
        json.dumps(line, ensure_ascii=False) + "\n"
        for line in sorted(batch.to_jsonl_lines(), key=_sort_key)
    ]


def _write_zip(lines: list[str], zip_path: Path, member_name: str) -> Path:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        with archive.open(member_name, "w") as member:
            for line in lines:
                member.write(line.encode("utf-8"))
    return zip_path


def _chunk_by_size(lines: list[str], max_uncompressed: int) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    size = 0
    for line in lines:
        line_size = len(line.encode("utf-8"))
        if current and size + line_size > max_uncompressed:
            chunks.append(current)
            current, size = [], 0
        current.append(line)
        size += line_size
    if current:
        chunks.append(current)
    return chunks


def build_archives(lines: list[str], out_dir: Path, stem: str,
                   max_bytes: int = OCL_MAX_UPLOAD_BYTES) -> list[Path]:
    """Write one ZIP, or ordered parts when a single archive would be too large.

    The part count is derived from the compression ratio actually measured on the
    whole payload, then verified; if a part still overflows the chunks are made
    smaller and the attempt repeats.
    """
    single = _write_zip(lines, out_dir / f"{stem}.zip", f"{stem}.jsonl")
    if single.stat().st_size <= max_bytes:
        return [single]

    uncompressed = sum(len(line.encode("utf-8")) for line in lines)
    ratio = single.stat().st_size / max(uncompressed, 1)
    single.unlink()

    budget = int(max_bytes / ratio * SIZE_SAFETY)
    for _ in range(6):
        chunks = _chunk_by_size(lines, budget)
        total = len(chunks)
        paths = [
            _write_zip(chunk, out_dir / f"{stem}.part{index:02d}of{total:02d}.zip",
                       f"{stem}.part{index:02d}of{total:02d}.jsonl")
            for index, chunk in enumerate(chunks, start=1)
        ]
        if all(path.stat().st_size <= max_bytes for path in paths):
            return paths
        for path in paths:
            path.unlink()
        budget = int(budget * 0.7)

    raise RuntimeError(
        "could not split the batch under the upload ceiling; a single concept line is "
        "probably enormous — check for oversized extras"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["csv", "pack"])
    parser.add_argument("batch", help="Path to the batch JSON file")
    parser.add_argument("--out-dir", default="output", type=Path)
    parser.add_argument("--stem", default=None,
                        help="Reuse the stem printed by the csv stage so both artifacts match")
    parser.add_argument("--probe", action="store_true",
                        help="Optional read-only lookup of the live source during validation (GETs only)")
    parser.add_argument("--token", default=None,
                        help="OCL API token, only needed with --probe on a private source")
    parser.add_argument("--max-bytes", type=int, default=OCL_MAX_UPLOAD_BYTES,
                        help="Upload ceiling per archive; larger batches are split into ordered parts")
    parser.add_argument("--allow-errors", action="store_true",
                        help="pack only: build despite validation errors (requires an explicit user override)")
    args = parser.parse_args(argv)

    batch = load_batch(args.batch)
    batch, report = validate(batch, probe=args.probe, token=args.token)
    stem = args.stem or artifact_stem(batch)

    if args.stage == "csv":
        path = build_csv(batch, report, args.out_dir / f"{stem}.csv")
        print(f"stem: {stem}")
        print(f"csv:  {path}")
        print(f"rows: {len(batch.concepts)} | errors: {len(report.errors)} | warnings: {len(report.warnings)}")
        for issue in report.errors:
            print(f"  {issue}")
        return 0

    if report.errors and not args.allow_errors:
        print(f"refusing to pack: {len(report.errors)} validation error(s)")
        for issue in report.errors:
            print(f"  {issue}")
        return 1

    lines = render_lines(batch)
    paths = build_archives(lines, args.out_dir, stem, args.max_bytes)

    print(f"stem:   {stem}")
    mapping_count = sum(len(batch.mappings_for(c)) for c in batch.concepts)
    print(f"lines:  {len(lines)} concepts, carrying {mapping_count} nested mapping(s)")
    print(f"target: {batch.target.source_url} "
          f"(schema={batch.target.validation_schema}, profile={batch.profile})")
    for path in paths:
        print(f"zip:    {path} ({path.stat().st_size:,} bytes)")
    print("\nHand these to the user to upload themselves — see reference/ocl-bulk-import.md "
          "section 8. Use 'Update existing' = OFF for a creation batch.")
    if len(paths) > 1:
        print(f"{len(paths)} parts: they must be uploaded IN ORDER, into the same import queue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
