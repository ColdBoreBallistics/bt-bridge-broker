# BT Bridge Protocol — v1.1

This document is the **authoritative specification** for the BT Bridge protocol.
All platform implementations (Android, iOS, and any future ports) must conform to this spec.
The canonical copy lives in the `bt-bridge-broker` repository.

---

## Overview

The BT Bridge protocol connects a **mobile app** (the Bluetooth side) to a **desktop broker** (the test
logic side) over a local TCP connection. The mobile app acts as a BT Agent — it scans,
connects to, and exchanges data with Bluetooth peripherals. The broker drives the agent by sending
commands, and the agent sends events back for every Bluetooth state change.

```
┌─────────────────────────────────────────────────────┐
│  Desktop (bt-bridge-broker)                         │
│  - runs test scripts                                │
│  - logs all events                                  │
│  - sends BT commands to agent                       │
└───────────────────┬─────────────────────────────────┘
                    │ TCP (port 9876)
                    │ newline-delimited JSON
┌───────────────────┴──────────────────────────────────┐
│  Mobile app (bt-bridge-agent-android / -ios)         │
│  - TCP client: connects to desktop broker            │
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
| Default port | `9876` |
| Direction | Mobile app initiates TCP connection to server |
| Framing | Newline-delimited JSON — one JSON object per line, terminated with `\n` |
| Encoding | UTF-8 |
| Byte arrays | Lowercase hex string, no `0x` prefix (e.g., `"1a2b3c"`) |
| Timestamps | Unix epoch milliseconds, integer field `"ts"` |
| UUIDs | Lowercase with hyphens, full 128-bit form (e.g., `"0000180f-0000-1000-8000-00805f9b34fb"`) |

The server **listens** on `0.0.0.0:9876`. The mobile app **connects** to the server's IP and port.
The server IP is entered by the user in the mobile app UI before connecting.

---

## Message Structure

Every message is a single JSON object on one line.

**Mobile → Server messages** have a top-level `"event"` field.
**Server → Mobile messages** have a top-level `"cmd"` field.

---

## Events (Mobile → Server)

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

## Commands (Server → Mobile)

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
Server starts, listens on :9876
Mobile app launches, user enters server IP, taps Connect
TCP connection established

Server  →  {"cmd":"scan_start","timeout_ms":15000,"name_filter":"WF-"}
Mobile  →  {"event":"scan_result","address":"AA:BB:...","name":"WF-1A2B3C4D","rssi":-62,"ts":...}
Mobile  →  {"event":"scan_result", ...}   (more results)

Server  →  {"cmd":"scan_stop"}
Server  →  {"cmd":"connect","address":"AA:BB:CC:DD:EE:FF"}
Mobile  →  {"event":"connected","address":"AA:BB:CC:DD:EE:FF","ts":...}

Server  →  {"cmd":"discover","address":"AA:BB:CC:DD:EE:FF"}
Mobile  →  {"event":"services_discovered","address":"AA:BB:CC:DD:EE:FF","services":[...],"ts":...}

Server  →  {"cmd":"subscribe","address":"AA:BB:CC:DD:EE:FF","char":"961f0005-..."}
Mobile  →  {"event":"notification","address":"...","char":"961f0005-...","value":"57465053...","ts":...}
Mobile  →  {"event":"notification", ...}   (continuous stream)

Server  →  {"cmd":"disconnect","address":"AA:BB:CC:DD:EE:FF"}
Mobile  →  {"event":"disconnected","address":"AA:BB:CC:DD:EE:FF","code":0,"ts":...}
```

---

## Versioning

The protocol version is `1.0`. Backwards-incompatible changes increment the major version.
Additive changes (new optional fields, new event/command types) increment the minor version.
Platform implementations should log an `"Unknown event/cmd"` warning for unrecognised message
types rather than crashing, to maintain forward compatibility.

---

## Known Device UUIDs

These are provided as a convenience reference for test script authors.

### WeatherFlow Tactical (WEATHERmeter for Precision Shooting)

| Role | UUID |
|---|---|
| Primary service | `961f0001-0000-1000-8000-00805f9b34fb` |
| Notify characteristic | `961f0005-0000-1000-8000-00805f9b34fb` |

Frame format (16 bytes): `WFPSM` header (5 bytes) + sensor payload (11 bytes).
Subscribe to the notify characteristic; wind speed is encoded in bytes 5–6 (raw / 1024 = m/s).
Full frame spec is in the internal Engine Documentation (OneDrive — confidential).

### BLE Battery Service (standard)

| Role | UUID |
|---|---|
| Service | `0000180f-0000-1000-8000-00805f9b34fb` |
| Battery Level characteristic | `00002a19-0000-1000-8000-00805f9b34fb` |

Read or subscribe. Value is a single byte, 0–100 (percent).

### Niimbot B1 / B21 Pro (ISSC UART-over-BLE bridge)

UUIDs to be confirmed against hardware with nRF Connect.
Expected to share the ISSC UART bridge service. See `bt-bridge-agent-android` README for B1 confirmed UUIDs.
