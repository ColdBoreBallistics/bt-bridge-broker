# BT Bridge Broker — Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Commit workflow (FOSS).** The `bt-bridge-*` repos are governed as open-source projects, not
> under the CBB app SDLC. The per-task `git commit` steps use **Conventional Commits**
> (`type(scope): subject`) and are the intended granularity — one focused commit per task. An
> executing agent should make these commits as written at each task boundary (after that task's
> tests pass), squashing/amending only within the current task. This is the standard FOSS
> commit-as-you-go flow; the CBB "ask before every commit" gate does not apply here. Pushing to
> the remote and opening PRs remain explicit, separate actions.

**Goal:** Replace `ble_server.py` (single-process asyncio TCP server) with a proper two-tier FastAPI broker: agent TCP on port 2653, REST+WebSocket API on port 2673.

**Architecture:** `AgentRegistry` holds all mutable state and handles fan-out; `agent_tcp.py` owns TCP accept/read/send per agent; `api/routes.py` + `api/ws.py` expose REST and WebSocket to test clients. Everything wires together in `main.py` via FastAPI's lifespan hook.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn[standard], pydantic-settings, pytest, httpx (async test client)

**Design reference:** `docs/2026-06-08-broker-rewrite-design.md`

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Delete | `ble_server.py` | Replaced entirely |
| Keep | `protocol.py` | Unchanged — event dataclasses + parse/cmd functions |
| Create | `broker/__init__.py` | Package marker |
| Create | `broker/main.py` | Entry point: CLI args, lifespan, uvicorn launch |
| Create | `broker/registry.py` | `AgentRegistry` + `AgentState` — all mutable state, fan-out |
| Create | `broker/agent_tcp.py` | TCP server accept loop; `AgentConnection` per agent |
| Create | `broker/api/__init__.py` | Package marker |
| Create | `broker/api/app.py` | FastAPI app factory, mount routers, custom error handler |
| Create | `broker/api/routes.py` | All REST endpoints + Pydantic request/response models |
| Create | `broker/api/ws.py` | WebSocket endpoint `/v1/ws` |
| Create | `broker/repl.py` | Optional interactive REPL (`--interactive`) |
| Create | `broker/template_registry.py` | Stub — disk scan + in-memory map (full logic in Plan 2) |
| Modify | `requirements.txt` | Add fastapi, uvicorn[standard], pydantic-settings |
| Create | `requirements-lock.txt` | Pinned versions |
| Create | `tests/__init__.py` | Package marker |
| Create | `tests/test_registry.py` | Unit tests for AgentRegistry |
| Create | `tests/test_api.py` | Integration tests for REST endpoints |
| Create | `tests/test_ws.py` | WebSocket tests |
| Create | `tests/helpers.py` | Mock agent connection + event injection helpers |

---

## Task 1: Dependencies and package skeleton

**Files:**
- Modify: `requirements.txt` (runtime only)
- Create: `requirements-dev.txt` (test/dev)
- Create: `requirements-lock.txt`
- Create: `broker/__init__.py`
- Create: `broker/api/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/helpers.py`

> **Dependency layout (FOSS-standard).** Runtime deps the broker actually imports go in
> `requirements.txt`; the test-only stack (`httpx`, `httpx-ws`, `pytest`, `pytest-asyncio`)
> goes in `requirements-dev.txt`, which includes the runtime set via `-r requirements.txt`.
> A user who only wants to run the broker installs `requirements.txt`; contributors install
> `requirements-dev.txt`. (`httpx-ws` is added in Task 8 when the WebSocket tests need it.)

- [ ] **Step 1: Set `requirements.txt` (runtime only)**

```text
# BT Bridge Broker — runtime dependencies
# Python 3.11 or later required (match statements, type union syntax).
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
pydantic-settings>=2.2.1
```

- [ ] **Step 2: Create `requirements-dev.txt` (test/dev)**

```text
# BT Bridge Broker — development & test dependencies
-r requirements.txt
httpx>=0.27.0
pytest>=8.2.0
pytest-asyncio>=0.23.0
```

- [ ] **Step 3: Create a virtual environment and install the dev set**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

Expected: all packages install with no errors.

- [ ] **Step 4: Pin versions to requirements-lock.txt**

```bash
pip freeze > requirements-lock.txt
```

- [ ] **Step 4: Create package markers**

`broker/__init__.py`:
```python
```

`broker/api/__init__.py`:
```python
```

`tests/__init__.py`:
```python
```

- [ ] **Step 5: Create tests/helpers.py**

```python
"""Shared test helpers — mock AgentConnection and event injection."""
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock


class MockAgentConnection:
    """Simulates an AgentConnection for registry unit tests."""

    def __init__(self, agent_id: str = "agent-001"):
        self.agent_id = agent_id
        self._sent: list[str] = []
        self._closed = False

    async def send(self, raw_json: str) -> None:
        self._sent.append(raw_json)

    async def close(self) -> None:
        self._closed = True

    def sent_commands(self) -> list[dict[str, Any]]:
        return [json.loads(s) for s in self._sent]

    def last_command(self) -> dict[str, Any] | None:
        if self._sent:
            return json.loads(self._sent[-1])
        return None
```

- [ ] **Step 6: Verify pytest discovers tests directory**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/ --collect-only
```

Expected: `no tests ran` (no test functions yet) with no import errors.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt requirements-dev.txt requirements-lock.txt broker/__init__.py broker/api/__init__.py tests/__init__.py tests/helpers.py
git commit -m "chore: add fastapi/uvicorn deps, test scaffolding"
```

---

## Task 2: AgentState and AgentRegistry — core state

**Files:**
- Create: `broker/registry.py`
- Create: `tests/test_registry.py`

- [ ] **Step 1: Write failing tests for AgentRegistry registration**

`tests/test_registry.py`:
```python
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


def test_resolve_agent_409_when_multiple(registry):
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
```

