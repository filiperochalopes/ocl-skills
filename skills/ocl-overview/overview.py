"""Structured read-only overview of an OCL organization or source.

Sequences the `ocl` CLI's read commands and renders one coherent summary, so a
question like "what is in CIEL/CIEL?" is answered in a single pass instead of
five ad-hoc lookups.

Read-only by construction: every invocation goes through `_ocl()`, which refuses
any subcommand outside `READ_COMMANDS`. The script cannot write to OCL even if
asked to.

Usage:
    python overview.py CIEL                 # organization
    python overview.py CIEL CIEL            # source in that organization
    python overview.py CIEL CIEL --json     # machine-readable
    python overview.py --user someuser      # a user-owned repository owner
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from typing import Any

# Every `ocl` subcommand this script may run. Anything that mutates OCL is
# absent on purpose; see CLAUDE.md rule 2.
READ_COMMANDS: frozenset[tuple[str, ...]] = frozenset({
    ("whoami",),
    ("org", "get"),
    ("org", "repos"),
    ("org", "members"),
    ("repo", "get"),
    ("repo", "versions"),
})


class OverviewError(RuntimeError):
    pass


def _ocl(*args: str, as_json: bool = True) -> Any:
    """Run one allowlisted `ocl` read command."""
    for length in (2, 1):
        if tuple(args[:length]) in READ_COMMANDS:
            break
    else:
        raise OverviewError(f"refusing to run non-read command: ocl {' '.join(args)}")

    if not shutil.which("ocl"):
        raise OverviewError(
            "the `ocl` CLI is not on PATH. Install it from "
            "https://github.com/OpenConceptLab/ocl-cli and run `ocl login`."
        )

    cmd = ["ocl", *(["-j"] if as_json else []), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise OverviewError(f"`{' '.join(cmd)}` failed: {(proc.stderr or proc.stdout).strip()}")
    if not as_json:
        return proc.stdout
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise OverviewError(f"`{' '.join(cmd)}` did not return JSON: {exc}") from exc


def whoami() -> dict[str, Any]:
    """Confirm the session first — the server matters as much as the user."""
    try:
        who = _ocl("whoami")
    except OverviewError as exc:
        raise OverviewError(
            f"not authenticated, or the CLI could not reach the server.\n  {exc}\n"
            "  Run `ocl login` and try again."
        ) from exc
    return who


def _server() -> str:
    """The plain-text `whoami` carries the server; the JSON form does not."""
    for line in str(_ocl("whoami", as_json=False)).splitlines():
        if line.lower().startswith("server:"):
            return line.split(":", 1)[1].strip()
    return "unknown"


def org_overview(org: str) -> dict[str, Any]:
    detail = _ocl("org", "get", org)
    repos = _ocl("org", "repos", org)
    return {
        "id": detail.get("id"),
        "name": detail.get("name"),
        "company": detail.get("company"),
        "location": detail.get("location"),
        "website": detail.get("website"),
        "created_on": detail.get("created_on"),
        "updated_on": detail.get("updated_on"),
        "public_sources": detail.get("public_sources"),
        "public_collections": detail.get("public_collections"),
        "repositories": [
            {
                "id": r.get("short_code") or r.get("id"),
                "name": r.get("name"),
                "type": r.get("source_type") or r.get("collection_type"),
                "kind": r.get("type"),
                "version": r.get("version"),
            }
            for r in repos.get("results", [])
        ],
        "repository_count": repos.get("count"),
    }


def source_overview(owner: str, repo: str, owner_type: str = "orgs",
                    version_limit: int = 5) -> dict[str, Any]:
    detail = _ocl("repo", "get", owner, repo, "--owner-type", owner_type)
    versions = _ocl("repo", "versions", owner, repo, "--owner-type", owner_type,
                    "--limit", str(version_limit))
    summary = detail.get("summary") or {}
    results = versions.get("results", [])
    released = [v for v in results if v.get("released")]
    return {
        "id": detail.get("short_code") or detail.get("id"),
        "name": detail.get("name"),
        "full_name": detail.get("full_name"),
        "owner": detail.get("owner"),
        "owner_type": detail.get("owner_type"),
        "url": detail.get("url"),
        "canonical_url": detail.get("canonical_url"),
        "source_type": detail.get("source_type"),
        "public_access": detail.get("public_access"),
        "description": detail.get("description"),
        "active_concepts": summary.get("active_concepts"),
        "active_mappings": summary.get("active_mappings"),
        "version_count": summary.get("versions") or versions.get("count"),
        # The four fields a bulk-import batch's `target` block needs.
        "validation_profile": {
            "custom_validation_schema": detail.get("custom_validation_schema") or "None",
            "default_locale": detail.get("default_locale"),
            "supported_locales": detail.get("supported_locales") or [],
            "autoid_concept_mnemonic": detail.get("autoid_concept_mnemonic"),
        },
        "autoid": {
            k: detail.get(k) for k in (
                "autoid_concept_mnemonic", "autoid_concept_external_id",
                "autoid_mapping_mnemonic", "autoid_mapping_external_id",
            ) if detail.get(k)
        },
        "match_algorithms": detail.get("match_algorithms") or [],
        "updated_on": detail.get("updated_on"),
        "latest_release": (released[0].get("version") or released[0].get("id")) if released else None,
        "recent_versions": [
            {"id": v.get("version") or v.get("id"), "released": bool(v.get("released")),
             "created_on": (v.get("created_at") or v.get("created_on") or "")[:10]}
            for v in versions.get("results", [])
        ],
    }


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) or "—"
    return str(value)


def render_org(data: dict[str, Any], server: str, user: str) -> str:
    out = [
        f"# {data['name']} (`{data['id']}`)",
        "",
        f"- Session: **{user}** on **{server}**",
        f"- Company: {_fmt(data['company'])} | Location: {_fmt(data['location'])}",
        f"- Public: {_fmt(data['public_sources'])} sources, "
        f"{_fmt(data['public_collections'])} collections",
        f"- Updated: {_fmt(data['updated_on'])[:10]}",
        "",
        f"## Repositories ({_fmt(data['repository_count'])})",
        "",
        "| id | name | type | version |",
        "| --- | --- | --- | --- |",
    ]
    for r in data["repositories"]:
        out.append(f"| `{r['id']}` | {_fmt(r['name'])} | {_fmt(r['type'])} | {_fmt(r['version'])} |")
    return "\n".join(out)


def render_source(data: dict[str, Any], server: str, user: str) -> str:
    profile = data["validation_profile"]
    out = [
        f"# {data['owner']}/{data['id']}",
        "",
        f"- Session: **{user}** on **{server}**",
        f"- {_fmt(data['name'])} — {_fmt(data['source_type'])}, access {_fmt(data['public_access'])}",
        f"- Content: **{_fmt(data['active_concepts'])}** active concepts, "
        f"**{_fmt(data['active_mappings'])}** active mappings",
        f"- Versions: {_fmt(data['version_count'])} | latest release: "
        f"**{_fmt(data['latest_release'])}** | updated {_fmt(data['updated_on'])[:10]}",
        "",
        "## Validation profile",
        "",
        f"- Schema: **{_fmt(profile['custom_validation_schema'])}**"
        + ("  ← the strict OpenMRS rule set applies"
           if profile["custom_validation_schema"] == "OpenMRS" else ""),
        f"- Default locale: {_fmt(profile['default_locale'])}",
        f"- Supported locales: {_fmt(profile['supported_locales'])}",
        f"- Concept mnemonics: {_fmt(profile['autoid_concept_mnemonic']) }"
        + (" (OCL assigns ids)" if profile["autoid_concept_mnemonic"] else " (ids must be supplied)"),
    ]
    if data["match_algorithms"]:
        out.append(f"- Match algorithms: {_fmt(data['match_algorithms'])}")
    out += ["", "## Recent versions", "", "| version | released | created |", "| --- | --- | --- |"]
    for v in data["recent_versions"]:
        out.append(f"| `{v['id']}` | {_fmt(v['released'])} | {v['created_on'] or '—'} |")
    out += [
        "",
        "## For a bulk-import batch",
        "",
        "```json",
        json.dumps({
            "owner": data["owner"], "owner_type":
                "Organization" if data["owner_type"] == "Organization" else "User",
            "source": data["id"],
            "validation_schema": profile["custom_validation_schema"],
            "default_locale": profile["default_locale"],
            "supported_locales": profile["supported_locales"],
            "autoid_concept_mnemonic": profile["autoid_concept_mnemonic"],
        }, indent=2),
        "```",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("owner", help="Organization or user id")
    parser.add_argument("source", nargs="?", help="Source id; omit for an organization overview")
    parser.add_argument("--user", action="store_true", dest="user_owner",
                        help="The owner is a user, not an organization")
    parser.add_argument("--versions", type=int, default=5, help="How many versions to list")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    try:
        who = whoami()
        server = _server()
        user = who.get("username") or "?"
        if args.source:
            data = source_overview(args.owner, args.source,
                                   "users" if args.user_owner else "orgs", args.versions)
            rendered = render_source(data, server, user)
        else:
            data = org_overview(args.owner)
            rendered = render_org(data, server, user)
    except OverviewError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps({"server": server, "user": user, **data}, indent=2, ensure_ascii=False))
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
