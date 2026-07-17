# AWiki Open Server Configuration Reference

[English](configuration.md) | [简体中文](configuration.zh-CN.md)

## 1. Core configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `AWIKI_DATA_DIR` | `.awiki-open-server` | Root for SQLite and object files. |
| `AWIKI_PUBLIC_BASE_URL` | `http://127.0.0.1:8000` | Public base for DID Documents, service endpoints, and object URLs. |
| `AWIKI_DID_DOMAIN` | `localhost` | Domain for local user DIDs and handles. |
| `AWIKI_SERVICE_DID` | `did:wba:<domain>` | Service DID published by `ANPMessageService`. |
| `AWIKI_SERVICE_PRIVATE_KEY_PEM` | unset | Inline Ed25519 PKCS#8 PEM; not recommended in production. |
| `AWIKI_SERVICE_PRIVATE_KEY_PATH` | unset | Service private-key path; preferred in production. |
| `AWIKI_SERVICE_DID_DOCUMENT_JSON` | generated | Optional fixed service DID Document. |

## 2. Routes

| Variable | Default | Purpose |
| --- | --- | --- |
| `AWIKI_IM_RPC_PATH` | `/im/rpc` | Local-client JSON-RPC. |
| `AWIKI_ANP_PUBLIC_RPC_PATH` | `/anp-im/rpc` | Cross-domain public ANP RPC. |
| `AWIKI_WS_PATH` | `/im/ws` | Local WebSocket notifications. |
| `AWIKI_OBJECT_UPLOAD_PATH` | `/objects/upload` | Attachment upload data plane. |
| `AWIKI_OBJECT_DOWNLOAD_PATH` | `/objects` | Attachment download data plane. |

Reverse proxies and clients must follow the actual routes; changing only one side is invalid.

## 3. Attachments

| Variable | Default | Purpose |
| --- | --- | --- |
| `AWIKI_MAX_ATTACHMENT_BYTES` | `10485760` | Maximum attachment size, 10 MiB. |
| `AWIKI_ATTACHMENT_ALLOWED_MIME_TYPES` | Built-in allowlist | Accepted attachment MIME types. |

Defaults include `application/anp-attachment-manifest+json`, `application/json`, `application/octet-stream`, `application/pdf`, `image/gif`, `image/jpeg`, `image/png`, and `text/plain`. Test upload, commit, download, client preview, and scanning policy when changing the allowlist.

## 4. Development and compatibility switches

| Variable | Default | Purpose and risk |
| --- | --- | --- |
| `AWIKI_ALLOW_UNSIGNED_PEER_DEV` | `false` | Allows unsigned public peers for local tests only; forbidden publicly. |
| `AWIKI_DID_RESOLVER_BASE_URLS` | unset | Maps fictional DID domains to loopback during local cross-domain tests. |
| `AWIKI_DID_VERIFY_DEV_CODE` | `666666` | Local DID verification code, not production authentication. |
| `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT` | `false` | Enables legacy phone/email shims; keep disabled publicly. |
| `AWIKI_CONTACT_VERIFICATION_DEV_OTP` | `123456` | Local OTP used only by the compatibility shim. |

Public deployments must not depend on development defaults.

## 5. Groups and operations

| Variable | Default | Purpose |
| --- | --- | --- |
| `AWIKI_GROUP_MAX_MESSAGE_BYTES` | `65536` | Maximum canonical Group message payload size. |
| `AWIKI_GROUP_OUTBOX_MAX_PENDING` | `10000` | Durable Group delivery backpressure threshold. |
| `AWIKI_OPERATIONS_TOKEN` | unset | Inline bearer secret for `/operations/status`; intended only for controlled tests. |
| `AWIKI_OPERATIONS_TOKEN_FILE` | unset | Preferred path to a file containing the independent operations bearer secret. |

`/operations/status` returns `404` when no operations token is configured and `401` for a missing or invalid bearer token. In a public deployment, create a random secret outside the checkout, set mode `0600`, grant the service user read access, and configure only `AWIKI_OPERATIONS_TOKEN_FILE`. Do not reuse an access token, refresh token, service key, or client credential.

## 6. Minimal public deployment

```bash
AWIKI_DATA_DIR=/var/lib/awiki-open-server
AWIKI_PUBLIC_BASE_URL=https://community.example.com
AWIKI_DID_DOMAIN=community.example.com
AWIKI_SERVICE_DID=did:wba:community.example.com
AWIKI_SERVICE_PRIVATE_KEY_PATH=/etc/awiki-open-server/keys/service-ed25519.pem
AWIKI_ALLOW_UNSIGNED_PEER_DEV=false
AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false
AWIKI_MAX_ATTACHMENT_BYTES=10485760
AWIKI_GROUP_MAX_MESSAGE_BYTES=65536
AWIKI_GROUP_OUTBOX_MAX_PENDING=10000
AWIKI_OPERATIONS_TOKEN_FILE=/etc/awiki-open-server/operations.token
```

## 7. Service DID Document

If fixed JSON is absent, the service generates the document from its private key. The public document must match `AWIKI_SERVICE_DID`; use a supported Ed25519 Multikey with correct authentication/assertion authorization and verifiable proof; contain exactly one `ANPMessageService`; and use an endpoint matching the public domain and RPC path. The service must not silently rewrite signed service entries.

## 8. Local user DIDs

Generated shape:

```text
did:wba:<domain>:users:<handle>:e1_default
```

Uploaded local DID Documents must belong to `AWIKI_DID_DOMAIN`, use the current e1 direction, include a proof by default, authorize the proof method through `assertionMethod`, and contain a service entry matching this server.

## 9. Tokens

Access tokens last one hour; refresh tokens last 30 days and rotate on refresh; stale/expired refresh tokens are rejected; and revocation invalidates tokens, DID verification, WebSocket tickets, and profile access. Never put tokens in screenshots, issues, ordinary logs, or client examples.
