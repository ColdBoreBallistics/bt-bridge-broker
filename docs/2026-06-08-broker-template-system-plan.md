# BT Bridge Broker — Template System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Commit workflow (FOSS).** The `bt-bridge-*` repos are governed as open-source projects, not
> under the CBB app SDLC. The per-task `git commit` steps use **Conventional Commits**
> (`type(scope): subject`) and are the intended granularity — one focused commit per task, made
> after that task's tests pass. This is the standard FOSS commit-as-you-go flow; the CBB "ask
> before every commit" gate does not apply here. Pushing and opening PRs remain explicit actions.

**Goal:** Implement the broker-side template system: full TemplateRegistry (startup scan, semver dependency resolution, quarantine), REST `/v1/templates/*` endpoints, template push to agent on TCP connect, signature matching, RE capture session, and CI lint script.

**Architecture:** `TemplateRegistry` replaces the stub from Plan 1 — it does full JSON scan, semver resolution, and conflict detection. `agent_tcp.py` gains template push/response handling on connect. New `/v1/templates/*` and `/v1/re/*` routes added to `routes.py`. CI lint lives in `tools/lint_templates.py`.

**Tech Stack:** Python 3.11+, FastAPI (existing), `packaging` (semver), pytest, `httpx.AsyncClient`

**Prerequisites:** Plan 1 complete — broker package structure, AgentRegistry, REST/WS API, TemplateRegistry stub, builtin templates on disk.

**Design reference:** `docs/2026-06-08-template-system-design.md`

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Replace | `broker/template_registry.py` | Full TemplateRegistry: scan, semver resolution, quarantine, sig match |
| Modify | `broker/agent_tcp.py` | Push templates on connect; handle `template_request`, `template_applied`, `view_changed` |
| Modify | `broker/api/routes.py` | Add `/v1/templates/*` and `/v1/re/*` routes |
| Create | `broker/re_session.py` | RE capture session state machine |
| Create | `tools/lint_templates.py` | CI lint script |
| ~~Create~~ | ~~`templates/shared/display.battery-service.json`~~ | Moved to catalog repo (`bt-bridge-templates`) — see Task 7 |
| ~~Create~~ | ~~`templates/shared/display.device-information.json`~~ | Moved to catalog repo (`bt-bridge-templates`) — see Task 7 |
| Create | `tests/test_template_registry.py` | Unit tests for TemplateRegistry |
| Create | `tests/test_template_api.py` | Integration tests for `/v1/templates/*` endpoints |
| Create | `tests/test_re_session.py` | RE session state machine tests |
| Create | `tests/test_lint.py` | Lint script tests |

---

## Task 1: Install semver dependency

**Files:**
- Modify: `requirements.txt`
- Modify: `requirements-lock.txt`

- [ ] **Step 1: Add packaging to requirements.txt**

In `requirements.txt`, add after existing entries:
```text
packaging>=24.0
```

- [ ] **Step 2: Install**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pip install packaging
pip freeze > requirements-lock.txt
```

- [ ] **Step 3: Commit**

```bash
git add requirements.txt requirements-lock.txt
git commit -m "chore: add packaging dep for semver resolution"
```

---

## Task 2: Full TemplateRegistry — scan, conflict detection, schema_version gate

**Files:**
- Replace: `broker/template_registry.py`
- Create: `tests/test_template_registry.py`

- [ ] **Step 1: Write failing tests for TemplateRegistry scan**

`tests/test_template_registry.py`:
```python
"""Unit tests for the full TemplateRegistry."""
from __future__ import annotations

import json
import pathlib
import pytest
import tempfile

from broker.template_registry import TemplateRegistry, SUPPORTED_SCHEMA_VERSIONS


@pytest.fixture
def tmpdir_path(tmp_path):
    return tmp_path


def write_template(directory: pathlib.Path, filename: str, content: dict) -> pathlib.Path:
    p = directory / filename
    p.write_text(json.dumps(content), encoding="utf-8")
    return p


def make_device_template(tid="builtin.test-device", ver="1.0.0"):
    return {
        "schema_version": 1,
        "id": tid,
        "version": ver,
        "type": "device",
        "name": "Test Device",
        "signature": {"service_uuids": ["0000abcd-0000-1000-8000-00805f9b34fb"]},
        "variants": []
    }


def make_display_template(tid="builtin.test-display", ver="1.0.0"):
    return {
        "schema_version": 1,
        "id": tid,
        "version": ver,
        "type": "display",
        "name": "Test Display",
        "notifications": [],
        "reads": []
    }


def test_load_empty_dir(tmpdir_path):
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert tr.list_all() == []


def test_load_single_template(tmpdir_path):
    write_template(tmpdir_path, "device.json", make_device_template())
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert len(tr.list_all()) == 1


def test_load_multiple_templates(tmpdir_path):
    write_template(tmpdir_path, "device.json", make_device_template())
    write_template(tmpdir_path, "display.json", make_display_template())
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert len(tr.list_all()) == 2


def test_duplicate_id_version_raises(tmpdir_path):
    write_template(tmpdir_path, "device1.json", make_device_template())
    write_template(tmpdir_path, "device2.json", make_device_template())
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    with pytest.raises(RuntimeError, match="Duplicate template"):
        tr.load()


def test_schema_version_too_high_skipped(tmpdir_path):
    t = make_device_template()
    t["schema_version"] = 9999
    write_template(tmpdir_path, "future.json", t)
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert tr.list_all() == []


def test_missing_id_skipped(tmpdir_path):
    t = make_device_template()
    del t["id"]
    write_template(tmpdir_path, "bad.json", t)
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert tr.list_all() == []


def test_missing_version_skipped(tmpdir_path):
    t = make_device_template()
    del t["version"]
    write_template(tmpdir_path, "bad.json", t)
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert tr.list_all() == []


def test_get_by_id_version(tmpdir_path):
    write_template(tmpdir_path, "device.json", make_device_template())
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    t = tr.get("builtin.test-device", "1.0.0")
    assert t is not None
    assert t["id"] == "builtin.test-device"


def test_get_missing_returns_none(tmpdir_path):
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert tr.get("builtin.nonexistent", "1.0.0") is None


