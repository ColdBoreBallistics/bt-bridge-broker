# BT Bridge — Architecture Draft Specification

**Status:** DRAFT — open for review, not yet implemented  
**Date:** 2026-06-08  
**Replaces:** N/A (additive to existing PROTOCOL.md v1.1)

---

## 1. Overview

This document specifies a revised architecture for the BT Bridge system. The current
single-process server is split into two independent tiers:

- **Agent** — the mobile app (Android, iOS). Unchanged from current behavior. Connects to
  the Broker over TCP and executes BLE operations as commanded.
- **Broker** — a new middle tier. Manages Agent registration, multiplexes Test Client
  connections, and proxies commands and events between them.
- **Test Client** — any consumer of the Broker's public API: a Python script, CI pipeline,
  REPL, or external tool.

The Agent ↔ Broker wire protocol (newline-delimited JSON over TCP) is preserved from
PROTOCOL.md v1.1 with minor additions for registration and status reporting. The Broker ↔
Test Client interface is new and is the primary subject of this document.

```
┌──────────────────────────────────────────────────────────────────┐
│  Test Clients (one or more, concurrent)                          │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ Python script│  │  REST client │  │  Interactive REPL      │ │
│  │ (CI/pytest)  │  │  (curl/HTTP) │  │  (built-in to Broker)  │ │
│  └──────┬───────┘  └──────┬───────┘  └───────────┬────────────┘ │
│         │  WebSocket      │  REST/HTTP            │  (in-proc)   │
└─────────┼─────────────────┼───────────────────────┼──────────────┘
          │                 │                        │
┌─────────▼─────────────────▼────────────────────────▼─────────────┐
│  Broker (bt-bridge-broker)                                       │
│                                                                   │
│  - Agent registry (one or more agents, by agent_id)              │
│  - REST API   (HTTP, port 2673) — operations + agent status       │
│  - WebSocket  (HTTP upgrade, /ws) — streaming events             │
│  - TCP server (port 2653) — existing Agent ↔ Broker channel      │
│  - Optional interactive REPL (stdin/stdout)                       │
└──────────────────────────────┬────────────────────────────────────┘
                               │ TCP port 2653
                               │ Newline-delimited JSON (PROTOCOL.md v1.x)
          ┌────────────────────┴────────────────────┐
          │                                         │
┌─────────▼───────────────┐             ┌───────────▼─────────────┐
│  Agent: bt-bridge-        │             │  Agent: bt-bridge-agent-ios  │
│  android                 │             │  (future)               │
│  BLE Central (Android)   │             │  BLE Central (iOS)      │
└─────────┬───────────────┘             └───────────┬─────────────┘
          │ BLE                                     │ BLE
   ┌──────┴──────┐                           ┌──────┴──────┐
   │  BLE Device │                           │  BLE Device │
   └─────────────┘                           └─────────────┘
```

---

## 2. Terminology

| Term | Definition |
|---|---|
| **Agent** | A mobile app instance (Android or iOS) registered with the Broker |
| **Broker** | The server process that mediates between Agents and Test Clients |
| **Test Client** | Any process that drives BLE operations via the Broker's REST/WebSocket API |
| **agent_id** | A string identifier assigned by the Broker when an Agent connects |
| **Session** | The lifetime of a single Agent TCP connection to the Broker |
| **Event** | A JSON message from Agent → Broker → Test Client describing a BLE state change |
| **Command** | A JSON message from Test Client → Broker → Agent requesting a BLE operation |

---

## 3. Agent ↔ Broker Protocol (Internal)

The existing PROTOCOL.md v1.1 wire format is preserved. The Agent is **not changed**.

### 3.1 Agent Registration

When an Agent connects, the Broker assigns it a unique `agent_id` (e.g., a short UUID or
sequential integer string) and immediately sends a `register` command:

```json
{"cmd":"register","agent_id":"agent-001"}
```

The Agent does not need to respond. The `agent_id` is for Broker and Test Client use only.
The Agent app may display it in the UI for debugging.

### 3.2 Agent Status Events (new in v1.2)

