# bt-bridge-broker

Desktop broker for the BT Bridge test harness. Receives Bluetooth events from a connected
agent app ([bt-bridge-agent-android](https://github.com/ColdBoreBallistics/bt-bridge-agent-android) or
[bt-bridge-agent-ios](https://github.com/ColdBoreBallistics/bt-bridge-agent-ios)) and drives
Bluetooth operations interactively or from a test script.

See [PROTOCOL.md](PROTOCOL.md) for the full wire protocol specification.

---

## Requirements

- Python 3.11 or later
- No third-party packages — stdlib only

### Installing Python 3.11+

**Debian:**
```bash
sudo apt update && sudo apt install python3 python3-pip
python3 --version   # confirm 3.11+
```

**Ubuntu:**
```bash
sudo apt update && sudo apt install python3 python3-pip
python3 --version
```

**RHEL / Fedora:**
```bash
sudo dnf install python3
python3 --version
```

**Windows:**
Download the installer from [python.org](https://www.python.org/downloads/).
During installation, check **"Add Python to PATH"**.
Confirm in a terminal: `python --version`

**macOS:**
```bash
brew install python
python3 --version
```

---

## Setup

No installation needed. Clone the repo and run directly:

```bash
git clone https://github.com/ColdBoreBallistics/bt-bridge-broker.git
cd bt-bridge-broker
python3 ble_server.py
```

---

## Quickstart — Interactive Mode

1. **Find your machine's local IP address.**

   On Linux/macOS:
   ```bash
   ip addr show   # look for your LAN IP, e.g. 172.31.1.200
   ```
   On Windows: `ipconfig` — look for IPv4 Address under your LAN adapter.

2. **Start the broker:**
   ```bash
   python3 ble_server.py --port 9876
   ```
   The broker prints `Listening on 0.0.0.0:9876` and waits for an agent connection.

3. **Connect the agent app.**
   Open bt-bridge-agent-android (or bt-bridge-agent-ios). Enter your machine's IP and port `9876`, then
   tap **Connect to Server**. The broker prints `Mobile client connected from …`.

4. **Type commands at the `ble>` prompt:**

   ```
   ble> scan WF-           # scan for WeatherFlow sensors
   ble> connect AA:BB:CC:DD:EE:FF
   ble> discover
   ble> sub 961f0005-0000-1000-8000-00805f9b34fb
   ble> ping
   ble> disconnect
   ble> quit
   ```

   Full command reference:

   | Command | Description |
   |---|---|
   | `scan [prefix]` | Start scanning; optional name prefix filter |
   | `stop` | Stop scanning |
   | `connect <addr>` | Connect to device |
   | `disconnect` | Disconnect current device |
   | `discover` | Discover services (call after connect) |
   | `sub <char-uuid>` | Subscribe to characteristic notifications |
   | `unsub <char-uuid>` | Unsubscribe |
   | `read <char-uuid>` | Read characteristic value |
   | `write <char-uuid> <hex>` | Write with response |
   | `writenr <char-uuid> <hex>` | Write without response |
   | `ping` | Ping agent app |
   | `quit` | Exit |

---

## Scripted Mode

Import `BleServer` and `protocol` for automated test scenarios:

```python
import asyncio
import sys
sys.path.insert(0, "/path/to/bt-bridge-broker")

from ble_server import BleServer
import protocol as P

async def main():
    server = BleServer(port=9876)
    await server.start()
    await server.wait_connected()

    await server.send(P.cmd_scan_start(name_filter="WF-"))
    result = await server.wait_for(P.ScanResult, timeout=20.0)
    print(f"Found: {result.address} ({result.name})")

    await server.send(P.cmd_scan_stop())
    await server.send(P.cmd_connect(result.address))
    await server.wait_for(P.Connected)

    await server.send(P.cmd_discover(result.address))
    svcs = await server.wait_for(P.ServicesDiscovered)
    for s in svcs.services:
        print(f"  {s.uuid}")

    await server.send(P.cmd_disconnect(result.address))
    await server.stop()

asyncio.run(main())
```

---

## Example Scripts

Pre-built verification scripts live in `examples/`:

| Script | Purpose | Related Jira |
|---|---|---|
| `weatherflow_verify.py` | WeatherFlow Tactical end-to-end data verification | DOPE-29, DOPE-30 |
| `niimbot_b1_verify.py` | Niimbot B1 / B21 Pro UUID discovery and comparison | DOPE-33 |

Run any example from the `examples/` directory:
```bash
cd examples
python3 weatherflow_verify.py --duration 120
python3 niimbot_b1_verify.py --name B21
```

---

## Options

```
python3 ble_server.py [--host HOST] [--port PORT] [--log FILE] [--debug]

  --host   Bind address (default: 0.0.0.0 — all interfaces)
  --port   TCP port (default: 9876)
  --log    Write log output to FILE in addition to stdout
  --debug  Enable verbose debug logging
```

---

## Protocol

See [PROTOCOL.md](PROTOCOL.md) — the authoritative wire protocol specification for all
platform implementations.

---

## Related Repos

| Repo | Description |
|---|---|
| [bt-bridge-agent-android](https://github.com/ColdBoreBallistics/bt-bridge-agent-android) | Android BT bridge agent app |
| [bt-bridge-agent-ios](https://github.com/ColdBoreBallistics/bt-bridge-agent-ios) | iOS BT bridge agent app |
