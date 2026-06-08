# BT Bridge Template System — Design Specification

**Date:** 2026-06-08  
**Status:** Approved — ready for implementation  
**Companion doc:** `2026-06-08-broker-rewrite-design.md`

---

## 1. Purpose

The template system decouples device-specific knowledge from the agent app. Rather than
hardcoding WeatherFlow or Niimbot parsing logic into the Android APK, that knowledge lives
in JSON template files on the broker. The agent is a generic renderer and executor; the
templates tell it what to do.

The system serves three use cases:

1. **Display** — parse raw BLE notification bytes and render named, unit-aware fields
2. **Workflow** — drive multi-step BLE command sequences (e.g., a Niimbot print job)
3. **Reverse engineering** — capture, annotate, and scaffold templates for unknown devices

---

## 2. Template Types

Five first-class template types, each a JSON file on disk:

| Type | Purpose |
|---|---|
| `device` | Device family definition — signature, variants, channel wiring, cross-references |
| `display` | Parses notification/read values into named fields for rendering |
| `workflow` | Drives multi-step BLE command sequences |
| `codec` | Defines a framing/deframing layer (e.g., Niimbot UART wrapper) |
| `component` | Reusable partial — shared characteristic definitions (e.g., Battery Service) |

The `device` template is the entry point. It cross-references the others. The agent matches
a connected device to a `device` template via its signature, then loads all referenced templates.

---

## 3. Identity and Versioning

### 3.1 ID Format

Every template declares its identity inside the file:

```json
{
  "schema_version": 1,
  "id": "builtin.weatherflow-tactical-display",
  "version": "1.0.0",
  "type": "display"
}
```

**ID format:** `namespace.template-name`

| Namespace | Owner | Rules |
|---|---|---|
| `builtin.` | Project maintainers | Never contributed by community PRs |
| `contrib.` | Community | First-PR-wins; CI lint enforces no duplicates |
| `<github-handle>.` | Individual contributor | Personal namespace by convention |

- IDs are lowercase, hyphens only, no spaces
- Filename is informational — the broker uses the `id` field inside the file, not the filename
- Broker startup fails loud if two files declare the same `(id, version)` pair, reporting both paths

### 3.2 Versioning

Two independent version concepts:

- **`schema_version`** (integer) — the JSON format itself. Broker refuses to load files with
  a `schema_version` higher than it understands. Increments only on breaking format changes.
- **`version`** (semver string) — the template content. Registry key is `(id, version)`.
  Multiple versions of the same template can coexist on disk.

### 3.3 Cross-References

Templates reference each other by ID with optional semver range constraints:

```json
"requires": {
  "builtin.niimbot-printer-display": "^1.0.0",
  "builtin.niimbot-uart-framed": ">=1.0.0 <3.0.0"
}
```

- Bare reference (no `@version`, no `requires` entry) → highest installed version
- Range in `requires` → broker resolves to highest installed version satisfying the range
- Broker logs a clear error at startup for unresolvable dependencies:
  `ERROR: builtin.niimbot-printer-display@1.0.0 requires builtin.niimbot-uart-framed@>=1.0.0 <3.0.0 but no matching version is installed`
- Templates with unresolved dependencies are quarantined (present in registry, flagged unavailable)

### 3.4 Compatibility Declarations

Three tiers:

```json
"min_broker_version": "1.0.0",
"requires": { ... },
"compatible_with": {
  "device_type": ["builtin.weatherflow-tactical"]
}
```

- `min_broker_version` — hard gate; broker refuses to load if its own version is lower
- `requires` — hard dependencies with semver ranges
- `compatible_with` — soft matching; used by broker to suggest templates for a connected device

---

## 4. Disk Layout

```
bt-bridge-broker/
└── templates/
    ├── weatherflow-tactical/
    │   ├── device.json                  — id: builtin.weatherflow-tactical
    │   ├── display-v1.json              — id: builtin.weatherflow-tactical-display
    │   └── workflow-v1.json             — id: builtin.weatherflow-tactical-workflow
    ├── niimbot-label-printer/
    │   ├── device.json                  — id: builtin.niimbot-label-printer
    │   ├── display-v1.json              — id: builtin.niimbot-printer-display
    │   ├── workflow-v1.json             — id: builtin.niimbot-printer-workflow
    │   └── display-v2.json              — id: builtin.niimbot-printer-display (version 2.0.0)
    └── shared/
        ├── codec.niimbot-uart-framed.json   — id: builtin.niimbot-uart-framed
        ├── display.battery-service.json     — id: builtin.battery-service-display
        └── display.device-information.json  — id: builtin.device-information-display
```

