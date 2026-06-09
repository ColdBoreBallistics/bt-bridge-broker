# BT Bridge Protocol

This document is the **authoritative specification** for the BT Bridge **agent wire protocol** —
the newline-delimited JSON spoken between the broker and an agent app over TCP. All agent
implementations (Android, iOS, and any future ports) must conform to it. The canonical copy lives
in the `bt-bridge-broker` repository. The version is recorded in the revision-control block at the
end of this document.

> The REST + WebSocket API that test *clients* use to drive the broker is a separate surface,
> documented by the broker's OpenAPI schema (`/docs`) and `README.md`. This file specifies only the
> broker↔agent TCP protocol.

---

## Overview

The BT Bridge harness is **two-tier**. An **agent app** (the Bluetooth side) connects to the
**broker** over a local TCP connection and acts as a BT Agent — it scans, connects to, and
exchanges data with Bluetooth peripherals. The broker drives the agent by sending commands, and the
agent sends events back for every Bluetooth state change. Separately, the broker exposes a REST +
WebSocket API on a second port so test clients (scripts, the interactive REPL, a browser) can issue
those commands and observe the event stream.

```
   Test clients (curl / scripts / browser / REPL)
        │  REST + WebSocket  (broker API, default 127.0.0.1:2673)
        ▼
┌─────────────────────────────────────────────────────┐
│  bt-bridge-broker                                    │
│  - AgentRegistry: all connected-agent state          │
│  - REST + WebSocket API for test clients             │
│  - agent TCP server (this protocol)                  │
└───────────────────┬──────────────────────────────────┘
                    │ TCP (agent port, default 127.0.0.1:2653)
                    │ newline-delimited JSON  ← THIS SPEC
┌───────────────────┴──────────────────────────────────┐
│  Agent app (bt-bridge-agent-android / -ios)          │
│  - TCP client: connects to the broker                │
│  - BT Central: scans, connects, reads, writes        │
└───────────────────┬──────────────────────────────────┘
                    │ BLE
     ┌──────────────┴───────────────┐
     │  BLE Peripheral(s)           │
     │  e.g. WeatherFlow Tactical,  │
     │  Niimbot B1, Niimbot B21 Pro │
     └──────────────────────────────┘
```

---

## Transport

| Property | Value |
|---|---|
| Protocol | TCP |
| Default agent port | `2653` |
| Direction | Agent app initiates the TCP connection to the broker |
| Framing | Newline-delimited JSON — one JSON object per line, terminated with `\n` |
| Encoding | UTF-8 |
| Byte arrays | Lowercase hex string, no `0x` prefix (e.g., `"1a2b3c"`) |
| Timestamps | Unix epoch milliseconds, integer field `"ts"` |
| UUIDs | Lowercase with hyphens, full 128-bit form (e.g., `"0000180f-0000-1000-8000-00805f9b34fb"`) |

The broker **listens** for agents on the agent port (default `127.0.0.1:2653`; bind `0.0.0.0` to
accept agents over the LAN). The agent app **connects** to the broker's IP and agent port — the IP
is entered by the user in the agent UI before connecting. The broker's REST + WebSocket API for
test clients listens separately (default `127.0.0.1:2673`) and is out of scope for this document.

On each new agent connection the broker assigns an `agent_id` (`agent-NNN`) and immediately sends a
`register` command (see Commands) so the agent learns its id.

---

## Message Structure

Every message is a single JSON object on one line.

**Agent → Broker messages** have a top-level `"event"` field.
**Broker → Agent messages** have a top-level `"cmd"` field.

The broker republishes agent events to its WebSocket subscribers, wrapping each in an envelope
that adds the originating `"agent_id"`. Agents do not see that envelope; it is part of the
broker↔client API, not this protocol.

---

## Broker-originated lifecycle events

The broker itself emits two lifecycle events into its event stream (they are not sent *by* the
agent, but they describe the agent connection and appear alongside agent events on the broker's
WebSocket fan-out):

### `agent_connected`
Emitted when an agent's TCP connection is accepted and registered.

```json
{"event":"agent_connected","peer":"127.0.0.1:54xxx","ts":1748982600000}
```

### `agent_disconnected`
Emitted when an agent's TCP connection closes.

```json
{"event":"agent_disconnected","ts":1748982699000}
```

Both carry the originating `agent_id` in the broker's WebSocket envelope.

---

## Events (Agent → Broker)

### `scan_result`
Emitted for each BLE advertisement received during a scan.

