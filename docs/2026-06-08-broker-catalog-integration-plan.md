# BT Bridge Broker — Catalog Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Commit workflow (FOSS).** The `bt-bridge-*` repos are governed as open-source projects, not
> under the CBB app SDLC. The per-task `git commit` steps use **Conventional Commits**
> (`type(scope): subject`) and are the intended granularity — one focused commit per task, made
> after that task's tests pass. This is the standard FOSS commit-as-you-go flow; the CBB "ask
> before every commit" gate does not apply here. Pushing and opening PRs remain explicit actions.

**Goal:** Give the broker a way to populate its local `templates/` directory **on demand** from the
remote **`bt-bridge-templates`** catalog repository, with two front ends — a CLI helper and a web
selection page — both driven by the same catalog index and install logic. The broker ships **no**
built-in templates; everything is fetched.

**Architecture:** `broker/catalog.py` holds a `CatalogClient` that fetches the remote
`catalog/index.json`, resolves selections (with semver + dependency closure), downloads template
files, verifies their `sha256`, and writes them into `templates/`. `tools/fetch_templates.py` is a
thin CLI over `CatalogClient`. New `/v1/templates/catalog`, `/v1/templates/catalog/install`, and a
static selection page expose the same logic over HTTP. After any install, the broker reloads its
`TemplateRegistry` (`POST /v1/templates/reload` logic) so newly fetched templates take effect.

**Tech Stack:** Python 3.11+, FastAPI (existing), `httpx` (already a dev dep; promoted to runtime
for the catalog client), `packaging` (semver, from Plan 2), pytest, `respx` (httpx mock for tests).

**Prerequisites:** Plan 1 (broker rewrite) and Plan 2 (template system) complete. The
`bt-bridge-templates` repo exists with a generated `catalog/index.json`.

**Design references:**
- `docs/2026-06-08-template-system-design.md` (§11 Broker Template Registry)
- `bt-bridge-templates/docs/TEMPLATE_FORMAT.md` (catalog/index format)

---

## Catalog index contract

The broker depends on the catalog repo's `catalog/index.json` shape. Treat this as the integration
contract (validated in `bt-bridge-templates` CI by `tools/build_index.py --check`):

```json
{
  "index_format_version": 1,
  "count": 6,
  "templates": [
    {
      "id": "builtin.weatherflow-tactical-display",
      "version": "1.0.0",
      "type": "display",
      "name": "WeatherFlow Tactical Display",
      "description": "...",
      "author": "builtin",
      "namespace": "builtin",
      "path": "catalog/builtin/weatherflow-tactical/display-v1.json",
      "sha256": "<hex>",
      "requires": {}
    }
  ]
}
```

**Source URLs** (configurable; defaults assume the private repo is reachable via an authenticated
raw URL or a published release asset):

- Index:    `${CATALOG_BASE_URL}/catalog/index.json`
- Template: `${CATALOG_BASE_URL}/<entry.path>`

`CATALOG_BASE_URL` defaults to the repo's raw content base and is overridable via the `BT_CATALOG_BASE_URL`
env var / `--catalog-url` CLI flag (so a local clone, a mirror, or a release tag can be substituted).

> **Private-repo access.** `bt-bridge-templates` is private. Fetching raw content requires auth —
> a GitHub token (`BT_CATALOG_TOKEN`, sent as `Authorization: Bearer …`) or a locally cloned path
> via `--catalog-url file://…`. The client must support both and fail with a clear message if a
> private URL returns 404/401 without a token.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `broker/catalog.py` | `CatalogClient`: fetch index, resolve, download, verify, write to `templates/` |
| Create | `tools/fetch_templates.py` | CLI over `CatalogClient` (list / search / install) |
| Modify | `broker/api/routes.py` | Add `/v1/templates/catalog`, `/v1/templates/catalog/install` |
| Modify | `broker/api/app.py` | Mount static selection page at `/templates/select` |
| Create | `broker/static/templates_select.html` | Web selection page (browse + install) |
| Modify | `requirements.txt` | Promote `httpx` to runtime (catalog client uses it) |
| Modify | `requirements-dev.txt` | Add `respx` (httpx mock for tests) |
| Create | `tests/test_catalog.py` | Unit tests for `CatalogClient` (mocked HTTP) |
| Create | `tests/test_catalog_api.py` | Integration tests for catalog REST endpoints |
| Create | `tests/fixtures/catalog_index.json` | Sample index for tests |

---

## Task 1: Dependencies

