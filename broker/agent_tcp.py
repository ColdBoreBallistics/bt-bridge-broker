"""Agent TCP server — one AgentConnection per connected agent app."""
from __future__ import annotations

import asyncio
import json
import logging
import time
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

    # Template push — send the manifest of available templates (if a registry is attached).
    template_registry = registry.template_registry
    if template_registry is not None:
        manifest = template_registry.manifest()
        if manifest:
            await conn.send(json.dumps({"cmd": "push_templates", "manifest": manifest}))
            log.debug("Sent push_templates to %s (%d templates)", agent_id, len(manifest))

    # Notify WebSocket subscribers
    registry.publish(agent_id, {"event": "agent_connected", "peer": f"{peer[0]}:{peer[1]}", "ts": int(time.time() * 1000)})

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

            etype = event.get("event")

            # template_request — respond with template_data for each requested id+version.
            if etype == "template_request" and template_registry is not None:
                ids = event.get("ids")
                if not isinstance(ids, list):
                    ids = []
                for item in ids:
                    if not isinstance(item, dict):
                        continue
                    tid = item.get("id")
                    ver = item.get("version")
                    content = template_registry.get(tid, ver) if tid and ver else None
                    if content is not None:
                        await conn.send(json.dumps({
                            "cmd": "template_data", "id": tid, "version": ver, "content": content,
                        }))
                    else:
                        log.warning("Agent %s requested unknown template %s@%s", agent_id, tid, ver)
                continue  # not published to the WS fan-out

            # services_discovered — cache services + run signature match → apply_template.
            if etype == "services_discovered" and template_registry is not None:
                raw_services = event.get("services")
                services = raw_services if isinstance(raw_services, list) else []
                service_uuids = [
                    s.get("uuid") for s in services
                    if isinstance(s, dict) and s.get("uuid")
                ]
                address = event.get("address", "")
                registry.set_services(agent_id, address, services)
                name = event.get("name")
                manufacturer_data = event.get("manufacturer_data")
                matches = template_registry.match_device(
                    service_uuids,
                    name_prefix=name if isinstance(name, str) and name else None,
                    manufacturer_data=manufacturer_data if isinstance(manufacturer_data, str) and manufacturer_data else None,
                )
                if matches:
                    best = matches[0]
                    await conn.send(json.dumps({
                        "cmd": "apply_template",
                        "address": address,
                        "device_template_id": best["device_template_id"],
                        "version": best["version"],
                        "variant_id": best["variant_id"],
                    }))
                    log.info("Matched %s to %s@%s variant=%s (%s)", address,
                             best["device_template_id"], best["version"],
                             best["variant_id"], best["confidence"])
                else:
                    log.info("No template match for %s — agent uses raw GATT", address)
                # services_discovered still falls through to update_state + publish below.

            registry.update_state(agent_id, event)
            registry.publish(agent_id, event)
    except Exception as exc:
        log.error("Unexpected error in agent loop for %s: %s", agent_id, exc)
    finally:
        registry.unregister(agent_id)
        registry.publish(agent_id, {"event": "agent_disconnected", "ts": int(time.time() * 1000)})
        await conn.close()
        log.info("Agent disconnected: %s", agent_id)
