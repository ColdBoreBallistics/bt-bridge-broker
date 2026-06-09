"""WebSocket endpoint for the BT Bridge broker."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from broker.registry import AgentRegistry

router = APIRouter()
log = logging.getLogger(__name__)


@router.websocket("/v1/ws")
async def ws_endpoint(
    websocket: WebSocket,
    agent: str | None = Query(default=None),
    events: str | None = Query(default=None),
):
    await websocket.accept()

    registry: AgentRegistry = websocket.app.state.registry
    # Normalize: empty/whitespace agent or events query param means "no filter".
    agent_filter = agent.strip() if agent and agent.strip() else None
    event_filter: set[str] | None = (
        {e.strip() for e in events.split(",") if e.strip()} if events and events.strip() else None
    )

    queue, token = registry.subscribe()

    # Replay buffered events
    for envelope in registry.buffered_events():
        if agent_filter is not None and envelope.get("agent_id") != agent_filter:
            continue
        if event_filter and envelope.get("event") not in event_filter:
            continue
        try:
            await websocket.send_text(json.dumps(envelope))
        except WebSocketDisconnect:
            registry.unsubscribe(token)
            return

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_drain_queue(websocket, queue, agent_filter, event_filter))
            tg.create_task(_receive_commands(websocket, registry))
    except* (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        registry.unsubscribe(token)
        log.debug("WebSocket client disconnected")


async def _drain_queue(
    ws: WebSocket,
    queue: asyncio.Queue,
    agent_filter: str | None,
    event_filter: set[str] | None,
) -> None:
    while True:
        envelope = await queue.get()
        if agent_filter and envelope.get("agent_id") != agent_filter:
            continue
        if event_filter and envelope.get("event") not in event_filter:
            continue
        await ws.send_text(json.dumps(envelope))


async def _receive_commands(ws: WebSocket, registry: AgentRegistry) -> None:
    while True:
        text = await ws.receive_text()
        try:
            msg = json.loads(text)
        except json.JSONDecodeError:
            log.warning("Malformed JSON from WS client: %r", text[:120])
            continue
        agent_id = msg.pop("agent_id", None)
        try:
            state = registry.resolve_agent(agent_id)
        except Exception as exc:
            await ws.send_text(json.dumps({"error": "agent_error", "message": str(exc)}))
            continue
        await registry.send_command(state.agent_id, msg)
