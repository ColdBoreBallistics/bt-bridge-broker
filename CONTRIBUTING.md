# Contributing to BT Bridge Broker

Thanks for your interest in contributing! The BT Bridge Broker is the two-tier server at the
center of the BT Bridge hardware-test harness: it accepts agent connections over TCP and exposes a
REST + WebSocket API to test clients.

This guide assumes no prior experience with this project.

## Table of contents

1. [Project layout](#1-project-layout)
2. [Development setup](#2-development-setup)
3. [Running the broker](#3-running-the-broker)
4. [Tests](#4-tests)
5. [Coding standards](#5-coding-standards)
6. [Commit and PR conventions](#6-commit-and-pr-conventions)
7. [Templates are a separate repo](#7-templates-are-a-separate-repo)
8. [Code of Conduct & licensing](#8-code-of-conduct--licensing)

---

## 1. Project layout

```
broker/
  main.py              entry point (CLI, lifespan, uvicorn)
  registry.py          AgentRegistry — all mutable state + fan-out
  agent_tcp.py         TCP accept loop, one AgentConnection per agent
  api/
    app.py             FastAPI app factory
    routes.py          REST endpoints
    ws.py              WebSocket endpoint
  template_registry.py template scan / resolution / signature matching
  catalog.py           remote catalog fetch client
  re_session.py        reverse-engineering capture sessions
tools/                 CLI utilities (fetch_templates.py, lint_templates.py)
tests/                 pytest suite
protocol.py            event dataclasses + parse/build helpers (do not break wire format)
```

## 2. Development setup

Requires **Python 3.11 or later** (the code uses `match` statements and `X | Y` type unions).

```bash
git clone git@github.com:ColdBoreBallistics/bt-bridge-broker.git
cd bt-bridge-broker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # runtime + test deps
```

- `requirements.txt` — runtime dependencies only.
- `requirements-dev.txt` — includes the runtime set plus the test stack (`pytest`, `httpx`, etc.).
- `requirements-lock.txt` — pinned, reproducible install (`pip install -r requirements-lock.txt`).

## 3. Running the broker

```bash
python3 -m broker.main --debug
# Agent TCP on 2653, REST + WebSocket API on 2673.
# Swagger UI: http://localhost:2673/docs
```

The broker ships with no templates. Install some from the catalog (see §7) or point it at a local
catalog clone via `BT_CATALOG_BASE_URL=file:///path/to/bt-bridge-templates`.

## 4. Tests

This project uses **test-driven development**. Write a failing test first, then the implementation.

```bash
pytest tests/ -v
```

All tests must pass before a PR is merged. Add tests for any new endpoint, registry behavior, or
catalog logic. Async tests use `pytest-asyncio` (`asyncio_mode = "auto"` in `pyproject.toml`).

## 5. Coding standards

- **Python 3.11+ idioms** — `X | None` over `Optional[X]`, `match` where it reads well.
- **No global mutable state** — all agent state lives in `AgentRegistry`, injected via
  `app.state.registry`. Don't add module-level mutable singletons.
- **Type hints** on public functions.
- **Keep `protocol.py` wire-compatible** — the agent apps depend on its JSON shapes. Additive
  changes only, documented in `PROTOCOL.md`.
- **No secrets in code or tests.** Catalog tokens come from `BT_CATALOG_TOKEN`.

## 6. Commit and PR conventions

- **Conventional Commits**: `type(scope): subject` (e.g. `feat(api): add /v1/templates/catalog`).
  Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`, `build`.
- One focused change per PR. Reference any related issue.
- CI must be green (tests + lint) before merge.

## 7. Templates are a separate repo

Device/display/codec/component **templates** are **not** in this repo. They live in
[`bt-bridge-templates`](https://github.com/ColdBoreBallistics/bt-bridge-templates) and are fetched
on demand. To contribute a *template* (no coding required), see that repo's `CONTRIBUTING.md`. This
repo contains only the broker software that *consumes* templates.

## 8. Code of Conduct & licensing

By contributing you agree your contribution is licensed under [Apache-2.0](LICENSE) and that you
will abide by our [Code of Conduct](CODE_OF_CONDUCT.md).