def test_list_versions(tmpdir_path):
    write_template(tmpdir_path, "v1.json", make_device_template(ver="1.0.0"))
    write_template(tmpdir_path, "v2.json", make_device_template(ver="2.0.0"))
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    versions = tr.list_versions("builtin.test-device")
    assert set(versions) == {"1.0.0", "2.0.0"}


def test_latest_version(tmpdir_path):
    write_template(tmpdir_path, "v1.json", make_device_template(ver="1.0.0"))
    write_template(tmpdir_path, "v2.json", make_device_template(ver="2.0.0"))
    write_template(tmpdir_path, "v110.json", make_device_template(ver="1.10.0"))
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert tr.latest_version("builtin.test-device") == "2.0.0"
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/test_template_registry.py -v 2>&1 | head -15
```

Expected: fails with import errors or missing `SUPPORTED_SCHEMA_VERSIONS`.

- [ ] **Step 3: Replace broker/template_registry.py with full implementation**

```python
"""Full TemplateRegistry — disk scan, semver resolution, quarantine, signature matching."""
from __future__ import annotations

import json
import logging
import pathlib
from typing import Any

from packaging.version import Version
from packaging.specifiers import SpecifierSet

log = logging.getLogger(__name__)

SUPPORTED_SCHEMA_VERSIONS: set[int] = {1}
TEMPLATES_DIR = pathlib.Path(__file__).parent.parent / "templates"


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
        """Return highest installed version of dep_id satisfying spec_str, or None."""
        versions = self.list_versions(dep_id)
        if not versions:
            return None
        spec = SpecifierSet(spec_str, prereleases=True)
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
```

- [ ] **Step 4: Run template registry tests**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/test_template_registry.py -v
```

Expected: all 13 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add broker/template_registry.py tests/test_template_registry.py
git commit -m "feat(template_registry): full scan, semver resolution, quarantine, sig match"
```

---

## Task 3: Template push on agent connect

**Files:**
- Modify: `broker/agent_tcp.py`
- Modify: `tests/test_template_registry.py` (add signature matching tests)

- [ ] **Step 1: Add signature matching tests**

Append to `tests/test_template_registry.py`:
```python
def test_match_device_exact(tmpdir_path):
    t = make_device_template()
    t["signature"] = {"service_uuids": ["0000abcd-0000-1000-8000-00805f9b34fb"]}
    write_template(tmpdir_path, "device.json", t)
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    matches = tr.match_device(["0000abcd-0000-1000-8000-00805f9b34fb"])
    assert len(matches) == 1
    assert matches[0]["confidence"] == "exact"
    assert matches[0]["device_template_id"] == "builtin.test-device"


def test_match_device_no_match(tmpdir_path):
    t = make_device_template()
    t["signature"] = {"service_uuids": ["0000abcd-0000-1000-8000-00805f9b34fb"]}
    write_template(tmpdir_path, "device.json", t)
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    matches = tr.match_device(["0000ffff-0000-1000-8000-00805f9b34fb"])
    assert matches == []


def test_match_device_name_prefix(tmpdir_path):
    t = make_device_template()
    t["signature"] = {
        "service_uuids": ["0000abcd-0000-1000-8000-00805f9b34fb"],
        "name_prefix": "WF"
    }
    write_template(tmpdir_path, "device.json", t)
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert tr.match_device(["0000abcd-0000-1000-8000-00805f9b34fb"], name_prefix="WF-Tactical") != []
    assert tr.match_device(["0000abcd-0000-1000-8000-00805f9b34fb"], name_prefix="Niimbot") == []


def test_manifest_excludes_quarantined(tmpdir_path):
    good = make_device_template("builtin.good", "1.0.0")
    bad = make_device_template("builtin.bad", "1.0.0")
    bad["requires"] = {"builtin.missing": "^1.0.0"}
    write_template(tmpdir_path, "good.json", good)
    write_template(tmpdir_path, "bad.json", bad)
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    manifest = tr.manifest()
    ids = [m["id"] for m in manifest]
    assert "builtin.good" in ids
    assert "builtin.bad" not in ids
```

- [ ] **Step 2: Run new tests**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/test_template_registry.py -v
```

Expected: all 17 tests PASS.

- [ ] **Step 3: Update broker/agent_tcp.py — add template push on connect and handle template_request**

Replace the `handle_agent` function in `broker/agent_tcp.py` with:
```python
async def handle_agent(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    registry: "AgentRegistry",
) -> None:
    """Called by asyncio.start_server for each new agent connection."""
    conn = AgentConnection(writer)
    agent_id = registry.register(conn)
    conn.agent_id = agent_id

    peer = writer.get_extra_info("peername", ("?", 0))
    log.info("Agent connected: %s from %s:%s", agent_id, peer[0], peer[1])

    # Registration acknowledgement
    await conn.send(json.dumps({"cmd": "register", "agent_id": agent_id}))

    # Template push — send manifest of available templates
    template_registry = getattr(registry, "_template_registry", None)
    if template_registry is not None:
        manifest = template_registry.manifest()
        if manifest:
            await conn.send(json.dumps({"cmd": "push_templates", "manifest": manifest}))
            log.debug("Sent push_templates manifest to %s (%d templates)", agent_id, len(manifest))

    # Notify WebSocket subscribers
    registry.publish(agent_id, {"event": "agent_connected", "agent_id": agent_id, "peer": f"{peer[0]}:{peer[1]}"})

    try:
        while True:
            try:
                line = await reader.readline()
            except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
                break
            if not line:
                break
            raw = line.decode(errors="replace").strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                log.warning("Malformed JSON from %s: %r", agent_id, raw[:120])
                continue

            etype = event.get("event")

            # Handle template_request — respond with template_data for each requested id+version
            if etype == "template_request" and template_registry is not None:
                requested = event.get("ids", [])
                for item in requested:
                    tid = item.get("id")
                    ver = item.get("version")
                    content = template_registry.get(tid, ver) if tid and ver else None
                    if content:
                        await conn.send(json.dumps({
                            "cmd": "template_data",
                            "id": tid,
                            "version": ver,
                            "content": content,
                        }))
                    else:
                        log.warning("Agent %s requested unknown template %s@%s", agent_id, tid, ver)
                continue  # template_request is not published to WebSocket

            # Handle services_discovered — run signature match and send apply_template
            if etype == "services_discovered" and template_registry is not None:
                services = event.get("services", [])
                service_uuids = [s["uuid"] for s in services]
                address = event.get("address", "")
                # Update services cache in registry
                state = registry.get_agent(agent_id)
                if state is not None:
                    state.services[address] = services
                matches = template_registry.match_device(service_uuids)
                if matches:
                    best = matches[0]
                    await conn.send(json.dumps({
                        "cmd": "apply_template",
                        "address": address,
                        "device_template_id": best["device_template_id"],
                        "version": best["version"],
                        "variant_id": best["variant_id"],
                    }))
                    log.info(
                        "Matched device %s to template %s@%s variant=%s (confidence=%s)",
                        address, best["device_template_id"], best["version"],
                        best["variant_id"], best["confidence"],
                    )
                else:
                    log.info("No template match for device %s — agent will use GATT analyser", address)

            registry.update_state(agent_id, event)
            registry.publish(agent_id, event)
    except Exception as exc:
        log.error("Unexpected error in agent loop for %s: %s", agent_id, exc)
    finally:
        registry.unregister(agent_id)
        registry.publish(agent_id, {"event": "agent_disconnected", "agent_id": agent_id})
        await conn.close()
        log.info("Agent disconnected: %s", agent_id)
```

