"""Agent TCP server — one AgentConnection per connected agent app."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from broker.registry import AgentRegistry

log = logging.getLogger(__name__)


class AgentConnection:
    """Wraps a single asyncio TCP stream to one agent."""

    def __init__(self, writer: asyncio.StreamWriter) -> None:
        self._writer = writer
        self.agent_id: str = ""  # assigned by registry.register()

    async def send(self, raw_json: str) -> None:
        try:
            self._writer.write((raw_json + "\n").encode())
            await self._writer.drain()
        except (ConnectionResetError, BrokenPipeError) as exc:
            log.warning("send failed for %s: %s", self.agent_id, exc)

    async def close(self) -> None:
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except Exception:
            pass


async def handle_agent(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    registry: "AgentRegistry",
) -> None:
    """Called by asyncio.start_server for each new agent connection."""
    conn = AgentConnection(writer)
    agent_id = registry.register(conn)
    conn.agent_id = agent_id

    peer = writer.get_extra_info("peername", ("?", 0))
    log.info("Agent connected: %s from %s:%s", agent_id, peer[0], peer[1])

    # Send registration acknowledgement
    await conn.send(json.dumps({"cmd": "register", "agent_id": agent_id}))

    # Notify WebSocket subscribers
    registry.publish(agent_id, {"event": "agent_connected", "agent_id": agent_id, "peer": f"{peer[0]}:{peer[1]}"})

    try:
        while True:
            try:
                line = await reader.readline()
            except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
                break
            if not line:
                break
            raw = line.decode(errors="replace").strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                log.warning("Malformed JSON from %s: %r", agent_id, raw[:120])
                continue
            registry.update_state(agent_id, event)
            registry.publish(agent_id, event)
    except Exception as exc:
        log.error("Unexpected error in agent loop for %s: %s", agent_id, exc)
    finally:
        registry.unregister(agent_id)
        registry.publish(agent_id, {"event": "agent_disconnected", "agent_id": agent_id})
        await conn.close()
        log.info("Agent disconnected: %s", agent_id)