```json
{"event":"scan_result","address":"AA:BB:CC:DD:EE:FF","name":"WF-1A2B3C4D","rssi":-65,"ts":1748982600000}
```

| Field | Type | Description |
|---|---|---|
| `address` | string | BLE MAC address (Android) or UUID (iOS — CoreBluetooth uses UUIDs, not MACs) |
| `name` | string \| null | Advertised device name; `null` if not present |
| `rssi` | integer | Signal strength in dBm |
| `ts` | integer | Timestamp (Unix ms) |

> **iOS note:** CoreBluetooth does not expose MAC addresses on iOS 13+. Use the `CBPeripheral.identifier`
> UUID string instead. The server and all test scripts must treat `address` as an opaque string
> identifier and not assume MAC format.

---

### `connected`
Emitted when a GATT connection is established.

```json
{"event":"connected","address":"AA:BB:CC:DD:EE:FF","ts":1748982601000}
```

---

### `disconnected`
Emitted when a GATT connection is dropped.

```json
{"event":"disconnected","address":"AA:BB:CC:DD:EE:FF","code":0,"ts":1748982602000}
```

| Field | Type | Description |
|---|---|---|
| `code` | integer | Platform disconnect/GATT status code. `0` = clean disconnect. Non-zero = error. |

---

### `services_discovered`
Emitted after service discovery completes on a connected device.

```json
{
  "event": "services_discovered",
  "address": "AA:BB:CC:DD:EE:FF",
  "services": [
    {
      "uuid": "0000180f-0000-1000-8000-00805f9b34fb",
      "chars": [
        {
          "uuid": "00002a19-0000-1000-8000-00805f9b34fb",
          "props": ["read", "notify"]
        }
      ]
    }
  ],
  "ts": 1748982603000
}
```

**Characteristic property values:** `"read"`, `"write"`, `"write_no_response"`, `"notify"`, `"indicate"`.

---

### `notification`
Emitted when a subscribed characteristic sends a notification or indication.

```json
{"event":"notification","address":"AA:BB:CC:DD:EE:FF","char":"961f0005-0000-1000-8000-00805f9b34fb","value":"57465053 4d000000 00000000 00000000","ts":1748982604000}
```

| Field | Type | Description |
|---|---|---|
| `char` | string | Characteristic UUID |
| `value` | string | Raw bytes as lowercase hex |

> **Formatting note:** Hex strings may include spaces for readability in logs; implementations
> must strip spaces before parsing.

---

### `read_result`
Response to a `read` command.

```json
{"event":"read_result","address":"AA:BB:CC:DD:EE:FF","char":"00002a19-0000-1000-8000-00805f9b34fb","value":"5a","status":0,"req_id":"a1b2c3d4","ts":1748982605000}
```

| Field | Type | Description |
|---|---|---|
| `status` | integer | `0` = success. Non-zero = platform GATT error code. |
| `req_id` | string | Echoed from the originating `read` command |

---

### `write_result`
Response to a `write` command sent with `"rsp": true`.

```json
{"event":"write_result","address":"AA:BB:CC:DD:EE:FF","char":"0000fff1-0000-1000-8000-00805f9b34fb","status":0,"req_id":"e5f6a7b8","ts":1748982606000}
```

---

### `error`
Emitted when an unrecoverable error occurs on the mobile side.

```json
{"event":"error","code":"scan_failed","message":"BLE scanner returned error code 2","ts":1748982607000}
```

**Error codes:**

| Code | Meaning |
|---|---|
| `scan_failed` | BLE scan could not start |
| `connect_failed` | GATT connection attempt failed |
| `gatt_error` | Unexpected GATT-layer error |
| `permission_denied` | Required BLE permission not granted |
| `ble_unavailable` | Bluetooth is off or unavailable |
| `tcp_error` | TCP connection problem (sent before disconnect) |

---

### `pong`
Response to a `ping` command.

```json
{"event":"pong","ts":1748982608000}
```

---

### `answer`
Response to an `ask` command. Sent when the field operator taps Yes or No.

```json
{"event":"answer","req_id":"q1","value":true,"ts":1748982610000}
```

| Field | Type | Description |
|---|---|---|
| `req_id` | string | Echoed from the originating `ask` command |
| `value` | boolean | `true` = Yes, `false` = No |

---

### `dismiss`
Sent when the field operator dismisses a question card without answering.

```json
{"event":"dismiss","req_id":"q1","ts":1748982611000}
```