- [ ] **Step 4: Wire template_registry into AgentRegistry**

In `broker/registry.py`, add a `set_template_registry` method and `_template_registry` attribute:

In `AgentRegistry.__init__`, add:
```python
self._template_registry: Any = None
```

After `__init__`, add:
```python
def set_template_registry(self, tr: Any) -> None:
    self._template_registry = tr
```

- [ ] **Step 5: Wire it up in main.py lifespan**

In `broker/main.py`, after `template_registry.load()`, add:
```python
registry.set_template_registry(template_registry)
```

- [ ] **Step 6: Run full test suite — confirm nothing broke**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add broker/agent_tcp.py broker/registry.py broker/main.py tests/test_template_registry.py
git commit -m "feat(agent_tcp): push templates on connect, handle template_request, apply_template on sig match"
```

---

## Task 4: Template REST endpoints

**Files:**
- Modify: `broker/api/routes.py`
- Create: `tests/test_template_api.py`

- [ ] **Step 1: Write failing tests for template REST endpoints**

`tests/test_template_api.py`:
```python
"""Integration tests for /v1/templates/* REST endpoints."""
from __future__ import annotations

import json
import pathlib
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from broker.registry import AgentRegistry
from broker.template_registry import TemplateRegistry
from broker.api.app import create_app


def make_device_template(tid="builtin.test-device", ver="1.0.0"):
    return {
        "schema_version": 1,
        "id": tid,
        "version": ver,
        "type": "device",
        "name": "Test Device",
        "signature": {"service_uuids": ["0000abcd-0000-1000-8000-00805f9b34fb"]},
        "variants": []
    }


@pytest.fixture
def template_dir(tmp_path):
    t = make_device_template()
    (tmp_path / "device.json").write_text(json.dumps(t))
    return tmp_path


@pytest.fixture
def registry():
    return AgentRegistry()


@pytest_asyncio.fixture
async def client(registry, template_dir):
    tr = TemplateRegistry(templates_dir=template_dir)
    tr.load()
    registry.set_template_registry(tr)
    app = create_app(registry)
    app.state.template_registry = tr
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_list_templates(client):
    resp = await client.get("/v1/templates")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["id"] == "builtin.test-device"


@pytest.mark.asyncio
async def test_list_template_versions(client):
    resp = await client.get("/v1/templates/builtin.test-device")
    assert resp.status_code == 200
    assert "1.0.0" in resp.json()["versions"]


@pytest.mark.asyncio
async def test_get_template_by_version(client):
    resp = await client.get("/v1/templates/builtin.test-device/1.0.0")
    assert resp.status_code == 200
    assert resp.json()["id"] == "builtin.test-device"


@pytest.mark.asyncio
async def test_get_template_not_found(client):
    resp = await client.get("/v1/templates/builtin.nonexistent/1.0.0")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_match_templates(client):
    resp = await client.get(
        "/v1/templates/match",
        params={"service_uuids": "0000abcd-0000-1000-8000-00805f9b34fb"}
    )
    assert resp.status_code == 200
    matches = resp.json()["matches"]
    assert len(matches) == 1
    assert matches[0]["device_template_id"] == "builtin.test-device"


@pytest.mark.asyncio
async def test_match_templates_no_match(client):
    resp = await client.get(
        "/v1/templates/match",
        params={"service_uuids": "0000ffff-0000-1000-8000-00805f9b34fb"}
    )
    assert resp.status_code == 200
    assert resp.json()["matches"] == []


@pytest.mark.asyncio
async def test_reload_templates(client):
    resp = await client.post("/v1/templates/reload")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_draft_and_delete(client, template_dir):
    draft = {
        "schema_version": 1,
        "id": "contrib.my-draft",
        "version": "0.1.0",
        "type": "display",
        "name": "My Draft"
    }
    resp = await client.post("/v1/templates/draft", json=draft)
    assert resp.status_code == 201

    # Reload to pick it up
    await client.post("/v1/templates/reload")

    resp = await client.get("/v1/templates/contrib.my-draft/0.1.0")
    assert resp.status_code == 200

    resp = await client.delete("/v1/templates/contrib.my-draft/0.1.0")
    assert resp.status_code == 200

    resp = await client.get("/v1/templates/contrib.my-draft/0.1.0")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests — expect 404 (routes not defined)**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/test_template_api.py -v 2>&1 | tail -20
```

Expected: 404 errors or import failures.

- [ ] **Step 3: Add template REST endpoints to broker/api/routes.py**

Append to `broker/api/routes.py`:
```python

# ---------------------------------------------------------------------------
# Template endpoints
# ---------------------------------------------------------------------------

def _template_registry(request: Request):
    from fastapi import HTTPException
    tr = getattr(request.app.state, "template_registry", None)
    if tr is None:
        raise HTTPException(status_code=503, detail={"error": "not_ready", "message": "Template registry not initialized"})
    return tr


