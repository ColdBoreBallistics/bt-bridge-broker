# bt-bridge-broker

Two-tier broker for the BT Bridge hardware-test harness. It accepts connections from an
agent app ([bt-bridge-agent-android](https://github.com/ColdBoreBallistics/bt-bridge-agent-android)
or [bt-bridge-agent-ios](https://github.com/ColdBoreBallistics/bt-bridge-agent-ios)) over TCP,
and exposes a REST + WebSocket API so test clients (scripts, the interactive REPL, or a browser)
can drive Bluetooth operations and observe events.

```
  Test clients (curl / scripts / browser / REPL)
        │  REST + WebSocket   (API, default 127.0.0.1:2673)
        ▼
  ┌─────────────────────────────┐
  │  bt-bridge-broker           │
  │  - AgentRegistry (state)    │
  │  - REST API + WebSocket     │
  │  - agent TCP server         │
  └─────────────┬───────────────┘
        │  newline-delimited JSON over TCP (agent, default 127.0.0.1:2653)
        ▼
  Agent app (bt-bridge-agent-android / -ios)
        │  BLE
        ▼
  BLE peripheral(s) — WeatherFlow Tactical, Niimbot B1 / B21 Pro, …
```

See [PROTOCOL.md](PROTOCOL.md) for the agent wire protocol and [docs/FOSS_GOVERNANCE.md](docs/FOSS_GOVERNANCE.md)
for how the project is organized.

> **Status:** pre-release (0.9.x). The broker is functional; the template system and the
> remote template catalog are delivered by follow-on work (see the plans in `docs/`).

---

## Requirements

- **Python 3.11 or later** (the code uses `match` statements, `X | Y` type unions, and
  `asyncio.TaskGroup` / `except*`).
- Third-party packages (installed via `requirements.txt`): FastAPI, uvicorn, pydantic-settings.

### Installing Python 3.11+

**Debian:**
```bash
sudo apt update && sudo apt install python3 python3-venv python3-pip
python3 --version   # confirm 3.11+
```

**Ubuntu:**
```bash
sudo apt update && sudo apt install python3 python3-venv python3-pip
python3 --version
```

**RHEL / Fedora:**
```bash
sudo dnf install python3 python3-pip
python3 --version
```

**Windows:**
Download the installer from [python.org](https://www.python.org/downloads/).
During installation, check **"Add Python to PATH"**. Confirm in a terminal: `python --version`

**macOS:**
```bash
brew install python
python3 --version
```

---

## Setup

```bash
git clone https://github.com/ColdBoreBallistics/bt-bridge-broker.git
cd bt-bridge-broker
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

To run the test suite or contribute, install the development dependencies instead:
```bash
pip install -r requirements-dev.txt
pytest -q
```

---

## Running the broker

```bash
python3 -m broker.main
```

This starts two listeners (both default to loopback):

| Listener | Default | Purpose |
|---|---|---|
| Agent TCP | `127.0.0.1:2653` | Agent apps connect here (newline-delimited JSON) |
| REST + WebSocket API | `127.0.0.1:2673` | Test clients drive the broker here |

Open the interactive API docs at <http://127.0.0.1:2673/docs>.

### Exposing on the LAN for real device testing

The broker is **unauthenticated**, so it binds loopback by default. To let an agent app on a
phone reach it over the LAN, bind all interfaces explicitly:

```bash
python3 -m broker.main --agent-host 0.0.0.0 --api-host 0.0.0.0
```

(or set `BT_AGENT_HOST` / `BT_API_HOST` environment variables.) Then find your machine's LAN IP
(`ip addr show` on Linux/macOS, `ipconfig` on Windows) and enter it in the agent app.

### Options

```
python3 -m broker.main [--agent-host H] [--agent-port P] [--api-host H] [--api-port P]
                       [--interactive] [--log FILE] [--debug]

  --agent-host   Agent TCP bind address   (default: 127.0.0.1)
  --agent-port   Agent TCP port           (default: 2653)
  --api-host     REST/WebSocket bind addr (default: 127.0.0.1)
  --api-port     REST/WebSocket port      (default: 2673)
  --interactive  Launch the interactive REPL alongside the server
  --log FILE     Also write logs to FILE
  --debug        Verbose debug logging
```

All options are also configurable via `BT_`-prefixed environment variables
(e.g. `BT_API_PORT=8080`).

---

## REST API

Once the broker is running, the API is self-documented at `/docs` (Swagger UI). Endpoints:

| Method & path | Purpose |
|---|---|
| `GET /v1/agents` | List connected agents |
| `GET /v1/agents/{agent_id}` | One agent's state |
| `POST /v1/scan/start` · `POST /v1/scan/stop` · `GET /v1/scan/results` | BLE scanning |
| `POST /v1/connect` · `POST /v1/disconnect` · `POST /v1/discover` · `GET /v1/services` | Device / GATT |
| `POST /v1/subscribe` · `POST /v1/unsubscribe` · `POST /v1/read` · `POST /v1/write` | Characteristics |
| `POST /v1/ping` · `POST /v1/ask` | Utility (liveness; push a Yes/No question to the operator) |
| `WS /v1/ws` | Live event stream (ring-buffer replay + fan-out); accepts inbound commands |

When more than one agent is connected, pass `?agent=<agent_id>` to target a specific one; with a
single agent it is selected automatically.

Example:
```bash
curl -s http://127.0.0.1:2673/v1/agents
curl -s -X POST http://127.0.0.1:2673/v1/scan/start -H 'Content-Type: application/json' \
     -d '{"timeout_ms":10000,"name_filter":"WF-"}'
```

---

## Interactive REPL

```bash
python3 -m broker.main --interactive
```

Drive agents from a `bt[...]>` prompt: `agents`, `agent set <id>`, `scan start [<filter>]`,
`scan stop`, `connect <addr>`, `disconnect <addr>`, `discover <addr>`,
`subscribe <addr> <char>`, `read <addr> <char>`, `ping`, `help`, `quit`.

---

## Templates

The broker renders device data using **templates**, which are **not** bundled here — they live in
the separate [bt-bridge-templates](https://github.com/ColdBoreBallistics/bt-bridge-templates)
catalog and are fetched on demand. A fresh broker has an empty `templates/` directory and the
agent falls back to a raw GATT view until templates are installed. (The full template system and
the catalog-fetch tooling are delivered by follow-on plans in `docs/`.)

---

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

---

## Related repos

| Repo | Description |
|---|---|
| [bt-bridge-agent-android](https://github.com/ColdBoreBallistics/bt-bridge-agent-android) | Android BT bridge agent app |
| [bt-bridge-agent-ios](https://github.com/ColdBoreBallistics/bt-bridge-agent-ios) | iOS BT bridge agent app |
| [bt-bridge-templates](https://github.com/ColdBoreBallistics/bt-bridge-templates) | Device / display / codec / component template catalog |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Licensed under
[Apache-2.0](LICENSE).