- One directory per device family — the natural FOSS PR contribution unit
- `shared/` holds codecs and standard GATT characteristic components reusable across families
- Multiple versions of the same template coexist as separate files within the same directory
- Filenames are informational; the broker uses `id` + `version` from file contents

---

## 5. Device Template

The entry point for a device family. Defines the signature, variants, channel wiring,
and cross-references to all other templates.

```json
{
  "schema_version": 1,
  "id": "builtin.niimbot-label-printer",
  "version": "1.0.0",
  "type": "device",
  "name": "Niimbot Label Printer Family",
  "description": "Supports D11, D110, B21, B21 Pro, B3S, B18, B203, and B1",
  "author": "builtin",
  "min_broker_version": "1.0.0",

  "requires": {
    "builtin.niimbot-printer-display": "^1.0.0",
    "builtin.niimbot-printer-workflow": "^1.0.0",
    "builtin.niimbot-uart-framed": "^1.0.0"
  },

  "display_template": "builtin.niimbot-printer-display",
  "workflow_template": "builtin.niimbot-printer-workflow",
  "codec": "builtin.niimbot-uart-framed",

  "variants": [
    {
      "variant_id": "modern",
      "description": "D11, D110, B21, B21 Pro, B3S, B18, B203",
      "signature": {
        "service_uuids": ["e7810a71-73ae-499d-8c15-faa9aef0c3f2"],
        "name_prefix": null,
        "manufacturer_data": null
      },
      "channels": {
        "write": {
          "service": "e7810a71-73ae-499d-8c15-faa9aef0c3f2",
          "char": "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f",
          "type": "write_no_response"
        },
        "notify": {
          "service": "e7810a71-73ae-499d-8c15-faa9aef0c3f2",
          "char": "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f"
        }
      }
    },
    {
      "variant_id": "b1-issc",
      "description": "B1 (Microchip ISSC UART bridge)",
      "signature": {
        "service_uuids": [
          "49535343-fe7d-4ae5-8fa9-9fafd205e455",
          "e7810a71-73ae-499d-8c15-faa9aef0c3f2"
        ],
        "name_prefix": null,
        "manufacturer_data": null
      },
      "channels": {
        "write": {
          "service": "49535343-fe7d-4ae5-8fa9-9fafd205e455",
          "char": "49535343-6daa-4d02-abf6-19569aca69fe",
          "type": "write_no_response"
        },
        "notify": {
          "service": "e7810a71-73ae-499d-8c15-faa9aef0c3f2",
          "char": "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f"
        }
      }
    }
  ]
}
```

### Signature Matching

The broker matches a connected device against device templates by comparing the device's
discovered GATT services against each variant's signature. Match rules:

- All specified `service_uuids` must be present in the discovered service list (AND)
- `name_prefix` must match the advertised device name prefix if specified
- `manufacturer_data` must match if specified
- Unspecified signature fields are wildcards
- If multiple variants match, the most specific (most fields specified) wins
- If multiple device templates match at equal specificity, broker logs a warning and
  presents both to the test client for manual selection

---

## 6. Display Template

Defines how to parse and render BLE notification and read values.