@router.get("/v1/templates")
async def list_templates(request: Request):
    tr = _template_registry(request)
    return [
        {
            "id": t["id"],
            "version": t["version"],
            "type": t.get("type"),
            "name": t.get("name"),
            "available": not tr.is_quarantined(t["id"], t["version"]),
        }
        for t in tr.list_all()
    ]


@router.get("/v1/templates/match")
async def match_templates(
    request: Request,
    service_uuids: str = Query(default=""),
    name_prefix: str | None = Query(default=None),
    manufacturer_data: str | None = Query(default=None),
):
    tr = _template_registry(request)
    uuids = [u.strip() for u in service_uuids.split(",") if u.strip()] if service_uuids else []
    matches = tr.match_device(uuids, name_prefix=name_prefix, manufacturer_data=manufacturer_data)
    return {"matches": matches}


@router.get("/v1/templates/{template_id}")
async def list_template_versions(template_id: str, request: Request):
    from fastapi import HTTPException
    tr = _template_registry(request)
    versions = tr.list_versions(template_id)
    if not versions:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": f"No template {template_id!r}"})
    return {"id": template_id, "versions": versions}


@router.get("/v1/templates/{template_id}/{version}")
async def get_template(template_id: str, version: str, request: Request):
    from fastapi import HTTPException
    tr = _template_registry(request)
    t = tr.get(template_id, version)
    if t is None:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": f"Template {template_id}@{version} not found"})
    return t


@router.post("/v1/templates/reload")
async def reload_templates(request: Request):
    tr = _template_registry(request)
    tr.load()
    return {"status": "ok", "loaded": len(tr.list_all())}


@router.post("/v1/templates/draft", status_code=201)
async def save_draft_template(body: dict, request: Request):
    from fastapi import HTTPException
    tr = _template_registry(request)
    if not body.get("id") or not body.get("version"):
        raise HTTPException(status_code=422, detail={"error": "invalid", "message": "Template must have id and version"})
    path = tr.save_draft(body)
    return {"status": "saved", "path": str(path)}


@router.delete("/v1/templates/{template_id}/{version}")
async def delete_template(template_id: str, version: str, request: Request):
    from fastapi import HTTPException
    tr = _template_registry(request)
    deleted = tr.delete(template_id, version)
    if not deleted:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": f"Template {template_id}@{version} not found"})
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Agent view endpoint
# ---------------------------------------------------------------------------

class SetViewIn(BaseModel):
    address: str
    view: str


@router.post("/v1/agents/{agent_id}/view")
async def set_agent_view(agent_id: str, body: SetViewIn, request: Request):
    reg = _registry(request)
    state = reg.resolve_agent(agent_id)
    await reg.send_command(state.agent_id, {
        "cmd": "set_view",
        "address": body.address,
        "view": body.view,
    })
    return {"status": "ok"}
```

- [ ] **Step 4: Enforce route ordering with a regression test (not prose)**

FastAPI matches routes in **declaration order**, so `GET /v1/templates/match` must be declared
**before** `GET /v1/templates/{template_id}` — otherwise the literal path `match` is captured as
`template_id="match"` and the match endpoint becomes unreachable. Rather than rely on a human
verifying the append order, lock the invariant with a test that fails loudly if the order ever
regresses.

Append to `tests/test_template_api.py`:
```python
@pytest.mark.asyncio
async def test_match_route_not_swallowed_by_template_id(client):
    """Regression guard: /v1/templates/match must bind to the match handler,
    NOT be captured as /v1/templates/{template_id} with template_id='match'.

    If route ordering regresses, this returns the 'list versions for template
    "match"' shape (a 404 'No template' or a {id,versions} body) instead of the
    match-result shape ({"matches": [...]}).
    """
    resp = await client.get(
        "/v1/templates/match",
        params={"service_uuids": "0000abcd-0000-1000-8000-00805f9b34fb"},
    )
    assert resp.status_code == 200, (
        f"/v1/templates/match returned {resp.status_code} — likely swallowed by "
        f"/v1/templates/{{template_id}}. Declare the match route first."
    )
    body = resp.json()
    assert "matches" in body, (
        f"Expected match-result shape with 'matches' key, got {body!r}. "
        f"The {{template_id}} route is shadowing /match — fix declaration order."
    )


def test_match_route_declared_before_template_id():
    """Static guard on declaration order in the router itself."""
    from broker.api.routes import router

    def _index(path_suffix: str) -> int:
        for i, route in enumerate(router.routes):
            if getattr(route, "path", "") == f"/v1/templates/{path_suffix}":
                return i
        raise AssertionError(f"route /v1/templates/{path_suffix} not found")

    assert _index("match") < _index("{template_id}"), (
        "/v1/templates/match must be declared before /v1/templates/{template_id}"
    )
```

> The second test inspects `router.routes` directly, so it catches an ordering regression even
> if the data-dependent first test happens to pass. Keep both.

- [ ] **Step 5: Run template API tests**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/test_template_api.py -v
```

Expected: all 11 tests PASS (9 original + 2 route-ordering guards).

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add broker/api/routes.py tests/test_template_api.py
git commit -m "feat(api): /v1/templates/* endpoints — list, match, reload, draft, delete, set_view"
```

---

## Task 5: RE capture session

**Files:**
- Create: `broker/re_session.py`
- Create: `tests/test_re_session.py`
- Modify: `broker/api/routes.py`

- [ ] **Step 1: Write failing tests for RE session**

`tests/test_re_session.py`:
```python
"""Tests for RE capture session state machine."""
from __future__ import annotations

import pytest
from broker.re_session import ReSession, ReSessionState


def test_initial_state():
    s = ReSession(session_id="s1", agent_id="agent-001", address="AA:BB:CC:DD:EE:FF")
    assert s.state == ReSessionState.IDLE
    assert s.session_id == "s1"


def test_start_transitions_to_active():
    s = ReSession(session_id="s1", agent_id="agent-001", address="AA:BB:CC:DD:EE:FF")
    s.start()
    assert s.state == ReSessionState.ACTIVE


