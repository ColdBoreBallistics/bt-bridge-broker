# BT Bridge Broker — Rewrite Design

**Date:** 2026-06-08  
**Status:** Approved — ready for implementation  
**Replaces:** `ble_server.py` + `protocol.py` (v1 single-process server)

---

## 1. Context

The existing `ble_server.py` is a single asyncio TCP server that accepts one mobile agent connection and provides an interactive REPL. The rewrite splits it into a proper two-tier broker:

- **Agent tier** — existing TCP channel (PROTOCOL.md v1.1, port 2653), unchanged from the agent app's perspective
- **Test Client tier** — new FastAPI HTTP server (port 2673) exposing REST + WebSocket

The agent apps (`bt-bridge-agent-android`, `bt-bridge-agent-ios`) are **not changed**.

---

## 2. Technology Choices

| Layer | Technology | Rationale |
|---|---|---|
| Agent TCP server | `asyncio.start_server` | Unchanged pattern; native asyncio |
| HTTP / WebSocket | FastAPI + uvicorn | FOSS contributor ergonomics; Swagger UI at `/docs`; clean route definitions; Pydantic validation |
| Config | `pydantic-settings` | Included with FastAPI; env var + CLI arg support with zero boilerplate |
| Protocol messages | `protocol.py` | Unchanged dataclasses; shared by all layers |

**Dependencies added:** `fastapi`, `uvicorn[standard]`, `pydantic-settings`

---

## 3. Module Structure

```
bt-bridge-broker/
├── broker/
│   ├── __init__.py
│   ├── main.py           — entry point, CLI args, uvicorn launch, lifespan wiring
│   ├── registry.py       — AgentRegistry: all mutable state + event fan-out
│   ├── agent_tcp.py      — asyncio TCP server + AgentConnection per agent
│   ├── api/
│   │   ├── __init__.py
│   │   ├── app.py        — FastAPI app factory, mounts routers, lifespan hook
│   │   ├── routes.py     — all REST endpoints
│   │   └── ws.py         — WebSocket endpoint /v1/ws
│   └── repl.py           — optional interactive REPL (--interactive)
├── protocol.py           — unchanged
├── requirements.txt      — adds fastapi, uvicorn[standard], pydantic-settings
├── requirements-lock.txt — pinned versions for reproducible CI (new)
└── examples/             — unchanged
```

**Deleted:** `ble_server.py`

---

## 4. AgentRegistry

Single shared instance created in `lifespan`, injected into routes via `app.state`. All mutable state lives here; no other module holds agent state.

### State

```python
@dataclass
class AgentState:
    agent_id: str
    connection: AgentConnection
    platform: str | None
    capabilities: list[str]
    connected_since_ms: int
    ble_enabled: bool
    scanning: bool
    connected_devices: list[str]
    scan_results: list[ScanResultEntry]   # deduplicated, last 30s
    services: dict[str, list[Service]]    # keyed by device address
    last_status_ms: int
```

### Interface

```python
class AgentRegistry:
    # Lifecycle
    def register(connection: AgentConnection) -> str
    def unregister(agent_id: str) -> None
    def update_state(agent_id: str, event: Event) -> None   # hello/status → AgentState

    # Command dispatch
    async def send_command(agent_id: str, cmd: dict) -> None
    async def send_and_wait(
        agent_id: str, cmd: dict,
        match: Callable[[Event], bool],
        timeout: float
    ) -> Event   # raises TimeoutError on timeout

    # Agent resolution
    def get_agent(agent_id: str) -> AgentState | None
    def list_agents() -> list[AgentState]
    def resolve_agent(agent_id: str | None) -> AgentState
        # None + 1 connected  → auto-select
        # None + 0 connected  → 404
        # None + N>1 connected → 409
        # specified + found   → return
        # specified + missing → 404

    # Scan results (deduplicated cache)
    def get_scan_results(agent_id: str) -> list[ScanResultEntry]

    # WebSocket fan-out
    def subscribe() -> tuple[asyncio.Queue, int]   # returns (queue, token)
    def unsubscribe(token: int) -> None
    def publish(agent_id: str, event: Event) -> None
        # → puts envelope onto every subscriber queue
        # → enforces ring buffer: 1000 events max, 60s TTL per entry
```

### Scan result deduplication

`update_state` processes `scan_result` events:
- If address already in cache: update RSSI and `last_seen_ms`
- If new: add entry
- Expire entries where `now - last_seen_ms > 30_000`

Raw `scan_result` events are still published to WebSocket subscribers before deduplication — WebSocket clients see every advertisement. `GET /v1/scan/results` returns the deduplicated cache only.

### `send_and_wait` pattern

1. Generate a `req_id` (UUID4 short)
2. Register a one-shot `asyncio.Future` keyed by `req_id` in an internal waiters dict
3. Send the command (with `req_id` injected)
4. `await asyncio.wait_for(future, timeout=timeout)`
5. `update_state` / `publish` resolves the future when the matching event arrives
6. On timeout: remove waiter, raise `asyncio.TimeoutError` → route returns `504`

---

## 5. Agent TCP Layer (`agent_tcp.py`)