### 6.1 Structure

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

  "default_view": "metric",

  "notifications": [
    {
      "char": "961f0005-0000-1000-8000-00805f9b34fb",
      "description": "16-byte sensor frame",
      "views": {
        "raw":      { ... },
        "metric":   { ... },
        "imperial": { ... }
      }
    }
  ],

  "reads": [
    {
      "char": "00002a19-0000-1000-8000-00805f9b34fb",
      "description": "Battery level",
      "views": {
        "raw":    { ... },
        "metric": { ... }
      }
    }
  ]
}
```

### 6.2 Views

Each notification or read entry contains a `views` map. Keys are arbitrary strings
(`raw`, `metric`, `imperial`, `knots`, `scientific` — whatever the template author defines).
`default_view` at the template level sets the initial active view.

The active view is:
- Selectable by the user in the agent UI
- Settable by the test client via `POST /v1/agents/{id}/view`
- Persisted per-agent in the agent's local DataStore

### 6.3 Field Types

Every field within a view declares its `type`. The agent dispatches to the appropriate
handler. If an agent encounters an unrecognized `type`, it falls back to `raw` for that
field with a visible warning.

#### `raw`
Hex display, no interpretation. Always available regardless of agent version.

```json
{
  "id": "header",
  "label": "Frame Header",
  "type": "raw",
  "offset": 0,
  "length": 5,
  "encoding": "bytes",
  "display": false
}
```

#### `scale_offset`
Linear transform: `display_value = (raw_value * scale) + offset_value`

```json
{
  "id": "wind_ms",
  "label": "Wind Speed",
  "type": "scale_offset",
  "offset": 5,
  "length": 2,
  "encoding": "uint16_be",
  "scale": 0.001,
  "offset_value": 0.0,
  "unit": "m/s",
  "display": true,
  "precision": 2
}
```

#### `bitmask`
Interprets individual bits of a byte as independent flags or states.

```json
{
  "id": "status_byte",
  "label": "Printer Status",
  "type": "bitmask",
  "offset": 1,
  "length": 1,
  "encoding": "uint8",
  "display": true,
  "bits": [
    {"bit": 0, "id": "cover_open",   "label": "Cover",    "values": {"0": "Closed", "1": "Open"}},
    {"bit": 1, "id": "paper_state",  "label": "Paper",    "values": {"0": "OK",     "1": "Low"}},
    {"bit": 2, "id": "rfid_present", "label": "RFID",     "values": {"0": "None",   "1": "Detected"}},
    {"bit": 3, "id": "printing",     "label": "Printing", "values": {"0": "Idle",   "1": "Busy"}}
  ]
}
```

#### `enum`
Maps a byte value to a human-readable label.

```json
{
  "id": "print_density",
  "label": "Print Density",
  "type": "enum",
  "offset": 2,
  "length": 1,
  "encoding": "uint8",
  "display": true,
  "values": {
    "1": "Light",
    "2": "Medium",
    "3": "Dark",
    "4": "Extra Dark"
  }
}
```

#### `expr`
Computed from sibling field values using an expression string. References fields by `id`.
`display: false` fields are parsed and available as inputs but not shown in the UI.

```json
{
  "id": "temp_c_hidden",
  "label": "Temp C (internal)",
  "type": "scale_offset",
  "offset": 7, "length": 2, "encoding": "int16_be",
  "scale": 0.1, "offset_value": 0.0,
  "display": false
},
{
  "id": "temp_f",
  "label": "Temperature",
  "type": "expr",
  "expr": "temp_c_hidden * 9/5 + 32",
  "unit": "°F",
  "display": true,
  "precision": 1
}
```

#### `formula`
Named built-in function. `inputs` maps formula parameter names to sibling field `id` values.

```json
{
  "id": "da_ft",
  "label": "Density Altitude",
  "type": "formula",
  "formula": "density_altitude",
  "inputs": {
    "temp_c":        "temp_c_hidden",
    "pressure_hpa":  "pres_hpa",
    "humidity_pct":  "humidity"
  },
  "unit": "ft",
  "display": true,
  "precision": 0
}
```

Built-in formulas (v1): `density_altitude`

### 6.4 Encodings

Supported `encoding` values for all field types:

| Value | Description |
|---|---|
| `uint8` | Unsigned 8-bit integer |
| `int8` | Signed 8-bit integer |
| `uint16_be` | Unsigned 16-bit big-endian |
| `uint16_le` | Unsigned 16-bit little-endian |
| `int16_be` | Signed 16-bit big-endian |
| `int16_le` | Signed 16-bit little-endian |
| `uint32_be` | Unsigned 32-bit big-endian |
| `uint32_le` | Unsigned 32-bit little-endian |
| `int32_be` | Signed 32-bit big-endian |
| `int32_le` | Signed 32-bit little-endian |
| `float32_be` | IEEE 754 single-precision big-endian |
| `float32_le` | IEEE 754 single-precision little-endian |
| `bytes` | Raw byte array (hex display only) |
| `utf8` | UTF-8 string |

### 6.5 Notification Matching (multi-response characteristics)

When a characteristic carries multiple response types (e.g., Niimbot heartbeat vs. print
response on the same `bef8d6c9` char), a `match` block selects which field layout applies:

```json
{
  "char": "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f",
  "match": {
    "cmd_byte_offset": 2,
    "cmd_byte_value": "0xDB"
  },
  "description": "Heartbeat response",
  "views": { ... }
}
```

Multiple notification entries for the same characteristic are evaluated in order; the first
match wins. A notification entry with no `match` block is the catch-all fallback.

---

## 7. Codec Template

Defines a framing/deframing layer applied before field parsing. The codec template
is referenced by the device template; display and workflow templates operate on the
already-deframed payload.

```json
{
  "schema_version": 1,
  "id": "builtin.niimbot-uart-framed",
  "version": "1.0.0",
  "type": "codec",
  "name": "Niimbot UART Frame Codec",
  "author": "builtin",
  "min_broker_version": "1.0.0",

  "framing": {
    "type": "wrapped",
    "header": ["0x55", "0x55"],
    "tail": ["0xAA", "0xAA"],
    "length_offset": 2,
    "length_size": 2,
    "length_encoding": "uint16_be",
    "checksum": {
      "algorithm": "xor",
      "range": "cmd_through_data",
      "position": "before_tail"
    },
    "payload_offset": 5
  },

  "reassembly": {
    "required": true,
    "strategy": "accumulate_until_tail"
  }
}
```

**Built-in codec types (v1):**

| `type` | Description |
|---|---|
| `raw` | No framing — payload is the raw characteristic value (WeatherFlow) |
| `wrapped` | Header + length + data + checksum + tail (Niimbot) |

The `reassembly` block handles BLE MTU fragmentation — packets larger than the MTU are
split across multiple BLE frames and must be reassembled before parsing.

---

## 8. Workflow Template

Defines multi-step BLE command sequences. Workflows are driven by the broker/test client
and executed by the agent. The agent does not autonomously run workflows — it executes
individual steps as commanded.

Full workflow template specification is deferred to a follow-on design doc. The schema
reserves the `type: "workflow"` value and the device template's `workflow_template` field.
The broker and agent must not error on the presence of a workflow template reference — they
log a warning if workflow execution is requested but no workflow template is loaded.

---

## 9. Component Template

Reusable partial definitions for standard GATT characteristics shared across device families.
A component template has `"type": "component"` and contains a `notifications` or `reads`
array in the same format as a display template. Device display templates include components
via a top-level `includes` array:

```json
{
  "includes": [
    "builtin.battery-service-display",
    "builtin.device-information-display"
  ]
}
```

The broker merges included component fields into the display template at load time.
Component fields are appended after the device-specific fields. If a component field
conflicts with a device field (same characteristic UUID + same `match`), the device field
wins and a warning is logged.

---

## 10. Partial Template Loading and Warnings

When a device template is matched but some referenced templates are missing or incompatible,
the agent operates in partial mode:

| Condition | Behaviour |
|---|---|
| Display template missing | Raw GATT analyser for all characteristics; yellow warning banner in agent UI: "No display template — showing raw GATT data" |
| Workflow template missing | Display works normally; workflow commands return error; yellow warning banner: "No workflow template — manual BLE operations only" |
| Codec template missing | All characteristic data shown as raw hex; yellow warning: "No codec — unable to deframe \[codec-id\]" |
| Display template present, workflow missing | Partial mode — yellow banner: "Display loaded. Workflow template \[id\] not found — check broker templates/" |
| Workflow present, display missing | Partial mode — yellow banner: "Workflow loaded. Display template \[id\] not found — showing raw GATT data" |
| Version incompatibility | Yellow banner: "Template \[id\]@\[version\] requires broker \[min_version\] — update broker or use older template" |

Warnings are:
- Visible in the agent UI as a persistent dismissible banner
- Included in `GET /v1/agents/{id}` response as a `template_warnings: []` array
- Published as a `log` event (level: `warn`) over WebSocket on connect

The raw GATT analyser is always available as the ultimate fallback regardless of template
load state. It renders every discovered characteristic with its UUID, properties, and raw
hex value for any notification received.

---

## 11. Broker Template Registry

### 11.1 Startup Scan

On broker startup (and on `POST /v1/templates/reload`):

1. Walk all `.json` files under `templates/`
2. Parse each — log and skip files that fail JSON parsing
3. Extract `(id, version)` — fatal error if the same `(id, version)` appears in two files
4. Warn if a file's `id` namespace doesn't match the directory structure convention
5. Build registry: `Map<id, SortedMap<version, TemplateObject>>`
6. Resolve all `requires` entries using semver matching; quarantine templates with
   unresolved dependencies (present in registry, flagged `available: false`)
7. Log summary: N templates loaded, M quarantined, K warnings

### 11.2 REST API Endpoints

All under `/v1/templates/`:

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/templates` | List all templates (id, version, type, available) |
| `GET` | `/v1/templates/{id}` | List all versions of a template |
| `GET` | `/v1/templates/{id}/{version}` | Full template JSON |
| `POST` | `/v1/templates/reload` | Re-scan templates directory, rebuild registry |
| `POST` | `/v1/templates/draft` | Save a template JSON to templates directory (for RE workflows) |
| `DELETE` | `/v1/templates/{id}/{version}` | Delete a template file from disk |
| `GET` | `/v1/templates/match` | Match a device signature against all device templates |

