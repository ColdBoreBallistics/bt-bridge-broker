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
