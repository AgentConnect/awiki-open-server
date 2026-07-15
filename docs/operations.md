# AWiki Open Server Data, Backup, and Operations

[English](operations.md) | [简体中文](operations.zh-CN.md)

## 1. Data assets

`AWIKI_DATA_DIR` is the primary persistence boundary. It contains at least SQLite, committed attachment objects, implementation-specific temporary/uncommitted object or slot state, and local business state. The service private key normally lives in a separate secure directory and must not be distributed unprotected with Git or public data backups.

## 2. Consistent backups

SQLite and object files jointly represent message/attachment facts. Backing up only one can create unrecoverable inconsistency.

Conservative single-node procedure:

1. Stop external writes.
2. Stop the app, or use a verified consistent snapshot method.
3. Back up all of `AWIKI_DATA_DIR`.
4. Back up the service DID private key and configuration separately with stricter access controls.
5. Record the code commit, Python/ANP versions, and a secret-free environment summary.
6. Restart and run health/smoke checks.

## 3. Restore

Restore in isolation first: use matching code and dependencies; restore `AWIKI_DATA_DIR` and the same service DID/key; verify ownership and permissions; start on a non-production port; run `healthz`, `smoke-local`, and required client smoke; confirm the DID Document/endpoint; then switch production traffic.

Never attempt schema or key repair on production data without a backup.

## 4. Upgrade

The baseline does not promise complete online migration, rollback, or cross-version compatibility. Before upgrading, read release/schema notes, record the current commit and ANP SDK version, take a complete backup, validate on copied data, stop writes, then run pytest, local smoke, CLI smoke, and public verification. On failure, restore a consistent combination of code, data, and key.

Replacing Python code alone is not a complete upgrade when data, objects, and service identity are involved.

## 5. Health and monitoring

```bash
curl --noproxy '*' https://community.example.com/healthz
```

Also monitor process restarts/failures, SQLite locks and disk space, file permissions, object capacity, HTTP and JSON-RPC errors, WebSocket count, attachment upload/commit failures, DID resolution/signature failures, refresh/revoke anomalies, and `verify-public` results. Logs must not contain access/refresh tokens, private keys, full message bodies, or sensitive attachment URLs.

## 6. Attachment cleanup

Upload slots expire after about 30 minutes and download tickets after about 15 minutes. A helper cleans expired state, but there is no public cleanup endpoint or background daemon.

Before production adoption, define the cleanup owner and interval, exactly which uncommitted slots/tickets are removed, committed-object retention/deletion, orphan detection, disk alerts, and capacity limits.

## 7. Realtime operations

WebSocket notifications are process-local. Multiple Uvicorn workers do not provide HA; there is no external pub/sub fanout; clients must use `sync.delta` or `sync.thread_after` for durable recovery; and realtime hints are not read watermarks or reliable checkpoints.

Before multi-process or multi-node operation, design a shared event bus, sessions, ordering, backfill, and failure recovery.

## 8. Troubleshooting order

1. `healthz`
2. systemd/process status
3. Nginx routes and TLS
4. `/.well-known/did.json`
5. `anp.get_capabilities`
6. local smoke
7. CLI smoke
8. public verification
9. bidirectional interop with direction, DIDs, target URL, and redacted errors recorded

Do not start by changing sibling AWiki services; this repository must explain its own request path independently.

## 9. Single-node risks

A process failure interrupts realtime and APIs; local-disk failure affects both DB and objects; there is no built-in replica/failover, complete event-log compaction/retention, production offline push, or remote object relay. Every production pilot must explicitly accept these risks in its SLO, backup, and capacity plans.
