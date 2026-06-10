# Versioning & Release Policy

The BT Bridge project follows [Semantic Versioning 2.0.0](https://semver.org/). This document is
the authoritative policy for how versions are assigned, tagged, and released across the
`bt-bridge-*` repositories.

## 1. Version format

`MAJOR.MINOR.PATCH`, optionally with a pre-release suffix (`-rc1`, `-beta1`).

| Component | Increment when |
|---|---|
| **MAJOR** | A backward-incompatible change: a breaking change to the agent wire protocol (`PROTOCOL.md`), the REST/WebSocket API, or the template `schema_version`. |
| **MINOR** | Backward-compatible new functionality: a new endpoint, command, event, field type, or capability. Additive only. |
| **PATCH** | Backward-compatible bug fixes and internal changes that don't alter the public surface. |

### The 0.x pre-release phase

While the version is **`0.y.z`** the project is pre-1.0 and the public surfaces are not yet
frozen. During 0.x:

- A `0.MINOR` bump may include breaking changes (there is no stability guarantee before 1.0.0).
- `0.PATCH` is still reserved for fixes.
- Reaching **`1.0.0`** is the gate that flips the project to a stable public contract — from that
  point MAJOR/MINOR/PATCH carry their full SemVer guarantees, and (per project policy) 1.0.0 also
  marks the transition from pre-production to production posture.

## 2. Version source of truth

Each repository declares its version in exactly one place:

| Repo | Version source |
|---|---|
| `bt-bridge-broker` | The `version=` in the FastAPI app (`broker/api/app.py`) and the `PROTOCOL.md` revision-control block. |
| `bt-bridge-agent-android` | `versionName` in `app/build.gradle.kts` (`versionCode` is a separate monotonic integer for store ordering, not the SemVer). |
| `bt-bridge-templates` | The repository follows the project version for releases; **individual templates carry their own independent `version`** field and are versioned per-template (a template bump does not require a repo release). |

The git **tag** is the release record (see §4). The tag and the in-repo version source must agree.

## 3. What a version number does NOT track

- `versionCode` (Android) — a build-ordering integer, incremented every store upload; unrelated to SemVer.
- Per-template versions in the catalog — independent of the catalog repo's release version.

## 4. Tags & releases

- **Tag format:** `v<version>` (e.g. `v0.9.0`, `v1.0.0-rc1`). Annotated tags only.
- **A release is a git tag plus a GitHub Release.** The GitHub Release notes are drawn from the
  `CHANGELOG.md` entry for that version.
- Tags are created **only from `main`**, only after the release checklist (§6) passes.
- Tags are immutable once pushed — never move or delete a published tag; cut a new patch instead.

## 5. Branching & release flow

```
  feature work ──▶ topic branch ──PR+review+green CI──▶ main
                                                          │
                                          release: bump version + CHANGELOG
                                                          │
                                              merge ──▶ tag v<version> ──▶ GitHub Release
```

- **`main` is always releasable** — green CI, all tests passing.
- Day-to-day work happens on short-lived topic branches (`feat/...`, `fix/...`) that squash-merge
  to `main` via reviewed PRs.
- A **release branch** (`release/v<version>`) may be used to stabilize a release candidate when
  needed; otherwise release directly from `main`.
- The historical long-lived `b<version>` branch (used during initial development) is retired in
  favor of this flow once the first tagged release lands.

## 6. Release checklist

Before tagging `v<version>`:

- [ ] All tests pass on `main` (CI green).
- [ ] The in-repo version source (§2) is set to `<version>`.
- [ ] `CHANGELOG.md` has a finalized `[<version>]` section (move items out of `Unreleased`).
- [ ] `PROTOCOL.md` revision-control block updated (broker) if the wire protocol changed.
- [ ] No unguarded debug output; no secrets.

Then: merge to `main` → `git tag -a v<version> -m "..."` → push tag → the release workflow
publishes the GitHub Release.

## 7. Coordinated changes across repos

A wire-protocol change spans `bt-bridge-broker` and the agent repos. When the protocol's
`MAJOR`/`MINOR` changes, bump it in `PROTOCOL.md` (the canonical spec) and release the affected
repos together so a deployed broker and agent remain compatible. The agent and broker need not
share an identical version number, but their supported protocol versions must overlap.

---

*This policy applies to all `bt-bridge-*` repositories. Linked from each repo's `CONTRIBUTING.md`.*