**Files:**
- Modify: `requirements.txt`, `requirements-dev.txt`

- [ ] **Step 1: Promote httpx to runtime**

`httpx` was a dev-only dep (test client). The catalog client uses it at runtime — move it to
`requirements.txt`:

```text
# add to requirements.txt (runtime)
httpx>=0.27.0
```

Remove the duplicate `httpx>=0.27.0` line from `requirements-dev.txt` (it's pulled in via
`-r requirements.txt`). Add the test mock:

```text
# add to requirements-dev.txt
respx>=0.21.0
```

- [ ] **Step 2: Install and re-lock**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pip install -r requirements-dev.txt
pip freeze > requirements-lock.txt
```

- [ ] **Step 3: Commit**

```bash
git add requirements.txt requirements-dev.txt requirements-lock.txt
git commit -m "chore: promote httpx to runtime, add respx for catalog tests"
```

---

## Task 2: CatalogClient — fetch and parse index

**Files:**
- Create: `broker/catalog.py`
- Create: `tests/fixtures/catalog_index.json`
- Create: `tests/test_catalog.py`

- [ ] **Step 1: Create the test fixture**

`tests/fixtures/catalog_index.json` — a minimal two-template index (one with a `requires`):
```json
{
  "index_format_version": 1,
  "count": 2,
  "templates": [
    {
      "id": "builtin.example-display", "version": "1.0.0", "type": "display",
      "name": "Example Display", "description": "x", "author": "builtin",
      "namespace": "builtin", "path": "catalog/builtin/example/display.json",
      "sha256": "REPLACE_IN_TEST", "requires": {}
    },
    {
      "id": "builtin.example-device", "version": "1.0.0", "type": "device",
      "name": "Example Device", "description": "x", "author": "builtin",
      "namespace": "builtin", "path": "catalog/builtin/example/device.json",
      "sha256": "REPLACE_IN_TEST",
      "requires": {"builtin.example-display": "^1.0.0"}
    }
  ]
}
```

- [ ] **Step 2: Write failing tests for index fetch + selection resolution**

`tests/test_catalog.py` (uses `respx` to mock the HTTP layer; for `file://` it reads disk):
```python
"""Unit tests for CatalogClient."""
from __future__ import annotations

import hashlib
import json
import pathlib
import pytest

from broker.catalog import CatalogClient, CatalogError


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture
def fake_catalog(tmp_path):
    """Build a real on-disk catalog so file:// fetch works end to end."""
    root = tmp_path / "catalog"
    (root / "builtin" / "example").mkdir(parents=True)
    display = {"schema_version": 1, "id": "builtin.example-display", "version": "1.0.0",
               "type": "display", "name": "Example Display", "notifications": [], "reads": []}
    device = {"schema_version": 1, "id": "builtin.example-device", "version": "1.0.0",
              "type": "device", "name": "Example Device",
              "signature": {"service_uuids": ["0000abcd-0000-1000-8000-00805f9b34fb"]},
              "requires": {"builtin.example-display": "^1.0.0"}}
    dpath = root / "builtin" / "example" / "display.json"
    vpath = root / "builtin" / "example" / "device.json"
    dpath.write_text(json.dumps(display))
    vpath.write_text(json.dumps(device))
    index = {
        "index_format_version": 1, "count": 2,
        "templates": [
            {"id": "builtin.example-display", "version": "1.0.0", "type": "display",
             "name": "Example Display", "author": "builtin", "namespace": "builtin",
             "path": "catalog/builtin/example/display.json",
             "sha256": _sha(dpath.read_bytes()), "requires": {}},
            {"id": "builtin.example-device", "version": "1.0.0", "type": "device",
             "name": "Example Device", "author": "builtin", "namespace": "builtin",
             "path": "catalog/builtin/example/device.json",
             "sha256": _sha(vpath.read_bytes()),
             "requires": {"builtin.example-display": "^1.0.0"}},
        ],
    }
    (root / "index.json").write_text(json.dumps(index))
    return tmp_path  # base url = file://{tmp_path}


@pytest.fixture
def client(fake_catalog):
    return CatalogClient(base_url=f"file://{fake_catalog}")


def test_fetch_index_lists_templates(client):
    index = client.fetch_index()
    ids = {t["id"] for t in index["templates"]}
    assert ids == {"builtin.example-display", "builtin.example-device"}


def test_resolve_selection_pulls_dependencies(client):
    # Selecting only the device must pull its display dependency too.
    resolved = client.resolve_selection(["builtin.example-device"])
    ids = {e["id"] for e in resolved}
    assert "builtin.example-device" in ids
    assert "builtin.example-display" in ids


def test_resolve_unknown_id_raises(client):
    with pytest.raises(CatalogError):
        client.resolve_selection(["builtin.does-not-exist"])


def test_install_writes_and_verifies(client, tmp_path):
    dest = tmp_path / "templates"
    written = client.install(["builtin.example-device"], dest_dir=dest)
    # Both device and dependency written
    assert (dest).exists()
    files = list(dest.rglob("*.json"))
    assert len(files) == 2


def test_install_detects_sha_mismatch(client, tmp_path, monkeypatch):
    # Corrupt the expected sha in the index after fetch → install must refuse.
    orig = client.fetch_index
    def tampered():
        idx = orig()
        idx["templates"][0]["sha256"] = "0" * 64
        return idx
    monkeypatch.setattr(client, "fetch_index", tampered)
    with pytest.raises(CatalogError, match="checksum"):
        client.install(["builtin.example-display"], dest_dir=tmp_path / "t")
```

