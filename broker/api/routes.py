"""REST API routes for the BT Bridge broker."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
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


# ---------------------------------------------------------------------------
# Device endpoints
# ---------------------------------------------------------------------------

class AddressIn(BaseModel):
    address: str


@router.post("/v1/connect", status_code=202)
async def connect_device(
    body: AddressIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    await reg.send_command(state.agent_id, {"cmd": "connect", "address": body.address})
    return {"status": "accepted"}


@router.post("/v1/disconnect", status_code=202)
async def disconnect_device(
    body: AddressIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    await reg.send_command(state.agent_id, {"cmd": "disconnect", "address": body.address})
    return {"status": "accepted"}


@router.post("/v1/discover", status_code=202)
async def discover_services(
    body: AddressIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    await reg.send_command(state.agent_id, {"cmd": "discover", "address": body.address})
    return {"status": "accepted"}


@router.get("/v1/services")
async def get_services(
    request: Request,
    address: str = Query(...),
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    services = state.services.get(address)
    if services is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_discovered", "message": f"No services discovered for {address!r}"},
        )
    return services


# ---------------------------------------------------------------------------
# Characteristic endpoints
# ---------------------------------------------------------------------------
# NOTE: subscribe/unsubscribe return 200 (effect is immediate) while connect/
# disconnect/discover return 202 (longer async device operation, merely accepted).

class CharOpIn(BaseModel):
    address: str
    char: str


class WriteIn(BaseModel):
    address: str
    char: str
    value: str  # lowercase hex
    rsp: bool = True


@router.post("/v1/subscribe")
async def subscribe_char(
    body: CharOpIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    await reg.send_command(state.agent_id, {"cmd": "subscribe", "address": body.address, "char": body.char})
    return {"status": "ok"}


@router.post("/v1/unsubscribe")
async def unsubscribe_char(
    body: CharOpIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    await reg.send_command(state.agent_id, {"cmd": "unsubscribe", "address": body.address, "char": body.char})
    return {"status": "ok"}


@router.post("/v1/read")
async def read_char(
    body: CharOpIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    req_id = uuid.uuid4().hex[:8]
    result = await reg.send_and_wait(
        state.agent_id,
        {"cmd": "read", "address": body.address, "char": body.char},
        req_id,
        timeout=5.0,
    )
    return {"value": result.get("value"), "status": result.get("status", 0)}


@router.post("/v1/write")
async def write_char(
    body: WriteIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    req_id = uuid.uuid4().hex[:8]
    cmd: dict[str, Any] = {
        "cmd": "write",
        "address": body.address,
        "char": body.char,
        "value": body.value,
        "rsp": body.rsp,
    }
    if body.rsp:
        result = await reg.send_and_wait(state.agent_id, cmd, req_id, timeout=5.0)
        return {"status": result.get("status", 0)}
    await reg.send_command(state.agent_id, {**cmd, "req_id": req_id})
    return {"status": "accepted"}


# ---------------------------------------------------------------------------
# Utility endpoints
# ---------------------------------------------------------------------------

@router.post("/v1/ping")
async def ping(
    body: EmptyIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    req_id = uuid.uuid4().hex[:8]
    t0 = time.monotonic()
    await reg.send_and_wait(state.agent_id, {"cmd": "ping"}, req_id, timeout=5.0)
    latency_ms = int((time.monotonic() - t0) * 1000)
    return {"latency_ms": latency_ms}


class AskIn(BaseModel):
    question: str


@router.post("/v1/ask")
async def ask(
    body: AskIn,
    request: Request,
    agent: str | None = Query(default=None),
):
    reg = _registry(request)
    state = reg.resolve_agent(agent)
    req_id = uuid.uuid4().hex[:8]
    result = await reg.send_and_wait(
        state.agent_id,
        {"cmd": "ask", "question": body.question},
        req_id,
        timeout=60.0,
    )
    return {"answered": True, "value": result.get("value")}
