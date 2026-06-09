"""Full TemplateRegistry — disk scan, semver resolution, quarantine, signature matching."""
from __future__ import annotations

import json
import logging
import pathlib
from typing import Any

from packaging.version import Version
from packaging.specifiers import SpecifierSet, InvalidSpecifier

log = logging.getLogger(__name__)

SUPPORTED_SCHEMA_VERSIONS: set[int] = {1}
TEMPLATES_DIR = pathlib.Path(__file__).parent.parent / "templates"


def _to_pep440(spec_str: str) -> str:
    """Translate npm/Cargo-style caret (^) and tilde (~) ranges to PEP 440.

    ^X.Y.Z  -> >=X.Y.Z,<(X+1).0.0   (compatible within the same major)
    ~X.Y.Z  -> >=X.Y.Z,<X.(Y+1).0   (compatible within the same minor)
    Anything else is assumed to already be a PEP 440 specifier and returned as-is.
    """
    s = spec_str.strip()
    if s[:1] in ("^", "~"):
        op = s[0]
        base = s[1:].strip()
        parts = base.split(".")
        # Normalize to 3 numeric components (pad missing with 0).
        nums = []
        for i in range(3):
            try:
                nums.append(int(parts[i]) if i < len(parts) else 0)
            except ValueError:
                # Non-numeric component — can't translate; let caller handle as PEP 440.
                return spec_str
        major, minor, patch = nums
        if op == "^":
            upper = f"{major + 1}.0.0"
        else:  # "~"
            upper = f"{major}.{minor + 1}.0"
        return f">={major}.{minor}.{patch},<{upper}"
    return spec_str


