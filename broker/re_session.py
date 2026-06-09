"""RE (reverse engineering) capture session state machine."""
from __future__ import annotations

import math
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ReSessionState(Enum):
    IDLE = "idle"
    ACTIVE = "active"
    COMPLETE = "complete"


def _normalize_hex(value_hex: str) -> str:
    """Validate and normalize a hex string. Strips spaces, lowercases.
    Raises ValueError on non-hex chars or odd length."""
    if not isinstance(value_hex, str):
        raise ValueError(f"value_hex must be a string, got {type(value_hex).__name__}")
    cleaned = value_hex.replace(" ", "").lower()
    # bytes.fromhex validates hex chars + even length; let its ValueError propagate (with our message).
    try:
        bytes.fromhex(cleaned)
    except ValueError:
        raise ValueError(f"invalid hex value: {value_hex!r}")
    return cleaned


@dataclass
class ReSession:
    session_id: str
    agent_id: str
    address: str
    state: ReSessionState = ReSessionState.IDLE
    started_at: int = field(default_factory=lambda: int(time.time() * 1000))
    _samples: dict[str, list[str]] = field(default_factory=dict)

    def start(self) -> None:
        self.state = ReSessionState.ACTIVE

    def complete(self) -> None:
        self.state = ReSessionState.COMPLETE

    def add_sample(self, char_uuid: str, value_hex: str) -> None:
        self._samples.setdefault(char_uuid, []).append(_normalize_hex(value_hex))

    def samples_for(self, char_uuid: str) -> list[str]:
        return self._samples.get(char_uuid, [])

    def analyse(self) -> dict[str, Any]:
        """Compute per-byte statistics for each captured characteristic."""
        result: dict[str, Any] = {}
        for char_uuid, samples in self._samples.items():
            byte_arrays = [bytes.fromhex(s) for s in samples]  # samples are pre-validated hex
            max_len = max((len(b) for b in byte_arrays), default=0)

            byte_stats = []
            for i in range(max_len):
                values = [arr[i] for arr in byte_arrays if i < len(arr)]
                if not values:
                    continue
                counts = Counter(values)
                total = len(values)
                entropy = -sum((c / total) * math.log2(c / total) for c in counts.values() if c > 0)
                change_count = sum(1 for j in range(1, len(values)) if values[j] != values[j - 1])
                hint = _infer_hint(i, entropy, min(values), max(values), change_count, total)
                byte_stats.append({
                    "offset": i,
                    "min": min(values),
                    "max": max(values),
                    "entropy": round(entropy, 4),
                    "change_frequency": round(change_count / max(total - 1, 1), 3),
                    "_re_hint": hint,
                })

            result[char_uuid] = {
                "sample_count": len(samples),
                "byte_count": max_len,
                "bytes": byte_stats,
            }
        return result

    def scaffold(self, device_name: str = "Unknown", namespace: str = "contrib") -> dict[str, Any]:
        """Generate a draft display template from session data."""
        analysis = self.analyse()
        notifications = []
        for char_uuid, stats in analysis.items():
            fields_raw = []
            for b in stats["bytes"]:
                fields_raw.append({
                    "id": f"field_{b['offset']}",
                    "label": f"Field @ offset {b['offset']} (auto)",
                    "type": "raw",
                    "offset": b["offset"],
                    "length": 1,
                    "encoding": "uint8",
                    "display": True,
                    "_re_hint": b["_re_hint"],
                })
            notifications.append({
                "char": char_uuid,
                "description": "Auto-captured (RE scaffold)",
                "views": {
                    "raw": {"fields": fields_raw}
                }
            })

        slug = device_name.lower().replace(" ", "-")
        return {
            "schema_version": 1,
            "id": f"{namespace}.{slug}-display",
            "version": "0.1.0",
            "type": "display",
            "name": f"{device_name} Display (RE scaffold)",
            "author": namespace,
            "_re_session_id": self.session_id,
            "_re_address": self.address,
            "notifications": notifications,
            "reads": [],
        }

    def export_tshark(self) -> dict[str, Any]:
        """Export session as tshark-compatible GATT JSON (GATT layer only)."""
        packets = []
        for char_uuid, samples in self._samples.items():
            for i, value_hex in enumerate(samples):
                packets.append({
                    "_index": f"packets-{len(packets)}",
                    "_source": {
                        "layers": {
                            "btatt": {
                                "btatt.handle": "0x0000",
                                "btatt.uuid128": char_uuid,
                                "btatt.value": value_hex,
                                "_bt_bridge_address": self.address,
                                "_bt_bridge_agent_id": self.agent_id,
                            }
                        }
                    }
                })
        return {
            "_bt_bridge_export": True,
            "_note": "GATT-layer only. For full HCI capture use Android HCI snoop log.",
            "_session_id": self.session_id,
            "_address": self.address,
            "packets": packets,
        }


def _infer_hint(
    offset: int,
    entropy: float,
    min_val: int,
    max_val: int,
    change_count: int,
    total: int,
) -> str:
    hints = []
    if entropy < 0.01:
        hints.append("near-zero entropy — likely static header/padding")
    elif entropy > 6.0:
        hints.append("high entropy — likely sensor reading or counter")
    if change_count == 0:
        hints.append("never changes — static field")
    elif change_count >= total - 1:
        hints.append("changes every sample — likely live sensor data")
    if min_val == 0x55 or min_val == 0xAA:
        hints.append("possible framing byte (0x55/0xAA)")
    if max_val - min_val > 200:
        hints.append(f"wide range {min_val}-{max_val} — likely multi-state or scaled value")
    return "; ".join(hints) if hints else "no strong signal"


class ReSessionStore:
    """In-memory store of active RE sessions keyed by session_id."""

    def __init__(self) -> None:
        self._sessions: dict[str, ReSession] = {}

    def create(self, agent_id: str, address: str) -> ReSession:
        session_id = uuid.uuid4().hex[:12]
        s = ReSession(session_id=session_id, agent_id=agent_id, address=address)
        self._sessions[session_id] = s
        return s

    def get(self, session_id: str) -> ReSession | None:
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