Agents emit two new events to support the registry:

#### `hello`
Sent immediately after the TCP connection is established (before any other message).
Provides the Broker with platform and capability metadata.

```json
{
  "event": "hello",
  "platform": "android",
  "platform_version": "15",
  "app_version": "1.0.0",
  "capabilities": ["scan", "connect", "read", "write", "subscribe", "ask"],
  "ts": 1748982600000
}
```

| Field | Type | Description |
|---|---|---|
| `platform` | string | `"android"` or `"ios"` |
| `platform_version` | string | OS version string |
| `app_version` | string | App build version |
| `capabilities` | array of strings | Operations this Agent supports |

#### `status`
Periodic heartbeat emitted by the Agent every 5 seconds. Includes current BLE state.

```json
{
  "event": "status",
  "ble_enabled": true,
  "scanning": false,
  "connected_devices": ["AA:BB:CC:DD:EE:FF"],
  "scan_results": [
    {"address": "AA:BB:CC:DD:EE:FF", "name": "WF-1A2B3C4D", "rssi": -65, "last_seen_ms": 1200}
  ],
  "ts": 1748982605000
}
```

| Field | Type | Description |
|---|---|---|
| `ble_enabled` | boolean | Whether Bluetooth is on and permissions granted |
| `scanning` | boolean | Whether a scan is currently active |
| `connected_devices` | array of strings | `address` values of currently connected GATT devices |
| `scan_results` | array | Most recent scan results, with `last_seen_ms` (ms since last advertisement) |

The Broker caches the latest `status` per Agent and surfaces it via the REST API.

---

## 4. Broker ↔ Test Client API

The Broker exposes two complementary interfaces on a single HTTP server (default port `2673`):

| Interface | Purpose | Best for |
|---|---|---|
| **REST API** | Request/response operations — scan, connect, read, write, agent status | Scripts, CI, one-shot queries |
| **WebSocket** | Streaming events — notifications, scan results, status updates | Real-time monitoring, long-running subscriptions |

These are complementary, not redundant. A typical automated test uses REST to issue commands
and WebSocket to receive the resulting events.

### 4.1 General Conventions

- **Base path:** `http://<host>:2673/v1/`
- **Content-Type:** `application/json` for all requests and responses
- **Agent targeting:** Most endpoints accept `?agent=<agent_id>`. If omitted and exactly one
  Agent is connected, it is selected automatically. If omitted and multiple Agents are
  connected, the request returns `409 Conflict`.
- **Async operations:** Commands that produce BLE events (connect, read, scan, etc.) return
  `202 Accepted` immediately. Results arrive via WebSocket. REST polling endpoints (e.g.,
  `GET /v1/agents/{id}/scan`) return the cached result buffer for clients that cannot use
  WebSocket.
- **Error format:**
  ```json
  {"error": "agent_not_found", "message": "No agent with id 'agent-007' is connected"}
  ```

---

### 4.2 Agent Registry — REST

#### `GET /v1/agents`
List all connected Agents.

**Response 200:**
```json
{
  "agents": [
    {
      "agent_id": "agent-001",
      "platform": "android",
      "platform_version": "15",
      "app_version": "1.0.0",
      "connected_since": 1748982600000,
      "ble_enabled": true,
      "scanning": false,
      "connected_devices": ["AA:BB:CC:DD:EE:FF"],
      "scan_results": [
        {"address": "AA:BB:CC:DD:EE:FF", "name": "WF-1A2B3C4D", "rssi": -65, "last_seen_ms": 1200}
      ],
      "capabilities": ["scan", "connect", "read", "write", "subscribe", "ask"]
    }
  ]
}
```

---

#### `GET /v1/agents/{agent_id}`
Get status for a single Agent. Returns the same object as one entry in the `agents` array above.

**Errors:** `404` if agent not connected.

---

### 4.3 BLE Operations — REST

All BLE operation endpoints accept an optional `?agent=<agent_id>` query parameter.

---

#### `POST /v1/scan/start`
Start a BLE scan.

