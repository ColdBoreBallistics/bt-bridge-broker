"""CatalogClient — fetch templates on demand from the bt-bridge-templates catalog.

Supports https(+token) and file:// base URLs. Resolves a user selection to its full
dependency closure, downloads each template, verifies its sha256 against the index, and
writes the files into the broker's templates/ directory. No template is ever loaded from
the network without a matching checksum in the index.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any
from urllib.parse import urlparse

import httpx
from packaging.specifiers import SpecifierSet
from packaging.version import Version, InvalidVersion

from broker.template_registry import _to_pep440


class CatalogError(RuntimeError):
    """Raised on any catalog fetch / resolve / verify failure."""


class CatalogResolveError(CatalogError):
    """Raised when a requested template id (or its dependency) cannot be resolved
    against the catalog — a client-input fault (bad/unknown id), distinct from an
    upstream fetch/transport failure."""


DEFAULT_BASE_URL = "https://raw.githubusercontent.com/ColdBoreBallistics/bt-bridge-templates/main"


class CatalogClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, token: str | None = None,
                 timeout: float = 15.0) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    # ---- low-level fetch -------------------------------------------------

    def _get_bytes(self, rel_path: str) -> bytes:
        url = f"{self._base}/{rel_path.lstrip('/')}"
        parsed = urlparse(url)
        if parsed.scheme == "file":
            base_root = pathlib.Path(urlparse(self._base).path).resolve()
            p = pathlib.Path(parsed.path).resolve()
            # Containment: a malicious index path must not escape the catalog root.
            if base_root != p and base_root not in p.parents:
                raise CatalogError(f"catalog path escapes base: {parsed.path}")
            if not p.exists():
                raise CatalogError(f"catalog file not found: {p}")
            try:
                return p.read_bytes()
            except OSError as exc:
                raise CatalogError(f"cannot read catalog file {p}: {exc}") from exc
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        try:
            resp = httpx.get(url, headers=headers, timeout=self._timeout,
                             follow_redirects=True)
        except httpx.HTTPError as exc:
            raise CatalogError(f"catalog request failed: {exc}") from exc
        if resp.status_code in (401, 404):
            hint = "" if self._token else " (private repo — set BT_CATALOG_TOKEN?)"
            raise CatalogError(f"catalog fetch {resp.status_code} for {url}{hint}")
        if resp.status_code != 200:
            raise CatalogError(f"catalog fetch {resp.status_code} for {url}")
        return resp.content

    # ---- index + resolution ---------------------------------------------

    def fetch_index(self) -> dict[str, Any]:
        raw = self._get_bytes("catalog/index.json")
        try:
            index = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CatalogError(f"catalog index is not valid JSON: {exc}") from exc
        if not isinstance(index, dict) or not isinstance(index.get("templates"), list):
            raise CatalogError("catalog index malformed: missing 'templates' list")
        for e in index["templates"]:
            if not isinstance(e, dict) or not e.get("id") or not e.get("version") or not e.get("path") or not e.get("sha256"):
                raise CatalogError(f"catalog index entry malformed (needs id/version/path/sha256): {e!r}")
            try:
                Version(e["version"])
            except InvalidVersion:
                raise CatalogError(f"catalog index entry has invalid version: {e.get('id')!r} {e['version']!r}")
        return index

    def _by_id(self, index: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for e in index["templates"]:
            out.setdefault(e["id"], []).append(e)
        return out

    def _highest(self, entries: list[dict[str, Any]],
                 spec: SpecifierSet | None = None) -> dict[str, Any]:
        cands = entries
        if spec is not None:
            cands = [e for e in entries if Version(e["version"]) in spec]
        if not cands:
            raise CatalogError("no version satisfies requirement")
        return max(cands, key=lambda e: Version(e["version"]))

    def resolve_selection(self, ids: list[str],
                          index: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Resolve selected IDs plus their full `requires` closure to index entries."""
        index = index or self.fetch_index()
        by_id = self._by_id(index)
        resolved: dict[str, dict[str, Any]] = {}
        queue = list(ids)
        while queue:
            tid = queue.pop()
            if tid in resolved:
                continue
            if tid not in by_id:
                raise CatalogResolveError(f"template not in catalog: {tid!r}")
            entry = self._highest(by_id[tid])
            resolved[tid] = entry
            for dep_id, spec_str in (entry.get("requires") or {}).items():
                if dep_id not in by_id:
                    raise CatalogResolveError(
                        f"{tid} requires {dep_id} which is not in the catalog")
                self._highest(by_id[dep_id], SpecifierSet(_to_pep440(spec_str), prereleases=True))
                queue.append(dep_id)
        return list(resolved.values())

    # ---- install --------------------------------------------------------

    def install(self, ids: list[str], dest_dir: pathlib.Path,
                index: dict[str, Any] | None = None) -> list[pathlib.Path]:
        """Download resolved templates into dest_dir, verifying each sha256.

        NOT atomic: if one template in the batch fails its checksum, earlier
        templates in the batch are already written to disk. This is safe in
        practice because the registry quarantines templates with unresolved
        ``requires`` on load, so a partial dependency closure lands as
        quarantined (not silently broken) rather than as a usable-but-incomplete
        install.
        """
        index = index or self.fetch_index()
        entries = self.resolve_selection(ids, index=index)
        dest_dir = pathlib.Path(dest_dir)
        written: list[pathlib.Path] = []
        for entry in entries:
            data = self._get_bytes(entry["path"])
            actual = hashlib.sha256(data).hexdigest()
            if actual != entry["sha256"]:
                raise CatalogError(
                    f"checksum mismatch for {entry['id']}@{entry['version']}: "
                    f"expected {entry['sha256']}, got {actual}")
            # Write flat by id+version to avoid path traversal from the index.
            safe = f"{entry['id']}_{entry['version']}.json".replace("/", "_")
            out = dest_dir / safe
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            written.append(out)
        return written