#### `GET /v1/templates/match`

Query params: `service_uuids` (comma-separated), `name_prefix`, `manufacturer_data` (hex)

```json
{
  "matches": [
    {
      "device_template_id": "builtin.niimbot-label-printer",
      "version": "1.0.0",
      "variant_id": "b1-issc",
      "confidence": "exact",
      "warnings": []
    }
  ]
}
```

`confidence` values: `exact` (all signature fields matched), `partial` (subset matched).

### 11.3 Template Push to Agent

When an agent connects, the broker:

1. Sends all available templates to the agent via the TCP channel using a new
   `push_templates` command (PROTOCOL.md v1.2 addition)
2. Agent compares received `(id, version)` pairs against its local cache
3. Agent requests full content only for templates where broker version > cached version
4. Broker sends full template JSON for each requested template
5. Agent persists updated templates to app-private storage (`filesDir/templates/`)

The push uses a request/response pattern on the existing TCP channel:

```json
{"cmd": "push_templates", "manifest": [
  {"id": "builtin.weatherflow-tactical-display", "version": "1.2.0"},
  {"id": "builtin.niimbot-label-printer", "version": "1.0.0"},
  ...
]}
```

```json
{"event": "template_request", "ids": [
  {"id": "builtin.weatherflow-tactical-display", "version": "1.2.0"}
]}
```