| Field | Type | Description |
|---|---|---|
| `req_id` | string | Echoed from the originating `ask` command |

---

### `log`
General-purpose log message from the mobile app for debugging.

```json
{"event":"log","level":"info","message":"Connected to GATT server","ts":1748982609000}
```

**Levels:** `"debug"`, `"info"`, `"warn"`, `"error"`

---

## Commands (Broker → Agent)

### `register`
Sent by the broker immediately after the agent's TCP connection is accepted. Tells the agent the
`agent_id` the broker assigned to it.

```json
{"cmd":"register","agent_id":"agent-001"}
```

| Field | Type | Description |
|---|---|---|
| `agent_id` | string | Broker-assigned id for this connection (`agent-NNN`) |

---

### `scan_start`
Begin BLE scanning.

```json
{"cmd":"scan_start","timeout_ms":10000,"name_filter":"WF-"}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `timeout_ms` | integer | No | Stop scanning automatically after this many ms. Default: `10000`. `0` = scan indefinitely. |
| `name_filter` | string | No | Only report devices whose advertised name starts with this prefix. Omit to report all devices. |

---

### `scan_stop`
Stop an in-progress scan.

```json
{"cmd":"scan_stop"}
```

---

### `connect`
Initiate a GATT connection to a device.

```json
{"cmd":"connect","address":"AA:BB:CC:DD:EE:FF"}
```

The mobile app emits `connected` on success or `error` on failure.

---

### `disconnect`
Drop the GATT connection to a device.

```json
{"cmd":"disconnect","address":"AA:BB:CC:DD:EE:FF"}
```

---

### `discover`
Trigger service/characteristic discovery on a connected device.
Must be sent after `connected` is received before any `read`, `write`, or `subscribe` commands.

```json
{"cmd":"discover","address":"AA:BB:CC:DD:EE:FF"}
```

The mobile app emits `services_discovered` when complete.

---

### `subscribe`
Enable notifications/indications on a characteristic.

```json
{"cmd":"subscribe","address":"AA:BB:CC:DD:EE:FF","char":"961f0005-0000-1000-8000-00805f9b34fb"}
```

The mobile app will emit `notification` events for each received notification until `unsubscribe` is sent.

> **Implementation note:** Enabling notifications requires writing `0x0100` to the characteristic's
> Client Characteristic Configuration Descriptor (CCCD, UUID `00002902-0000-1000-8000-00805f9b34fb`).
> This must be handled internally by the mobile app — the server does not send a separate CCCD write.

---

### `unsubscribe`
Disable notifications on a characteristic.

```json
{"cmd":"unsubscribe","address":"AA:BB:CC:DD:EE:FF","char":"961f0005-0000-1000-8000-00805f9b34fb"}
```

---

### `read`
Read the current value of a characteristic.

```json
{"cmd":"read","address":"AA:BB:CC:DD:EE:FF","char":"00002a19-0000-1000-8000-00805f9b34fb","req_id":"a1b2c3d4"}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `req_id` | string | Yes | Arbitrary string echoed back in `read_result` to correlate request/response |

---

### `write`
Write a value to a characteristic.

```json
{"cmd":"write","address":"AA:BB:CC:DD:EE:FF","char":"0000fff1-0000-1000-8000-00805f9b34fb","value":"55aa01","rsp":true,"req_id":"e5f6a7b8"}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `value` | string | Yes | Bytes to write, as lowercase hex |
| `rsp` | boolean | No | `true` = write with response (default). `false` = write without response (command). |
| `req_id` | string | Yes | Echoed in `write_result` (only sent when `rsp` is `true`) |

---

### `ping`
Check that the mobile app is alive and responsive.

```json
{"cmd":"ping"}
```

The mobile app emits `pong`.

---

### `ask`
Push a Yes/No question to the field operator's screen. Used to drive hardware test plans — the server sends test steps as questions, the operator taps Yes/No, and the server logs the result.

```json
{"cmd":"ask","req_id":"q1","question":"Does the bearing match your reference compass?"}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `req_id` | string | Yes | Unique ID echoed in the `answer` or `dismiss` response |
| `question` | string | Yes | Question text displayed on screen |

The mobile app emits `answer` (Yes/No) or `dismiss` (no answer, card closed).

---

### `dismiss_all`
Clear all pending question cards on the phone immediately.

```json
{"cmd":"dismiss_all"}
```

---

## Session Lifecycle

