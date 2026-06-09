#!/usr/bin/env python3
"""CI lint for BT Bridge template files (broker copy).

Validates JSON, schema_version, required fields, semver, duplicates, dependency
resolvability, and (with --community-pr) the builtin.-namespace rule.

Usage:
    python3 tools/lint_templates.py [templates_dir] [--community-pr]

Exit code 0 = clean. Exit code 1 = errors found.

This mirrors the validation the BT Bridge broker applies at load time, packaged here so
the templates fetched into the broker's templates/ dir can be gated in CI. It is kept
functionally consistent with the catalog repository's tools/lint_templates.py — the two
must agree on any given template. The one difference is the default directory: this copy
defaults to the broker's templates/ dir (the catalog copy defaults to its catalog/).

Requires resolution uses the broker registry's caret/tilde translation (_to_pep440) so
the lint's verdict matches what TemplateRegistry will actually do at load time.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from dataclasses import dataclass, field
from typing import Any

from packaging.version import Version, InvalidVersion
from packaging.specifiers import SpecifierSet, InvalidSpecifier

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
# When invoked as a script, sys.path[0] is tools/, not the repo root, so the broker
# package would not be importable. Ensure the repo root is importable either way.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from broker.template_registry import _to_pep440  # noqa: E402

SUPPORTED_SCHEMA_VERSIONS = {1}
TEMPLATES_DIR = REPO_ROOT / "templates"
INDEX_NAME = "index.json"


@dataclass
class LintResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def lint_directory(directory: pathlib.Path, is_community_pr: bool = False) -> LintResult:
    result = LintResult()
    seen: dict[tuple[str, str], pathlib.Path] = {}
    templates: list[dict[str, Any]] = []

    for path in sorted(directory.rglob("*.json")):
        if path.name == INDEX_NAME:
            continue  # the generated index is not a template
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            result.errors.append(f"{path}: JSON parse error: {exc}")
            continue

        if not isinstance(data, dict):
            result.errors.append(f"{path}: top-level JSON is not an object")
            continue

        schema_ver = data.get("schema_version")
        if schema_ver not in SUPPORTED_SCHEMA_VERSIONS:
            result.errors.append(
                f"{path}: unsupported schema_version={schema_ver!r} "
                f"(supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)})"
            )
            continue

        tid = data.get("id")
        ver = data.get("version")
        if not tid:
            result.errors.append(f"{path}: missing required field 'id'")
            continue
        if not ver:
            result.errors.append(f"{path}: missing required field 'version'")
            continue

        try:
            Version(ver)
        except InvalidVersion:
            result.errors.append(f"{path}: invalid semver version {ver!r}")
            continue

        if is_community_pr and tid.startswith("builtin."):
            result.errors.append(
                f"{path}: community PRs may not add or modify builtin. templates "
                f"(use the contrib. namespace)"
            )

        key = (tid, ver)
        if key in seen:
            result.errors.append(
                f"Duplicate template ({tid}, {ver}): {path} conflicts with {seen[key]}"
            )
        else:
            seen[key] = path
            templates.append(data)

    # Resolve all requires entries against the installed set.
    all_ids: dict[str, list[str]] = {}
    for t in templates:
        all_ids.setdefault(t["id"], []).append(t["version"])

    for t in templates:
        tid, ver = t["id"], t["version"]
        for dep_id, spec_str in t.get("requires", {}).items():
            try:
                spec = SpecifierSet(_to_pep440(spec_str), prereleases=True)
            except InvalidSpecifier:
                result.errors.append(
                    f"{tid}@{ver}: invalid requires specifier for {dep_id}: {spec_str!r}"
                )
                continue
            dep_versions = all_ids.get(dep_id, [])
            candidates = [v for v in dep_versions if Version(v) in spec]
            if not candidates:
                result.errors.append(
                    f"{tid}@{ver}: unresolvable requires {dep_id}@{spec_str} "
                    f"(installed versions: {dep_versions or 'none'})"
                )

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="BT Bridge template CI lint")
    parser.add_argument("directory", nargs="?", default=str(TEMPLATES_DIR))
    parser.add_argument("--community-pr", action="store_true")
    args = parser.parse_args()

    directory = pathlib.Path(args.directory)
    if not directory.exists():
        print(f"ERROR: directory not found: {directory}")
        sys.exit(1)

    result = lint_directory(directory, is_community_pr=args.community_pr)

    for w in result.warnings:
        print(f"WARN:  {w}")
    for e in result.errors:
        print(f"ERROR: {e}")

    if result.ok:
        print(f"OK: {directory} — no errors")
        sys.exit(0)
    print(f"FAIL: {len(result.errors)} error(s)")
    sys.exit(1)


if __name__ == "__main__":
    main()
