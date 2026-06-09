"""REST API routes for the BT Bridge broker."""
from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from broker.registry import AgentRegistry, ScanResultEntry

router = APIRouter()


def _registry(request: Request) -> AgentRegistry:
    return request.app.state.registry


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AgentStateOut(BaseModel):
    agent_id: str
    platform: str | None
    capabilities: list[str]
    connected_since_ms: int
    ble_enabled: bool
    scanning: bool
    connected_devices: list[str]
    last_status_ms: int


class ScanResultOut(BaseModel):
    address: str
    name: str | None
    rssi: int
    last_seen_ms: int


class ScanStartIn(BaseModel):
    timeout_ms: int = 10000
    name_filter: str | None = None


class EmptyIn(BaseModel):
    pass


# ---------------------------------------------------------------------------
# Agent endpoints
# ---------------------------------------------------------------------------

@router.get("/v1/agents", response_model=list[AgentStateOut])
async def list_agents(request: Request):
    reg = _registry(request)
    return [
        AgentStateOut(
            agent_id=a.agent_id,
            platform=a.platform,
            capabilities=a.capabilities,
            connected_since_ms=a.connected_since_ms,
            ble_enabled=a.ble_enabled,
            scanning=a.scanning,
            connected_devices=a.connected_devices,
            last_status_ms=a.last_status_ms,
        )
        for a in reg.list_agents()
    ]


@router.get("/v1/agents/{agent_id}", response_model=AgentStateOut)
async def get_agent(agent_id: str, request: Request):
    reg = _registry(request)
    state = reg.resolve_agent(agent_id)
    return AgentStateOut(
        agent_id=state.agent_id,
        platform=state.platform,
        capabilities=state.capabilities,
        connected_since_ms=state.connected_since_ms,
        ble_enabled=state.ble_enabled,
        scanning=state.scanning,
        connected_devices=state.connected_devices,
        last_status_ms=state.last_status_ms,
    )


# ---------------------------------------------------------------------------
# Scan endpoints
# ---------------------------------------------------------------------------

@router.post("/v1/scan/start", status_code=202)
async def scan_start(
    body: ScanStartIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    cmd: dict[str, Any] = {"cmd": "scan_start", "timeout_ms": body.timeout_ms}
    if body.name_filter is not None:
        cmd["name_filter"] = body.name_filter
    await reg.send_command(state.agent_id, cmd)
    return {"status": "accepted"}


@router.post("/v1/scan/stop")
async def scan_stop(
    body: EmptyIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    await reg.send_command(state.agent_id, {"cmd": "scan_stop"})
    return {"status": "ok"}


@router.get("/v1/scan/results", response_model=list[ScanResultOut])
async def scan_results(
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    results = reg.get_scan_results(state.agent_id)
    return [
        ScanResultOut(
            address=r.address,
            name=r.name,
            rssi=r.rssi,
            last_seen_ms=r.last_seen_ms,
        )
        for r in results
    ]