- [ ] **Step 3: Run tests — expect ImportError**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/test_catalog.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'broker.catalog'`.

- [ ] **Step 4: Create broker/catalog.py**

```python
"""CatalogClient — fetch templates on demand from the bt-bridge-templates catalog.

Supports https(+token) and file:// base URLs. Resolves a user selection to its full
dependency closure, downloads each template, verifies its sha256 against the index, and
writes the files into the broker's templates/ directory. No template is ever loaded from
the network without a matching checksum in the signed index.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any
from urllib.parse import urlparse

import httpx
from packaging.specifiers import SpecifierSet
from packaging.version import Version


class CatalogError(RuntimeError):
    """Raised on any catalog fetch / resolve / verify failure."""


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
            p = pathlib.Path(parsed.path)
            if not p.exists():
                raise CatalogError(f"catalog file not found: {p}")
            return p.read_bytes()
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
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CatalogError(f"catalog index is not valid JSON: {exc}") from exc

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
                raise CatalogError(f"template not in catalog: {tid!r}")
            entry = self._highest(by_id[tid])
            resolved[tid] = entry
            for dep_id, spec_str in (entry.get("requires") or {}).items():
                if dep_id not in by_id:
                    raise CatalogError(
                        f"{tid} requires {dep_id} which is not in the catalog")
                # ensure a satisfying version exists; add to queue for closure
                self._highest(by_id[dep_id], SpecifierSet(spec_str, prereleases=True))
                queue.append(dep_id)
        return list(resolved.values())

    # ---- install --------------------------------------------------------

    def install(self, ids: list[str], dest_dir: pathlib.Path,
                index: dict[str, Any] | None = None) -> list[pathlib.Path]:
        """Download resolved templates into dest_dir, verifying each sha256."""
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
```

> **Security note (path traversal).** Template files are written under `dest_dir` using a name
> derived from the *index entry's id+version*, never the raw `path` from the index — a malicious
> index cannot write outside `templates/`. The `sha256` check rejects any tampered file.

- [ ] **Step 5: Run catalog tests**

```bash
pytest tests/test_catalog.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add broker/catalog.py tests/test_catalog.py tests/fixtures/catalog_index.json
git commit -m "feat(catalog): CatalogClient — fetch, resolve deps, verify sha256, install"
```

---

## Task 3: CLI helper — tools/fetch_templates.py

**Files:**
- Create: `tools/fetch_templates.py`

- [ ] **Step 1: Create the CLI**

```python
#!/usr/bin/env python3
"""Fetch BT Bridge templates from the catalog into the broker's templates/ dir.

Examples:
    python3 tools/fetch_templates.py list
    python3 tools/fetch_templates.py search weatherflow
    python3 tools/fetch_templates.py install builtin.weatherflow-tactical-device
    python3 tools/fetch_templates.py install --all-builtin

