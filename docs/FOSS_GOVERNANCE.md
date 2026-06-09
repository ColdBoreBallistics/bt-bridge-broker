# BT Bridge — Open Source Governance

This document describes how the BT Bridge project is organized as an open-source effort: the
repositories, their licensing, how templates are distributed, and how contributions flow. It is the
deeper-detail companion to each repo's root `CONTRIBUTING.md`.

> Status: the BT Bridge repositories are currently **private** but are structured, licensed, and
> documented **as if public**, so they can be opened with no restructuring. References below to
> "FOSS" and "community" describe the intended public model.

## 1. Repositories

| Repository | Language | Role |
|---|---|---|
| [`bt-bridge-broker`](https://github.com/ColdBoreBallistics/bt-bridge-broker) | Python / FastAPI | Two-tier server: agent TCP + REST/WebSocket API. Consumes templates. |
| [`bt-bridge-agent-android`](https://github.com/ColdBoreBallistics/bt-bridge-agent-android) | Kotlin / Compose | On-device BLE agent. Renders data using templates pushed from the broker. |
| [`bt-bridge-agent-ios`](https://github.com/ColdBoreBallistics/bt-bridge-agent-ios) | Swift | iOS agent (placeholder; implementation begins with iOS app development). |
| [`bt-bridge-templates`](https://github.com/ColdBoreBallistics/bt-bridge-templates) | JSON (data) | Catalog of device/display/codec/component templates. No code required to contribute. |

## 2. Licensing

All BT Bridge repositories are licensed under **Apache-2.0** (see each repo's `LICENSE` and
`NOTICE`). Apache-2.0 was chosen over MIT for its explicit patent grant and trademark protections,
appropriate for a company-backed open-source project. Community contributions are accepted under the
same license; contributor attribution is retained (in commit history for code, and in each
template's `author` field for catalog data).

## 3. Template distribution model (catalog-only)

The broker ships **no** built-in templates. All templates live in `bt-bridge-templates` and are
fetched **on demand**:

```
  bt-bridge-templates (catalog repo)
    catalog/index.json  ──fetch──▶  broker CatalogClient
    catalog/**/*.json   ──download (verify sha256)──▶  broker templates/  ──load──▶  TemplateRegistry
                                                                                         │
                                                                       push_templates ──▶ agent
```

This separation is deliberate:

- **Choice** — users install only the templates they need, via a CLI (`tools/fetch_templates.py`)
  or a web selection page (`/templates-ui/`). The FOSS community values explicit choice over
  bundled defaults.
- **Independent contribution** — adding a device template is a data-only PR against the catalog
  repo; it requires no broker release and no programming.
- **Clean separation of concerns** — the broker is software; the catalog is data. They version
  independently.

Integrity: each catalog entry carries a `sha256`; the broker refuses any downloaded template whose
hash doesn't match the index. Files are written under `templates/` using names derived from the
template id+version (never the raw index path), preventing path traversal from a malicious index.

See **`docs/2026-06-08-broker-catalog-integration-plan.md`** for the implementation plan.

## 4. Contribution flow

| Contribution | Repo | Process |
|---|---|---|
| Broker code | `bt-bridge-broker` | Fork → branch → TDD → `pytest` green → PR (Conventional Commits) |
| Agent code | `bt-bridge-agent-android` | Fork → branch → unit tests green → PR |
| **A new device template** | `bt-bridge-templates` | Fork → add `contrib.*` JSON under `catalog/community/` → lint green → regenerate index → PR |

Community template PRs are gated by CI: structural lint over the whole catalog, plus a
`contrib.`-only namespace rule for `catalog/community/`. First-party `builtin.*` templates are
maintained by the project.

## 5. Governance and maintainers

- **Maintainers** review and merge PRs, cut releases, and enforce the Code of Conduct.
- **Decisions** on protocol changes (the `Protocol.kt` / `protocol.py` / `PROTOCOL.md` wire format)
  must be coordinated across the broker and agent repos, since both sides must agree on the format.
- **Releases** are tagged per repo with independent semantic versions. Template versions in the
  catalog are independent of broker/agent versions.
- **Security reports** and Code of Conduct reports go to `conduct@coldboreballisticsllc.com`.

## 6. Roadmap

- **Open-sourcing.** Repos are private today; the structure here supports flipping them public with
  no rework. When public, the catalog's GitHub-token requirement becomes optional.
- **Community templates repo growth.** As `catalog/community/` grows, expect labeled "verified on
  hardware" vs "unverified" templates and possibly a curated featured set.
- **Signed catalog index.** The per-entry `sha256` protects file integrity today; a future step is
  signing `index.json` itself (e.g. minisign) so the broker can verify provenance before trusting
  any hash.
- **iOS agent.** Begins when iOS app development starts; consumes templates identically to Android.
