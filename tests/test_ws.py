"""WebSocket endpoint tests."""
from __future__ import annotations

import asyncio
import json
import pytest
import pytest_asyncio
from httpx import AsyncClient
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

from broker.registry import AgentRegistry
from broker.api.app import create_app
from tests.helpers import MockAgentConnection


@pytest.fixture
def registry() -> AgentRegistry:
    return AgentRegistry()


@pytest_asyncio.fixture
async def app(registry):
    return create_app(registry)


@pytest.mark.asyncio
async def test_ws_connects(app):
    async with AsyncClient(transport=ASGIWebSocketTransport(app=app), base_url="http://test") as client:
        async with aconnect_ws("/v1/ws", client) as ws:
            assert ws is not None


@pytest.mark.asyncio
async def test_ws_receives_published_event(app, registry):
    conn = MockAgentConnection()
    agent_id = registry.register(conn)
    async with AsyncClient(transport=ASGIWebSocketTransport(app=app), base_url="http://test") as client:
        async with aconnect_ws("/v1/ws", client) as ws:
            registry.publish(agent_id, {"event": "notification", "value": "ab"})
            msg = await asyncio.wait_for(ws.receive_text(), timeout=2.0)
            data = json.loads(msg)
            assert data["event"] == "notification"
            assert data["agent_id"] == agent_id


@pytest.mark.asyncio
async def test_ws_replays_buffer_on_connect(app, registry):
    conn = MockAgentConnection()
    agent_id = registry.register(conn)
    registry.publish(agent_id, {"event": "notification", "value": "bb"})
    async with AsyncClient(transport=ASGIWebSocketTransport(app=app), base_url="http://test") as client:
        async with aconnect_ws("/v1/ws", client) as ws:
            msg = await asyncio.wait_for(ws.receive_text(), timeout=2.0)
            data = json.loads(msg)
            assert data["event"] == "notification"


@pytest.mark.asyncio
async def test_ws_inbound_command_forwarded_to_agent(app, registry):
    conn = MockAgentConnection()
    agent_id = registry.register(conn)
    async with AsyncClient(transport=ASGIWebSocketTransport(app=app), base_url="http://test") as client:
        async with aconnect_ws("/v1/ws", client) as ws:
            await ws.send_text(json.dumps({"cmd": "scan_start", "timeout_ms": 1000}))
            # Give the server a moment to process the inbound command.
            for _ in range(50):
                await asyncio.sleep(0.01)
                if conn.last_command() is not None:
                    break
            cmd = conn.last_command()
            assert cmd is not None
            assert cmd["cmd"] == "scan_start"
            assert cmd["timeout_ms"] == 1000


@pytest.mark.asyncio
async def test_ws_inbound_command_unknown_agent_error_frame(app, registry):
    # No agents registered -> resolve_agent raises -> server sends an error frame, stays alive.
    async with AsyncClient(transport=ASGIWebSocketTransport(app=app), base_url="http://test") as client:
        async with aconnect_ws("/v1/ws", client) as ws:
            await ws.send_text(json.dumps({"cmd": "scan_start"}))
            msg = await asyncio.wait_for(ws.receive_text(), timeout=2.0)
            data = json.loads(msg)
            assert data.get("error") == "agent_error"


@pytest.mark.asyncio
async def test_ws_malformed_json_keeps_connection_alive(app, registry):
    conn = MockAgentConnection()
    agent_id = registry.register(conn)
    async with AsyncClient(transport=ASGIWebSocketTransport(app=app), base_url="http://test") as client:
        async with aconnect_ws("/v1/ws", client) as ws:
            await ws.send_text("this is not json{{{")
            # Connection should stay open: a subsequent published event still arrives.
            registry.publish(agent_id, {"event": "notification", "value": "zz"})
            msg = await asyncio.wait_for(ws.receive_text(), timeout=2.0)
            data = json.loads(msg)
            assert data["event"] == "notification"


@pytest.mark.asyncio
async def test_ws_event_filter_excludes_nonmatching(app, registry):
    conn = MockAgentConnection()
    agent_id = registry.register(conn)
    async with AsyncClient(transport=ASGIWebSocketTransport(app=app), base_url="http://test") as client:
        async with aconnect_ws("/v1/ws?events=notification", client) as ws:
            # This 'status' event must be filtered OUT.
            registry.publish(agent_id, {"event": "status", "scanning": True})
            # This 'notification' event must pass through.
            registry.publish(agent_id, {"event": "notification", "value": "yes"})
            msg = await asyncio.wait_for(ws.receive_text(), timeout=2.0)
            data = json.loads(msg)
            # First (and matching) message must be the notification, not the status.
            assert data["event"] == "notification"
            assert data["value"] == "yes"


@pytest.mark.asyncio
async def test_ws_agent_filter_empty_string_means_no_filter(app, registry):
    conn = MockAgentConnection()
    agent_id = registry.register(conn)
    async with AsyncClient(transport=ASGIWebSocketTransport(app=app), base_url="http://test") as client:
        # agent="" must be treated as no filter (normalized), so the event still arrives.
        async with aconnect_ws("/v1/ws?agent=", client) as ws:
            registry.publish(agent_id, {"event": "notification", "value": "ok"})
            msg = await asyncio.wait_for(ws.receive_text(), timeout=2.0)
            data = json.loads(msg)
            assert data["event"] == "notification"