**Request body:**
```json
{"timeout_ms": 10000, "name_filter": "WF-"}
```
Both fields optional. Mirrors `scan_start` command in PROTOCOL.md.

**Response 202:** Scan started. Events arrive via WebSocket (`scan_result` type).

**Response 409:** A scan is already in progress on this Agent.

---

#### `POST /v1/scan/stop`
Stop an active scan.

**Response 200:** `{"status": "stopped"}`

---

#### `GET /v1/scan/results`
Return the current scan result buffer (most recent advertisement per device, last 30 seconds).
For clients that poll instead of using WebSocket.

**Response 200:**
```json
{
  "results": [
    {"address": "AA:BB:CC:DD:EE:FF", "name": "WF-1A2B3C4D", "rssi": -65, "last_seen_ms": 800}
  ]
}
```

---

#### `POST /v1/connect`
Initiate a GATT connection.

**Request body:**
```json
{"address": "AA:BB:CC:DD:EE:FF"}
```

**Response 202:** Connection attempt started. Wait for `connected` event via WebSocket.

---

#### `POST /v1/disconnect`
Drop a GATT connection.

**Request body:**
```json
{"address": "AA:BB:CC:DD:EE:FF"}
```

**Response 202:** Disconnect sent. Wait for `disconnected` event via WebSocket.

---

#### `POST /v1/discover`
Run service/characteristic discovery on a connected device.

**Request body:**
```json
{"address": "AA:BB:CC:DD:EE:FF"}
```

**Response 202:** Discovery started. Wait for `services_discovered` event via WebSocket.

---

#### `GET /v1/services`
Return cached service/characteristic list for a connected device (populated after `discover`).

**Query params:** `?address=AA:BB:CC:DD:EE:FF&agent=agent-001`

**Response 200:**
```json
{
  "address": "AA:BB:CC:DD:EE:FF",
  "services": [
    {
      "uuid": "961f0001-0000-1000-8000-00805f9b34fb",
      "chars": [
        {"uuid": "961f0005-0000-1000-8000-00805f9b34fb", "props": ["notify"]}
      ]
    }
  ]
}
```

**Response 404:** Device not connected or discovery not yet run.

---

#### `POST /v1/read`
Read a characteristic value. Synchronous — waits for `read_result` and returns it inline.

**Request body:**
```json
{"address": "AA:BB:CC:DD:EE:FF", "char": "00002a19-0000-1000-8000-00805f9b34fb"}
```

**Response 200:**
```json
{"address": "AA:BB:CC:DD:EE:FF", "char": "00002a19-0000-1000-8000-00805f9b34fb", "value": "5a", "status": 0}
```

**Response 504:** Read timed out (default 5 seconds).

> Read is offered as synchronous REST because the request/response pattern maps cleanly.
> The Broker generates a `req_id` internally, awaits `read_result`, and returns it.

---

#### `POST /v1/write`
Write a characteristic value.

**Request body:**
```json
{
  "address": "AA:BB:CC:DD:EE:FF",
  "char": "0000fff1-0000-1000-8000-00805f9b34fb",
  "value": "55aa01",
  "rsp": true
}
```

**Response 200** (if `rsp: true`): `{"status": 0}` once `write_result` received.  
**Response 202** (if `rsp: false`): Fire-and-forget; no result.  
**Response 504:** Write timed out (default 5 seconds).

---

#### `POST /v1/subscribe`
Enable notifications on a characteristic. After this call, `notification` events stream
via WebSocket until `unsubscribe` is called.

**Request body:**
```json
{"address": "AA:BB:CC:DD:EE:FF", "char": "961f0005-0000-1000-8000-00805f9b34fb"}
```

**Response 200:** `{"status": "subscribed"}`

---

#### `POST /v1/unsubscribe`
Disable notifications.

**Request body:**
```json
{"address": "AA:BB:CC:DD:EE:FF", "char": "961f0005-0000-1000-8000-00805f9b34fb"}
```

**Response 200:** `{"status": "unsubscribed"}`

---

