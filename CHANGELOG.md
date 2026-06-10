# Changelog

All notable changes to `bt-bridge-broker` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/) (see [`docs/VERSIONING.md`](docs/VERSIONING.md)).

## [Unreleased]

## [0.9.0] — 2026-06-09

First versioned release. Complete rewrite of the broker from the single-process `ble_server.py`
into a two-tier FastAPI service, plus the template system and on-demand template catalog.

### Added
- **Two-tier broker architecture** — an agent TCP server (default `127.0.0.1:2653`) and a separate
  REST + WebSocket API for test clients (default `127.0.0.1:2673`), wired together via a FastAPI
  lifespan. All connected-agent state lives in a single `AgentRegistry`.
- **REST API** — agents, scan, device (connect/disconnect/discover/services), characteristic
  (subscribe/unsubscribe/read/write), and utility (ping/ask) endpoints, with `?agent=` selection
  and a normalized `{error, message}` error envelope.
- **WebSocket endpoint** (`/v1/ws`) — ring-buffer replay on connect plus live event fan-out, with
  `agent`/`events` filtering and inbound command forwarding.
- **Template system** — full `TemplateRegistry` (disk scan, `schema_version` gate, duplicate
  detection, semver dependency resolution with caret/tilde support, quarantine of unresolvable
  templates, signature matching); `/v1/templates/*` endpoints (list, match, versions, get, reload,
  draft, delete); template push to agents on connect; `apply_template` on `services_discovered`
  signature match; per-agent view selection.
- **Remote template catalog integration** — `CatalogClient` fetches templates on demand from the
  `bt-bridge-templates` catalog (https + token or `file://`), resolves dependency closures, verifies
  `sha256`, and installs into `templates/`; `tools/fetch_templates.py` CLI; `/v1/templates/catalog`
  + install REST endpoints; and a web selection page at `/templates-ui/`.
- **RE (reverse-engineering) capture sessions** — `/v1/re/session/*` endpoints for capturing BLE
  samples, per-byte entropy/range analysis, draft-template scaffolding, and tshark-compatible export.
- **Interactive REPL** (`--interactive`) and **`tools/lint_templates.py`** CI lint.
- FOSS scaffolding: Apache-2.0 `LICENSE`/`NOTICE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `docs/FOSS_GOVERNANCE.md`, `docs/VERSIONING.md`.

### Changed
- Default bind is loopback (`127.0.0.1`) — the broker is unauthenticated; pass `0.0.0.0` to expose
  on the LAN.
- The broker ships **no** built-in templates (catalog-only); a fresh checkout has an empty
  `templates/` and the agent renders via its raw GATT analyser until templates are installed.
- `PROTOCOL.md` updated to the two-tier topology (agent port `9876 → 2653`) and documented the
  template protocol; version markers corrected to `0.9.x`.
- Dependencies split into `requirements.txt` (runtime) and `requirements-dev.txt` (test).

### Removed
- `ble_server.py` — replaced by the `broker/` package. (The `examples/` scripts that imported it
  are tracked for migration to the REST API in CBB-111.)

[Unreleased]: https://github.com/ColdBoreBallistics/bt-bridge-broker/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/ColdBoreBallistics/bt-bridge-broker/releases/tag/v0.9.0
