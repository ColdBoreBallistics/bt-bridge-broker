"""AgentRegistry — central state store and event fan-out for the BT Bridge broker."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

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
        self._template_registry: Any = None

    def set_template_registry(self, tr: Any) -> None:
        self._template_registry = tr

    @property
    def template_registry(self) -> Any:
        return self._template_registry

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

    def set_services(self, agent_id: str, address: str, services: list[Any]) -> None:
        """Cache the discovered GATT services for a device under the given agent."""
        state = self._agents.get(agent_id)
        if state is not None and address:
            state.services[address] = services

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
                if event.get("name"):
                    entry.name = event.get("name")
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