Configuration:
    --catalog-url URL   override base URL (default: GitHub raw; or file://<path>)
    BT_CATALOG_BASE_URL env var (same as --catalog-url)
    BT_CATALOG_TOKEN    env var: GitHub token for the private repo
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

from broker.catalog import CatalogClient, CatalogError, DEFAULT_BASE_URL

TEMPLATES_DIR = pathlib.Path(__file__).resolve().parent.parent / "templates"


def _client(args) -> CatalogClient:
    base = args.catalog_url or os.environ.get("BT_CATALOG_BASE_URL") or DEFAULT_BASE_URL
    token = os.environ.get("BT_CATALOG_TOKEN")
    return CatalogClient(base_url=base, token=token)


def main() -> None:
    p = argparse.ArgumentParser(description="Fetch BT Bridge templates from the catalog.")
    p.add_argument("--catalog-url", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("search"); s.add_argument("query")
    i = sub.add_parser("install")
    i.add_argument("ids", nargs="*")
    i.add_argument("--all-builtin", action="store_true")
    args = p.parse_args()

    client = _client(args)
    try:
        index = client.fetch_index()
    except CatalogError as exc:
        print(f"ERROR: {exc}", file=sys.stderr); sys.exit(1)

    if args.cmd == "list":
        for e in sorted(index["templates"], key=lambda x: x["id"]):
            print(f"{e['id']:50s} {e['version']:10s} {e.get('type','?'):10s} {e.get('name','')}")
    elif args.cmd == "search":
        q = args.query.lower()
        for e in index["templates"]:
            blob = f"{e['id']} {e.get('name','')} {e.get('description','')}".lower()
            if q in blob:
                print(f"{e['id']:50s} {e['version']:10s} {e.get('name','')}")
    elif args.cmd == "install":
        ids = list(args.ids)
        if args.all_builtin:
            ids += [e["id"] for e in index["templates"] if e.get("namespace") == "builtin"]
        if not ids:
            print("ERROR: nothing to install (give IDs or --all-builtin)", file=sys.stderr)
            sys.exit(1)
        try:
            written = client.install(ids, dest_dir=TEMPLATES_DIR, index=index)
        except CatalogError as exc:
            print(f"ERROR: {exc}", file=sys.stderr); sys.exit(1)
        print(f"Installed {len(written)} template(s) into {TEMPLATES_DIR}:")
        for w in written:
            print(f"  {w.name}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Manual smoke test against the catalog repo via file://**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
python3 tools/fetch_templates.py --catalog-url "file://$(cd ../bt-bridge-templates && pwd)" list
```

Expected: lists the catalog's templates (WeatherFlow, Niimbot, shared components).

- [ ] **Step 3: Commit**

```bash
git add tools/fetch_templates.py
git commit -m "feat(catalog): fetch_templates.py CLI — list, search, install"
```

---

## Task 4: Catalog REST endpoints

**Files:**
- Modify: `broker/api/routes.py`
- Create: `tests/test_catalog_api.py`

- [ ] **Step 1: Write failing tests**

`tests/test_catalog_api.py`:
```python
"""Integration tests for catalog REST endpoints (mocked CatalogClient)."""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from broker.registry import AgentRegistry
from broker.api.app import create_app


@pytest.fixture
def registry():
    return AgentRegistry()


@pytest_asyncio.fixture
async def client(registry, monkeypatch, tmp_path):
    app = create_app(registry)

    # Stub the catalog client used by the routes with a fake.
    class FakeCatalog:
        def fetch_index(self):
            return {"index_format_version": 1, "count": 1, "templates": [
                {"id": "builtin.x-display", "version": "1.0.0", "type": "display",
                 "name": "X", "namespace": "builtin", "path": "catalog/x.json",
                 "sha256": "deadbeef", "requires": {}}]}
        def install(self, ids, dest_dir, index=None):
            return [tmp_path / f"{i}.json" for i in ids]

    app.state.catalog_client = FakeCatalog()
    app.state.templates_dir = tmp_path
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_catalog_list(client):
    resp = await client.get("/v1/templates/catalog")
    assert resp.status_code == 200
    assert resp.json()["templates"][0]["id"] == "builtin.x-display"


@pytest.mark.asyncio
async def test_catalog_install(client):
    resp = await client.post("/v1/templates/catalog/install",
                             json={"ids": ["builtin.x-display"]})
    assert resp.status_code == 200
    assert resp.json()["installed"] == 1
```

- [ ] **Step 2: Add the routes to broker/api/routes.py**

Append (note: declare `/v1/templates/catalog` and `/v1/templates/catalog/install` **before**
`/v1/templates/{template_id}` — same shadowing hazard as `/match`; the Task 4 route-ordering
guard test in Plan 2 should be extended to cover `catalog` too):
```python

# ---------------------------------------------------------------------------
# Catalog (remote template fetch) endpoints
# ---------------------------------------------------------------------------

def _catalog_client(request: Request):
    from fastapi import HTTPException
    cc = getattr(request.app.state, "catalog_client", None)
    if cc is None:
        from broker.catalog import CatalogClient
        request.app.state.catalog_client = CatalogClient()
        cc = request.app.state.catalog_client
    return cc


def _templates_dir(request: Request):
    import pathlib
    d = getattr(request.app.state, "templates_dir", None)
    return pathlib.Path(d) if d else pathlib.Path("templates")


@router.get("/v1/templates/catalog")
async def catalog_list(request: Request):
    from fastapi import HTTPException
    from broker.catalog import CatalogError
    cc = _catalog_client(request)
    try:
        return cc.fetch_index()
    except CatalogError as exc:
        raise HTTPException(status_code=502, detail={"error": "catalog_error", "message": str(exc)})


class CatalogInstallIn(BaseModel):
    ids: list[str]


@router.post("/v1/templates/catalog/install")
async def catalog_install(body: CatalogInstallIn, request: Request):
    from fastapi import HTTPException
    from broker.catalog import CatalogError
    cc = _catalog_client(request)
    dest = _templates_dir(request)
    try:
        written = cc.install(body.ids, dest_dir=dest)
    except CatalogError as exc:
        raise HTTPException(status_code=502, detail={"error": "catalog_error", "message": str(exc)})
    # Reload the registry so newly installed templates take effect immediately.
    tr = getattr(request.app.state, "template_registry", None)
    if tr is not None:
        tr.load()
    return {"installed": len(written), "files": [p.name for p in written]}
```

- [ ] **Step 3: Extend the route-ordering guard (from Plan 2 Task 4)**

In `tests/test_template_api.py`, extend `test_match_route_declared_before_template_id` (or add a
sibling) to assert `/v1/templates/catalog` and `/v1/templates/catalog/install` are declared before
`/v1/templates/{template_id}`.

- [ ] **Step 4: Run catalog API tests**

```bash
pytest tests/test_catalog_api.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add broker/api/routes.py tests/test_catalog_api.py tests/test_template_api.py
git commit -m "feat(api): /v1/templates/catalog list + install endpoints with registry reload"
```

---

## Task 5: Web selection page

**Files:**
- Create: `broker/static/templates_select.html`
- Modify: `broker/api/app.py`

- [ ] **Step 1: Create the selection page**

A single self-contained HTML page (no build step) that calls `/v1/templates/catalog` to list,
lets the user check templates, and POSTs to `/v1/templates/catalog/install`. Keep it dependency-free
(vanilla JS, fetch). `broker/static/templates_select.html`:
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BT Bridge — Template Catalog</title>
  <style>
    body { font: 14px system-ui, sans-serif; margin: 2rem; max-width: 60rem; }
    h1 { font-size: 1.4rem; }
    table { border-collapse: collapse; width: 100%; }
    th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #ddd; }
    .muted { color: #666; }
    button { padding: 8px 16px; font-size: 14px; cursor: pointer; }
    #status { margin-top: 1rem; }
  </style>
</head>
<body>
  <h1>BT Bridge Template Catalog</h1>
  <p class="muted">Select templates to install into this broker. Dependencies are pulled in automatically.</p>
  <p><input id="filter" placeholder="Filter…" oninput="render()"></p>
  <table>
    <thead><tr><th></th><th>ID</th><th>Version</th><th>Type</th><th>Name</th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
  <p><button onclick="install()">Install selected</button></p>
  <div id="status"></div>
  <script>
    let templates = [];
    async function load() {
      const r = await fetch('/v1/templates/catalog');
      if (!r.ok) { status('Failed to load catalog: ' + r.status, true); return; }
      templates = (await r.json()).templates || [];
      render();
    }
    function render() {
      const q = document.getElementById('filter').value.toLowerCase();
      const rows = document.getElementById('rows');
      rows.innerHTML = '';
      for (const t of templates) {
        const blob = (t.id + ' ' + (t.name||'') + ' ' + (t.description||'')).toLowerCase();
        if (q && !blob.includes(q)) continue;
        const tr = document.createElement('tr');
        tr.innerHTML = `<td><input type="checkbox" value="${t.id}"></td>
          <td><code>${t.id}</code></td><td>${t.version}</td>
          <td>${t.type||''}</td><td>${t.name||''}</td>`;
        rows.appendChild(tr);
      }
    }
    function status(msg, err) {
      const d = document.getElementById('status');
      d.textContent = msg; d.style.color = err ? '#b00' : '#070';
    }
    async function install() {
      const ids = [...document.querySelectorAll('#rows input:checked')].map(c => c.value);
      if (!ids.length) { status('Select at least one template.', true); return; }
      status('Installing…');
      const r = await fetch('/v1/templates/catalog/install', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ ids })
      });
      const body = await r.json();
      if (!r.ok) { status('Install failed: ' + (body.message || r.status), true); return; }
      status(`Installed ${body.installed} template(s): ${(body.files||[]).join(', ')}`);
    }
    load();
  </script>
</body>
</html>
```

- [ ] **Step 2: Mount static files in broker/api/app.py**

In `create_app`, after the routers are included:
```python
    import pathlib
    from fastapi.staticfiles import StaticFiles
    static_dir = pathlib.Path(__file__).parent.parent / "static"
    if static_dir.exists():
        app.mount("/templates-ui", StaticFiles(directory=str(static_dir), html=True), name="static")
```

The selection page is then served at `http://localhost:2673/templates-ui/templates_select.html`.

> Keep the API route prefix `/v1/templates/...` and the static mount `/templates-ui/...` distinct so
> the static mount never shadows the REST routes.

- [ ] **Step 3: Manual smoke test**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
BT_CATALOG_BASE_URL="file://$(cd ../bt-bridge-templates && pwd)" timeout 5 python3 -m broker.main --debug &
sleep 2
curl -s http://localhost:2673/v1/templates/catalog | python3 -c "import sys,json; print('catalog templates:', json.load(sys.stdin)['count'])"
curl -s -o /dev/null -w "select page: %{http_code}\n" http://localhost:2673/templates-ui/templates_select.html
kill %1 2>/dev/null || true
```

Expected: catalog count > 0, select page `200`.

- [ ] **Step 4: Commit**

```bash
git add broker/static/templates_select.html broker/api/app.py
git commit -m "feat(catalog): web template selection page served at /templates-ui"
```

---

## Task 6: Wire catalog config into main.py and final integration

**Files:**
- Modify: `broker/main.py`

- [ ] **Step 1: Add catalog settings**

In `Settings` (pydantic-settings, `env_prefix="BT_"`), add:
```python
    catalog_base_url: str | None = None   # None → CatalogClient default
    catalog_token: str | None = None
```

In the lifespan, construct the catalog client and attach it + the templates dir to app.state:
```python
    from broker.catalog import CatalogClient, DEFAULT_BASE_URL
    app.state.catalog_client = CatalogClient(
        base_url=settings.catalog_base_url or DEFAULT_BASE_URL,
        token=settings.catalog_token,
    )
    app.state.templates_dir = (pathlib.Path(__file__).parent.parent / "templates")
```

- [ ] **Step 2: Full suite + lint**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 3: End-to-end smoke (file:// catalog)**

```bash
BT_CATALOG_BASE_URL="file://$(cd ../bt-bridge-templates && pwd)" timeout 8 python3 -m broker.main --debug &
sleep 2
# install the WeatherFlow device (+ its display dependency) via REST
curl -s -X POST http://localhost:2673/v1/templates/catalog/install \
  -H 'Content-Type: application/json' \
  -d '{"ids":["builtin.weatherflow-tactical-device"]}'
echo
# confirm the registry now lists them
curl -s http://localhost:2673/v1/templates | python3 -c "import sys,json; print('loaded:', len(json.load(sys.stdin)))"
kill %1 2>/dev/null || true
```

Expected: install reports `"installed": 2` (device + display dependency); `/v1/templates` then
lists 2.

- [ ] **Step 4: Commit**

```bash
git add broker/main.py
git commit -m "feat(catalog): wire catalog client + templates dir into lifespan config"
```

---

## Post-Plan Notes

- **Private-repo auth in production.** `bt-bridge-templates` is private; the default GitHub raw URL
  requires `BT_CATALOG_TOKEN`. For a fully offline broker, point `BT_CATALOG_BASE_URL` at a local
  clone (`file://…`) or a vendored mirror. When/if the catalog repo is made public, the token
  becomes optional.
- **Signed index (future).** The `sha256` per entry protects file integrity, but the index itself is
  fetched over TLS only. A future hardening step could sign `index.json` (e.g. minisign) and verify
  the signature before trusting any hash.
- **Catalog caching.** This plan fetches the index on each catalog call. A short-TTL cache is a
  reasonable follow-on once usage patterns are known.
- **iOS agent.** The catalog model is broker-side; the iOS agent (when built) consumes templates the
  same way the Android agent does (push/request/apply), unaffected by where the broker sourced them.