```json
{"cmd": "template_data", "id": "builtin.weatherflow-tactical-display", "version": "1.2.0", "content": { ... }}
```

Higher version always wins — agent replaces its cached copy if broker version is higher.
The raw GATT analyser is built into the agent and cannot be overwritten by any template push.

---

## 12. RE Capture Workflow

### 12.1 Guided Capture Session

The broker provides a guided RE workflow via REST:

```
POST /v1/re/session/start     — begin a capture session for connected device
POST /v1/re/session/discover  — run GATT discovery, record all services/characteristics
POST /v1/re/session/capture   — subscribe to all notifying chars, capture N samples
POST /v1/re/session/probe     — optionally send test writes and capture responses
POST /v1/re/session/analyse   — run statistical analysis on captured samples
POST /v1/re/session/scaffold  — generate draft template from session data
GET  /v1/re/session/export    — export full session as tshark-compatible JSON
```

### 12.2 Statistical Analysis

For each captured characteristic, the analyser computes per-byte statistics across all
samples:

- **Entropy:** bytes with near-zero entropy are likely static (header, padding, version)
- **Range:** min/max per byte position hints at value fields
- **Change frequency:** bytes that change every sample are likely sensor readings;
  bytes that rarely change are likely state/config fields
- **Common patterns:** detects `0x55 0x55` / `0xAA 0xAA` framing markers, XOR checksums,
  length fields

