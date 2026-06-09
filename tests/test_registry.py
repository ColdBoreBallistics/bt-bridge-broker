"""Unit tests for AgentRegistry."""
from __future__ import annotations

import asyncio
import pytest
from broker.registry import AgentRegistry, AgentState
from tests.helpers import MockAgentConnection


@pytest.fixture
def registry() -> AgentRegistry:
    return AgentRegistry()


@pytest.fixture
def conn() -> MockAgentConnection:
    return MockAgentConnection("agent-001")


def test_register_assigns_id(registry, conn):
    agent_id = registry.register(conn)
    assert agent_id.startswith("agent-")
    assert registry.get_agent(agent_id) is not None


def test_unregister_removes_agent(registry, conn):
    agent_id = registry.register(conn)
    registry.unregister(agent_id)
    assert registry.get_agent(agent_id) is None


def test_list_agents_empty(registry):
    assert registry.list_agents() == []


def test_list_agents_shows_registered(registry, conn):
    registry.register(conn)
    assert len(registry.list_agents()) == 1


def test_resolve_agent_auto_select_single(registry, conn):
    agent_id = registry.register(conn)
    state = registry.resolve_agent(None)
    assert state.agent_id == agent_id


def test_resolve_agent_404_when_empty(registry):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        registry.resolve_agent(None)
    assert exc.value.status_code == 404


def test_resolve_agent_409_when_multiple(registry, conn):
    from fastapi import HTTPException
    conn2 = MockAgentConnection("conn2")
    registry.register(conn)
    registry.register(conn2)
    with pytest.raises(HTTPException) as exc:
        registry.resolve_agent(None)
    assert exc.value.status_code == 409


def test_resolve_agent_by_id_found(registry, conn):
    agent_id = registry.register(conn)
    state = registry.resolve_agent(agent_id)
    assert state.agent_id == agent_id


def test_resolve_agent_by_id_not_found(registry):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        registry.resolve_agent("agent-999")
    assert exc.value.status_code == 404


def test_scan_result_name_refreshes_on_later_event(registry, conn):
    agent_id = registry.register(conn)
    # First advertisement: no name
    registry.update_state(agent_id, {"event": "scan_result", "address": "AA:BB:CC:DD:EE:FF", "rssi": -70})
    # Later advertisement: name appears
    registry.update_state(agent_id, {"event": "scan_result", "address": "AA:BB:CC:DD:EE:FF", "rssi": -68, "name": "MyDevice"})
    results = registry.get_scan_results(agent_id)
    assert len(results) == 1
    assert results[0].name == "MyDevice"
    # A later nameless advertisement must NOT wipe the name
    registry.update_state(agent_id, {"event": "scan_result", "address": "AA:BB:CC:DD:EE:FF", "rssi": -72})
    results = registry.get_scan_results(agent_id)
    assert results[0].name == "MyDevice"


@pytest.mark.asyncio
async def test_send_and_wait_resolves_on_event(registry, conn):
    agent_id = registry.register(conn)
    import uuid as _uuid
    req_id = _uuid.uuid4().hex[:8]
    # Schedule a delayed event injection
    async def inject():
        await asyncio.sleep(0.05)
        registry.update_state(agent_id, {"event": "read_result", "req_id": req_id, "value": "ff"})
    asyncio.create_task(inject())
    result = await registry.send_and_wait(agent_id, {"cmd": "read"}, req_id, timeout=1.0)
    assert result["req_id"] == req_id
    assert result["value"] == "ff"


@pytest.mark.asyncio
async def test_send_and_wait_timeout(registry, conn):
    agent_id = registry.register(conn)
    with pytest.raises(Exception) as exc:
        await registry.send_and_wait(agent_id, {"cmd": "read"}, "noreply", timeout=0.05)
    assert exc.value.status_code == 504


def test_scan_result_dedup_updates_rssi(registry, conn):
    agent_id = registry.register(conn)
    registry.update_state(agent_id, {"event": "scan_result", "address": "AA:BB:CC:DD:EE:FF", "rssi": -70, "name": "Device"})
    registry.update_state(agent_id, {"event": "scan_result", "address": "AA:BB:CC:DD:EE:FF", "rssi": -65, "name": "Device"})
    results = registry.get_scan_results(agent_id)
    assert len(results) == 1
    assert results[0].rssi == -65


def test_scan_result_dedup_new_address(registry, conn):
    agent_id = registry.register(conn)
    registry.update_state(agent_id, {"event": "scan_result", "address": "AA:BB:CC:DD:EE:FF", "rssi": -70})
    registry.update_state(agent_id, {"event": "scan_result", "address": "11:22:33:44:55:66", "rssi": -80})
    results = registry.get_scan_results(agent_id)
    assert len(results) == 2


def test_ring_buffer_replay(registry, conn):
    agent_id = registry.register(conn)
    registry.publish(agent_id, {"event": "notification", "value": "01"})
    registry.publish(agent_id, {"event": "notification", "value": "02"})
    buffered = registry.buffered_events()
    assert len(buffered) == 2


def test_publish_fan_out(registry, conn):
    agent_id = registry.register(conn)
    q, token = registry.subscribe()
    registry.publish(agent_id, {"event": "notification", "value": "ab"})
    registry.unsubscribe(token)
    assert not q.empty()
    envelope = q.get_nowait()
    assert envelope["agent_id"] == agent_id
    assert envelope["value"] == "ab"