def test_add_capture_sample():
    s = ReSession(session_id="s1", agent_id="agent-001", address="AA:BB:CC:DD:EE:FF")
    s.start()
    s.add_sample(char_uuid="0000ff01-0000-1000-8000-00805f9b34fb", value_hex="55550102aa")
    samples = s.samples_for("0000ff01-0000-1000-8000-00805f9b34fb")
    assert len(samples) == 1
    assert samples[0] == "55550102aa"


def test_analyse_entropy():
    s = ReSession(session_id="s1", agent_id="agent-001", address="AA:BB:CC:DD:EE:FF")
    s.start()
    # 5 identical samples — all bytes have zero entropy
    for _ in range(5):
        s.add_sample("0000ff01-0000-1000-8000-00805f9b34fb", "0102030405")
    analysis = s.analyse()
    char_analysis = analysis["0000ff01-0000-1000-8000-00805f9b34fb"]
    assert char_analysis["sample_count"] == 5
    assert char_analysis["byte_count"] == 5
    assert all(b["entropy"] == pytest.approx(0.0) for b in char_analysis["bytes"])


def test_analyse_range():
    s = ReSession(session_id="s1", agent_id="agent-001", address="AA:BB:CC:DD:EE:FF")
    s.start()
    s.add_sample("0000ff01-0000-1000-8000-00805f9b34fb", "01")
    s.add_sample("0000ff01-0000-1000-8000-00805f9b34fb", "ff")
    analysis = s.analyse()
    b = analysis["0000ff01-0000-1000-8000-00805f9b34fb"]["bytes"][0]
    assert b["min"] == 1
    assert b["max"] == 255


def test_scaffold_generates_template():
    s = ReSession(session_id="s1", agent_id="agent-001", address="AA:BB:CC:DD:EE:FF")
    s.start()
    for _ in range(3):
        s.add_sample("0000ff01-0000-1000-8000-00805f9b34fb", "55aa0102")
    scaffold = s.scaffold(device_name="MyDevice", namespace="contrib")
    assert scaffold["type"] == "display"
    assert scaffold["id"].startswith("contrib.")
    chars = scaffold["notifications"]
    assert any(c["char"] == "0000ff01-0000-1000-8000-00805f9b34fb" for c in chars)


def test_export_tshark_format():
    s = ReSession(session_id="s1", agent_id="agent-001", address="AA:BB:CC:DD:EE:FF")
    s.start()
    s.add_sample("0000ff01-0000-1000-8000-00805f9b34fb", "aabbcc")
    export = s.export_tshark()
    assert export["_bt_bridge_export"] is True
    assert len(export["packets"]) == 1
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/test_re_session.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'broker.re_session'`

- [ ] **Step 3: Create broker/re_session.py**

```python
"""RE (reverse engineering) capture session state machine."""
from __future__ import annotations

import math
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ReSessionState(Enum):
    IDLE = "idle"
    ACTIVE = "active"
    COMPLETE = "complete"


@dataclass
class ReSession:
    session_id: str
    agent_id: str
    address: str
    state: ReSessionState = ReSessionState.IDLE
    started_at: int = field(default_factory=lambda: int(time.time() * 1000))
    _samples: dict[str, list[str]] = field(default_factory=dict)

    def start(self) -> None:
        self.state = ReSessionState.ACTIVE

    def complete(self) -> None:
        self.state = ReSessionState.COMPLETE

    def add_sample(self, char_uuid: str, value_hex: str) -> None:
        self._samples.setdefault(char_uuid, []).append(value_hex)

    def samples_for(self, char_uuid: str) -> list[str]:
        return self._samples.get(char_uuid, [])

    def analyse(self) -> dict[str, Any]:
        """Compute per-byte statistics for each captured characteristic."""
        result: dict[str, Any] = {}
        for char_uuid, samples in self._samples.items():
            # Pad all samples to the same length
            max_len = max((len(bytes.fromhex(s)) for s in samples), default=0)
            byte_arrays = []
            for s in samples:
                b = bytes.fromhex(s)
                # Pad with last byte if shorter (preserves statistical intent)
                if len(b) < max_len:
                    b = b + b[-1:] * (max_len - len(b)) if b else b"\x00" * max_len
                byte_arrays.append(b)

            byte_stats = []
            for i in range(max_len):
                values = [arr[i] for arr in byte_arrays if i < len(arr)]
                counts = Counter(values)
                total = len(values)
                entropy = -sum((c / total) * math.log2(c / total) for c in counts.values() if c > 0)
                change_count = sum(1 for j in range(1, len(values)) if values[j] != values[j - 1])
                hint = _infer_hint(i, entropy, min(values), max(values), change_count, total)
                byte_stats.append({
                    "offset": i,
                    "min": min(values),
                    "max": max(values),
                    "entropy": round(entropy, 4),
                    "change_frequency": round(change_count / max(total - 1, 1), 3),
                    "_re_hint": hint,
                })

            result[char_uuid] = {
                "sample_count": len(samples),
                "byte_count": max_len,
                "bytes": byte_stats,
            }
        return result

    def scaffold(self, device_name: str = "Unknown", namespace: str = "contrib") -> dict[str, Any]:
        """Generate a draft display template from session data."""
        analysis = self.analyse()
        notifications = []
        for char_uuid, stats in analysis.items():
            fields_raw = []
            for b in stats["bytes"]:
                fields_raw.append({
                    "id": f"field_{b['offset']}",
                    "label": f"Field @ offset {b['offset']} (auto)",
                    "type": "raw",
                    "offset": b["offset"],
                    "length": 1,
                    "encoding": "uint8",
                    "display": True,
                    "_re_hint": b["_re_hint"],
                })
            notifications.append({
                "char": char_uuid,
                "description": "Auto-captured (RE scaffold)",
                "views": {
                    "raw": {"fields": fields_raw}
                }
            })

        slug = device_name.lower().replace(" ", "-")
        return {
            "schema_version": 1,
            "id": f"{namespace}.{slug}-display",
            "version": "0.1.0",
            "type": "display",
            "name": f"{device_name} Display (RE scaffold)",
            "author": namespace,
            "_re_session_id": self.session_id,
            "_re_address": self.address,
            "notifications": notifications,
            "reads": [],
        }

    def export_tshark(self) -> dict[str, Any]:
        """Export session as tshark-compatible GATT JSON (GATT layer only)."""
        packets = []
        for char_uuid, samples in self._samples.items():
            for i, value_hex in enumerate(samples):
                packets.append({
                    "_index": f"packets-{len(packets)}",
                    "_source": {
                        "layers": {
                            "btatt": {
                                "btatt.handle": "0x0000",
                                "btatt.uuid128": char_uuid,
                                "btatt.value": value_hex,
                                "_bt_bridge_address": self.address,
                                "_bt_bridge_agent_id": self.agent_id,
                            }
                        }
                    }
                })
        return {
            "_bt_bridge_export": True,
            "_note": "GATT-layer only. For full HCI capture use Android HCI snoop log.",
            "_session_id": self.session_id,
            "_address": self.address,
            "packets": packets,
        }