#### `POST /v1/ping`
Ping a connected Agent.

**Response 200:** `{"latency_ms": 12}`

---

#### `POST /v1/ask`
Push a Yes/No question to the Agent's screen. Synchronous — waits for `answer` or `dismiss`.

**Request body:**
```json
{"question": "Does the wind reading match the reference anemometer?"}
```

**Response 200:**
```json
{"answered": true, "value": true}
```
`answered: false` if the operator dismissed without answering.

**Response 504:** No answer within timeout (default 60 seconds).

---

### 4.4 WebSocket API

Connect to `ws://<host>:2673/v1/ws` to receive a stream of events from all connected
Agents (or a filtered subset).

#### Upgrade request (optional filter via query params)

```
ws://localhost:2673/v1/ws?agent=agent-001&events=notification,scan_result
```

| Query param | Description |
|---|---|
| `agent` | Filter to events from a specific Agent. Omit for all Agents. |
| `events` | Comma-separated event type filter. Omit for all event types. |

#### Event envelope

All events forwarded over WebSocket are wrapped in an envelope that adds the source Agent:

```json
{
  "agent_id": "agent-001",
  "event": "notification",
  "address": "AA:BB:CC:DD:EE:FF",
  "char": "961f0005-0000-1000-8000-00805f9b34fb",
  "value": "574650534d000000000000000000",
  "ts": 1748982610000
}
```

The `event` field and all original fields from PROTOCOL.md are preserved. `agent_id` is
added by the Broker.

#### Event types forwarded

All Agent events defined in PROTOCOL.md are forwarded:
`scan_result`, `connected`, `disconnected`, `services_discovered`, `notification`,
`read_result`, `write_result`, `error`, `pong`, `answer`, `dismiss`, `log`

Plus two Broker-generated meta-events:

#### `agent_connected` (Broker meta-event)
Emitted to all WebSocket clients when a new Agent registers.

```json
{"agent_id": "agent-001", "event": "agent_connected", "platform": "android", "ts": 1748982600000}
```

#### `agent_disconnected` (Broker meta-event)
Emitted to all WebSocket clients when an Agent TCP connection closes.

```json
{"agent_id": "agent-001", "event": "agent_disconnected", "ts": 1748982700000}
```

#### Sending commands via WebSocket (optional)

Test Clients may also send commands via WebSocket (in addition to REST). This allows a
WebSocket-only client to issue operations without a separate HTTP request.

Command envelope (Test Client → Broker via WebSocket):

```json
{
  "cmd": "scan_start",
  "agent_id": "agent-001",
  "timeout_ms": 10000,
  "name_filter": "WF-"
}
```

The `agent_id` field selects the target Agent. All other fields mirror the command
definitions in PROTOCOL.md. The Broker strips `agent_id`, adds `cmd`, and forwards
to the appropriate Agent.

---

### 4.5 Interactive REPL (built-in to Broker)

The existing interactive REPL from `ble_server.py` is preserved as an optional mode.
When `--interactive` is passed on the Broker command line, it starts a stdin/stdout
REPL that drives commands through the same internal dispatch layer as REST and WebSocket
clients. This is implemented as a built-in Test Client, not a separate process.

When multiple Agents are connected, the REPL maintains an "active agent" selection
(`agent set <agent_id>`). All commands apply to the active agent.

```
ble> agents                    # list registered agents
ble> agent set agent-001       # set active agent
ble> scan WF-                  # scan via active agent
ble> connect AA:BB:CC:DD:EE:FF
ble> discover
ble> sub 961f0005-...
ble> ping
ble> disconnect
ble> quit
```

---

## 5. Broker Configuration

Command-line options (all optional, with defaults):

| Option | Default | Description |
|---|---|---|
| `--agent-host` | `0.0.0.0` | Bind address for Agent TCP listener |
| `--agent-port` | `2653` | Port for Agent TCP connections |
| `--api-host` | `0.0.0.0` | Bind address for REST/WebSocket HTTP server |
| `--api-port` | `2673` | Port for REST/WebSocket |
| `--interactive` | off | Enable REPL on stdin/stdout |
| `--log` | stdout | Log file path |
| `--debug` | off | Verbose debug logging |

