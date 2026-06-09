"""Shared test helpers — mock AgentConnection and event injection."""
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock


class MockAgentConnection:
    """Simulates an AgentConnection for registry unit tests."""

    def __init__(self, agent_id: str = "agent-001"):
        self.agent_id = agent_id
        self._sent: list[str] = []
        self._closed = False

    async def send(self, raw_json: str) -> None:
        self._sent.append(raw_json)

    async def close(self) -> None:
        self._closed = True

    def sent_commands(self) -> list[dict[str, Any]]:
        return [json.loads(s) for s in self._sent]

    def last_command(self) -> dict[str, Any] | None:
        if self._sent:
            return json.loads(self._sent[-1])
        return None