A typical test session follows this sequence:

```
Broker starts, listens for agents on :2653 (and its client API on :2673)
Agent app launches, user enters broker IP + agent port, taps Connect
TCP connection established

Broker  →  {"cmd":"register","agent_id":"agent-001"}
                                  (broker also emits agent_connected on its WS fan-out)

Broker  →  {"cmd":"scan_start","timeout_ms":15000,"name_filter":"WF-"}
Agent   →  {"event":"scan_result","address":"AA:BB:...","name":"WF-1A2B3C4D","rssi":-62,"ts":...}
Agent   →  {"event":"scan_result", ...}   (more results)

Broker  →  {"cmd":"scan_stop"}
Broker  →  {"cmd":"connect","address":"AA:BB:CC:DD:EE:FF"}
Agent   →  {"event":"connected","address":"AA:BB:CC:DD:EE:FF","ts":...}

Broker  →  {"cmd":"discover","address":"AA:BB:CC:DD:EE:FF"}
Agent   →  {"event":"services_discovered","address":"AA:BB:CC:DD:EE:FF","services":[...],"ts":...}

Broker  →  {"cmd":"subscribe","address":"AA:BB:CC:DD:EE:FF","char":"961f0005-..."}
Agent   →  {"event":"notification","address":"...","char":"961f0005-...","value":"57465053...","ts":...}
Agent   →  {"event":"notification", ...}   (continuous stream)

Broker  →  {"cmd":"disconnect","address":"AA:BB:CC:DD:EE:FF"}
Agent   →  {"event":"disconnected","address":"AA:BB:CC:DD:EE:FF","code":0,"ts":...}
                                  (broker emits agent_disconnected when the TCP socket closes)
```

---

## Versioning

The protocol version tracks the broker's own version and is recorded in the revision-control block
at the end of this document — it is **0.9.x** through the pre-release cycle and is assigned `1.0.0`
only when the broker is tagged/released at `v1.0.0`. Backwards-incompatible changes increment the
major version; additive changes (new optional fields, new event/command types) increment the minor
version. Agent implementations should log an `"Unknown event/cmd"` warning for unrecognised message
types rather than crashing, to maintain forward compatibility.

The template-system commands and events are specified in the **Template Protocol** section below.

---

## Template Protocol

These commands and events let the broker push device/display templates to the agent and direct the
agent to render a connected device with a matched template. They are additive — an agent that does
not implement template handling simply ignores the new commands, and the broker tolerates their
absence. (Broker-side behavior is in `broker/agent_tcp.py` + `broker/template_registry.py`; agent-side
rendering is the agent app's responsibility.)

### New Broker → Agent commands

#### `push_templates`
Sent immediately after `register`. Lists every template currently available on the broker so the
agent can decide which (if any) it needs to request.

```json
{"cmd":"push_templates","manifest":[
  {"id":"builtin.weatherflow-tactical-display","version":"1.0.0"},
  {"id":"builtin.niimbot-label-printer-device","version":"1.0.0"}
]}
```

| Field | Type | Description |
|---|---|---|
| `manifest` | array | `{id, version}` entries for all **available** (non-quarantined) templates |

#### `template_data`
Full template JSON, sent in response to a `template_request` event.

```json
{"cmd":"template_data","id":"builtin.weatherflow-tactical-display","version":"1.0.0","content":{ "...": "..." }}
```

| Field | Type | Description |
|---|---|---|
| `content` | object | The complete template document |

#### `apply_template`
Tells the agent to activate a specific device template (and variant) for a connected device. Sent by
the broker after it signature-matches a `services_discovered` event.

```json
{"cmd":"apply_template","address":"AA:BB:CC:DD:EE:FF","device_template_id":"builtin.niimbot-label-printer-device","version":"1.0.0","variant_id":"b1"}
```

`variant_id` is `null` when the matched device template has no variants.

#### `set_view`
Changes the active display view for a connected device (e.g. `raw` → `imperial`).

```json
{"cmd":"set_view","address":"AA:BB:CC:DD:EE:FF","view":"imperial"}
```

### New Agent → Broker events

#### `template_request`
The agent asks for the full content of templates it doesn't already have cached (typically a subset
of the `push_templates` manifest).

```json
{"event":"template_request","ids":[{"id":"builtin.weatherflow-tactical-display","version":"1.0.0"}],"ts":1748982600000}
```

