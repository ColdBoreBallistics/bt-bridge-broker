"""Integration tests for REST API endpoints."""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from broker.registry import AgentRegistry
from broker.api.app import create_app
from tests.helpers import MockAgentConnection


@pytest.fixture
def registry() -> AgentRegistry:
    return AgentRegistry()


@pytest_asyncio.fixture
async def client(registry):
    app = create_app(registry)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_get_agents_empty(client):
    resp = await client.get("/v1/agents")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_agents_shows_registered(client, registry):
    conn = MockAgentConnection()
    registry.register(conn)
    resp = await client.get("/v1/agents")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_get_agent_by_id(client, registry):
    conn = MockAgentConnection()
    agent_id = registry.register(conn)
    resp = await client.get(f"/v1/agents/{agent_id}")
    assert resp.status_code == 200
    assert resp.json()["agent_id"] == agent_id


@pytest.mark.asyncio
async def test_get_agent_not_found(client):
    resp = await client.get("/v1/agents/agent-999")
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("error") == "agent_not_found"
    assert "message" in body
    assert "detail" not in body  # must NOT be double-wrapped


@pytest.mark.asyncio
async def test_scan_start_no_agent(client):
    resp = await client.post("/v1/scan/start", json={})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_scan_start_sends_command(client, registry):
    conn = MockAgentConnection()
    agent_id = registry.register(conn)
    resp = await client.post("/v1/scan/start", json={"timeout_ms": 5000})
    assert resp.status_code == 202
    cmd = conn.last_command()
    assert cmd is not None
    assert cmd["cmd"] == "scan_start"
    assert cmd["timeout_ms"] == 5000


@pytest.mark.asyncio
async def test_scan_stop_sends_command(client, registry):
    conn = MockAgentConnection()
    registry.register(conn)
    resp = await client.post("/v1/scan/stop", json={})
    assert resp.status_code == 200
    cmd = conn.last_command()
    assert cmd["cmd"] == "scan_stop"


@pytest.mark.asyncio
async def test_scan_results_empty(client, registry):
    conn = MockAgentConnection()
    registry.register(conn)
    resp = await client.get("/v1/scan/results")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_scan_results_returns_dedup_cache(client, registry):
    conn = MockAgentConnection()
    agent_id = registry.register(conn)
    registry.update_state(agent_id, {"event": "scan_result", "address": "AA:BB:CC:DD:EE:FF", "rssi": -70, "name": "TestDev"})
    resp = await client.get("/v1/scan/results")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["address"] == "AA:BB:CC:DD:EE:FF"


@pytest.mark.asyncio
async def test_multiple_agents_409(client, registry):
    registry.register(MockAgentConnection("c1"))
    registry.register(MockAgentConnection("c2"))
    resp = await client.post("/v1/scan/start", json={})
    assert resp.status_code == 409
    body = resp.json()
    assert body.get("error") == "agent_ambiguous"
    assert "detail" not in body


@pytest.mark.asyncio
async def test_scan_start_explicit_agent_targets_that_agent(client, registry):
    c1 = MockAgentConnection("c1")
    c2 = MockAgentConnection("c2")
    id1 = registry.register(c1)
    id2 = registry.register(c2)
    resp = await client.post(f"/v1/scan/start?agent={id2}", json={"timeout_ms": 3000})
    assert resp.status_code == 202
    # Only agent 2 should have received the command.
    assert c2.last_command() is not None
    assert c2.last_command()["cmd"] == "scan_start"
    assert c1.last_command() is None


@pytest.mark.asyncio
async def test_scan_start_includes_name_filter(client, registry):
    conn = MockAgentConnection()
    registry.register(conn)
    resp = await client.post("/v1/scan/start", json={"timeout_ms": 4000, "name_filter": "Niimbot"})
    assert resp.status_code == 202
    cmd = conn.last_command()
    assert cmd["name_filter"] == "Niimbot"


@pytest.mark.asyncio
async def test_connect_sends_command(client, registry):
    conn = MockAgentConnection()
    agent_id = registry.register(conn)
    resp = await client.post("/v1/connect", json={"address": "AA:BB:CC:DD:EE:FF"})
    assert resp.status_code == 202
    cmd = conn.last_command()
    assert cmd["cmd"] == "connect"
    assert cmd["address"] == "AA:BB:CC:DD:EE:FF"


@pytest.mark.asyncio
async def test_disconnect_sends_command(client, registry):
    conn = MockAgentConnection()
    registry.register(conn)
    resp = await client.post("/v1/disconnect", json={"address": "AA:BB:CC:DD:EE:FF"})
    assert resp.status_code == 202
    assert conn.last_command()["cmd"] == "disconnect"


@pytest.mark.asyncio
async def test_discover_sends_command(client, registry):
    conn = MockAgentConnection()
    registry.register(conn)
    resp = await client.post("/v1/discover", json={"address": "AA:BB:CC:DD:EE:FF"})
    assert resp.status_code == 202
    assert conn.last_command()["cmd"] == "discover"


@pytest.mark.asyncio
async def test_services_not_found(client, registry):
    conn = MockAgentConnection()
    registry.register(conn)
    resp = await client.get("/v1/services", params={"address": "AA:BB:CC:DD:EE:FF"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_subscribe_sends_command(client, registry):
    conn = MockAgentConnection()
    registry.register(conn)
    resp = await client.post("/v1/subscribe", json={"address": "AA:BB:CC:DD:EE:FF", "char": "0000ff01-0000-1000-8000-00805f9b34fb"})
    assert resp.status_code == 200
    assert conn.last_command()["cmd"] == "subscribe"


@pytest.mark.asyncio
async def test_unsubscribe_sends_command(client, registry):
    conn = MockAgentConnection()
    registry.register(conn)
    resp = await client.post("/v1/unsubscribe", json={"address": "AA:BB:CC:DD:EE:FF", "char": "0000ff01-0000-1000-8000-00805f9b34fb"})
    assert resp.status_code == 200
    assert conn.last_command()["cmd"] == "unsubscribe"


@pytest.mark.asyncio
async def test_ping_timeout(client, registry):
    conn = MockAgentConnection()
    registry.register(conn)
    # No pong will arrive — expect 504
    resp = await client.post("/v1/ping", json={}, timeout=2.0)
    assert resp.status_code == 504


@pytest.mark.asyncio
async def test_read_timeout(client, registry):
    conn = MockAgentConnection()
    registry.register(conn)
    resp = await client.post(
        "/v1/read",
        json={"address": "AA:BB:CC:DD:EE:FF", "char": "0000ff01-0000-1000-8000-00805f9b34fb"},
        timeout=2.0,
    )
    assert resp.status_code == 504