- [ ] **Step 2: Run tests — expect ImportError (registry.py doesn't exist yet)**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/test_registry.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'broker.registry'`

- [ ] **Step 3: Create broker/registry.py — AgentState and registry core**

```python
"""AgentRegistry — central state store and event fan-out for the BT Bridge broker."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from fastapi import HTTPException

if TYPE_CHECKING:
    from broker.agent_tcp import AgentConnection


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class ScanResultEntry:
    address: str
    name: str | None
    rssi: int
    last_seen_ms: int


@dataclass
class AgentState:
    agent_id: str
    connection: Any  # AgentConnection — Any to avoid circular at dataclass level
    platform: str | None = None
    capabilities: list[str] = field(default_factory=list)
    connected_since_ms: int = field(default_factory=_now_ms)
    ble_enabled: bool = False
    scanning: bool = False
    connected_devices: list[str] = field(default_factory=list)
    scan_results: list[ScanResultEntry] = field(default_factory=list)
    services: dict[str, list[Any]] = field(default_factory=dict)
    last_status_ms: int = field(default_factory=_now_ms)


class AgentRegistry:
    """All mutable broker state lives here. No other module holds agent state."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentState] = {}
        self._counter: int = 0
        self._subscribers: dict[int, asyncio.Queue[dict[str, Any]]] = {}
        self._sub_token: int = 0
        self._ring_buffer: list[tuple[int, dict[str, Any]]] = []  # (ts_ms, envelope)
        self._ring_max = 1000
        self._ring_ttl_ms = 60_000
        self._waiters: dict[str, asyncio.Future[Any]] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def register(self, connection: Any) -> str:
        self._counter += 1
        agent_id = f"agent-{self._counter:03d}"
        self._agents[agent_id] = AgentState(agent_id=agent_id, connection=connection)
        return agent_id

    def unregister(self, agent_id: str) -> None:
        self._agents.pop(agent_id, None)
        # Cancel any pending waiters for this agent
        for key in list(self._waiters):
            if key.startswith(f"{agent_id}:"):
                fut = self._waiters.pop(key)
                if not fut.done():
                    fut.cancel()

    def update_state(self, agent_id: str, event: dict[str, Any]) -> None:
        """Update AgentState from hello/status events. Also handles scan_result dedup."""
        state = self._agents.get(agent_id)
        if state is None:
            return
        etype = event.get("event")
        if etype == "hello":
            state.platform = event.get("platform")
            state.capabilities = event.get("capabilities", [])
            state.ble_enabled = event.get("ble_enabled", False)
        elif etype == "status":
            state.ble_enabled = event.get("ble_enabled", state.ble_enabled)
            state.scanning = event.get("scanning", state.scanning)
            state.connected_devices = event.get("connected_devices", state.connected_devices)
            state.last_status_ms = _now_ms()
        elif etype == "scan_result":
            self._upsert_scan_result(state, event)
        # Resolve any matching send_and_wait futures
        req_id = event.get("req_id")
        if req_id:
            waiter_key = f"{agent_id}:{req_id}"
            fut = self._waiters.get(waiter_key)
            if fut and not fut.done():
                fut.set_result(event)
                self._waiters.pop(waiter_key, None)

    def _upsert_scan_result(self, state: AgentState, event: dict[str, Any]) -> None:
        now = _now_ms()
        address = event.get("address", "")
        # Expire stale entries
        state.scan_results = [
            e for e in state.scan_results if now - e.last_seen_ms <= 30_000
        ]
        for entry in state.scan_results:
            if entry.address == address:
                entry.rssi = event.get("rssi", entry.rssi)
                entry.last_seen_ms = now
                return
        state.scan_results.append(
            ScanResultEntry(
                address=address,
                name=event.get("name"),
                rssi=event.get("rssi", 0),
                last_seen_ms=now,
            )
        )

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    async def send_command(self, agent_id: str, cmd: dict[str, Any]) -> None:
        import json
        state = self._agents.get(agent_id)
        if state is None:
            return
        await state.connection.send(json.dumps(cmd))

    async def send_and_wait(
        self,
        agent_id: str,
        cmd: dict[str, Any],
        req_id: str,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """Send a command and wait for the response event carrying req_id."""
        import json
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        waiter_key = f"{agent_id}:{req_id}"
        self._waiters[waiter_key] = fut
        cmd["req_id"] = req_id
        state = self._agents.get(agent_id)
        if state is None:
            self._waiters.pop(waiter_key, None)
            raise HTTPException(status_code=404, detail={"error": "agent_not_found", "message": f"Agent {agent_id!r} not connected"})
        try:
            await state.connection.send(json.dumps(cmd))
            return await asyncio.wait_for(fut, timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError):
            raise HTTPException(status_code=504, detail={"error": "timeout", "message": "Agent did not respond in time"})
        finally:
            # Idempotent cleanup — the waiter is removed here on EVERY exit path
            # (success, timeout, send failure, cancellation). On the success path
            # update_state() may have already popped it; pop(..., None) is a no-op then.
            self._waiters.pop(waiter_key, None)

    # ------------------------------------------------------------------
    # Agent resolution
    # ------------------------------------------------------------------

    def get_agent(self, agent_id: str) -> AgentState | None:
        return self._agents.get(agent_id)

    def list_agents(self) -> list[AgentState]:
        return list(self._agents.values())

    def resolve_agent(self, agent_id: str | None) -> AgentState:
        if agent_id is not None:
            state = self._agents.get(agent_id)
            if state is None:
                raise HTTPException(
                    status_code=404,
                    detail={"error": "agent_not_found", "message": f"Agent {agent_id!r} not connected"},
                )
            return state
        agents = list(self._agents.values())
        if len(agents) == 0:
            raise HTTPException(
                status_code=404,
                detail={"error": "agent_not_found", "message": "No agent connected"},
            )
        if len(agents) > 1:
            raise HTTPException(
                status_code=409,
                detail={"error": "agent_ambiguous", "message": f"{len(agents)} agents connected — specify ?agent=<id>"},
            )
        return agents[0]

    def get_scan_results(self, agent_id: str) -> list[ScanResultEntry]:
        state = self._agents.get(agent_id)
        return state.scan_results if state else []

    # ------------------------------------------------------------------
    # WebSocket fan-out
    # ------------------------------------------------------------------

    def subscribe(self) -> tuple[asyncio.Queue[dict[str, Any]], int]:
        token = self._sub_token
        self._sub_token += 1
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers[token] = q
        return q, token

    def unsubscribe(self, token: int) -> None:
        self._subscribers.pop(token, None)

    def publish(self, agent_id: str, event: dict[str, Any]) -> None:
        now = _now_ms()
        envelope = {"agent_id": agent_id, **event}
        # Maintain ring buffer
        self._ring_buffer.append((now, envelope))
        # Evict old entries
        cutoff = now - self._ring_ttl_ms
        self._ring_buffer = [
            (ts, e) for ts, e in self._ring_buffer if ts >= cutoff
        ]
        if len(self._ring_buffer) > self._ring_max:
            self._ring_buffer = self._ring_buffer[-self._ring_max:]
        # Fan out to subscribers
        for q in self._subscribers.values():
            try:
                q.put_nowait(envelope)
            except asyncio.QueueFull:
                pass

    def buffered_events(self, max_age_ms: int = 60_000) -> list[dict[str, Any]]:
        """Return ring buffer contents not older than max_age_ms."""
        now = _now_ms()
        cutoff = now - max_age_ms
        return [e for ts, e in self._ring_buffer if ts >= cutoff]
```

- [ ] **Step 4: Run registry tests — expect them to pass**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/test_registry.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add broker/registry.py tests/test_registry.py
git commit -m "feat(registry): AgentRegistry with register/resolve/fan-out"
```

---

## Task 3: AgentRegistry — send_and_wait and scan dedup

**Files:**
- Modify: `tests/test_registry.py` (add tests)

- [ ] **Step 1: Add failing tests for send_and_wait and scan dedup**

Append to `tests/test_registry.py`:
```python
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
```

- [ ] **Step 2: Add pytest-asyncio config to pyproject.toml**

Create `pyproject.toml` in the repo root:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 3: Run new tests**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/test_registry.py -v
```

Expected: all 16 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_registry.py pyproject.toml
git commit -m "test(registry): send_and_wait, scan dedup, ring buffer, fan-out"
```

---

## Task 4: Agent TCP layer

**Files:**
- Create: `broker/agent_tcp.py`

- [ ] **Step 1: Create broker/agent_tcp.py**

```python
"""Agent TCP server — one AgentConnection per connected agent app."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from broker.registry import AgentRegistry

log = logging.getLogger(__name__)


class AgentConnection:
    """Wraps a single asyncio TCP stream to one agent."""

    def __init__(self, writer: asyncio.StreamWriter) -> None:
        self._writer = writer
        self.agent_id: str = ""  # assigned by registry.register()

    async def send(self, raw_json: str) -> None:
        try:
            self._writer.write((raw_json + "\n").encode())
            await self._writer.drain()
        except (ConnectionResetError, BrokenPipeError) as exc:
            log.warning("send failed for %s: %s", self.agent_id, exc)

    async def close(self) -> None:
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except Exception:
            pass

    async def run(self, registry: "AgentRegistry") -> None:
        reader = self._writer  # type hint trick — we get both below
        # NOTE: reader comes from the accept callback; captured in handle_agent
        raise NotImplementedError("Use handle_agent() — not run() directly")


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

    # Send registration acknowledgement
    await conn.send(json.dumps({"cmd": "register", "agent_id": agent_id}))

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

- [ ] **Step 2: Write a smoke test for the TCP layer**

Append to `tests/test_registry.py`:
```python
@pytest.mark.asyncio
async def test_tcp_handle_agent_registers_and_publishes():
    """Integration test over a real loopback socket.

    Starts an actual asyncio TCP server bound to handle_agent, connects a real
    client, sends one event line, then closes. This exercises the true
    StreamReader/StreamWriter path — no mocked transports, so it is stable
    across Python versions (unlike hand-constructing a StreamWriter around a
    MagicMock transport).
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
    registry.unsubscribe(token)
```

> This test no longer needs `MagicMock`/`AsyncMock` from `tests.helpers`. The `unittest.mock` import in `tests/helpers.py` is still used by `MockAgentConnection` for other tests, so leave it.

- [ ] **Step 3: Run tests**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/test_registry.py -v
```

Expected: all tests PASS. This is a real loopback socket test — it is stable across Python versions and must not be skipped. If it hangs, the most likely cause is `handle_agent` not exiting its read loop on EOF; fix `handle_agent` rather than skipping the test.

- [ ] **Step 4: Commit**

```bash
git add broker/agent_tcp.py tests/test_registry.py
git commit -m "feat(agent_tcp): TCP accept loop and AgentConnection"
```

---

## Task 5: FastAPI app factory and error handler

**Files:**
- Create: `broker/api/app.py`

- [ ] **Step 1: Create broker/api/app.py**

```python
"""FastAPI app factory for the BT Bridge broker."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from broker.registry import AgentRegistry


def create_app(registry: AgentRegistry) -> FastAPI:
    """Create and configure the FastAPI application.

    The registry is attached to app.state so all routes can access it via
    request.app.state.registry without global state.
    """

    app = FastAPI(
        title="BT Bridge Broker",
        version="1.2.0",
        description="REST + WebSocket API for the BT Bridge hardware test harness.",
    )
    app.state.registry = registry

    # Register routers
    from broker.api.routes import router as rest_router
    from broker.api.ws import router as ws_router

    app.include_router(rest_router)
    app.include_router(ws_router)

    # Custom error handler — normalise HTTPException bodies to {"error": ..., "message": ...}
    @app.exception_handler(Exception)
    async def _http_exc_handler(request: Request, exc: Exception) -> JSONResponse:
        from fastapi import HTTPException
        if isinstance(exc, HTTPException):
            detail = exc.detail
            if isinstance(detail, dict):
                return JSONResponse(status_code=exc.status_code, content=detail)
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": "http_error", "message": str(detail)},
            )
        return JSONResponse(status_code=500, content={"error": "internal_error", "message": str(exc)})

    return app
```

- [ ] **Step 2: No isolated test yet — verified in Task 6 integration tests**

- [ ] **Step 3: Commit**

```bash
git add broker/api/app.py
git commit -m "feat(api): FastAPI app factory with error handler"
```

---

## Task 6: REST routes — agents and scan

**Files:**
- Create: `broker/api/routes.py` (agents + scan section)
- Create: `tests/test_api.py`

- [ ] **Step 1: Write failing tests for agent and scan endpoints**

`tests/test_api.py`:
```python
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
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/test_api.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'broker.api.routes'`

- [ ] **Step 3: Create broker/api/routes.py — agents + scan**

```python
"""REST API routes for the BT Bridge broker."""
from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from broker.registry import AgentRegistry, ScanResultEntry

router = APIRouter()


def _registry(request: Request) -> AgentRegistry:
    return request.app.state.registry


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AgentStateOut(BaseModel):
    agent_id: str
    platform: str | None
    capabilities: list[str]
    connected_since_ms: int
    ble_enabled: bool
    scanning: bool
    connected_devices: list[str]
    last_status_ms: int


class ScanResultOut(BaseModel):
    address: str
    name: str | None
    rssi: int
    last_seen_ms: int


class ScanStartIn(BaseModel):
    timeout_ms: int = 10000
    name_filter: str | None = None


class EmptyIn(BaseModel):
    pass


# ---------------------------------------------------------------------------
# Agent endpoints
# ---------------------------------------------------------------------------

@router.get("/v1/agents", response_model=list[AgentStateOut])
async def list_agents(request: Request):
    reg = _registry(request)
    return [
        AgentStateOut(
            agent_id=a.agent_id,
            platform=a.platform,
            capabilities=a.capabilities,
            connected_since_ms=a.connected_since_ms,
            ble_enabled=a.ble_enabled,
            scanning=a.scanning,
            connected_devices=a.connected_devices,
            last_status_ms=a.last_status_ms,
        )
        for a in reg.list_agents()
    ]


@router.get("/v1/agents/{agent_id}", response_model=AgentStateOut)
async def get_agent(agent_id: str, request: Request):
    reg = _registry(request)
    state = reg.resolve_agent(agent_id)
    return AgentStateOut(
        agent_id=state.agent_id,
        platform=state.platform,
        capabilities=state.capabilities,
        connected_since_ms=state.connected_since_ms,
        ble_enabled=state.ble_enabled,
        scanning=state.scanning,
        connected_devices=state.connected_devices,
        last_status_ms=state.last_status_ms,
    )


# ---------------------------------------------------------------------------
# Scan endpoints
# ---------------------------------------------------------------------------

@router.post("/v1/scan/start", status_code=202)
async def scan_start(
    body: ScanStartIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    cmd: dict[str, Any] = {"cmd": "scan_start", "timeout_ms": body.timeout_ms}
    if body.name_filter is not None:
        cmd["name_filter"] = body.name_filter
    await reg.send_command(state.agent_id, cmd)
    return {"status": "accepted"}


@router.post("/v1/scan/stop")
async def scan_stop(
    body: EmptyIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    await reg.send_command(state.agent_id, {"cmd": "scan_stop"})
    return {"status": "ok"}


@router.get("/v1/scan/results", response_model=list[ScanResultOut])
async def scan_results(
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    results = reg.get_scan_results(state.agent_id)
    return [
        ScanResultOut(
            address=r.address,
            name=r.name,
            rssi=r.rssi,
            last_seen_ms=r.last_seen_ms,
        )
        for r in results
    ]
```

- [ ] **Step 4: Run agent + scan tests**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/test_api.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add broker/api/routes.py tests/test_api.py
git commit -m "feat(api): agent and scan REST endpoints"
```

---

## Task 7: REST routes — device, characteristic, utility

**Files:**
- Modify: `broker/api/routes.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add failing tests for device, characteristic, and utility endpoints**

Append to `tests/test_api.py`:
```python
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
```

- [ ] **Step 2: Run new tests — expect 404 (routes not defined yet)**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/test_api.py -v -k "connect or disconnect or discover or services or subscribe or unsubscribe or ping or read" 2>&1 | tail -20
```

Expected: various failures (404 or ImportError).

- [ ] **Step 3: Append device/char/utility routes to broker/api/routes.py**

Append to the end of `broker/api/routes.py`:
```python

# ---------------------------------------------------------------------------
# Device endpoints
# ---------------------------------------------------------------------------

class AddressIn(BaseModel):
    address: str


@router.post("/v1/connect", status_code=202)
async def connect_device(
    body: AddressIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    await reg.send_command(state.agent_id, {"cmd": "connect", "address": body.address})
    return {"status": "accepted"}


@router.post("/v1/disconnect", status_code=202)
async def disconnect_device(
    body: AddressIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    await reg.send_command(state.agent_id, {"cmd": "disconnect", "address": body.address})
    return {"status": "accepted"}


@router.post("/v1/discover", status_code=202)
async def discover_services(
    body: AddressIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    await reg.send_command(state.agent_id, {"cmd": "discover", "address": body.address})
    return {"status": "accepted"}


@router.get("/v1/services")
async def get_services(
    request: Request,
    address: str = Query(...),
    agent: str | None = Query(default=None),
):
    from fastapi import HTTPException
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    services = state.services.get(address)
    if services is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_discovered", "message": f"No services discovered for {address!r}"},
        )
    return services


# ---------------------------------------------------------------------------
# Characteristic endpoints
# ---------------------------------------------------------------------------

class CharOpIn(BaseModel):
    address: str
    char: str


class WriteIn(BaseModel):
    address: str
    char: str
    value: str  # lowercase hex
    rsp: bool = True


@router.post("/v1/subscribe")
async def subscribe_char(
    body: CharOpIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    await reg.send_command(state.agent_id, {"cmd": "subscribe", "address": body.address, "char": body.char})
    return {"status": "ok"}


@router.post("/v1/unsubscribe")
async def unsubscribe_char(
    body: CharOpIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    await reg.send_command(state.agent_id, {"cmd": "unsubscribe", "address": body.address, "char": body.char})
    return {"status": "ok"}


@router.post("/v1/read")
async def read_char(
    body: CharOpIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    req_id = uuid.uuid4().hex[:8]
    result = await reg.send_and_wait(
        state.agent_id,
        {"cmd": "read", "address": body.address, "char": body.char},
        req_id,
        timeout=5.0,
    )
    return {"value": result.get("value"), "status": result.get("status", 0)}


@router.post("/v1/write")
async def write_char(
    body: WriteIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    req_id = uuid.uuid4().hex[:8]
    cmd: dict[str, Any] = {
        "cmd": "write",
        "address": body.address,
        "char": body.char,
        "value": body.value,
        "rsp": body.rsp,
    }
    if body.rsp:
        result = await reg.send_and_wait(state.agent_id, cmd, req_id, timeout=5.0)
        return {"status": result.get("status", 0)}
    await reg.send_command(state.agent_id, {**cmd, "req_id": req_id})
    return {"status": "accepted"}


# ---------------------------------------------------------------------------
# Utility endpoints
# ---------------------------------------------------------------------------

@router.post("/v1/ping")
async def ping(
    body: EmptyIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    import time as _time
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    req_id = uuid.uuid4().hex[:8]
    t0 = _time.monotonic()
    result = await reg.send_and_wait(state.agent_id, {"cmd": "ping"}, req_id, timeout=5.0)
    latency_ms = int((_time.monotonic() - t0) * 1000)
    return {"latency_ms": latency_ms}


class AskIn(BaseModel):
    question: str


@router.post("/v1/ask")
async def ask(
    body: AskIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    req_id = uuid.uuid4().hex[:8]
    result = await reg.send_and_wait(
        state.agent_id,
        {"cmd": "ask", "question": body.question},
        req_id,
        timeout=60.0,
    )
    return {"answered": True, "value": result.get("value")}
```

- [ ] **Step 4: Run all API tests**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/test_api.py -v
```

Expected: all tests PASS (ping and read should get 504 since no agent responds).

- [ ] **Step 5: Commit**

```bash
git add broker/api/routes.py tests/test_api.py
git commit -m "feat(api): device, characteristic, and utility REST endpoints"
```

---

## Task 8: WebSocket endpoint

**Files:**
- Create: `broker/api/ws.py`
- Create: `tests/test_ws.py`

- [ ] **Step 1: Write failing WebSocket tests**

`tests/test_ws.py`:
```python
"""WebSocket endpoint tests."""
from __future__ import annotations

import asyncio
import json
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from httpx_ws import aconnect_ws

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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with aconnect_ws("/v1/ws", client) as ws:
            # Should connect without error
            assert ws is not None


@pytest.mark.asyncio
async def test_ws_receives_published_event(app, registry):
    conn = MockAgentConnection()
    agent_id = registry.register(conn)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with aconnect_ws("/v1/ws", client) as ws:
            # Publish an event
            registry.publish(agent_id, {"event": "notification", "value": "ab"})
            msg = await asyncio.wait_for(ws.receive_text(), timeout=2.0)
            data = json.loads(msg)
            assert data["event"] == "notification"
            assert data["agent_id"] == agent_id


@pytest.mark.asyncio
async def test_ws_replays_buffer_on_connect(app, registry):
    conn = MockAgentConnection()
    agent_id = registry.register(conn)
    # Publish before WS connects
    registry.publish(agent_id, {"event": "notification", "value": "bb"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with aconnect_ws("/v1/ws", client) as ws:
            msg = await asyncio.wait_for(ws.receive_text(), timeout=2.0)
            data = json.loads(msg)
            assert data["event"] == "notification"
```

- [ ] **Step 2: Add httpx-ws to the dev/test dependencies and install**

`httpx-ws` is a **test-only** dependency (it provides `aconnect_ws` for driving the
WebSocket endpoint over the in-memory ASGI transport). Add it to `requirements-dev.txt`,
not `requirements.txt`:

```text
# append to requirements-dev.txt
httpx-ws>=0.6.0
```

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pip install -r requirements-dev.txt
pip freeze > requirements-lock.txt
```

- [ ] **Step 3: Run WS tests — expect ImportError**

```bash
pytest tests/test_ws.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'broker.api.ws'`

- [ ] **Step 4: Create broker/api/ws.py**

```python
"""WebSocket endpoint for the BT Bridge broker."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from broker.registry import AgentRegistry

router = APIRouter()
log = logging.getLogger(__name__)


@router.websocket("/v1/ws")
async def ws_endpoint(
    websocket: WebSocket,
    agent: str | None = Query(default=None),
    events: str | None = Query(default=None),
):
    await websocket.accept()

    registry: AgentRegistry = websocket.app.state.registry
    event_filter: set[str] | None = {e.strip() for e in events.split(",")} if events else None

    queue, token = registry.subscribe()

    # Replay buffered events
    for envelope in registry.buffered_events():
        if agent is not None and envelope.get("agent_id") != agent:
            continue
        if event_filter and envelope.get("event") not in event_filter:
            continue
        try:
            await websocket.send_text(json.dumps(envelope))
        except WebSocketDisconnect:
            registry.unsubscribe(token)
            return

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_drain_queue(websocket, queue, agent, event_filter))
            tg.create_task(_receive_commands(websocket, registry))
    except* (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        registry.unsubscribe(token)
        log.debug("WebSocket client disconnected")


async def _drain_queue(
    ws: WebSocket,
    queue: asyncio.Queue,
    agent_filter: str | None,
    event_filter: set[str] | None,
) -> None:
    while True:
        envelope = await queue.get()
        if agent_filter and envelope.get("agent_id") != agent_filter:
            continue
        if event_filter and envelope.get("event") not in event_filter:
            continue
        await ws.send_text(json.dumps(envelope))


async def _receive_commands(ws: WebSocket, registry: AgentRegistry) -> None:
    while True:
        try:
            text = await ws.receive_text()
        except WebSocketDisconnect:
            raise
        try:
            msg = json.loads(text)
        except json.JSONDecodeError:
            log.warning("Malformed JSON from WS client: %r", text[:120])
            continue
        agent_id = msg.pop("agent_id", None)
        try:
            state = registry.resolve_agent(agent_id)
        except Exception as exc:
            await ws.send_text(json.dumps({"error": "agent_error", "message": str(exc)}))
            continue
        await registry.send_command(state.agent_id, msg)
```

- [ ] **Step 5: Run WS tests**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/test_ws.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add broker/api/ws.py tests/test_ws.py requirements-dev.txt requirements-lock.txt
git commit -m "feat(ws): WebSocket endpoint with ring buffer replay and fan-out"
```

---

## Task 9: REPL

**Files:**
- Create: `broker/repl.py`

- [ ] **Step 1: Create broker/repl.py**

```python
"""Optional interactive REPL for the BT Bridge broker (--interactive)."""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

from broker.registry import AgentRegistry

log = logging.getLogger(__name__)

HELP = """
BT Bridge REPL — commands
  agents                      list connected agents
  agent set <id>[,<id>...]    set active agent(s)
  agent clear                 clear selection
  scan start [<filter>]       start BLE scan
  scan stop                   stop BLE scan
  connect <address>           connect to device
  disconnect <address>        disconnect from device
  discover <address>          discover GATT services
  subscribe <address> <char>  subscribe to notifications
  read <address> <char>       read characteristic
  ping                        ping agent(s)
  help                        show this help
  exit / quit                 exit
""".strip()


async def run_repl(registry: AgentRegistry) -> None:
    selected: list[str] = []
    loop = asyncio.get_running_loop()

    def _prompt() -> None:
        agents = registry.list_agents()
        if selected:
            label = ",".join(selected)
        elif len(agents) == 1:
            label = agents[0].agent_id
        else:
            label = "no agent"
        sys.stdout.write(f"bt[{label}]> ")
        sys.stdout.flush()

    async def _readline() -> str:
        return await loop.run_in_executor(None, sys.stdin.readline)

    async def _resolve() -> list[str]:
        """Return list of agent IDs to target, or [] with a printed message."""
        agents = registry.list_agents()
        if selected:
            return selected
        if not agents:
            print("[no agent connected]")
            return []
        if len(agents) == 1:
            return [agents[0].agent_id]
        print(f"[{len(agents)} agents — use: agent set <id>]")
        return []

    while True:
        _prompt()
        line = await _readline()
        if not line:
            break
        parts = line.strip().split()
        if not parts:
            continue
        cmd = parts[0].lower()

        if cmd in ("exit", "quit"):
            break

        elif cmd == "help":
            print(HELP)

        elif cmd == "agents":
            for a in registry.list_agents():
                mark = "*" if not selected or a.agent_id in selected else " "
                print(f"  {mark} {a.agent_id}  platform={a.platform or '?'}  ble={a.ble_enabled}  scanning={a.scanning}")

        elif cmd == "agent":
            sub = parts[1] if len(parts) > 1 else ""
            if sub == "set" and len(parts) > 2:
                selected = parts[2].split(",")
                print(f"[active: {', '.join(selected)}]")
            elif sub == "clear":
                selected = []
                print("[selection cleared]")
            else:
                print("usage: agent set <id>[,<id>...] | agent clear")

        elif cmd == "scan":
            targets = await _resolve()
            if not targets:
                continue
            sub = parts[1].lower() if len(parts) > 1 else ""
            if sub == "start":
                name_filter = parts[2] if len(parts) > 2 else None
                c: dict[str, Any] = {"cmd": "scan_start", "timeout_ms": 30000}
                if name_filter:
                    c["name_filter"] = name_filter
                for aid in targets:
                    await registry.send_command(aid, c)
            elif sub == "stop":
                for aid in targets:
                    await registry.send_command(aid, {"cmd": "scan_stop"})
            else:
                print("usage: scan start [<filter>] | scan stop")

        elif cmd == "connect":
            if len(parts) < 2:
                print("usage: connect <address>")
                continue
            targets = await _resolve()
            for aid in targets:
                await registry.send_command(aid, {"cmd": "connect", "address": parts[1]})

        elif cmd == "disconnect":
            if len(parts) < 2:
                print("usage: disconnect <address>")
                continue
            targets = await _resolve()
            for aid in targets:
                await registry.send_command(aid, {"cmd": "disconnect", "address": parts[1]})

        elif cmd == "discover":
            if len(parts) < 2:
                print("usage: discover <address>")
                continue
            targets = await _resolve()
            for aid in targets:
                await registry.send_command(aid, {"cmd": "discover", "address": parts[1]})

        elif cmd == "subscribe":
            if len(parts) < 3:
                print("usage: subscribe <address> <char-uuid>")
                continue
            targets = await _resolve()
            for aid in targets:
                await registry.send_command(aid, {"cmd": "subscribe", "address": parts[1], "char": parts[2]})

        elif cmd == "read":
            if len(parts) < 3:
                print("usage: read <address> <char-uuid>")
                continue
            targets = await _resolve()
            for aid in targets:
                import uuid
                req_id = uuid.uuid4().hex[:8]
                try:
                    result = await registry.send_and_wait(
                        aid,
                        {"cmd": "read", "address": parts[1], "char": parts[2]},
                        req_id,
                        timeout=5.0,
                    )
                    print(f"  [{aid}] {result.get('value', '?')}  status={result.get('status', '?')}")
                except Exception as exc:
                    print(f"  [{aid}] error: {exc}")

        elif cmd == "ping":
            import time as _time
            targets = await _resolve()
            for aid in targets:
                import uuid
                req_id = uuid.uuid4().hex[:8]
                t0 = _time.monotonic()
                try:
                    await registry.send_and_wait(aid, {"cmd": "ping"}, req_id, timeout=5.0)
                    ms = int((_time.monotonic() - t0) * 1000)
                    print(f"  [{aid}] pong  {ms} ms")
                except Exception as exc:
                    print(f"  [{aid}] timeout: {exc}")

        else:
            print(f"Unknown command: {cmd!r}. Type 'help'.")
```

- [ ] **Step 2: No automated tests for REPL (stdin-driven) — manual smoke test at integration step**

- [ ] **Step 3: Commit**

```bash
git add broker/repl.py
git commit -m "feat(repl): interactive REPL with multi-agent selection"
```

---

## Task 10: Entry point (main.py) and config

**Files:**
- Create: `broker/main.py`

- [ ] **Step 1: Create broker/main.py**

```python
"""BT Bridge Broker — entry point.

Run with:
    python3 -m broker.main
    python3 -m broker.main --agent-port 2653 --api-port 2673 --interactive --debug
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BT_")

    agent_host: str = "0.0.0.0"
    agent_port: int = 2653
    api_host: str = "0.0.0.0"
    api_port: int = 2673
    interactive: bool = False
    log_file: str | None = None
    debug: bool = False


settings = Settings()


def _configure_logging() -> None:
    level = logging.DEBUG if settings.debug else logging.INFO
    handlers: list[Any] = [logging.StreamHandler()]
    if settings.log_file:
        handlers.append(logging.FileHandler(settings.log_file))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        handlers=handlers,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    from broker.agent_tcp import handle_agent
    from broker.registry import AgentRegistry
    from broker.template_registry import TemplateRegistry

    registry = AgentRegistry()
    template_registry = TemplateRegistry()
    template_registry.load()

    tcp_server = await asyncio.start_server(
        lambda r, w: handle_agent(r, w, registry),
        host=settings.agent_host,
        port=settings.agent_port,
    )
    log = logging.getLogger(__name__)
    log.info(
        "BT Bridge Broker started — agent TCP %s:%s  API %s:%s",
        settings.agent_host,
        settings.agent_port,
        settings.api_host,
        settings.api_port,
    )

    app.state.registry = registry
    app.state.template_registry = template_registry

    if settings.interactive:
        from broker.repl import run_repl
        asyncio.create_task(run_repl(registry))

    yield

    tcp_server.close()
    await tcp_server.wait_closed()
    log.info("BT Bridge Broker stopped")


def create_app_with_lifespan() -> FastAPI:
    from broker.api.app import create_app
    from broker.registry import AgentRegistry

    # Registry is created in lifespan; app.py needs a placeholder to wire routers
    placeholder = AgentRegistry()
    app = create_app(placeholder)
    app.router.lifespan_context = lifespan
    return app


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="BT Bridge Broker")
    parser.add_argument("--agent-host", default=settings.agent_host)
    parser.add_argument("--agent-port", type=int, default=settings.agent_port)
    parser.add_argument("--api-host", default=settings.api_host)
    parser.add_argument("--api-port", type=int, default=settings.api_port)
    parser.add_argument("--interactive", action="store_true", default=settings.interactive)
    parser.add_argument("--log", default=settings.log_file, dest="log_file")
    parser.add_argument("--debug", action="store_true", default=settings.debug)
    args = parser.parse_args()

    # Override settings from CLI args
    settings.agent_host = args.agent_host
    settings.agent_port = args.agent_port
    settings.api_host = args.api_host
    settings.api_port = args.api_port
    settings.interactive = args.interactive
    settings.log_file = args.log_file
    settings.debug = args.debug

    _configure_logging()

    app = create_app_with_lifespan()
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Fix app.py — registry should come from lifespan, not factory arg**

The `create_app` factory currently takes a registry argument and attaches it. When launched via `main.py`, the real registry is assigned in lifespan. Update `broker/api/app.py` to accept an optional registry and handle both modes:

```python
"""FastAPI app factory for the BT Bridge broker."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from broker.registry import AgentRegistry


def create_app(registry: AgentRegistry | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title="BT Bridge Broker",
        version="1.2.0",
        description="REST + WebSocket API for the BT Bridge hardware test harness.",
    )
    if registry is not None:
        app.state.registry = registry

    from broker.api.routes import router as rest_router
    from broker.api.ws import router as ws_router

    app.include_router(rest_router)
    app.include_router(ws_router)

    @app.exception_handler(Exception)
    async def _http_exc_handler(request: Request, exc: Exception) -> JSONResponse:
        from fastapi import HTTPException
        if isinstance(exc, HTTPException):
            detail = exc.detail
            if isinstance(detail, dict):
                return JSONResponse(status_code=exc.status_code, content=detail)
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": "http_error", "message": str(detail)},
            )
        return JSONResponse(status_code=500, content={"error": "internal_error", "message": str(exc)})

    return app
```

- [ ] **Step 3: Create TemplateRegistry stub (full implementation in Plan 2)**

`broker/template_registry.py`:
```python
"""Template registry stub — full implementation in Plan 2 (broker-template-system-plan)."""
from __future__ import annotations

import json
import logging
import pathlib
from typing import Any

log = logging.getLogger(__name__)

TEMPLATES_DIR = pathlib.Path(__file__).parent.parent / "templates"


class TemplateRegistry:
    """In-memory store of all template files loaded from disk.

    Key: (template_id, version_string) → full template dict.
    """

    def __init__(self, templates_dir: pathlib.Path | None = None) -> None:
        self._dir = templates_dir or TEMPLATES_DIR
        self._store: dict[tuple[str, str], dict[str, Any]] = {}

    def load(self) -> None:
        """Scan templates/ directory and load all *.json files."""
        if not self._dir.exists():
            log.info("templates/ directory not found — no templates loaded")
            return
        loaded = 0
        errors = 0
        for path in self._dir.rglob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                tid = data.get("id")
                ver = data.get("version")
                if not tid or not ver:
                    log.warning("Template %s missing id or version — skipped", path)
                    errors += 1
                    continue
                key = (tid, ver)
                if key in self._store:
                    log.error(
                        "Duplicate template (%s, %s): %s conflicts with existing",
                        tid, ver, path,
                    )
                    errors += 1
                    continue
                self._store[key] = data
                loaded += 1
            except Exception as exc:
                log.error("Failed to load template %s: %s", path, exc)
                errors += 1
        log.info("Templates loaded: %d ok, %d errors", loaded, errors)

    def list_all(self) -> list[dict[str, Any]]:
        return list(self._store.values())

    def get(self, template_id: str, version: str) -> dict[str, Any] | None:
        return self._store.get((template_id, version))

    def list_versions(self, template_id: str) -> list[str]:
        return [v for (tid, v) in self._store if tid == template_id]
```

- [ ] **Step 4: Create the empty templates/ directory**

> **Catalog-only model.** The broker ships **no** built-in templates. All templates live in the
> separate **`bt-bridge-templates`** catalog repo and are fetched on demand into this `templates/`
> directory by the catalog tooling (see **Plan 4: Catalog Integration**). The broker simply scans
> whatever is present in `templates/` at startup; a fresh checkout starts empty and renders via the
> agent's raw GATT analyser until the user installs templates from the catalog.

```bash
mkdir -p /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker/templates
touch /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker/templates/.gitkeep
```

> `templates/*.json` is gitignored (fetched content is not committed to the broker repo); only
> `.gitkeep` is tracked so the directory exists. Add this to `.gitignore` in Task 13.

- [ ] **Step 5: Smoke-test the broker starts**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
timeout 3 python3 -m broker.main --debug 2>&1 || true
```

Expected: startup log lines including "BT Bridge Broker started" then graceful shutdown after 3s.

- [ ] **Step 6: Run full test suite**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add broker/main.py broker/api/app.py broker/template_registry.py templates/.gitkeep
git commit -m "feat(main): entry point, pydantic-settings config, TemplateRegistry stub"
```

---

## Task 11: Delete ble_server.py and update requirements.txt header

**Files:**
- Delete: `ble_server.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Delete ble_server.py**

```bash
git rm /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker/ble_server.py
```

- [ ] **Step 2: Split runtime vs. dev/test dependencies**

> **Why split:** `httpx`, `httpx-ws`, `pytest`, and `pytest-asyncio` are **test-only** — they
> are not imported by the running broker. A FOSS consumer who just wants to *run* the broker
> should not be forced to install the test stack. Runtime deps go in `requirements.txt`; the
> test stack goes in `requirements-dev.txt`. This is standard Python FOSS layout and keeps the
> runtime install minimal.

Set `requirements.txt` (runtime only) to:
```text
# BT Bridge Broker — runtime dependencies
# Python 3.11 or later required (match statements, type union syntax).
# Install (runtime only):  pip install -r requirements.txt
# Install (with test deps): pip install -r requirements-dev.txt
# Reproducible install:     pip install -r requirements-lock.txt
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
pydantic-settings>=2.2.1
```

Create `requirements-dev.txt` (test/dev only):
```text
# BT Bridge Broker — development & test dependencies
# Includes the runtime set, then the test-only stack.
-r requirements.txt
httpx>=0.27.0
httpx-ws>=0.6.0
pytest>=8.2.0
pytest-asyncio>=0.23.0
```

> The `requirements-lock.txt` produced by `pip freeze` (Task 1 / Task 8) captures the full
> resolved set including test deps, since the dev environment installs `requirements-dev.txt`.

- [ ] **Step 3: Confirm examples/ scripts need updating (out of scope — note in commit)**

```bash
grep -r "ble_server\|BleServer" /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker/examples/
```

Note: examples still import from `ble_server`. They will be updated as a separate task (tracked in Plan 2 or separately) after the REST API is validated end-to-end.

- [ ] **Step 4: Run full test suite — confirm nothing broke**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt requirements-dev.txt
git commit -m "chore: remove ble_server.py, finalize runtime/dev requirements split"
```

---

## Task 12: ~~Initial builtin templates~~ → moved to the catalog repo

> **This task is intentionally removed.** Under the catalog-only model, the broker ships **no**
> built-in templates. The WeatherFlow Tactical, Niimbot, and shared GATT-component templates now
> live in the **`bt-bridge-templates`** catalog repository
> (`github.com/ColdBoreBallistics/bt-bridge-templates`), under `catalog/builtin/`, validated by
> that repo's own lint + index CI. The broker obtains them on demand via **Plan 4: Catalog
> Integration** (the `fetch_templates.py` CLI and the `/v1/templates/catalog` web selection page),
> which download selected templates into the broker's local `templates/` directory.
>
> Nothing is created in the broker repo for this task. The reference template content (correct
> design-§6 schema, confirmed WeatherFlow LE protocol, vendor UUIDs) is already authored in the
> catalog repo. Proceed to Task 13.

<details>
<summary>Historical: the original builtin template JSON (now in the catalog repo)</summary>

The following blocks are retained for reference only. **Do not create these files in the broker
repo.** Their canonical, maintained versions live in `bt-bridge-templates/catalog/builtin/`.

- [ ] ~~Step 1: Create templates/weatherflow-tactical/device.json~~ *(now `catalog/builtin/weatherflow-tactical/device.json`)*

```json
{
  "schema_version": 1,
  "id": "builtin.weatherflow-tactical-device",
  "version": "1.0.0",
  "type": "device",
  "name": "WeatherFlow Tactical",
  "manufacturer": "WeatherFlow",
  "description": "WeatherFlow Tactical wind/temp/humidity/pressure meter",
  "signature": {
    "service_uuids": ["961f0001-d2d6-43e3-a417-3bb8217e0e01"],
    "name_prefix": "WF"
  },
  "channels": [
    {
      "name": "weather_data",
      "service_uuid": "961f0001-d2d6-43e3-a417-3bb8217e0e01",
      "char_uuid": "961f0005-d2d6-43e3-a417-3bb8217e0e01",
      "operation": "notify"
    }
  ],
  "references": {
    "display": "builtin.weatherflow-tactical-display@^1.0.0"
  }
}
```

> **UUID note (confirmed protocol).** WeatherFlow Tactical uses vendor-specific 128-bit
> UUIDs — service `961f0001-d2d6-43e3-a417-3bb8217e0e01`, notify char
> `961f0005-d2d6-43e3-a417-3bb8217e0e01` — **not** the Bluetooth-base `...-0000-1000-8000-00805f9b34fb`
> form. A real device advertises the `-d2d6-…` UUIDs; signature matching and the agent's
> `startsWith` char match both fail if the base form is used. The design doc's §6.1 example
> uses the base form as an illustration only; these builtin templates use the real UUIDs.
> (Source: `scopedope-android` HCI-snoop RE; agent `Protocol.kt` `WF_NOTIFY_CHAR`.)

- [ ] **Step 2: Create templates/weatherflow-tactical/display-v1.json**

> **Schema + protocol authority.** This template MUST follow the design §6 display schema
> (`notifications[].views[].fields[]` with typed fields), because that is what the Plan 3
> Android `TemplateRenderer` and the Plan 2 component templates expect. The byte layout and
> scaling are the **confirmed** WeatherFlow Tactical protocol as implemented in the agent's
> `Protocol.kt` (`parseWeatherFlowFrame`), corroborated by the reverse-engineering record:
>
> | Offset | Encoding | Field | Conversion |
> |---|---|---|---|
> | 0 | `uint16_le` | wind speed raw | `× 1/1024` = mph |
> | 8 | `int16_le` | temperature | `× 0.1` = °C |
> | 10 | `uint8` | humidity | `%` (no scaling) |
> | 12 | `uint16_le` | pressure | `× 0.1` = hPa |
>
> **There is NO wind-direction field and NO density-altitude field** in the confirmed
> protocol — do not add them. Bytes 2–7 and 14–15 are not interpreted by the confirmed
> parser; they are left unmapped here (a future `raw` field can expose them once their
> meaning is reverse-engineered). The wind-speed unit is mph at source; m/s is derived via
> `expr` (`mph × 0.44704`) and °F via `expr` (`c × 9/5 + 32`) so every conversion is visible
> in the template rather than baked into an opaque scale constant.

```json
{
  "schema_version": 1,
  "id": "builtin.weatherflow-tactical-display",
  "version": "1.0.0",
  "type": "display",
  "name": "WeatherFlow Tactical Display",
  "author": "builtin",
  "min_broker_version": "1.0.0",
  "compatible_with": {
    "device_type": ["builtin.weatherflow-tactical"]
  },
  "default_view": "imperial",
  "notifications": [
    {
      "char": "961f0005-d2d6-43e3-a417-3bb8217e0e01",
      "description": "16-byte little-endian sensor frame (~1 Hz)",
      "views": {
        "raw": {
          "fields": [
            {
              "id": "wind_raw",
              "label": "Wind (raw u16le @0)",
              "type": "raw",
              "offset": 0,
              "length": 2,
              "encoding": "bytes",
              "display": true
            },
            {
              "id": "temp_raw",
              "label": "Temp (raw s16le @8)",
              "type": "raw",
              "offset": 8,
              "length": 2,
              "encoding": "bytes",
              "display": true
            },
            {
              "id": "humidity_raw",
              "label": "Humidity (raw u8 @10)",
              "type": "raw",
              "offset": 10,
              "length": 1,
              "encoding": "bytes",
              "display": true
            },
            {
              "id": "pressure_raw",
              "label": "Pressure (raw u16le @12)",
              "type": "raw",
              "offset": 12,
              "length": 2,
              "encoding": "bytes",
              "display": true
            }
          ]
        },
        "imperial": {
          "fields": [
            {
              "id": "wind_mph",
              "label": "Wind Speed",
              "type": "scale_offset",
              "offset": 0,
              "length": 2,
              "encoding": "uint16_le",
              "scale": 0.0009765625,
              "offset_value": 0.0,
              "unit": "mph",
              "precision": 1,
              "display": true
            },
            {
              "id": "temp_c",
              "label": "Temp C (internal)",
              "type": "scale_offset",
              "offset": 8,
              "length": 2,
              "encoding": "int16_le",
              "scale": 0.1,
              "offset_value": 0.0,
              "display": false
            },
            {
              "id": "temp_f",
              "label": "Temperature",
              "type": "expr",
              "expr": "temp_c * 9 / 5 + 32",
              "unit": "°F",
              "precision": 1,
              "display": true
            },
            {
              "id": "humidity",
              "label": "Humidity",
              "type": "scale_offset",
              "offset": 10,
              "length": 1,
              "encoding": "uint8",
              "scale": 1.0,
              "offset_value": 0.0,
              "unit": "%",
              "precision": 0,
              "display": true
            },
            {
              "id": "pressure_hpa",
              "label": "Pressure",
              "type": "scale_offset",
              "offset": 12,
              "length": 2,
              "encoding": "uint16_le",
              "scale": 0.1,
              "offset_value": 0.0,
              "unit": "hPa",
              "precision": 1,
              "display": true
            }
          ]
        },
        "metric": {
          "fields": [
            {
              "id": "wind_mph_hidden",
              "label": "Wind mph (internal)",
              "type": "scale_offset",
              "offset": 0,
              "length": 2,
              "encoding": "uint16_le",
              "scale": 0.0009765625,
              "offset_value": 0.0,
              "display": false
            },
            {
              "id": "wind_ms",
              "label": "Wind Speed",
              "type": "expr",
              "expr": "wind_mph_hidden * 0.44704",
              "unit": "m/s",
              "precision": 2,
              "display": true
            },
            {
              "id": "temp_c",
              "label": "Temperature",
              "type": "scale_offset",
              "offset": 8,
              "length": 2,
              "encoding": "int16_le",
              "scale": 0.1,
              "offset_value": 0.0,
              "unit": "°C",
              "precision": 1,
              "display": true
            },
            {
              "id": "humidity",
              "label": "Humidity",
              "type": "scale_offset",
              "offset": 10,
              "length": 1,
              "encoding": "uint8",
              "scale": 1.0,
              "offset_value": 0.0,
              "unit": "%",
              "precision": 0,
              "display": true
            },
            {
              "id": "pressure_hpa",
              "label": "Pressure",
              "type": "scale_offset",
              "offset": 12,
              "length": 2,
              "encoding": "uint16_le",
              "scale": 0.1,
              "offset_value": 0.0,
              "unit": "hPa",
              "precision": 1,
              "display": true
            }
          ]
        }
      }
    }
  ],
  "reads": []
}
```

- [ ] **Step 3: Create templates/niimbot-label-printer/device.json**

```json
{
  "schema_version": 1,
  "id": "builtin.niimbot-label-printer-device",
  "version": "1.0.0",
  "type": "device",
  "name": "Niimbot Label Printer",
  "manufacturer": "Niimbot",
  "description": "Niimbot thermal label printer — B1 / B21 Pro (ISSC UART-over-BLE)",
  "variants": [
    {
      "name": "B1",
      "name_prefix": "B1"
    },
    {
      "name": "B21 Pro",
      "name_prefix": "B21"
    }
  ],
  "signature": {
    "service_uuids": ["0000ff00-0000-1000-8000-00805f9b34fb"],
    "name_prefix": "B"
  },
  "channels": [
    {
      "name": "uart_write",
      "service_uuid": "0000ff00-0000-1000-8000-00805f9b34fb",
      "char_uuid": "0000ff02-0000-1000-8000-00805f9b34fb",
      "operation": "write"
    },
    {
      "name": "uart_notify",
      "service_uuid": "0000ff00-0000-1000-8000-00805f9b34fb",
      "char_uuid": "0000ff01-0000-1000-8000-00805f9b34fb",
      "operation": "notify"
    }
  ],
  "references": {
    "codec": "builtin.niimbot-uart-framed@^1.0.0"
  }
}
```

- [ ] **Step 4: Create templates/shared/codec.niimbot-uart-framed.json**

```json
{
  "schema_version": 1,
  "id": "builtin.niimbot-uart-framed",
  "version": "1.0.0",
  "type": "codec",
  "name": "Niimbot UART Framing",
  "description": "ISSC UART-over-BLE framing for Niimbot printers: 55 55 [cmd] [len_hi] [len_lo] [data...] [xor] AA AA",
  "frame": {
    "preamble": "5555",
    "postamble": "aaaa",
    "cmd_byte_offset": 2,
    "len_field": {
      "offset": 3,
      "length": 2,
      "endian": "big"
    },
    "data_offset": 5,
    "checksum": {
      "type": "xor",
      "covers": "cmd_and_data",
      "offset_from_end": 3
    }
  },
  "known_commands": {
    "0x01": "get_info_request",
    "0x02": "get_info_response",
    "0xA9": "start_print",
    "0xAF": "set_dimension",
    "0xBE": "set_quantity",
    "0x85": "get_rfid",
    "0xE3": "end_page",
    "0xF3": "end_print",
    "0x84": "get_print_status",
    "0xA3": "set_label_type",
    "0xA4": "set_label_density"
  }
}
```

- [ ] **Step 5: Run TemplateRegistry load smoke test**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
python3 -c "
from broker.template_registry import TemplateRegistry
tr = TemplateRegistry()
tr.load()
print('Loaded:', len(tr.list_all()), 'templates')
for t in tr.list_all():
    print(' ', t['id'], t['version'], t['type'])
"
```

Expected (historical — when these were broker builtins):
```
Loaded: 4 templates
  builtin.weatherflow-tactical-device 1.0.0 device
  builtin.weatherflow-tactical-display 1.0.0 display
  builtin.niimbot-label-printer-device 1.0.0 device
  builtin.niimbot-uart-framed 1.0.0 codec
```

</details>

> **Catalog-only smoke test (current model):** with an empty `templates/` directory, the load
> smoke test should report `Templates loaded: 0 ok, 0 quarantined` and the broker must start
> cleanly. Verify with:
>
> ```bash
> cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
> source .venv/bin/activate
> python3 -c "from broker.template_registry import TemplateRegistry; tr=TemplateRegistry(); tr.load(); print('Loaded:', len(tr.list_all()))"
> ```
>
> Expected: `Loaded: 0`. Templates appear here only after a catalog fetch (Plan 4).

---

## Task 13: Final integration smoke test and cleanup

**Files:**
- Modify: `__pycache__` — add to `.gitignore`

- [ ] **Step 1: Create/update .gitignore**

```text
__pycache__/
*.pyc
*.pyo
.venv/
*.egg-info/
.pytest_cache/
.ruff_cache/
dist/
build/

# Catalog-fetched templates are NOT committed to the broker repo — they are
# downloaded on demand from bt-bridge-templates (see Plan 4). Keep the directory
# (via .gitkeep) but ignore its fetched contents.
templates/*.json
templates/**/*.json
!templates/.gitkeep
```

- [ ] **Step 2: Run full test suite one final time**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
pytest tests/ -v --tb=short
```

Expected: all tests PASS, no warnings about unclosed resources.

- [ ] **Step 3: Start broker and verify Swagger UI is reachable**

```bash
cd /home/jschwefel/repositories/ColdBoreBallistics/bt-bridge-broker
source .venv/bin/activate
timeout 5 python3 -m broker.main --debug 2>&1 &
sleep 2
curl -s http://localhost:2673/docs | head -5 || echo "Swagger UI not reachable"
curl -s http://localhost:2673/v1/agents
```

Expected: HTML response from `/docs`, `[]` from `/v1/agents`.

- [ ] **Step 4: Verify agent TCP port is open**

```bash
ss -tlnp | grep 2653 || echo "port 2653 not listening"
```

Expected: a `LISTEN` line for port 2653.

- [ ] **Step 5: Kill background broker**

```bash
kill %1 2>/dev/null || true
```

- [ ] **Step 6: Final commit**

```bash
git add .gitignore
git commit -m "chore: gitignore, broker rewrite complete"
```

---

## Post-Plan Notes

- `examples/` scripts (`niimbot_b1_verify.py`, etc.) still import `ble_server.BleServer` — they are **out of scope for Plan 1** and will be updated in a follow-on task (tracked in Jira) to use the REST API instead.
- **The broker ships no built-in templates.** All templates live in the separate **`bt-bridge-templates`** catalog repo and are fetched on demand into `templates/` by the catalog tooling in **Plan 4 (Catalog Integration)**. A fresh broker checkout has an empty `templates/`; the agent renders via its raw GATT analyser until templates are installed.
- The TemplateRegistry created here is a stub. Full template push-to-agent, REST template endpoints (`/v1/templates/*`), dependency resolution, signature matching, and RE capture are covered in **Plan 2 (Broker Template System)**.
- Remote catalog fetch — `CatalogClient`, `tools/fetch_templates.py` CLI, `/v1/templates/catalog` endpoints, and the web selection page — is covered in **Plan 4 (Catalog Integration)**.
- Android template runtime (agent-side rendering, GATT analyser fallback, view selection) is covered in **Plan 3 (Android Template Runtime)**.
