"""FastAPI app factory for the BT Bridge broker."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from broker.registry import AgentRegistry


def create_app(registry: AgentRegistry) -> FastAPI:
    """Create and configure the FastAPI application.

    The registry is attached to app.state so all routes can access it via
    request.app.state.registry without global state.
    """

    app = FastAPI(
        title="BT Bridge Broker",
        version="1.2.0",
        description="REST + WebSocket API for the BT Bridge hardware test harness.",
    )
    app.state.registry = registry

    # Register routers
    from broker.api.routes import router as rest_router
    from broker.api.ws import router as ws_router

    app.include_router(rest_router)
    app.include_router(ws_router)

    # Custom error handler — normalise HTTPException bodies to {"error": ..., "message": ...}
    @app.exception_handler(Exception)
    async def _http_exc_handler(request: Request, exc: Exception) -> JSONResponse:
        from fastapi import HTTPException
        if isinstance(exc, HTTPException):
            detail = exc.detail
            if isinstance(detail, dict):
                return JSONResponse(status_code=exc.status_code, content=detail)
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": "http_error", "message": str(detail)},
            )
        return JSONResponse(status_code=500, content={"error": "internal_error", "message": str(exc)})

    return app