```python
class AgentConnection:
    agent_id: str
    _writer: asyncio.StreamWriter

    async def run(registry: AgentRegistry) -> None
        # readline loop → parse JSON → registry.update_state + registry.publish
        # IncompleteReadError / ConnectionResetError → registry.unregister

    async def send(raw_json: str) -> None
        # writes line to _writer; called only by registry

    async def close() -> None
```

**Connection lifecycle:**
1. TCP accept → create `AgentConnection`
2. `registry.register(conn)` → assigns `agent_id`
3. Send `{"cmd":"register","agent_id":"<id>"}` immediately
4. Publish `agent_connected` meta-event to WebSocket subscribers
5. Read loop runs until socket closes
6. `registry.unregister(agent_id)` → publish `agent_disconnected` meta-event

**Error handling:**
- Malformed JSON line → `log.warning`, skip line, keep connection
- `IncompleteReadError` (EOF) → clean unregister
- `ConnectionResetError` → clean unregister
- Any other exception → log error, unregister

**Protocol compatibility:** Wire format is PROTOCOL.md v1.1. `hello` and `status` events (v1.2) are handled by `registry.update_state`; agents that don't send them are treated as unknown capabilities and remain fully functional.

---

## 6. REST API (`api/routes.py`)

All routes share `agent: str | None = Query(default=None)` and call `registry.resolve_agent(agent)` at the top. All errors use `HTTPException` with body `{"error": "<code>", "message": "<text>"}` via a custom exception handler registered in `app.py`.

### Agent endpoints

| Method | Path | Returns | Notes |
|---|---|---|---|
| `GET` | `/v1/agents` | `200` list | All connected agents + state |
| `GET` | `/v1/agents/{agent_id}` | `200` single | `404` if not connected |

### Scan endpoints

| Method | Path | Returns | Notes |
|---|---|---|---|
| `POST` | `/v1/scan/start` | `202` | Body: `{timeout_ms?, name_filter?}` |
| `POST` | `/v1/scan/stop` | `200` | |
| `GET` | `/v1/scan/results` | `200` | Deduplicated cache |

### Device endpoints

| Method | Path | Returns | Notes |
|---|---|---|---|
| `POST` | `/v1/connect` | `202` | Body: `{address}` |
| `POST` | `/v1/disconnect` | `202` | Body: `{address}` |
| `POST` | `/v1/discover` | `202` | Body: `{address}` |
| `GET` | `/v1/services` | `200` | Query: `address=`. `404` if no discovery yet |

### Characteristic endpoints

| Method | Path | Returns | Notes |
|---|---|---|---|
| `POST` | `/v1/read` | `200` inline value | Synchronous via `send_and_wait`; `504` on timeout (5s) |
| `POST` | `/v1/write` | `200` or `202` | `200`+status if `rsp:true`; `202` if `rsp:false`; `504` on timeout (5s) |
| `POST` | `/v1/subscribe` | `200` | |
| `POST` | `/v1/unsubscribe` | `200` | |

### Utility endpoints

| Method | Path | Returns | Notes |
|---|---|---|---|
| `POST` | `/v1/ping` | `200 {latency_ms}` | `send_and_wait`; `504` on timeout (5s) |
| `POST` | `/v1/ask` | `200 {answered, value}` | `send_and_wait`; `504` on timeout (60s) |

### Pydantic request/response models

One `RequestModel` and `ResponseModel` per endpoint — defined in `api/routes.py` alongside the route. FastAPI picks them up automatically for Swagger UI and validation.

---

## 7. WebSocket Layer (`api/ws.py`)

**Endpoint:** `GET /v1/ws`  
**Query params:** `agent: str | None`, `events: str | None` (comma-separated type filter)

```python
@router.websocket("/v1/ws")
async def ws_endpoint(websocket, agent, events):
    queue, token = registry.subscribe()
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_drain_queue(websocket, queue, agent_filter, event_filter))
            tg.create_task(_receive_commands(websocket, registry))
    finally:
        registry.unsubscribe(token)
```

**`_drain_queue`:**
- On subscribe: replays buffered events (up to 1000, not older than 60s) that pass filters
- Then drains live events: dequeue → apply agent/event filters → send JSON text frame
- Envelope format: `{"agent_id": "...", "event": "...", ...all original fields}`

**`_receive_commands`:**
- Receives text frames from client
- Parses `agent_id` field → `registry.resolve_agent()`
- Removes `agent_id` from payload, forwards as command to agent TCP socket
- Same 409/404 rules as REST

**Filter logic:** Agent filter and event-type filter are ANDed. No filter = pass all.

**Disconnect handling:** Any `WebSocketDisconnect` or `asyncio.CancelledError` in either task cancels the `TaskGroup`, unsubscribes the queue, and exits cleanly.

---

## 8. REPL (`repl.py`)

Enabled by `--interactive` flag. Runs as an `asyncio.create_task` inside uvicorn's event loop.

**Active agent selection:**
- 0 agents: commands print `[no agent connected]` and are dropped
- 1 agent, none selected: auto-selects, prints `[auto-selected agent-001]`
- N>1 agents, none selected: prints `[use: agent set <id>]`, blocks command
- Multi-select: `agent set agent-001,agent-002` — subsequent commands fan out to all

