# AWiki Open Server Public Deployment

[English](deployment.md) | [简体中文](deployment.zh-CN.md)

This is the current recommended single-node Uvicorn, systemd, and Nginx path. Examples under `deploy/` use `rwiki.cn`; replace it with your own domain.

## 1. Deployment boundary

The public domain must point directly to this repository's process. Business routes must not proxy to `awiki.info`, external User Service, or external Message Service. `awiki.info` may only be a remote interoperability peer or diagnostic target.

## 2. Suggested directories

```text
/opt/awiki-open-server/        release checkout
/etc/awiki-open-server/        private env/config
/var/lib/awiki-open-server/    SQLite and objects
/var/log/awiki-open-server/    service logs if not using journal only
/etc/awiki-open-server/keys/   service private key
/etc/awiki-open-server/operations.token  independent operations bearer secret
```

Adapt paths to the environment while keeping private keys/data separate from the Git checkout.

## 3. Install

```bash
cd /opt/awiki-open-server
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e .
```

Production does not need `.[dev]` unless the server also runs tests.

## 4. Service DID and private key

```bash
AWIKI_PUBLIC_BASE_URL=https://community.example.com
AWIKI_DID_DOMAIN=community.example.com
AWIKI_SERVICE_DID=did:wba:community.example.com
AWIKI_SERVICE_PRIVATE_KEY_PATH=/etc/awiki-open-server/keys/service-ed25519.pem
AWIKI_ALLOW_UNSIGNED_PEER_DEV=false
AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false
AWIKI_GROUP_MAX_MESSAGE_BYTES=65536
AWIKI_GROUP_OUTBOX_MAX_PENDING=10000
AWIKI_OPERATIONS_TOKEN_FILE=/etc/awiki-open-server/operations.token
```

Use an Ed25519 PKCS#8 PEM with minimal file permissions. Create a separate random operations token file outside the checkout with mode `0600`; do not reuse or inline the service key or a user token. Never put secrets in Git, ordinary environment dumps, logs, or issues. The service DID, `/.well-known/did.json`, endpoint, and domain must agree.

## 5. Uvicorn and systemd

Use `deploy/awiki-open-server.service.example`. Bind Uvicorn to loopback, let systemd own restart/environment/permissions, grant the service user only required data/key access, do not run the app as root, and use journald or controlled logs without tokens or payloads.

## 6. Nginx

`deploy/nginx-rwiki.cn.conf.example` demonstrates the reverse proxy. Expose `/.well-known/did.json`, DID resolution, `/healthz` as policy permits, `/anp-im/rpc`, required local compatibility routes, WebSocket upgrades, and attachment upload/download. Every `proxy_pass` must target the local Open Server process, never AWiki hosted services.

```bash
nginx -t
systemctl reload nginx
```

## 7. TLS and public base

Use a stable HTTPS certificate. `AWIKI_PUBLIC_BASE_URL` must equal the external origin, and the DID Document endpoint should be:

```text
https://community.example.com/anp-im/rpc
```

Keep reverse-proxy paths, Host, WebSocket, and object URLs consistent.

## 8. Verify deployment

```bash
PYTHONPATH=src \
.venv/bin/python scripts/awiki_open_cli.py verify-public \
  --base-url https://community.example.com \
  --did-domain community.example.com
```

This checks `/.well-known/did.json`, the service DID, exactly one `ANPMessageService`, its endpoint, health, `anp.get_capabilities`, Community cross-domain modes, disabled relay/E2EE boundaries, and disabled contact-verification compatibility. Also verify `/operations/status` is unauthorized without its bearer token, succeeds with it, and does not expand `/healthz`. Then run real bidirectional interoperability.

## 9. Bidirectional interoperability

Verify Direct in both directions and Group interoperability in both host directions: an Open Server-hosted Group with remote add/join members, and a remote-hosted Group with Open Server add/join members. Cover create/get/list/members, profile/policy update, bidirectional send/read, projection/sync/realtime, Group Receipt validation, leave/remove, and outbox retry/restart recovery. Capability discovery alone proves none of these. Record DIDs, operation/message IDs, event/state versions, receipt/delivery results, target URL, redacted error body, and redacted service logs.

## 10. Disable development switches

Public deployments must keep both switches false and must not use the development OTP as production authentication:

```text
AWIKI_ALLOW_UNSIGNED_PEER_DEV=false
AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false
```

## 11. Container status

The public baseline is venv/systemd/Nginx. Do not publish Docker/Compose commands that do not exist or lack continuous verification. A future container path must provide a pinned base image, non-root user, persistent DB/object volume, healthcheck, service-key secret mount, migration/upgrade policy, Compose smoke, and the same secure defaults.
