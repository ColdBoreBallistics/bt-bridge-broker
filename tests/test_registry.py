"""Unit tests for AgentRegistry."""
from __future__ import annotations

import asyncio
import pytest
from broker.registry import AgentRegistry, AgentState
from tests.helpers import MockAgentConnection


@pytest.fixture
def registry() -> AgentRegistry:
    return AgentRegistry()


@pytest.fixture
def conn() -> MockAgentConnection:
    return MockAgentConnection("agent-001")


def test_register_assigns_id(registry, conn):
    agent_id = registry.register(conn)
    assert agent_id.startswith("agent-")
    assert registry.get_agent(agent_id) is not None


def test_unregister_removes_agent(registry, conn):
    agent_id = registry.register(conn)
    registry.unregister(agent_id)
    assert registry.get_agent(agent_id) is None


def test_list_agents_empty(registry):
    assert registry.list_agents() == []


def test_list_agents_shows_registered(registry, conn):
    registry.register(conn)
    assert len(registry.list_agents()) == 1


def test_resolve_agent_auto_select_single(registry, conn):
    agent_id = registry.register(conn)
    state = registry.resolve_agent(None)
    assert state.agent_id == agent_id


def test_resolve_agent_404_when_empty(registry):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        registry.resolve_agent(None)
    assert exc.value.status_code == 404


def test_resolve_agent_409_when_multiple(registry, conn):
    from fastapi import HTTPException
    conn2 = MockAgentConnection("conn2")
    registry.register(conn)
    registry.register(conn2)
    with pytest.raises(HTTPException) as exc:
        registry.resolve_agent(None)
    assert exc.value.status_code == 409


def test_resolve_agent_by_id_found(registry, conn):
    agent_id = registry.register(conn)
    state = registry.resolve_agent(agent_id)
    assert state.agent_id == agent_id


def test_resolve_agent_by_id_not_found(registry):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        registry.resolve_agent("agent-999")
    assert exc.value.status_code == 404
