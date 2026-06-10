# Security Policy

## Supported versions

BT Bridge is pre-1.0 (`0.x`). Security fixes are applied to the latest released `0.x` version only;
there is no back-porting to older pre-release versions during the 0.x phase.

| Version | Supported |
|---|---|
| latest `0.9.x` | ✅ |
| older `0.x` | ❌ |

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately through either channel:

1. **GitHub private vulnerability reporting** (preferred) — on this repository, go to the
   **Security** tab → **Report a vulnerability**. This opens a private advisory visible only to the
   maintainers.
2. **Email** — `security@coldboreballisticsllc.com` with a description, affected version/commit, and
   reproduction steps.

## What to expect

- **Acknowledgement** within 5 business days.
- An assessment of severity and affected versions, and a remediation plan if confirmed.
- Coordinated disclosure: we will agree on a disclosure timeline with you and credit you in the
  release notes unless you prefer to remain anonymous.

## Scope notes

This is a LAN-only hardware-test tool and is **unauthenticated by design** — it binds loopback by
default and exposes no auth layer. Running it bound to `0.0.0.0` on an untrusted network is outside
the intended threat model; the relevant concerns we do treat as in-scope include: template/catalog
content handling (path traversal, checksum bypass, malformed input causing crashes or RCE),
dependency vulnerabilities, and any way a malicious agent or catalog could compromise the host
beyond the documented unauthenticated-LAN posture.

---

*Part of the BT Bridge project by Cold Bore Ballistics, LLC.*