The broker replies with one `template_data` command per resolvable entry; unknown ids are logged and
skipped. Malformed `ids` (not a list, or non-object entries) are ignored without dropping the
connection.

#### `template_applied`
The agent confirms it loaded and activated a template for a device.

```json
{"event":"template_applied","address":"AA:BB:CC:DD:EE:FF","device_template_id":"builtin.niimbot-label-printer-device","version":"1.0.0","variant_id":"b1","ts":1748982601000}
```

#### `view_changed`
The user changed the active display view in the agent UI (the broker forwards this to its WebSocket
subscribers).

```json
{"event":"view_changed","address":"AA:BB:CC:DD:EE:FF","view":"imperial","ts":1748982602000}
```

> **Signature matching:** the broker matches a device by the `service_uuids` from `services_discovered`
> (all required UUIDs must be present), optionally refined by advertised `name_prefix` and
> `manufacturer_data`. The highest-version, most-specific matching template wins. Templates with
> unresolved `requires` dependencies are quarantined and never appear in `push_templates` or matches.

---

## Known Device UUIDs

These are provided as a convenience reference for test script authors.

### WeatherFlow Tactical (WEATHERmeter for Precision Shooting)

| Role | UUID |
|---|---|
| Primary service | `961f0001-d2d6-43e3-a417-3bb8217e0e01` |
| Notify characteristic | `961f0005-d2d6-43e3-a417-3bb8217e0e01` |

> These are vendor-specific 128-bit UUIDs — **not** the Bluetooth-base `…-0000-1000-8000-00805f9b34fb`
> form. A real device advertises the `-d2d6-…` UUIDs.

Confirmed 16-byte little-endian notify frame (~1 Hz): wind speed `uint16_le` at offset 0
(`raw / 1024 = mph`), temperature `int16_le` at offset 8 (`× 0.1 = °C`), humidity `uint8` at
offset 10 (`%`), pressure `uint16_le` at offset 12 (`× 0.1 = hPa`). There is no wind-direction and
no density-altitude field. Full frame spec is in the internal Engine Documentation (OneDrive —
confidential).

### BLE Battery Service (standard)

| Role | UUID |
|---|---|
| Service | `0000180f-0000-1000-8000-00805f9b34fb` |
| Battery Level characteristic | `00002a19-0000-1000-8000-00805f9b34fb` |

Read or subscribe. Value is a single byte, 0–100 (percent).

### Niimbot B1 / B21 Pro (ISSC UART-over-BLE bridge)

Confirmed against B1 hardware:

| Role | UUID |
|---|---|
| TX write characteristic (write-without-response) | `49535343-6daa-4d02-abf6-19569aca69fe` |
| TX service | `49535343-fe7d-4ae5-8fa9-9fafd205e455` |
| RX notify characteristic | `bef8d6c9-9c21-4c9e-b632-bd58c1009f9f` |
| RX service | `e7810a71-73ae-499d-8c15-faa9aef0c3f2` |

The RX notify characteristic is in a **different service** from the TX write characteristic — a
common ISSC quirk. Frames use a `55 55 [cmd] [len] [data…] [xor] AA AA` wrapper. The B21 Pro shares
the same protocol (in progress). Full opcode/packet detail is maintained internally.

---

## Revision Control

| Version | Date | Status | Changes |
|---|---|---|---|
| 0.9.0 | 2026-06-09 | DRAFT | Updated for the two-tier broker rewrite: agent TCP port `9876 → 2653`; documented the separate REST + WebSocket client API on `2673`; added the `register` command and `agent_connected`/`agent_disconnected` lifecycle events; relabeled Mobile/Server → Agent/Broker; corrected WeatherFlow Tactical to confirmed vendor UUIDs and the confirmed LE frame (wind = raw/1024 **mph**, no wind-direction/DA); added confirmed Niimbot B1 ISSC UUIDs; corrected the version markers (header/body previously read 1.1 / 1.0). Template-system commands/events deferred to the next revision. |
| 0.9.0 | 2026-06-09 | DRAFT | Added the **Template Protocol** section: Broker → Agent commands `push_templates`, `template_data`, `apply_template`, `set_view`; Agent → Broker events `template_request`, `template_applied`, `view_changed`. Documented signature-match → `apply_template` behavior and the quarantine rule. Additive only — version remains 0.9.x. |

> Version numbers are assigned only on Founder approval. This block is the sole authority on the
> document's version and date. The protocol version stays at 0.9.x until the broker is released at
> `v1.0.0`.
