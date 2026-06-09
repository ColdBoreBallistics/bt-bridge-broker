"""Template registry stub — full implementation in a later plan (broker-template-system).

Catalog-only model: the broker ships no builtin templates. This stub scans the (initially
empty) templates/ directory; templates are fetched on demand from the bt-bridge-templates
catalog repo by the catalog tooling (a later plan).
"""
from __future__ import annotations

import json
import logging
import pathlib
from typing import Any

log = logging.getLogger(__name__)

TEMPLATES_DIR = pathlib.Path(__file__).parent.parent / "templates"


class TemplateRegistry:
    """In-memory store of all template files loaded from disk.

    Key: (template_id, version_string) -> full template dict.
    """

    def __init__(self, templates_dir: pathlib.Path | None = None) -> None:
        self._dir = templates_dir or TEMPLATES_DIR
        self._store: dict[tuple[str, str], dict[str, Any]] = {}

    def load(self) -> None:
        """Scan templates/ directory and load all *.json files."""
        if not self._dir.exists():
            log.info("templates/ directory not found — no templates loaded")
            return
        loaded = 0
        errors = 0
        for path in self._dir.rglob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                tid = data.get("id")
                ver = data.get("version")
                if not tid or not ver:
                    log.warning("Template %s missing id or version — skipped", path)
                    errors += 1
                    continue
                key = (tid, ver)
                if key in self._store:
                    log.error(
                        "Duplicate template (%s, %s): %s conflicts with existing",
                        tid, ver, path,
                    )
                    errors += 1
                    continue
                self._store[key] = data
                loaded += 1
            except Exception as exc:
                log.error("Failed to load template %s: %s", path, exc)
                errors += 1
        log.info("Templates loaded: %d ok, %d errors", loaded, errors)

    def list_all(self) -> list[dict[str, Any]]:
        return list(self._store.values())

    def get(self, template_id: str, version: str) -> dict[str, Any] | None:
        return self._store.get((template_id, version))

    def list_versions(self, template_id: str) -> list[str]:
        return [v for (tid, v) in self._store if tid == template_id]