def _infer_hint(
    offset: int,
    entropy: float,
    min_val: int,
    max_val: int,
    change_count: int,
    total: int,
) -> str:
    hints = []
    if entropy < 0.01:
        hints.append("near-zero entropy — likely static header/padding")
    elif entropy > 6.0:
        hints.append("high entropy — likely sensor reading or counter")
    if change_count == 0:
        hints.append("never changes — static field")
    elif change_count >= total - 1:
        hints.append("changes every sample — likely live sensor data")
    if min_val == 0x55 or min_val == 0xAA:
        hints.append("possible framing byte (0x55/0xAA)")
    if max_val - min_val > 200:
        hints.append(f"wide range {min_val}-{max_val} — likely multi-state or scaled value")
    return "; ".join(hints) if hints else "no strong signal"


class ReSessionStore:
    """In-memory store of active RE sessions keyed by session_id."""

    def __init__(self) -> None:
        self._sessions: dict[str, ReSession] = {}

    def create(self, agent_id: str, address: str) -> ReSession:
        session_id = uuid.uuid4().hex[:12]
        s = ReSession(session_id=session_id, agent_id=agent_id, address=address)
        self._sessions[session_id] = s
        return s

    def get(self, session_id: str) -> ReSession | None:
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
```

- [ ] **Step 4: Run RE session tests**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/test_re_session.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Add RE session REST endpoints to broker/api/routes.py**

Append to `broker/api/routes.py`:
```python

# ---------------------------------------------------------------------------
# RE capture session endpoints
# ---------------------------------------------------------------------------

def _re_store(request: Request):
    store = getattr(request.app.state, "re_store", None)
    if store is None:
        from broker.re_session import ReSessionStore
        request.app.state.re_store = ReSessionStore()
        store = request.app.state.re_store
    return store


class ReStartIn(BaseModel):
    address: str


class ReCaptureIn(BaseModel):
    session_id: str
    samples: int = 20


class ReProbeIn(BaseModel):
    session_id: str
    char: str
    value_hex: str


class ReScaffoldIn(BaseModel):
    session_id: str
    device_name: str = "Unknown"
    namespace: str = "contrib"


class ReSampleIn(BaseModel):
    session_id: str
    char_uuid: str
    value_hex: str


