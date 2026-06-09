"""BT Bridge Broker — entry point.

Run with:
    python3 -m broker.main
    python3 -m broker.main --agent-port 2653 --api-port 2673 --interactive --debug
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BT_")

    # Default to loopback — the broker is unauthenticated. Pass 0.0.0.0 (or set
    # BT_AGENT_HOST / BT_API_HOST) to expose it on the LAN for real device testing.
    agent_host: str = "127.0.0.1"
    agent_port: int = 2653
    api_host: str = "127.0.0.1"
    api_port: int = 2673
    interactive: bool = False
    log_file: str | None = None
    debug: bool = False


settings = Settings()


def _configure_logging() -> None:
    level = logging.DEBUG if settings.debug else logging.INFO
    handlers: list[Any] = [logging.StreamHandler()]
    if settings.log_file:
        handlers.append(logging.FileHandler(settings.log_file))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        handlers=handlers,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    from broker.agent_tcp import handle_agent
    from broker.registry import AgentRegistry
    from broker.template_registry import TemplateRegistry

    registry = AgentRegistry()
    template_registry = TemplateRegistry()
    template_registry.load()
    registry.set_template_registry(template_registry)

    tcp_server = await asyncio.start_server(
        lambda r, w: handle_agent(r, w, registry),
        host=settings.agent_host,
        port=settings.agent_port,
    )
    log = logging.getLogger(__name__)
    log.info(
        "BT Bridge Broker started — agent TCP %s:%s  API %s:%s",
        settings.agent_host,
        settings.agent_port,
        settings.api_host,
        settings.api_port,
    )

    app.state.registry = registry
    app.state.template_registry = template_registry

    if settings.interactive:
        from broker.repl import run_repl
        asyncio.create_task(run_repl(registry))

    yield

    tcp_server.close()
    await tcp_server.wait_closed()
    log.info("BT Bridge Broker stopped")


def create_app_with_lifespan() -> FastAPI:
    from broker.api.app import create_app

    # The registry is created and assigned to app.state by the lifespan (below),
    # so the factory is called WITHOUT one — the lifespan is the sole owner.
    app = create_app()
    app.router.lifespan_context = lifespan
    return app


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="BT Bridge Broker")
    parser.add_argument("--agent-host", default=settings.agent_host)
    parser.add_argument("--agent-port", type=int, default=settings.agent_port)
    parser.add_argument("--api-host", default=settings.api_host)
    parser.add_argument("--api-port", type=int, default=settings.api_port)
    parser.add_argument("--interactive", action="store_true", default=settings.interactive)
    parser.add_argument("--log", default=settings.log_file, dest="log_file")
    parser.add_argument("--debug", action="store_true", default=settings.debug)
    args = parser.parse_args()

    settings.agent_host = args.agent_host
    settings.agent_port = args.agent_port
    settings.api_host = args.api_host
    settings.api_port = args.api_port
    settings.interactive = args.interactive
    settings.log_file = args.log_file
    settings.debug = args.debug

    _configure_logging()

    app = create_app_with_lifespan()
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