All options can also be set via environment variables (`BLE_AGENT_PORT`, `BLE_API_PORT`, etc.)
for container/CI use.

---

## 6. Authentication and Security

**v1.0 scope: no authentication.** The Broker is designed for use on a trusted local
network (lab environment, CI VLAN, developer workstation). No API keys, no TLS in v1.0.

Future considerations (not in scope for v1.0):
- Static API key via `Authorization: Bearer <token>` header
- mTLS for Agent ↔ Broker channel
- Per-client WebSocket session tokens

> Anyone on the same network as the Broker can drive BLE operations. Deploy accordingly.

---

## 7. Alternative Radio Backends (Non-Phone)

The Agent protocol is not inherently mobile-specific. The same PROTOCOL.md v1.2 wire
format can be implemented by non-phone BLE radio backends, enabling flexibility in test
infrastructure.

### 7.1 ESP32 + ESPHome

An ESP32 development board ($5–$20) running ESPHome firmware with Bluetooth Proxy enabled
connects to the local WiFi network and exposes BLE via the ESPHome native binary API.

A thin Python adapter process (`bt-bridge-agent-esphome`) could:
1. Connect to the ESP32 via the `bleak-esphome` Python library
2. Translate incoming BLE events to PROTOCOL.md JSON
3. Connect to the Broker as if it were a mobile Agent

This would allow Python scripts and the interactive REPL to drive the ESP32 through the
same REST/WebSocket interface as a phone Agent — with zero changes to the Broker.

**Capabilities:** Full GATT (scan, connect, read, write, notify). No `ask` command
(no operator screen). Up to ~5 active BLE connections per ESP32.

**Not yet designed or implemented.** The architecture must not preclude this path:
- `capabilities` field in `hello` handles missing `ask`
- `agent_id` in all API calls handles multi-backend scenarios
- The `platform` field in `hello` would be `"esphome"` or `"rpi"` for non-phone agents

### 7.2 Raspberry Pi

A Raspberry Pi (any model with onboard or USB Bluetooth) running Linux and BlueZ can
implement the same thin adapter using `bleak` (Python BLE library for BlueZ/macOS/Windows).
Capabilities identical to ESP32 path above.

Cost: $15–$80 depending on model. Unlike ESP32, the Pi can also run the Broker itself,
making it a self-contained BLE test node.

### 7.3 Desktop (Linux/macOS/Windows)

Any machine with a Bluetooth adapter can run the same thin adapter using `bleak` directly
(no ESP32 or Pi required) — useful for local development when the device under test is
on the same desk.

### 7.4 Design Constraint

**The Broker must treat all Agent types identically.** The only differences are expressed
via the `capabilities` array in the `hello` event. The Broker must not special-case
`platform == "android"` anywhere in its dispatch logic.

---

## 8. Versioning and Migration

### Protocol version bump: v1.1 → v1.2

Changes from PROTOCOL.md v1.1:
- New Agent → Broker events: `hello`, `status`
- New Broker → Agent command: `register`
- All existing events and commands unchanged

Agent apps (Android/iOS) must emit `hello` on connect and `status` every 5 seconds.
Existing Agent builds that do not emit `hello`/`status` remain functional — the Broker
treats a missing `hello` as an Agent with unknown capabilities, and an absent `status`
as stale state.

### REST/WebSocket API versioning

The API base path includes a version prefix (`/v1/`). Breaking changes increment to `/v2/`.
Additive changes (new endpoints, new optional fields) do not change the version.

---

## 9. Decisions

All open questions resolved 2026-06-08:

1. **Multiple Agents, ambiguous operation — RESOLVED:** Return `409 Conflict`. Explicit
   `?agent=<id>` required whenever more than one Agent is connected. No implicit broadcast.

2. **Event buffering — RESOLVED:** Yes. Per-client ring buffer: 1000 events, 60-second TTL.
   Allows brief WebSocket disconnects (network hiccup, client restart) to resume without
   missing events.