@router.post("/v1/re/session/start", status_code=201)
async def re_start(
    body: ReStartIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    store = _re_store(request)
    session = store.create(agent_id=state.agent_id, address=body.address)
    session.start()
    return {"session_id": session.session_id, "address": body.address, "agent_id": state.agent_id}


@router.post("/v1/re/session/sample")
async def re_add_sample(body: ReSampleIn, request: Request):
    from fastapi import HTTPException
    store = _re_store(request)
    session = store.get(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": f"Session {body.session_id!r} not found"})
    session.add_sample(body.char_uuid, body.value_hex)
    return {"status": "ok", "sample_count": len(session.samples_for(body.char_uuid))}


@router.post("/v1/re/session/analyse")
async def re_analyse(body: dict, request: Request):
    from fastapi import HTTPException
    session_id = body.get("session_id")
    store = _re_store(request)
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": f"Session {session_id!r} not found"})
    return session.analyse()


@router.post("/v1/re/session/scaffold")
async def re_scaffold(body: ReScaffoldIn, request: Request):
    from fastapi import HTTPException
    store = _re_store(request)
    session = store.get(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": f"Session {body.session_id!r} not found"})
    return session.scaffold(device_name=body.device_name, namespace=body.namespace)


@router.get("/v1/re/session/export")
async def re_export(
    request: Request,
    session_id: str = Query(...),
):
    from fastapi import HTTPException
    store = _re_store(request)
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": f"Session {session_id!r} not found"})
    return session.export_tshark()
```

- [ ] **Step 6: Run full test suite**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add broker/re_session.py broker/api/routes.py tests/test_re_session.py
git commit -m "feat(re): RE capture session — analyse, scaffold, tshark export + REST endpoints"
```

---

## Task 6: CI lint script

**Files:**
- Create: `tools/__init__.py` (empty)
- Create: `tools/lint_templates.py`
- Create: `tests/test_lint.py`

- [ ] **Step 1: Write failing lint tests**

`tests/test_lint.py`:
```python
"""Tests for the template CI lint script."""
from __future__ import annotations

import json
import pathlib
import pytest

from tools.lint_templates import lint_directory, LintResult


@pytest.fixture
def tmpdir_path(tmp_path):
    return tmp_path


def write_template(directory, filename, content):
    (directory / filename).write_text(json.dumps(content))


def make_valid_template(tid="contrib.test", ver="1.0.0"):
    return {
        "schema_version": 1,
        "id": tid,
        "version": ver,
        "type": "display",
        "name": "Test"
    }


def test_lint_empty_dir(tmpdir_path):
    result = lint_directory(tmpdir_path)
    assert result.errors == []
    assert result.warnings == []


def test_lint_valid_template(tmpdir_path):
    write_template(tmpdir_path, "t.json", make_valid_template())
    result = lint_directory(tmpdir_path)
    assert result.errors == []


def test_lint_invalid_json(tmpdir_path):
    (tmpdir_path / "bad.json").write_text("not json")
    result = lint_directory(tmpdir_path)
    assert any("JSON" in e for e in result.errors)


def test_lint_missing_id(tmpdir_path):
    t = make_valid_template()
    del t["id"]
    write_template(tmpdir_path, "t.json", t)
    result = lint_directory(tmpdir_path)
    assert any("id" in e.lower() for e in result.errors)


def test_lint_missing_version(tmpdir_path):
    t = make_valid_template()
    del t["version"]
    write_template(tmpdir_path, "t.json", t)
    result = lint_directory(tmpdir_path)
    assert any("version" in e.lower() for e in result.errors)


def test_lint_duplicate_id_version(tmpdir_path):
    write_template(tmpdir_path, "a.json", make_valid_template())
    write_template(tmpdir_path, "b.json", make_valid_template())
    result = lint_directory(tmpdir_path)
    assert any("duplicate" in e.lower() for e in result.errors)


def test_lint_builtin_in_contrib_pr(tmpdir_path):
    t = make_valid_template("builtin.should-fail", "1.0.0")
    write_template(tmpdir_path, "t.json", t)
    # When is_community_pr=True, builtin. templates are rejected
    result = lint_directory(tmpdir_path, is_community_pr=True)
    assert any("builtin" in e.lower() for e in result.errors)


def test_lint_unresolvable_requires(tmpdir_path):
    t = make_valid_template()
    t["requires"] = {"builtin.missing-dep": "^1.0.0"}
    write_template(tmpdir_path, "t.json", t)
    result = lint_directory(tmpdir_path)
    assert any("requires" in e.lower() or "unresolvable" in e.lower() for e in result.errors)


def test_lint_exit_code(tmpdir_path, monkeypatch):
    import sys
    from tools.lint_templates import main
    monkeypatch.setattr(sys, "argv", ["lint_templates", str(tmpdir_path)])
    # Clean dir — should exit 0
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/test_lint.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'tools.lint_templates'`

- [ ] **Step 3: Create tools/__init__.py**

```bash
mkdir -p /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker/tools
touch /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker/tools/__init__.py
```

- [ ] **Step 4: Create tools/lint_templates.py**

```python
"""CI lint script for BT Bridge template files.

Usage:
    python3 tools/lint_templates.py [templates_dir] [--community-pr]

Exit code 0 = clean. Exit code 1 = errors found.
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

SUPPORTED_SCHEMA_VERSIONS = {1}
TEMPLATES_DIR = pathlib.Path(__file__).parent.parent / "templates"


@dataclass
class LintResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def lint_directory(
    directory: pathlib.Path,
    is_community_pr: bool = False,
) -> LintResult:
    result = LintResult()
    seen: dict[tuple[str, str], pathlib.Path] = {}
    templates: list[dict[str, Any]] = []

    for path in sorted(directory.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            result.errors.append(f"{path}: JSON parse error: {exc}")
            continue

        schema_ver = data.get("schema_version")
        if schema_ver not in SUPPORTED_SCHEMA_VERSIONS:
            result.errors.append(
                f"{path}: unsupported schema_version={schema_ver!r} (supported: {SUPPORTED_SCHEMA_VERSIONS})"
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

        # Validate version is valid semver
        try:
            Version(ver)
        except InvalidVersion:
            result.errors.append(f"{path}: invalid semver version {ver!r}")
            continue

        # Community PR gate: builtin. templates are not allowed
        if is_community_pr and tid.startswith("builtin."):
            result.errors.append(
                f"{path}: community PRs may not add or modify builtin. templates"
            )

        # Duplicate detection
        key = (tid, ver)
        if key in seen:
            result.errors.append(
                f"Duplicate template ({tid}, {ver}): {path} conflicts with {seen[key]}"
            )
        else:
            seen[key] = path
            templates.append(data)

    # Resolve all requires entries
    all_ids: dict[str, list[str]] = {}
    for t in templates:
        tid = t["id"]
        ver = t["version"]
        all_ids.setdefault(tid, []).append(ver)

    for t in templates:
        tid = t["id"]
        ver = t["version"]
        requires = t.get("requires", {})
        for dep_id, spec_str in requires.items():
            try:
                spec = SpecifierSet(spec_str, prereleases=True)
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
    else:
        print(f"FAIL: {len(result.errors)} error(s)")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run lint tests**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/test_lint.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 6: Run lint on the actual templates/ directory**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
python3 tools/lint_templates.py templates/
```

Expected: `OK: templates/ — no errors`

- [ ] **Step 7: Commit**

```bash
git add tools/__init__.py tools/lint_templates.py tests/test_lint.py
git commit -m "feat(tools): CI lint script for template files"
```

---

## Task 7: ~~Shared GATT component templates~~ → moved to the catalog repo

> **This task is intentionally removed.** Under the catalog-only model the broker ships no
> templates. The Battery Service and Device Information GATT component templates now live in the
> **`bt-bridge-templates`** catalog repo at `catalog/builtin/shared/`, validated by that repo's
> lint + index CI. They are fetched on demand via **Plan 4: Catalog Integration**. Nothing is
> created in the broker repo for this task — proceed to Task 8.

<details>
<summary>Historical: the component template JSON (now in the catalog repo)</summary>

**Do not create these in the broker repo.** Canonical versions:
`bt-bridge-templates/catalog/builtin/shared/display.battery-service.json` and
`.../display.device-information.json`.

```json
{
  "schema_version": 1,
  "id": "builtin.battery-service-display",
  "version": "1.0.0",
  "type": "component",
  "name": "Battery Service (GATT standard)",
  "description": "Standard GATT Battery Service — UUID 0x180F",
  "reads": [
    {
      "char": "00002a19-0000-1000-8000-00805f9b34fb",
      "description": "Battery Level (0-100%)",
      "views": {
        "raw": {
          "fields": [
            {
              "id": "battery_raw",
              "label": "Battery Level (raw)",
              "type": "raw",
              "offset": 0,
              "length": 1,
              "encoding": "uint8",
              "display": true
            }
          ]
        },
        "metric": {
          "fields": [
            {
              "id": "battery_pct",
              "label": "Battery",
              "type": "scale_offset",
              "offset": 0,
              "length": 1,
              "encoding": "uint8",
              "scale": 1.0,
              "offset_value": 0.0,
              "unit": "%",
              "precision": 0,
              "display": true
            }
          ]
        }
      }
    }
  ],
  "notifications": []
}
```

- [ ] **Step 2: Create templates/shared/display.device-information.json**

```json
{
  "schema_version": 1,
  "id": "builtin.device-information-display",
  "version": "1.0.0",
  "type": "component",
  "name": "Device Information Service (GATT standard)",
  "description": "Standard GATT Device Information Service — UUID 0x180A",
  "reads": [
    {
      "char": "00002a29-0000-1000-8000-00805f9b34fb",
      "description": "Manufacturer Name String",
      "views": {
        "raw": {
          "fields": [
            {
              "id": "manufacturer_name",
              "label": "Manufacturer",
              "type": "raw",
              "offset": 0,
              "length": 64,
              "encoding": "utf8",
              "display": true
            }
          ]
        }
      }
    },
    {
      "char": "00002a24-0000-1000-8000-00805f9b34fb",
      "description": "Model Number String",
      "views": {
        "raw": {
          "fields": [
            {
              "id": "model_number",
              "label": "Model",
              "type": "raw",
              "offset": 0,
              "length": 64,
              "encoding": "utf8",
              "display": true
            }
          ]
        }
      }
    },
    {
      "char": "00002a26-0000-1000-8000-00805f9b34fb",
      "description": "Firmware Revision String",
      "views": {
        "raw": {
          "fields": [
            {
              "id": "firmware_revision",
              "label": "Firmware",
              "type": "raw",
              "offset": 0,
              "length": 64,
              "encoding": "utf8",
              "display": true
            }
          ]
        }
      }
    }
  ],
  "notifications": []
}
```

</details>

> The catalog repo's own CI (`tools/lint_templates.py` + `tools/build_index.py --check`) validates
> these component templates. The broker's `tools/lint_templates.py` (Task 6) is still built — it is
> used to lint any templates fetched into the broker's local `templates/` dir, and is the shared
> lint logic the catalog repo also runs.

---

## Task 8: PROTOCOL.md v1.2 update

**Files:**
- Modify: `PROTOCOL.md`

- [ ] **Step 1: Read current PROTOCOL.md to find where to insert v1.2 additions**

Read `PROTOCOL.md` and locate the end of the command/event tables.

- [ ] **Step 2: Add v1.2 template protocol additions**

Find the section near the end of PROTOCOL.md documenting commands and add:

```markdown
---

## Protocol v1.2 — Template System Additions

These additions are backward-compatible. Agents that do not implement template handling
ignore the new commands; the broker handles `template_request` and `view_changed` events
transparently.

### New Broker → Agent Commands

#### `push_templates`
Sent immediately after `register`. Lists all available templates on the broker.
```json
{"cmd": "push_templates", "manifest": [
  {"id": "builtin.weatherflow-tactical-display", "version": "1.0.0"},
  {"id": "builtin.niimbot-label-printer-device", "version": "1.0.0"}
]}
```

#### `template_data`
Full template JSON sent in response to a `template_request`.
```json
{"cmd": "template_data", "id": "builtin.weatherflow-tactical-display", "version": "1.0.0", "content": { ... }}
```

#### `apply_template`
Instructs the agent to activate a specific device template and variant for a connected device.
```json
{"cmd": "apply_template", "address": "AA:BB:CC:DD:EE:FF", "device_template_id": "builtin.niimbot-label-printer-device", "version": "1.0.0", "variant_id": "b1-issc"}
```
`variant_id` may be `null` if the device template has no variants.

#### `set_view`
Changes the active display view for a connected device.
```json
{"cmd": "set_view", "address": "AA:BB:CC:DD:EE:FF", "view": "imperial"}
```

### New Agent → Broker Events

#### `template_request`
Agent requests full template content for templates newer than its local cache.
```json
{"event": "template_request", "ids": [
  {"id": "builtin.weatherflow-tactical-display", "version": "1.0.0"}
]}
```

#### `template_applied`
Agent confirms a template has been loaded and activated.
```json
{"event": "template_applied", "address": "AA:BB:CC:DD:EE:FF", "device_template_id": "builtin.niimbot-label-printer-device", "version": "1.0.0", "variant_id": "b1-issc", "ts": 1700000000000}
```

#### `view_changed`
User changed the active display view in the agent UI.
```json
{"event": "view_changed", "address": "AA:BB:CC:DD:EE:FF", "view": "imperial", "ts": 1700000000000}
```
```

- [ ] **Step 3: Commit**

```bash
git add PROTOCOL.md
git commit -m "docs: PROTOCOL.md v1.2 — template push/request/apply/view protocol additions"
```

---

## Task 9: Final integration and cleanup

- [ ] **Step 1: Run full test suite**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/ -v --tb=short
```

Expected: all tests PASS.

- [ ] **Step 2: Run lint on templates/**

```bash
python3 tools/lint_templates.py templates/
```

Expected: `OK: templates/ — no errors`. Under the catalog-only model the broker's `templates/`
dir is empty on a fresh checkout (fetched content is gitignored), so the lint trivially passes
with nothing to check. To exercise the lint against real templates, fetch some from the catalog
first (Plan 4) or point it at the catalog repo: `python3 tools/lint_templates.py ../bt-bridge-templates/catalog/`.

- [ ] **Step 3: Start broker, confirm Swagger UI lists all new endpoints**

```bash
timeout 5 python3 -m broker.main --debug 2>&1 &
sleep 2
curl -s http://localhost:2673/openapi.json | python3 -c "import sys,json; paths=json.load(sys.stdin)['paths']; [print(p) for p in sorted(paths)]"
kill %1 2>/dev/null || true
```

Expected: output includes `/v1/templates`, `/v1/templates/match`, `/v1/templates/{template_id}`, `/v1/re/session/start`, etc.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: template system complete — broker-side (Plan 2)"
```

---

## Post-Plan Notes

- Workflow template execution is **out of scope for v1.0** — schema reserved, `workflow_template` field in device templates is valid but ignored at runtime.
- Template component merging (the `includes` array) is declared in the design but not implemented in this plan — the broker stores and serves component templates; agent-side merging is covered in Plan 3.
- Android template runtime (persistent storage, field rendering, view selection, GATT analyser fallback) is covered in **Plan 3 (Android Template Runtime)**.
