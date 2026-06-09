"""Unit tests for AgentRegistry."""
from __future__ import annotations

import asyncio
import json
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


@pytest.mark.asyncio
async def test_tcp_handle_agent_registers_and_publishes():
    """Integration test over a real loopback socket.

    Starts an actual asyncio TCP server bound to handle_agent, connects a real
    client, sends one event line, then closes. This exercises the true
    StreamReader/StreamWriter path — no mocked transports, so it is stable
    across Python versions.
    """
    from broker.agent_tcp import handle_agent
    registry = AgentRegistry()
    q, token = registry.subscribe()

    server = await asyncio.start_server(
        lambda r, w: handle_agent(r, w, registry),
        host="127.0.0.1",
        port=0,  # OS-assigned free port
    )
    host, port = server.sockets[0].getsockname()[:2]

    async with server:
        # Connect a real client to the broker's agent TCP port.
        reader, writer = await asyncio.open_connection(host, port)

        # The broker sends a "register" command immediately on connect — read it.
        register_line = await asyncio.wait_for(reader.readline(), timeout=1.0)
        register_msg = json.loads(register_line)
        assert register_msg["cmd"] == "register"
        assert register_msg["agent_id"].startswith("agent-")

        # Agent emits one event, then disconnects.
        writer.write((json.dumps({"event": "pong", "ts": 1000}) + "\n").encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()

        # Give the server task a moment to observe EOF and run its finally block.
        for _ in range(50):
            if registry.list_agents() == []:
                break
            await asyncio.sleep(0.01)

    # After disconnect, the agent must be unregistered.
    assert registry.list_agents() == []

    # Published events must include agent_connected, the pong, and agent_disconnected.
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    event_types = [e.get("event") for e in events]
    assert "agent_connected" in event_types
    assert "pong" in event_types
    assert "agent_disconnected" in event_types
    # Every envelope carries agent_id (added by publish) and lifecycle events carry ts.
    assert all("agent_id" in e for e in events)
    for e in events:
        if e.get("event") in ("agent_connected", "agent_disconnected"):
            assert "ts" in e
    registry.unsubscribe(token)


@pytest.mark.asyncio
async def test_tcp_push_templates_and_services_discovered(tmp_path):
    """With a template registry attached, the broker pushes templates on connect and
    responds to services_discovered with apply_template, caching services."""
    import json as _json
    from broker.agent_tcp import handle_agent
    from broker.template_registry import TemplateRegistry

    # Build a tiny catalog: one device template matching service 0000abcd.
    (tmp_path / "device.json").write_text(_json.dumps({
        "schema_version": 1, "id": "builtin.demo-device", "version": "1.0.0", "type": "device",
        "name": "Demo", "signature": {"service_uuids": ["0000abcd-0000-1000-8000-00805f9b34fb"]},
        "variants": [],
    }))
    tr = TemplateRegistry(templates_dir=tmp_path)
    tr.load()

    registry = AgentRegistry()
    registry.set_template_registry(tr)

    server = await asyncio.start_server(
        lambda r, w: handle_agent(r, w, registry),
        host="127.0.0.1", port=0,
    )
    host, port = server.sockets[0].getsockname()[:2]
    async with server:
        reader, writer = await asyncio.open_connection(host, port)

        # 1) register ack
        register = _json.loads(await asyncio.wait_for(reader.readline(), timeout=1.0))
        assert register["cmd"] == "register"
        agent_id = register["agent_id"]

        # 2) push_templates manifest (sent right after register)
        push = _json.loads(await asyncio.wait_for(reader.readline(), timeout=1.0))
        assert push["cmd"] == "push_templates"
        assert any(m["id"] == "builtin.demo-device" for m in push["manifest"])

        # 3) agent reports services_discovered for a device exposing 0000abcd
        writer.write((_json.dumps({
            "event": "services_discovered",
            "address": "AA:BB:CC:DD:EE:FF",
            "services": [{"uuid": "0000abcd-0000-1000-8000-00805f9b34fb", "chars": []}],
        }) + "\n").encode())
        await writer.drain()

        # 4) broker replies with apply_template for the matched device
        apply = _json.loads(await asyncio.wait_for(reader.readline(), timeout=1.0))
        assert apply["cmd"] == "apply_template"
        assert apply["device_template_id"] == "builtin.demo-device"
        assert apply["address"] == "AA:BB:CC:DD:EE:FF"

        # services were cached on the agent state
        state = registry.get_agent(agent_id)
        assert "AA:BB:CC:DD:EE:FF" in state.services

        writer.close()
        await writer.wait_closed()