**Commands:** Same vocabulary as the original `ble>` REPL plus:
```
agents                     list registered agents
agent set <id>[,<id>...]   set active agent(s)
agent clear                clear selection
```

REPL calls `registry` methods directly — not via HTTP. Same code paths as REST routes.

---

## 9. Entry Point & Configuration (`main.py`)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    registry = AgentRegistry()
    tcp_server = await asyncio.start_server(
        lambda r, w: handle_agent(r, w, registry),
        host=settings.agent_host,
        port=settings.agent_port,
    )
    if settings.interactive:
        asyncio.create_task(run_repl(registry))
    app.state.registry = registry
    yield
    tcp_server.close()
    await tcp_server.wait_closed()
```

**Configuration (`pydantic-settings`):**

| Setting | Env var | Default | CLI flag |
|---|---|---|---|
| Agent bind host | `BT_AGENT_HOST` | `0.0.0.0` | `--agent-host` |
| Agent TCP port | `BT_AGENT_PORT` | `2653` | `--agent-port` |
| API bind host | `BT_API_HOST` | `0.0.0.0` | `--api-host` |
| API HTTP port | `BT_API_PORT` | `2673` | `--api-port` |
| Interactive REPL | `BT_INTERACTIVE` | `false` | `--interactive` |
| Log file | `BT_LOG_FILE` | stdout | `--log` |
| Debug logging | `BT_DEBUG` | `false` | `--debug` |

**Launch:**
```bash
python3 -m broker.main
python3 -m broker.main --agent-port 2653 --api-port 2673 --interactive --debug
```

---

## 10. Error Handling Summary

| Scenario | Behaviour |
|---|---|
| No agent connected | `404 agent_not_found` |
| Multiple agents, no `?agent=` | `409 agent_ambiguous` |
| Agent disconnects mid-command | `send_and_wait` future resolves with error or times out → `504` |
| `send_and_wait` timeout | `504 timeout` |
| Malformed request body | FastAPI/Pydantic → `422 Unprocessable Entity` (automatic) |
| Malformed JSON from agent | Log warning, skip line, keep connection |
| Agent TCP disconnect | Unregister, publish `agent_disconnected`, pending `send_and_wait` futures cancelled |
| WebSocket client disconnect | Unsubscribe queue, cancel drain/receive tasks, no error |

---

## 11. Testing Strategy

- **Unit tests** for `AgentRegistry` in isolation: register/unregister, resolve_agent 409/404/auto-select, dedup logic, ring buffer eviction, `send_and_wait` timeout
- **Integration tests** using `httpx.AsyncClient` (FastAPI test client) + a mock `AgentConnection` that injects events into the registry — no real TCP or BLE required
- **Example scripts** in `examples/` serve as end-to-end smoke tests against a real agent

---

## 12. Template System Integration

The broker rewrite includes the broker-side half of the template system. Full template
system specification: `2026-06-08-template-system-design.md`.

### Broker responsibilities in this implementation

**Template registry (`broker/template_registry.py`):**
- Startup scan of `templates/` directory — builds `Map<(id, version), TemplateObject>`
- Semver-based dependency resolution; quarantines templates with unresolved `requires`
- Duplicate `(id, version)` detection — fatal at startup
- Reload on `POST /v1/templates/reload`

**Template REST endpoints (added to `api/routes.py`):**
- `GET /v1/templates` — list all templates
- `GET /v1/templates/{id}` — list versions
- `GET /v1/templates/{id}/{version}` — full template JSON
- `POST /v1/templates/reload` — rescan disk
- `POST /v1/templates/draft` — save template JSON to `templates/` directory
- `DELETE /v1/templates/{id}/{version}` — delete from disk
- `GET /v1/templates/match` — match a device signature against device templates

**Template push to agent (added to `agent_tcp.py`):**
- On agent connect: send `push_templates` manifest (all available template IDs + versions)
- Handle `template_request` events: send `template_data` for each requested template
- Handle `services_discovered` events: run signature match, send `apply_template` command
- Handle `view_changed` events: forward to WebSocket subscribers

**New REST endpoint:**
- `POST /v1/agents/{id}/view` — set active display view on a connected agent

**Module structure addition:**
```
broker/
└── template_registry.py    — TemplateRegistry class
```

**`templates/` directory** added to repo root with initial builtin templates:
```
templates/
├── weatherflow-tactical/
│   ├── device.json
│   └── display-v1.json
├── niimbot-label-printer/
│   ├── device.json
│   └── display-v1.json
└── shared/
    ├── codec.niimbot-uart-framed.json
    └── display.battery-service.json
```

---

## 13. Migration Notes

- `ble_server.py` is deleted; `protocol.py` is preserved unchanged
- Port defaults change: Agent `9876 → 2653`, API is new on `2673`
- Existing `examples/` scripts import `BleServer` from `ble_server` — they will need updating to use the REST/WebSocket client API (tracked separately, not in scope for this implementation)
- `requirements.txt` gains three packages; `requirements-lock.txt` is new
