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
from tests.helpers import MockAgentConnection


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


@pytest.mark.asyncio
async def test_draft_rejects_unsafe_id(client):
    # save_draft raises ValueError on a path-traversal id -> endpoint must return 422, not 500.
    draft = {
        "schema_version": 1,
        "id": "../../../../tmp/evil",
        "version": "1.0.0",
        "type": "display",
        "name": "Evil"
    }
    resp = await client.post("/v1/templates/draft", json=draft)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_match_route_not_swallowed_by_template_id(client):
    """Regression guard: /v1/templates/match binds to the match handler, not {template_id}."""
    resp = await client.get(
        "/v1/templates/match",
        params={"service_uuids": "0000abcd-0000-1000-8000-00805f9b34fb"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "matches" in body, f"Expected match-result shape, got {body!r} — route ordering regressed"


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


@pytest.mark.asyncio
async def test_draft_non_string_version_returns_422_not_500(client):
    # A non-string version must yield 422 (validated), never a 500 leaking a TypeError.
    draft = {
        "schema_version": 1,
        "id": "contrib.numbered",
        "version": 1.0,            # not a string
        "type": "display",
        "name": "Numbered",
    }
    resp = await client.post("/v1/templates/draft", json=draft)
    assert resp.status_code == 422
    body = resp.json()
    assert body.get("error") == "invalid"
    assert "internal_error" not in body.get("error", "")


@pytest.mark.asyncio
async def test_draft_non_string_type_returns_422(client):
    draft = {
        "schema_version": 1,
        "id": "contrib.typed",
        "version": "1.0.0",
        "type": 123,               # not a string
        "name": "Typed",
    }
    resp = await client.post("/v1/templates/draft", json=draft)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_set_agent_view_sends_command(client, registry):
    conn = MockAgentConnection()
    agent_id = registry.register(conn)
    resp = await client.post(
        f"/v1/agents/{agent_id}/view",
        json={"address": "AA:BB:CC:DD:EE:FF", "view": "imperial"},
    )
    assert resp.status_code == 200
    cmd = conn.last_command()
    assert cmd is not None
    assert cmd["cmd"] == "set_view"
    assert cmd["address"] == "AA:BB:CC:DD:EE:FF"
    assert cmd["view"] == "imperial"


@pytest.mark.asyncio
async def test_set_agent_view_unknown_agent_404(client):
    resp = await client.post(
        "/v1/agents/agent-999/view",
        json={"address": "AA:BB:CC:DD:EE:FF", "view": "metric"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_re_session_full_flow(client, registry):
    from tests.helpers import MockAgentConnection
    conn = MockAgentConnection()
    registry.register(conn)
    # start
    resp = await client.post("/v1/re/session/start", json={"address": "AA:BB:CC:DD:EE:FF"})
    assert resp.status_code == 201
    sid = resp.json()["session_id"]
    # sample
    resp = await client.post("/v1/re/session/sample", json={"session_id": sid, "char_uuid": "0000ff01-0000-1000-8000-00805f9b34fb", "value_hex": "55aa0102"})
    assert resp.status_code == 200
    assert resp.json()["sample_count"] == 1
    # analyse
    resp = await client.post("/v1/re/session/analyse", json={"session_id": sid})
    assert resp.status_code == 200
    assert "0000ff01-0000-1000-8000-00805f9b34fb" in resp.json()
    # scaffold
    resp = await client.post("/v1/re/session/scaffold", json={"session_id": sid, "device_name": "Test Dev", "namespace": "contrib"})
    assert resp.status_code == 200
    assert resp.json()["type"] == "display"
    # export
    resp = await client.get("/v1/re/session/export", params={"session_id": sid})
    assert resp.status_code == 200
    assert resp.json()["_bt_bridge_export"] is True


@pytest.mark.asyncio
async def test_re_session_sample_unknown_session_404(client):
    resp = await client.post("/v1/re/session/sample", json={"session_id": "nope", "char_uuid": "0000ff01-0000-1000-8000-00805f9b34fb", "value_hex": "01"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_re_session_sample_malformed_hex_422(client, registry):
    from tests.helpers import MockAgentConnection
    registry.register(MockAgentConnection())
    resp = await client.post("/v1/re/session/start", json={"address": "AA:BB:CC:DD:EE:FF"})
    sid = resp.json()["session_id"]
    resp = await client.post("/v1/re/session/sample", json={"session_id": sid, "char_uuid": "0000ff01-0000-1000-8000-00805f9b34fb", "value_hex": "not-hex!"})
    assert resp.status_code == 422
    body = resp.json()
    assert body.get("error") == "invalid"
    assert "internal_error" not in str(body)
