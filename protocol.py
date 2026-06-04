"""
BLE Bridge Protocol v1.0 — message dataclasses and serialization.

All byte values are transmitted as lowercase hex strings.
Timestamps are Unix epoch milliseconds.
UUIDs are lowercase with hyphens (full 128-bit form).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_ms() -> int:
    return int(time.time() * 1000)


def hex_to_bytes(h: str) -> bytes:
    return bytes.fromhex(h.replace(" ", ""))


def bytes_to_hex(b: bytes) -> str:
    return b.hex()


# ---------------------------------------------------------------------------
# Events (Mobile → Server)
# ---------------------------------------------------------------------------

@dataclass
class ScanResult:
    address: str
    name:    str | None
    rssi:    int
    ts:      int = field(default_factory=_now_ms)

@dataclass
class Connected:
    address: str
    ts:      int = field(default_factory=_now_ms)

@dataclass
class Disconnected:
    address: str
    code:    int
    ts:      int = field(default_factory=_now_ms)

@dataclass
class CharDescriptor:
    uuid:  str
    props: list[str]

@dataclass
class ServiceDescriptor:
    uuid:  str
    chars: list[CharDescriptor]

@dataclass
class ServicesDiscovered:
    address:  str
    services: list[ServiceDescriptor]
    ts:       int = field(default_factory=_now_ms)

@dataclass
class Notification:
    address: str
    char:    str
    value:   str         # lowercase hex
    ts:      int = field(default_factory=_now_ms)

    @property
    def value_bytes(self) -> bytes:
        return hex_to_bytes(self.value)

@dataclass
class ReadResult:
    address: str
    char:    str
    value:   str         # lowercase hex
    status:  int
    req_id:  str
    ts:      int = field(default_factory=_now_ms)

    @property
    def value_bytes(self) -> bytes:
        return hex_to_bytes(self.value)

@dataclass
class WriteResult:
    address: str
    char:    str
    status:  int
    req_id:  str
    ts:      int = field(default_factory=_now_ms)

@dataclass
class Error:
    code:    str
    message: str
    ts:      int = field(default_factory=_now_ms)

@dataclass
class Pong:
    ts: int = field(default_factory=_now_ms)

@dataclass
class Log:
    level:   str
    message: str
    ts:      int = field(default_factory=_now_ms)


Event = (
    ScanResult | Connected | Disconnected | ServicesDiscovered |
    Notification | ReadResult | WriteResult | Error | Pong | Log
)


# ---------------------------------------------------------------------------
# Commands (Server → Mobile)
# ---------------------------------------------------------------------------

def cmd_scan_start(timeout_ms: int = 10000, name_filter: str | None = None) -> str:
    d: dict[str, Any] = {"cmd": "scan_start", "timeout_ms": timeout_ms}
    if name_filter is not None:
        d["name_filter"] = name_filter
    return json.dumps(d)

def cmd_scan_stop() -> str:
    return json.dumps({"cmd": "scan_stop"})

def cmd_connect(address: str) -> str:
    return json.dumps({"cmd": "connect", "address": address})

def cmd_disconnect(address: str) -> str:
    return json.dumps({"cmd": "disconnect", "address": address})

def cmd_discover(address: str) -> str:
    return json.dumps({"cmd": "discover", "address": address})

def cmd_subscribe(address: str, char: str) -> str:
    return json.dumps({"cmd": "subscribe", "address": address, "char": char})

def cmd_unsubscribe(address: str, char: str) -> str:
    return json.dumps({"cmd": "unsubscribe", "address": address, "char": char})

def cmd_read(address: str, char: str, req_id: str) -> str:
    return json.dumps({"cmd": "read", "address": address, "char": char, "req_id": req_id})

def cmd_write(address: str, char: str, value: bytes, req_id: str, rsp: bool = True) -> str:
    return json.dumps({
        "cmd":     "write",
        "address": address,
        "char":    char,
        "value":   bytes_to_hex(value),
        "rsp":     rsp,
        "req_id":  req_id,
    })

def cmd_ping() -> str:
    return json.dumps({"cmd": "ping"})


# ---------------------------------------------------------------------------
# Parsing (incoming events from mobile)
# ---------------------------------------------------------------------------

def parse_event(line: str) -> Event | None:
    """Parse a newline-terminated JSON line into an Event dataclass.
    Returns None for unrecognised event types (forward-compatibility)."""
    try:
        d = json.loads(line.strip())
    except json.JSONDecodeError:
        return None

    etype = d.get("event")

    match etype:
        case "scan_result":
            return ScanResult(
                address=d["address"],
                name=d.get("name"),
                rssi=d["rssi"],
                ts=d.get("ts", _now_ms()),
            )
        case "connected":
            return Connected(address=d["address"], ts=d.get("ts", _now_ms()))
        case "disconnected":
            return Disconnected(
                address=d["address"],
                code=d.get("code", -1),
                ts=d.get("ts", _now_ms()),
            )
        case "services_discovered":
            services = [
                ServiceDescriptor(
                    uuid=s["uuid"],
                    chars=[CharDescriptor(uuid=c["uuid"], props=c.get("props", [])) for c in s.get("chars", [])],
                )
                for s in d.get("services", [])
            ]
            return ServicesDiscovered(address=d["address"], services=services, ts=d.get("ts", _now_ms()))
        case "notification":
            return Notification(
                address=d["address"],
                char=d["char"],
                value=d["value"].replace(" ", ""),
                ts=d.get("ts", _now_ms()),
            )
        case "read_result":
            return ReadResult(
                address=d["address"],
                char=d["char"],
                value=d["value"].replace(" ", ""),
                status=d.get("status", -1),
                req_id=d.get("req_id", ""),
                ts=d.get("ts", _now_ms()),
            )
        case "write_result":
            return WriteResult(
                address=d["address"],
                char=d["char"],
                status=d.get("status", -1),
                req_id=d.get("req_id", ""),
                ts=d.get("ts", _now_ms()),
            )
        case "error":
            return Error(code=d.get("code", "unknown"), message=d.get("message", ""), ts=d.get("ts", _now_ms()))
        case "pong":
            return Pong(ts=d.get("ts", _now_ms()))
        case "log":
            return Log(level=d.get("level", "info"), message=d.get("message", ""), ts=d.get("ts", _now_ms()))
        case _:
            return None
