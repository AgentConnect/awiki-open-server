# AWiki Open Server README Pre-release Maintainer Notes

[English](maintainer-notes.md) | [简体中文](maintainer-notes.zh-CN.md)

This document is not for end users.

## 1. Suggested GitHub About

**Description**

```text
Self-hosted single-node AWiki Community Server with DID identity, messaging, attachments, realtime, and ANP interoperability.
```

**Topics**

```text
self-hosted, fastapi, anp, did, messaging, community-server, federation, python
```

Replace the low-information `awiki lite server` description with wording aligned to the README opening.

## 2. Status

`pyproject.toml` is currently `0.1.0` and describes a single-process Community Server MVP. Keep `v0.1 MVP` and the no-E2EE, single-node, no-production-SMS/email, small-group/no-complex-governance, no-HA/offline-push, and no-relay/peer-route boundaries near the top. Community Group v1 creation, management, direct cross-domain delivery, and member-home projection are supported and must not be described as commercial-only. Do not call it Stable unless those facts materially change.

## 3. Chinese filename

Use `README.zh-CN.md` and update the language link in the English README.

## 4. Public example and general documentation

Existing deployment documentation uses `rwiki.cn` as a real example. The main README and general deployment guide use `community.example.com`. Keep temporary `rwiki.cn` outages, PyPI SSL EOF details, and local-path workarounds in case-specific operations records rather than the project opening.

## 5. Containers

There is no verified Dockerfile/Compose primary path. A future container path needs a non-root image, persistent data/object volume, key secret mount, healthcheck, Compose smoke, and upgrade/backup contract before documentation publishes commands.

## 6. Client compatibility

Before release, run pytest, `smoke-asgi`, `smoke-local`, `smoke-cross-domain-local`, the Rust CLI full Group lifecycle in both public host directions, public `verify-public`, and AWiki Me custom-tenant smoke if app compatibility is claimed. Confirm receipt/outbox/restart evidence and AWiki Me's Agent realm allowlist; never state complete app support.

## 7. Security and license

Keep stable links to `SECURITY.md`, `CONTRIBUTING.md`, `LICENSE`, and a private vulnerability reporting contact. The organization owner still needs to fill the proposed security contact.

## 8. Content moved out of the README

Keep complete environment variables, route/API tables, JSON-RPC semantics, Read/Sync/Heartbeat/Group/Realtime/Attachment details, `rwiki.cn` diagnostics, test-file lists, and temporary installation issues in focused documentation. The home page retains only adoption-critical summaries and entry points.