class TemplateRegistry:
    """In-memory registry of all templates loaded from disk.

    Internal structure:
        _store: dict[id_str, dict[version_str, TemplateObject]]
        _quarantined: set of (id, version) with unresolved requires
        _disk_paths: dict[(id, version), Path] — for deletion and conflict reporting
    """

    def __init__(self, templates_dir: pathlib.Path | None = None) -> None:
        self._dir = templates_dir or TEMPLATES_DIR
        self._store: dict[str, dict[str, dict[str, Any]]] = {}
        self._quarantined: set[tuple[str, str]] = set()
        self._disk_paths: dict[tuple[str, str], pathlib.Path] = {}

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Scan templates/ directory, parse, validate, and build registry."""
        self._store.clear()
        self._quarantined.clear()
        self._disk_paths.clear()

        if not self._dir.exists():
            log.info("templates/ directory not found at %s — no templates loaded", self._dir)
            return

        raw: list[dict[str, Any]] = []
        for path in sorted(self._dir.rglob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                log.error("Failed to parse %s: %s — skipped", path, exc)
                continue

            schema_ver = data.get("schema_version")
            if schema_ver not in SUPPORTED_SCHEMA_VERSIONS:
                log.warning(
                    "Template %s has schema_version=%s (supported: %s) — skipped",
                    path, schema_ver, SUPPORTED_SCHEMA_VERSIONS,
                )
                continue

            tid = data.get("id")
            ver = data.get("version")
            if not tid or not ver:
                log.warning("Template %s missing id or version — skipped", path)
                continue

            key = (tid, ver)
            if key in self._disk_paths:
                raise RuntimeError(
                    f"Duplicate template ({tid}, {ver}): "
                    f"{path} conflicts with {self._disk_paths[key]}"
                )

            self._disk_paths[key] = path
            raw.append(data)

        # Populate store
        for data in raw:
            tid, ver = data["id"], data["version"]
            self._store.setdefault(tid, {})[ver] = data

        # Resolve requires — quarantine unresolvable
        for data in raw:
            tid, ver = data["id"], data["version"]
            requires = data.get("requires", {})
            for dep_id, spec_str in requires.items():
                resolved = self._resolve_dep(dep_id, spec_str)
                if resolved is None:
                    log.error(
                        "ERROR: %s@%s requires %s@%s but no matching version is installed",
                        tid, ver, dep_id, spec_str,
                    )
                    self._quarantined.add((tid, ver))

        loaded = len(raw) - len(self._quarantined)
        log.info(
            "Templates loaded: %d ok, %d quarantined",
            loaded, len(self._quarantined),
        )

    def _resolve_dep(self, dep_id: str, spec_str: str) -> str | None:
        """Return highest installed version of dep_id satisfying spec_str, or None.

        Accepts PEP 440 specifiers and npm/Cargo-style ^/~ ranges. A spec that cannot
        be parsed yields None (the requiring template is quarantined) rather than raising.
        """
        versions = self.list_versions(dep_id)
        if not versions:
            return None
        try:
            spec = SpecifierSet(_to_pep440(spec_str), prereleases=True)
        except InvalidSpecifier:
            log.error("Invalid requires specifier %r for %s — cannot resolve", spec_str, dep_id)
            return None
        candidates = [v for v in versions if Version(v) in spec]
        if not candidates:
            return None
        return str(max(candidates, key=Version))

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def list_all(self) -> list[dict[str, Any]]:
        result = []
        for tid, versions in self._store.items():
            for ver, data in versions.items():
                result.append(data)
        return result

    def list_available(self) -> list[dict[str, Any]]:
        """List all non-quarantined templates."""
        return [
            data
            for data in self.list_all()
            if (data["id"], data["version"]) not in self._quarantined
        ]

    def get(self, template_id: str, version: str) -> dict[str, Any] | None:
        return self._store.get(template_id, {}).get(version)

    def list_versions(self, template_id: str) -> list[str]:
        return list(self._store.get(template_id, {}).keys())

    def latest_version(self, template_id: str) -> str | None:
        versions = self.list_versions(template_id)
        if not versions:
            return None
        return str(max(versions, key=Version))

    def is_quarantined(self, template_id: str, version: str) -> bool:
        return (template_id, version) in self._quarantined

    def manifest(self) -> list[dict[str, str]]:
        """Return [{id, version}] for all available templates — used for push_templates."""
        return [
            {"id": d["id"], "version": d["version"]}
            for d in self.list_available()
        ]

    # ------------------------------------------------------------------
    # Signature matching
    # ------------------------------------------------------------------

    def match_device(
        self,
        service_uuids: list[str],
        name_prefix: str | None = None,
        manufacturer_data: str | None = None,
    ) -> list[dict[str, Any]]:
        """Match device signature against all device templates.

        Returns list of match dicts: {device_template_id, version, variant_id, confidence, warnings}
        """
        results = []
        for data in self.list_available():
            if data.get("type") != "device":
                continue
            tid = data["id"]
            ver = data["version"]
            variants = data.get("variants", [])
            if not variants:
                # Flat device template — check top-level signature
                sig = data.get("signature", {})
                m = self._match_signature(sig, service_uuids, name_prefix, manufacturer_data)
                if m is not None:
                    results.append({
                        "device_template_id": tid,
                        "version": ver,
                        "variant_id": None,
                        "confidence": m,
                        "warnings": [],
                    })
            else:
                for variant in variants:
                    sig = variant.get("signature", {})
                    m = self._match_signature(sig, service_uuids, name_prefix, manufacturer_data)
                    if m is not None:
                        results.append({
                            "device_template_id": tid,
                            "version": ver,
                            "variant_id": variant.get("variant_id"),
                            "confidence": m,
                            "warnings": [],
                        })
        # Sort: exact before partial, then by template id
        results.sort(key=lambda x: (0 if x["confidence"] == "exact" else 1, x["device_template_id"]))
        return results

    def _match_signature(
        self,
        sig: dict[str, Any],
        service_uuids: list[str],
        name_prefix: str | None,
        manufacturer_data: str | None,
    ) -> str | None:
        """Return 'exact' or 'partial' if sig matches, None if no match."""
        if not sig:
            return None
        required_svc = sig.get("service_uuids", [])
        sig_name_prefix = sig.get("name_prefix")
        sig_mfr = sig.get("manufacturer_data")

        matched_fields = 0
        total_fields = 0

        if required_svc:
            total_fields += 1
            lowered = [u.lower() for u in service_uuids]
            if all(u.lower() in lowered for u in required_svc):
                matched_fields += 1
            else:
                return None  # Hard requirement — must match all service UUIDs

        if sig_name_prefix is not None:
            total_fields += 1
            if name_prefix and name_prefix.startswith(sig_name_prefix):
                matched_fields += 1
            else:
                return None

        if sig_mfr is not None:
            total_fields += 1
            if manufacturer_data == sig_mfr:
                matched_fields += 1
            else:
                return None

        if total_fields == 0:
            return None
        return "exact" if matched_fields == total_fields else "partial"

    # ------------------------------------------------------------------
    # Disk write / delete (for draft and DELETE endpoints)
    # ------------------------------------------------------------------

    def save_draft(self, content: dict[str, Any]) -> pathlib.Path:
        """Write a template JSON to disk in templates/<type-based-dir>/<id-local-part>.json."""
        tid = content.get("id", "unknown")
        namespace, _, local = tid.partition(".")
        ttype = content.get("type", "unknown")
        target_dir = self._dir / f"{local}-{ttype}"
        target_dir.mkdir(parents=True, exist_ok=True)
        ver = content.get("version", "0.0.0")
        filename = f"{local}-v{ver.replace('.', '_')}.json"
        path = target_dir / filename
        path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        return path

    def delete(self, template_id: str, version: str) -> bool:
        """Delete a template from disk and from in-memory store. Returns True if deleted."""
        key = (template_id, version)
        path = self._disk_paths.get(key)
        if path is None:
            return False
        path.unlink(missing_ok=True)
        self._store.get(template_id, {}).pop(version, None)
        if not self._store.get(template_id):
            self._store.pop(template_id, None)
        self._disk_paths.pop(key, None)
        self._quarantined.discard(key)
        return True
