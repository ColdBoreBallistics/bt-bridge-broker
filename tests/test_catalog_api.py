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