3. **Scan result deduplication — RESOLVED:** Deduplicate. Broker forwards only on meaningful
   change; `GET /v1/scan/results` returns deduplicated cache. Prevents WebSocket flooding
   from high-frequency advertisers.

4. **REPL multi-agent UX — RESOLVED:** Auto-select when exactly one Agent is connected.
   Require explicit `agent set <id>` when more than one is connected. Multi-agent commands
   must be explicitly issued per-agent — no implicit broadcast from the REPL either.
   Multi-select supported but must be explicit (`agent set agent-001,agent-002`).

5. **Python client library — RESOLVED:** Not a priority. Raw `requests`/`websockets` is
   sufficient for scripted use. Revisit if adoption warrants it.

6. **FOSS licensing — RESOLVED:** Apache-2.0.

---

## 10. Out of Scope for v1.0

- Authentication / API keys
- TLS on any channel
- Persistent event log / database
- Web UI (browser-based dashboard)
- Agent auto-discovery (mDNS / Zeroconf)
- Firmware OTA via BLE (no DFU support)
- BLE pairing / bonding orchestration
- Multi-peripheral concurrent GATT operations from a single Test Client request

---

## Appendix A: Example — Python Test Script (proposed API)

```python
import asyncio
from ble_bridge_client import BleClient  # proposed thin client library

async def test_weatherflow():
    async with BleClient("localhost", 8080) as client:
        # Wait for an agent to connect
        agent = await client.wait_for_agent(timeout=30.0)
        print(f"Agent ready: {agent.agent_id} ({agent.platform})")

        # Scan for WeatherFlow
        await client.scan_start(agent_id=agent.agent_id, name_filter="WF-", timeout_ms=15000)
        result = await client.wait_for_event("scan_result", timeout=20.0)
        print(f"Found: {result['address']} ({result['name']}) RSSI={result['rssi']}")

        # Connect and discover
        await client.connect(result["address"])
        await client.wait_for_event("connected")
        await client.discover(result["address"])
        svcs = await client.wait_for_event("services_discovered")

        # Subscribe and read 10 notifications
        notify_char = "961f0005-0000-1000-8000-00805f9b34fb"
        await client.subscribe(result["address"], notify_char)
        for i in range(10):
            evt = await client.wait_for_event("notification", char=notify_char)
            print(f"  [{i}] {evt['value']}")

        await client.unsubscribe(result["address"], notify_char)
        await client.disconnect(result["address"])

asyncio.run(test_weatherflow())
```

---

## Appendix B: Example — curl (REST, no scripting required)

```bash
# List agents
curl http://localhost:2673/v1/agents

# Start a scan on agent-001
curl -X POST http://localhost:2673/v1/scan/start?agent=agent-001 \
     -H "Content-Type: application/json" \
     -d '{"timeout_ms": 10000, "name_filter": "WF-"}'

# Read battery level (synchronous — blocks until result)
curl -X POST http://localhost:2673/v1/read?agent=agent-001 \
     -H "Content-Type: application/json" \
     -d '{"address": "AA:BB:CC:DD:EE:FF", "char": "00002a19-0000-1000-8000-00805f9b34fb"}'

# Subscribe to notifications, then stream events via WebSocket in a separate terminal:
# wscat -c "ws://localhost:2673/v1/ws?agent=agent-001&events=notification"
curl -X POST http://localhost:2673/v1/subscribe?agent=agent-001 \
     -H "Content-Type: application/json" \
     -d '{"address": "AA:BB:CC:DD:EE:FF", "char": "961f0005-0000-1000-8000-00805f9b34fb"}'
```

---

## Appendix C: Relationship to PROTOCOL.md

`PROTOCOL.md` remains the authoritative spec for the **Agent ↔ Broker** wire protocol.
This document specifies the **Broker ↔ Test Client** API and the Agent registration
extensions (Section 3). When this spec is ratified, PROTOCOL.md will be updated to v1.2
to incorporate the `hello`, `status`, and `register` additions.
