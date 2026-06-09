"""Integration tests for catalog REST endpoints (stubbed CatalogClient)."""
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
async def client(registry, tmp_path):
    app = create_app(registry)

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


@pytest.mark.asyncio
async def test_catalog_list_error_502(registry, tmp_path):
    # A CatalogClient whose fetch_index raises CatalogError → 502.
    from broker.api.app import create_app
    from broker.catalog import CatalogError
    app = create_app(registry)

    class BrokenCatalog:
        def fetch_index(self):
            raise CatalogError("catalog fetch 404 for ... (private repo — set BT_CATALOG_TOKEN?)")
        def install(self, ids, dest_dir, index=None):
            raise CatalogError("nope")

    app.state.catalog_client = BrokenCatalog()
    app.state.templates_dir = tmp_path
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/v1/templates/catalog")
        assert resp.status_code == 502
        assert resp.json()["error"] == "catalog_error"


@pytest.mark.asyncio
async def test_catalog_install_resolve_error_422(registry, tmp_path):
    """An unknown/unresolvable template id is a client error → 422, not 502."""
    from broker.api.app import create_app
    from broker.catalog import CatalogResolveError
    app = create_app(registry)

    class ResolveFailCatalog:
        def fetch_index(self):
            return {"index_format_version": 1, "count": 0, "templates": []}
        def install(self, ids, dest_dir, index=None):
            raise CatalogResolveError("template not in catalog: 'builtin.nope'")

    app.state.catalog_client = ResolveFailCatalog()
    app.state.templates_dir = tmp_path
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/v1/templates/catalog/install", json={"ids": ["builtin.nope"]})
        assert resp.status_code == 422
        assert resp.json()["error"] == "invalid_selection"


@pytest.mark.asyncio
async def test_catalog_install_upstream_error_502(registry, tmp_path):
    """An upstream/transport failure during install → 502."""
    from broker.api.app import create_app
    from broker.catalog import CatalogError
    app = create_app(registry)

    class FetchFailCatalog:
        def fetch_index(self):
            return {"index_format_version": 1, "count": 0, "templates": []}
        def install(self, ids, dest_dir, index=None):
            raise CatalogError("catalog fetch 404 for ...")

    app.state.catalog_client = FetchFailCatalog()
    app.state.templates_dir = tmp_path
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/v1/templates/catalog/install", json={"ids": ["x"]})
        assert resp.status_code == 502
        assert resp.json()["error"] == "catalog_error"


@pytest.mark.asyncio
async def test_catalog_install_reload_reflects_disk(registry, tmp_path):
    """End-to-end: installing a real template via a file:// catalog makes it appear
    in /v1/templates after the post-install reload."""
    import hashlib, json
    from broker.api.app import create_app
    from broker.catalog import CatalogClient
    from broker.template_registry import TemplateRegistry

    # Build a real on-disk file:// catalog with one display template.
    catroot = tmp_path / "cat"
    (catroot / "catalog" / "builtin").mkdir(parents=True)
    tmpl = {"schema_version": 1, "id": "builtin.demo-display", "version": "1.0.0",
            "type": "display", "name": "Demo Display", "notifications": [], "reads": []}
    tfile = catroot / "catalog" / "builtin" / "demo.json"
    tfile.write_text(json.dumps(tmpl))
    sha = hashlib.sha256(tfile.read_bytes()).hexdigest()
    index = {"index_format_version": 1, "count": 1, "templates": [
        {"id": "builtin.demo-display", "version": "1.0.0", "type": "display", "name": "Demo Display",
         "namespace": "builtin", "path": "catalog/builtin/demo.json", "sha256": sha, "requires": {}}]}
    (catroot / "catalog" / "index.json").write_text(json.dumps(index))

    # Broker templates dir (initially empty) + a registry pointed at it.
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    tr = TemplateRegistry(templates_dir=templates_dir)
    tr.load()
    assert tr.list_all() == []

    app = create_app(registry)
    app.state.template_registry = tr
    app.state.templates_dir = templates_dir
    app.state.catalog_client = CatalogClient(base_url=f"file://{catroot}")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Before install: /v1/templates is empty.
        resp = await c.get("/v1/templates")
        assert resp.json() == []
        # Install from the catalog.
        resp = await c.post("/v1/templates/catalog/install", json={"ids": ["builtin.demo-display"]})
        assert resp.status_code == 200
        assert resp.json()["installed"] == 1
        # After install + reload: the template now appears.
        resp = await c.get("/v1/templates")
        ids = [t["id"] for t in resp.json()]
        assert "builtin.demo-display" in ids