Output included in the scaffold as annotations:

```json
{
  "id": "unknown_field_3",
  "label": "Field @ offset 3 (auto)",
  "type": "raw",
  "offset": 3,
  "length": 1,
  "encoding": "uint8",
  "display": true,
  "_re_hint": "high entropy, range 0-255, changes every sample — likely sensor reading"
}
```

`_re_hint` fields are stripped when the template is saved via `POST /v1/templates/draft`.

### 12.3 tshark-Compatible Export

The raw session export produces a JSON structure mimicking tshark's GATT dissector output
(`tshark -T json`). This is GATT-layer only (no HCI/L2CAP frames — the agent's BLE APIs
don't expose HCI). The file is clearly marked:

```json
{
  "_bt_bridge_export": true,
  "_note": "GATT-layer only. For full HCI capture use Android HCI snoop log.",
  "packets": [ ... ]
}
```

Complementary method documented in RE session output: Android HCI snoop log
(`/etc/bluetooth/bt_stack.conf`, `BtSnoopLogOutput=true`) produces a real pcap file
openable in Wireshark, capturing full HCI frames. Use when deeper protocol analysis
is needed.

---

## 13. Agent Runtime — Template Handling

### 13.1 Local Storage

Templates are persisted to Android app-private storage:
`filesDir/templates/<namespace>/<id-local-part>/<version>.json`

The raw GATT analyser is built into the APK and is never stored in `filesDir` — it cannot
be overwritten.

### 13.2 Template Lifecycle on Agent

1. **On broker connect:** Agent receives `push_templates` manifest, requests missing/outdated templates, persists received content, rebuilds local template registry
2. **On device connect:** Agent discovers GATT services, sends `services_discovered` event to broker, broker responds with `apply_template` command specifying `(device_template_id, version, variant_id)`
3. **On `apply_template`:** Agent loads device template from local cache, loads all referenced display/workflow/codec templates, activates the `default_view`
4. **On no match:** Agent activates raw GATT analyser, displays warning banner
5. **On partial match:** Agent activates whatever templates loaded successfully, displays appropriate warning banner per Section 10
6. **On broker disconnect:** Agent continues using currently loaded templates from cache

### 13.3 View Selection

Active view is stored per-connected-device in DataStore. When the user changes the view
in the agent UI, the agent notifies the broker via a new `view_changed` event:

```json
{"event": "view_changed", "address": "AA:BB:CC:DD:EE:FF", "view": "imperial", "ts": ...}
```

The broker can set the active view on the agent via REST (`POST /v1/agents/{id}/view`),
which sends a `set_view` command over TCP.

---

## 14. PROTOCOL.md v1.2 Additions

The template system adds the following to the Agent ↔ Broker protocol:

**New Broker → Agent commands:**
- `push_templates` — manifest of available templates with versions
- `template_data` — full template JSON for one template
- `apply_template` — instruct agent to activate a specific template + variant
- `set_view` — change the active display view for a connected device

**New Agent → Broker events:**
- `template_request` — agent requests full content for listed template IDs/versions
- `template_applied` — agent confirms a template has been loaded and activated
- `view_changed` — user changed the active view in the agent UI

---

## 15. CI Lint (FOSS Contribution Gate)

A Python script (`tools/lint_templates.py`) runs in CI on every PR:

1. Scans all files in `templates/`
2. Validates JSON syntax for each file
3. Checks `schema_version` is present and supported
4. Checks `id` and `version` fields are present and well-formed
5. Detects `(id, version)` duplicate pairs — fails with both file paths
6. Validates `id` namespace: community PRs may not add `builtin.` templates
7. Resolves all `requires` entries against the full template set in the PR — fails if any
   dependency is unresolvable
8. Warns if filename doesn't match ID local part (informational only, not a failure)

---

## 16. Out of Scope for v1.0

- Workflow template execution (schema reserved, implementation deferred)
- Template signing / cryptographic verification
- Template marketplace / remote fetch (broker is the only distribution mechanism)
- Agent-side template authoring UI
- ESP32 / Raspberry Pi agent template runtime
- Template inheritance (`inherits` field reserved for future use)
