# awiki-open-server

[English](README.md) | [简体中文](README.cn.md)

`awiki-open-server` is a self-contained Awiki Community Server MVP. It runs as
one FastAPI process and implements the local identity, messaging, attachment,
site, and ANP interop surfaces needed for Community deployments.

It is not a proxy to `awiki.info`. It does not require `awiki.info`, User
Service, Message Service, or other sibling AWiki services to run.

## What This Server Provides

| Area | Included in this MVP |
| --- | --- |
| Identity | DID registration, public DID documents, profile APIs, local tokens, DID verification compatibility, DID revoke. |
| Messaging | Plaintext direct messages, local inbox/history, sync/read-state, participant-only group messaging. |
| Attachments | Local upload slots, committed object storage, download tickets, protected object download. |
| Site content | Markdown page APIs and public raw Markdown page routes. |
| Compatibility | Local User Service and Message Service compatibility routes used by current clients and the Rust CLI. |
| Interop | Public `/anp-im/rpc` entry for cross-domain ANP direct calls and selected group/attachment methods. |
| Realtime | Single-process WebSocket notifications for local direct and group activity. |

## Current Boundaries

The Community edition intentionally keeps the runtime small. These capabilities
are outside this MVP:

| Not included | Notes |
| --- | --- |
| Group administration | `group.create`, `group.add`, `group.remove`, `group.update_profile`, and `group.update_policy` return `not_supported`. |
| Direct or group E2EE | Messages preserve payload shapes, but this server does not implement end-to-end encryption. |
| Federation infrastructure | No federation peer routes, relay, remote projection, or remote object relay. |
| Production identity providers | No production SMS, email, Aliyun, phone verification, or email verification flow. |
| Hosted platform features | No billing, multi-tenant hosting, hosted runtime orchestration, delegated secret management, or production policy engine. |
| High availability realtime | WebSocket notifications are in-process only; no external pub/sub, offline push, presence, typing indicators, or HA fanout. |
| Sync log repair | No snapshot repair, retention-floor pruning, or event-log compaction beyond the MVP `retention_floor_event_seq = "0"` contract. |

## Quick Start

Use Python 3.10 or newer. If your system `python3` is older, create the
environment with an explicit interpreter such as `python3.11`.

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e '.[dev]'
```

Start the server:

```bash
PYTHONPATH=src \
AWIKI_DATA_DIR=.awiki-open-server \
AWIKI_PUBLIC_BASE_URL=http://127.0.0.1:8765 \
AWIKI_DID_DOMAIN=localhost \
.venv/bin/python -m uvicorn 'awiki_open_server.app.main:create_app' \
  --factory --host 127.0.0.1 --port 8765
```

Check the health endpoint:

```bash
curl --noproxy '*' http://127.0.0.1:8765/healthz
```

Expected response:

```json
{"status":"ok","edition":"community"}
```

`--noproxy '*'` keeps local checks from being routed through a developer
machine's HTTP proxy.

## Dependency Notes

The dependency set pins the ANP Python SDK to `anp==0.8.8`.

`awiki_open_server.protocol.anp_adapter` fails fast if another SDK version is
loaded. In this workspace, local verification can use the sibling SDK checkout
with `PYTHONPATH=../anp/anp:src` when the active environment still has an older
installed `anp` package.

## Security Notes

Do not commit local runtime data or secrets:

- `.awiki-open-server/`
- SQLite databases
- Object files
- `.env`
- Real tokens
- Service private keys

For public deployment, keep `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false`
and do not enable `AWIKI_ALLOW_UNSIGNED_PEER_DEV`. Prefer
`AWIKI_SERVICE_PRIVATE_KEY_PATH` over inline private key environment variables
when deploying with real service keys.

## Identity And Tokens

Local users are constrained to this server's DID domain. Generated user DIDs
use the `did:wba:<domain>:users:<handle>:e1_default` shape, and uploaded local
DID documents must use `did:wba:<AWIKI_DID_DOMAIN>:...` with an `e1_` segment.
Domain mismatches and non-e1/K1-like DIDs fail closed.

Uploaded DID documents require a proof unless
`AWIKI_ALLOW_UNSIGNED_PEER_DEV=true` is explicitly enabled for local
development. Current proof handling validates structure and service binding:
the proof verification method must belong to the DID, and the document must
contain exactly one `ANPMessageService` whose endpoint and service DID match
this server. The Community MVP does not yet perform cryptographic
DataIntegrity/JCS proof verification for uploaded user DID documents.

Registration returns an access token and refresh token. Access tokens expire in
1 hour; refresh tokens expire in 30 days and rotate on refresh. Stale or
expired refresh tokens are rejected. Legacy rows created before refresh-token
storage may use the old access token only when `refresh_token` is still null.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `AWIKI_DATA_DIR` | `.awiki-open-server` | SQLite database and object files. |
| `AWIKI_PUBLIC_BASE_URL` | `http://127.0.0.1:8000` | Public base used in DID docs and object URLs. |
| `AWIKI_DID_DOMAIN` | `localhost` | Default DID and handle domain. |
| `AWIKI_SERVICE_DID` | `did:wba:<domain>` | Service DID advertised in `ANPMessageService`. |
| `AWIKI_SERVICE_PRIVATE_KEY_PEM` | unset | Ed25519 PKCS#8 PEM used to sign service-to-service HTTP requests. Use `\n` escapes when passing through env files. |
| `AWIKI_SERVICE_PRIVATE_KEY_PATH` | unset | File path for the same Ed25519 private key. Prefer this for local deployment. |
| `AWIKI_SERVICE_DID_DOCUMENT_JSON` | generated | Optional fixed service DID document. If omitted, the server generates one from the service private key. |
| `AWIKI_IM_RPC_PATH` | `/im/rpc` | Local client JSON-RPC path. |
| `AWIKI_ANP_PUBLIC_RPC_PATH` | `/anp-im/rpc` | Public ANP RPC path. |
| `AWIKI_WS_PATH` | `/im/ws` | Local WebSocket notification path. |
| `AWIKI_OBJECT_UPLOAD_PATH` | `/objects/upload` | Local object upload path prefix. |
| `AWIKI_OBJECT_DOWNLOAD_PATH` | `/objects` | Local object download path prefix. |
| `AWIKI_MAX_ATTACHMENT_BYTES` | `10485760` | Maximum accepted attachment object size, in bytes. |
| `AWIKI_ATTACHMENT_ALLOWED_MIME_TYPES` | `application/anp-attachment-manifest+json,application/json,application/octet-stream,application/pdf,image/gif,image/jpeg,image/png,text/plain` | Comma-separated attachment MIME allowlist. |
| `AWIKI_ALLOW_UNSIGNED_PEER_DEV` | `false` | Allows unsigned `/anp-im/rpc direct.send` only for local development tests. Do not enable for real interop. |
| `AWIKI_DID_RESOLVER_BASE_URLS` | unset | Optional development resolver map such as `source.test=http://127.0.0.1:9001,target.test=http://127.0.0.1:9002` or a JSON object. Leave unset in normal public deployment. |
| `AWIKI_DID_VERIFY_DEV_CODE` | `666666` | Local `/did-verify/rpc login` dev code. Falls back to `DEV_BYPASS_CODE` if set. |
| `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT` | `false` | Enables legacy local phone/email verification shims for old client tests. Keep disabled for the MVP and public deployment. |
| `AWIKI_CONTACT_VERIFICATION_DEV_OTP` | `123456` | Local compatibility OTP used only when contact verification compatibility is explicitly enabled. |

## Public Deployment And Interop

For real cross-domain direct interop, configure a stable service DID and private
key:

```bash
AWIKI_PUBLIC_BASE_URL=https://rwiki.cn
AWIKI_DID_DOMAIN=rwiki.cn
AWIKI_SERVICE_DID=did:wba:rwiki.cn
AWIKI_SERVICE_PRIVATE_KEY_PATH=/secure/path/rwiki-service-ed25519.pem
AWIKI_ALLOW_UNSIGNED_PEER_DEV=false
AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false
AWIKI_MAX_ATTACHMENT_BYTES=10485760
AWIKI_ATTACHMENT_ALLOWED_MIME_TYPES=application/anp-attachment-manifest+json,application/json,application/octet-stream,application/pdf,image/gif,image/jpeg,image/png,text/plain
```

Deployment requirements:

- `https://rwiki.cn/.well-known/did.json` must be served by this process.
- The DID document must contain the matching `verificationMethod`,
  `authentication`, proof, and exactly one public `ANPMessageService`.
- Outbound remote direct requests require the client or CLI ANP envelope with
  `auth.origin_proof`.
- The server forwards `auth.origin_proof` unchanged and signs the HTTP hop with
  `AWIKI_SERVICE_DID`.
- `rwiki.cn` must proxy to this process, not to `awiki.info`, `user-service`, or
  `message-service`.

Example deployment templates are in `deploy/`. They show how to run Uvicorn on
localhost and publish `https://rwiki.cn` through nginx.

## Test And Smoke Checks

Run the full test suite:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests -q
```

Focused test areas:

| Area | Files |
| --- | --- |
| ANP SDK and signatures | `tests/test_protocol_anp_sdk.py` |
| Route and path configuration | `tests/test_route_config.py` |
| User Service compatibility | `tests/test_user_service_compat.py`, `tests/test_identity_documents.py`, `tests/test_contact_auth_compat.py`, `tests/test_profile_compat.py`, `tests/test_agent_compat.py`, `tests/test_site_relationships.py` |
| Messaging surface | `tests/test_messaging_surface.py`, `tests/test_direct_messages.py`, `tests/test_group_participant.py`, `tests/test_attachments.py`, `tests/test_sync_read_state.py` |
| Public deployment gate | `tests/test_rwiki_cn_system.py`, skipped unless `AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1` |

Smoke commands:

| Check | Command | What it verifies |
| --- | --- | --- |
| In-process ASGI smoke | `PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-cli-asgi` | Core local flows without starting Uvicorn. |
| Local HTTP smoke | `PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-local --base-url http://127.0.0.1:8765 --did-domain localhost` | A running local server over HTTP. |
| Local cross-domain smoke | `PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-cross-domain-local --clean` | Two local servers, DID discovery, client origin proof, service HTTP Signature, signed `/anp-im/rpc direct.send`, and bidirectional inbox delivery. |
| Public deployment verification | `PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py verify-public --base-url https://rwiki.cn --did-domain rwiki.cn` | Confirms the public domain is serving this repository. |
| Guarded public system tests | `AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 PYTHONPATH=src .venv/bin/python -m pytest tests/test_rwiki_cn_system.py -q` | Public service DID document, capabilities, disabled contact verification, DID registration, inbox/history, and open group boundary on `https://rwiki.cn`. |

Notes:

- `smoke-cross-domain-local` starts two independent Uvicorn processes with
  separate SQLite stores, service DIDs, and Ed25519 service keys.
- It uses `AWIKI_DID_RESOLVER_BASE_URLS` only to map test DID domains to
  loopback ports.
- It is a local protocol gate, not a replacement for the public `rwiki.cn` to
  `awiki.info` interoperability gate.
- `verify-public` must pass before using `rwiki.cn` for real `awiki.info`
  interoperability tests.
- A 404 for `/.well-known/did.json`, `/healthz`, or `/anp-im/rpc` means the
  public domain is not routed to this server yet.

## Rust CLI Compatibility

The existing Rust CLI can connect to this server. Use an isolated
`awiki-cli-rs2` worktree and temporary CLI workspace so validation does not
write into a developer's active CLI checkout.

Build the CLI:

```bash
CARGO_TARGET_DIR=/tmp/awiki-cli-rs2-open-server-target \
  cargo build -p awiki-cli --bin awiki-cli --locked
```

Register a local test identity:

```bash
AWIKI_CLI_WORKSPACE_HOME_DIR=/tmp/awiki-cli-open-server-workspace \
  /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli \
  id register --handle cli-alice --phone 13800138000 --otp 123456
```

The current Rust CLI still requires either `--phone` or `--email` for
`id register`. In this MVP, those arguments only preserve the existing CLI
command shape. The server-side `did-auth.register` path does not send SMS, send
email, call Aliyun, or persist phone/email verification state.

Run the repeatable local Rust CLI gate:

```bash
PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-rust-cli-local \
  --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli \
  --data-root /tmp/awiki-open-server-rust-cli-local --clean
```

This verifies:

- DID registration through the local DID registration path.
- Direct send, inbox, and history.
- Group join, send, and messages.
- People `follow`, `status`, `following`, and `followers`.
- Site root and page commands.

This is a local User Service / Message Service compatibility gate. It does not
replace the public `rwiki.cn` to `awiki.info` interoperability gate.

## Compatibility Model

| Compatibility area | Behavior |
| --- | --- |
| Rust CLI routes | `/user-service/did-auth/rpc`, `/user-service/did/profile/rpc`, and `/user-service/handle/rpc` are implemented locally and do not forward to an external User Service. |
| Agent routes | `/user-service/agent-registration/rpc`, `/user-service/message-agent/rpc`, and `/user-service/agent-inventory/rpc` cover daemon status, controller scope, sender checks, invocation authorization, archive, and local policy fields. |
| Agent limitations | Agent compatibility covers local one-time registration tokens, message-agent binding state, and daemon compatibility only. It does not implement hosted runtime orchestration, delegated secret management, or a production policy engine. |
| Contact verification | `/auth/sms`, `/auth/sms-codes`, `/auth/email-send`, `/auth/email-status`, and phone-bind routes return `contact_verification_not_enabled` by default. |
| Contact verification shims | Set `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=true` only for local compatibility tests. Even then, the routes remain in-process dev shims and never call SMS, email, Aliyun, `awiki.info`, User Service, or Message Service. |
| Token and WebSocket verification | Compatibility helpers return `X-User-Id` and `X-DID` headers for nginx `auth_request` integrations. |
| DID verification | `/did-verify/rpc` and `/user-service/did-verify/rpc` expose `send_code`, `login`, and `refresh`. `send_code` does not call an external message service. `login` accepts `AWIKI_DID_VERIFY_DEV_CODE`, default `666666`, or `DEV_BYPASS_CODE` if set. |
| DID verification scope | DID verification uses local Community tokens already stored for registered DIDs. It does not enable phone or email verification. |
| DID revoke | `revoke` marks the local user and DID document inactive. The same token or DID can no longer pass token verification, DID verify login/refresh, WebSocket ticket verification, `get_me`, or `update_document`. |
| Revoke data retention | Profile and historical message data remain stored, but the active DID document route returns 404. |
| Unsupported DID auth methods | `replace_did` and `recover_handle` remain unsupported in the Community server. |
| Older profile clients | `/me`, `/me/rpc`, `/profiles/{user_id}`, `/user-service/profiles/{user_id}`, `/users/{user_id}/profile`, and `/users/rpc` map `user_id` to the local DID and do not call an external User Service. |

## Remote awiki.info Diagnostics

Remote capability diagnostics can call the online `awiki.info` service, but
`awiki.info` is a remote peer for interoperability testing, not this server's
backend.

```bash
PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-awiki-info \
  --base-url https://awiki.info \
  --did-domain rwiki.cn
```

To send a direct test message, also provide:

- `--token`
- `--sender-did`
- `--recipient-did`
- `--origin-proof-json`

Request shape expectations:

| Check | Shape |
| --- | --- |
| Remote capability | ANP JSON-RPC `params.meta/body` |
| Remote direct message | ANP JSON-RPC `params.meta/auth/body` |

A `missing params.meta` response means the request shape is wrong and is not a
passing remote check.

For real interoperability validation:

1. Run this server on its own reachable base URL.
2. Configure a service private key.
3. Configure the Rust CLI for that URL.
4. Use an existing or test user on `awiki.info` as the remote side.

A valid test proves both directions:

| Direction | Expected behavior |
| --- | --- |
| Local open-server user to `awiki.info` user | This server resolves the remote DID document, preserves CLI `auth.origin_proof`, signs the HTTP hop as `AWIKI_SERVICE_DID`, and POSTs `direct.send` to the remote `ANPMessageService.serviceEndpoint`. |
| `awiki.info` user to local open-server user | `awiki.info` resolves this server's DID document and POSTs signed `direct.send` to this server's `/anp-im/rpc`. |

Do not treat two CLI workspaces that both point at `https://awiki.info` as
validation for this repository. That only verifies the online service itself.

## API Reference

Core and compatibility routes are mounted together. Contact-verification
compatibility routes are present for old clients, but they return
`contact_verification_not_enabled` unless
`AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=true` is explicitly set for local
testing.

| Route | Purpose | Notes |
| --- | --- | --- |
| `GET /healthz`<br>`GET /health`<br>`GET /user-service/health`<br>`GET /im/healthz` | Health checks. | `/healthz` returns the server status and edition. |
| `POST /did-auth/rpc`<br>`POST /user-service/did-auth/rpc` | DID auth and registration compatibility. | Local implementation. Supports local revoke. Does not send SMS/email or call Aliyun. |
| `POST /did-verify/rpc`<br>`POST /user-service/did-verify/rpc` | DID verification compatibility. | Exposes `send_code`, `login`, and `refresh` with a local dev code. |
| `POST /did/profile/rpc`<br>`POST /user-service/did/profile/rpc` | DID profile RPC compatibility. | Maps profile fields to local DID profile records. |
| `GET /me`<br>`PATCH /me`<br>`POST /me/rpc`<br>`GET /user-service/me`<br>`PATCH /user-service/me`<br>`POST /user-service/me/rpc` | Current-user profile compatibility. | Uses local Community tokens and local DID identity. |
| `GET /profiles/{user_id}`<br>`GET /user-service/profiles/{user_id}`<br>`GET /users/{user_id}/profile`<br>`GET /user-service/users/{user_id}/profile` | Profile lookup compatibility. | In this server, `user_id` is the local DID. |
| `POST /users/rpc`<br>`POST /user-service/users/rpc` | Older user lookup RPC compatibility. | Local only. Does not call an external User Service. |
| `POST /handle/rpc`<br>`POST /user-service/handle/rpc` | Handle compatibility RPC. | Uses this server's configured DID domain. |
| `POST /did/relationships/rpc`<br>`POST /user-service/did/relationships/rpc` | Local DID relationships. | Supports `follow`, `unfollow`, `get_following`, `get_followers`, and `get_status` for users registered in the configured DID domain. |
| `POST /user-service/agent-registration/rpc` | Agent registration compatibility. | Local one-time agent registration token support. |
| `POST /user-service/agent-inventory/rpc` | Agent inventory compatibility. | Covers local daemon and inventory fields used by current clients. |
| `POST /user-service/message-agent/rpc` | Message-agent compatibility. | Covers binding state, sender checks, controller scope, invocation authorization, archive, and local policy fields. |
| `POST /auth/sms-codes`<br>`POST /user-service/auth/sms-codes`<br>`POST /auth/sms`<br>`POST /user-service/auth/sms` | Legacy SMS verification compatibility. | Disabled by default. Dev shim only when contact verification compatibility is enabled. |
| `POST /auth/email-send`<br>`POST /user-service/auth/email-send`<br>`GET /auth/email-status`<br>`GET /user-service/auth/email-status` | Legacy email verification compatibility. | Disabled by default. Dev shim only; never sends real email. |
| `POST /auth/phone-bind-send`<br>`POST /user-service/auth/phone-bind-send`<br>`POST /auth/phone-bind-verify`<br>`POST /user-service/auth/phone-bind-verify` | Legacy phone-bind compatibility. | Disabled by default. Dev shim only; never calls SMS or Aliyun. |
| `POST /auth/token-refresh`<br>`POST /user-service/auth/token-refresh` | Token refresh compatibility. | Local Community token flow with refresh-token rotation. |
| `GET /auth/token-verify`<br>`GET /user-service/auth/token-verify`<br>`GET /auth/verify`<br>`GET /user-service/auth/verify`<br>`GET /sessions/verify`<br>`GET /user-service/sessions/verify` | Token and session verification compatibility. | Returns local verification headers for nginx `auth_request` integrations. |
| `POST /ws/tickets`<br>`POST /user-service/ws/tickets` | Local WebSocket ticket creation. | Tickets can be used with `/im/ws`. |
| `GET /ws/tickets/verify`<br>`GET /user-service/ws/tickets/verify`<br>`GET /auth/ws-ticket/verify`<br>`GET /user-service/auth/ws-ticket/verify` | WebSocket ticket verification. | Local compatibility helper for proxies and older clients. |
| `POST /content/rpc`<br>`POST /user-service/content/rpc` | Markdown content compatibility RPC. | Local content APIs. |
| `GET /content/{slug}.md` | Raw Markdown content route. | Returns Markdown for the configured local domain. |
| `POST /site/rpc` | Markdown site RPC. | Supports root and page management methods listed below. |
| `GET /`<br>`GET /pages/{slug}.md` | Public Markdown site routes. | Return raw Markdown. Not production tenant hosting. |
| `POST /im/rpc` or `AWIKI_IM_RPC_PATH` | Local client JSON-RPC entry. | Inbox, history, sync, read-state, group participant, and attachment control methods. |
| `POST /anp-im/rpc` or `AWIKI_ANP_PUBLIC_RPC_PATH` | Public ANP JSON-RPC entry. | Cross-domain entry with limited public methods. Requires origin proof and service HTTP Signature for public `direct.send` and `group.join`, unless unsigned peer dev mode is enabled. |
| `PUT /objects/upload/{slot_id}` or `AWIKI_OBJECT_UPLOAD_PATH/{slot_id}` | Attachment upload data plane. | Accepts `?token=...` or returned `X-ANP-Upload-Token`. |
| `GET /objects/{object_id}` or `AWIKI_OBJECT_DOWNLOAD_PATH/{object_id}` | Attachment download data plane. | Accepts `?ticket=...` and `Authorization: Bearer <download_ticket>`. |
| `GET /.well-known/did.json` | Public service DID document. | Must be served by this process for real public interop. |
| `GET /dids/resolve/{sub_path}/did.json`<br>`GET /{sub_path}/did.json` | Public DID document resolution. | Publishes local DID documents for the configured domain. |

## JSON-RPC Surfaces

| Surface | Methods | Behavior |
| --- | --- | --- |
| Local `/im/rpc` | Inbox, history, sync, read-state, group participant, and attachment control methods. | Local client entry for authenticated Community users. Accepts Message Service `params.meta/body` shape and older flat params where documented. |
| Public `/anp-im/rpc` | `anp.get_capabilities`, `direct.send`, `group.get_info`, `group.join`, `attachment.get_download_ticket`. | Cross-domain entry. Public `direct.send` and `group.join` require business `auth.origin_proof` plus service-to-service HTTP Signature unless unsigned peer dev mode is enabled. |
| DID relationships | `follow`, `unfollow`, `get_following`, `get_followers`, `get_status`. | Only operates on users registered in this server's configured DID domain. |
| Site RPC | `get_root`, `set_root`, `list_pages`, `get_page`, `create_page`, `update_page`, `rename_page`, `delete_page`. | Small Markdown site compatibility surface for the configured local domain. |

## Messaging Semantics

| Topic | Behavior |
| --- | --- |
| Payload storage | Direct and group messages preserve Message Service payload shapes. |
| Text payloads | `text/plain` uses `body.text`. |
| JSON payloads | `application/json` and `application/anp-attachment-manifest+json` use `body.payload` as a JSON object. |
| Other payloads | Other non-text content types use `body.payload_b64u`. |
| Validation | ANP-envelope messages are rejected when body fields do not match `meta.content_type`. Older flat text CLI calls remain compatible. |
| Local projections | `inbox.get`, `direct.get_history`, `group.list_messages`, and `sync.thread_after` return Message Service-style projections: `type=text`, `type=json`, `type=attachment_manifest`, or `type=binary`. |
| Raw data | The original `body` and `content_type` remain included for clients that need the raw ANP shape. |
| Local owner validation | When present, `meta.sender_did` and `body.user_did` must match the authenticated local DID. |
| Pagination | `inbox.get` supports `skip` and `limit`. `direct.get_history` supports `peer_did`, `since_seq` or `since`, `skip`, and `limit`. |
| Deprecated group history path | The direct-history `group_did` path is rejected. Use `group.list_messages` for group history. |

## Read State And Sync

| Method | Behavior |
| --- | --- |
| `inbox.mark_read` | Marks the current user's visible direct message IDs in `direct_message_views.read_at`. |
| `inbox.get` | Returns unread messages by default. Use `{"include_read": true}` to include read messages. |
| `direct.get_history` | Can show read messages with `is_read` and `read_at`. |
| `sync.delta` | Returns account-level metadata events. `direct.message.created` and `group.message.created` payloads identify the thread and message but do not include `body`, `content`, or message text. Pagination uses an extra-row check for stable `has_more`; `retention_floor_event_seq` remains `"0"`. |
| `sync.thread_after` | Returns durable thread content after `after_server_seq` and uses the same membership checks as group reads. It cannot be used to read a group after leaving it. Pagination also uses an extra-row check for stable `has_more`. |
| `read_state.mark_read` | Thread watermark API only. Direct threads update unread message views up to `read_up_to_server_seq`; group threads compute by thread-local `server_seq` watermark. The result includes actual `updated_count` and remaining `unread_count`. |
| Unsupported read-state checkpoints | `event_seq`, `since_event_seq`, `next_event_seq`, `checkpoint`, and `read_up_to_group_event_seq` are rejected. The MVP does not emit `message.read_state_updated` sync events. |

## Heartbeat Messages

Only the documented daemon liveness heartbeat is treated as no-store:

| Required field | Value |
| --- | --- |
| Content type | `application/json` |
| `body.payload.schema` | `awiki.agent.status.v1` |
| `status_scope` | `daemon` |
| `message` | `daemon heartbeat` |

For that heartbeat, the server returns `delivery_state = ephemeral` and may
notify an online recipient. It does not write the heartbeat to inbox, history,
sync events, or sender-side history.

Other daemon/App status payloads, including run and snapshot statuses, remain
durable messages.

## Group Participation

| Supported participant method | Notes |
| --- | --- |
| `group.get_info` | Exposes minimal existing-group information for discovery and open join. |
| `group.join` | Allows joining the seeded open group. Public use requires origin proof and service signature. |
| `group.leave` | Requires current membership. |
| `group.send` | Requires current membership. |
| `group.get` | Requires current membership. |
| `group.list` | Lists local group participation. |
| `group.list_members` | Requires current membership. |
| `group.list_messages` | Requires current membership. Supports `limit`, `skip`, and `since_seq`. |

Unsupported management methods return `not_supported`:

- `group.create`
- `group.add`
- `group.remove`
- `group.update_profile`
- `group.update_policy`

The seeded open-join group DID follows `AWIKI_DID_DOMAIN`, for example:

- Local: `did:wba:localhost:groups:open`
- Public deployment: `did:wba:rwiki.cn:groups:open`

## Realtime

`/im/ws` accepts a local ticket from `/ws/tickets` or
`/user-service/ws/tickets`.

The connection:

- Stays open.
- Sends an initial sync hint without a checkpoint or `event_seq`.
- Publishes in-process notifications for local direct and group participant
  activity.

Notification types:

- `direct.incoming`
- `group.incoming`
- `group.state_changed`

Clients should still use `sync.delta` and `sync.thread_after` as the durable
recovery path. The `sync` object attached to direct and group notifications is
a scheduling/gap hint only; it is not a read watermark, checkpoint, or thread
`server_seq`.

## Attachments

| Step | Behavior |
| --- | --- |
| Create upload slot | Returns both legacy `upload_token` and `upload_headers`. |
| Upload object | `PUT /objects/upload/{slot_id}?token=...` or send the returned `X-ANP-Upload-Token` header. |
| Request download ticket | `attachment.get_download_ticket` accepts the local `object_id` owner flow and the Message Service ANP body shape. |
| Download object | `GET /objects/{object_id}` accepts `?ticket=...` and `Authorization: Bearer <download_ticket>`. |

Upload slots expire after 30 minutes. Download tickets expire after 15 minutes.
`attachment.create_slot` accepts expected metadata such as `expected_size`,
`expected_digest`/`expected_sha256`, and `content_type`/`expected_content_type`.
Upload and commit validate the token, slot state, expiry, maximum size, SHA-256
digest, and MIME allowlist before an object becomes committed. The helper
`cleanup_expired_attachments` can remove expired uncommitted slots and expired
tickets, but there is no public cleanup endpoint or background daemon in the
MVP.

`attachment.get_download_ticket` accepts:

- `object_uri`
- `attachment_id`
- `requester_did`
- `sender_did`
- `message_id`
- `message_security_profile`
- either `message_target_did` or `group_did`

Responses include both legacy `ticket/download_uri` fields and
`download_ticket_b64u/ticket_binding`.

This Community server only issues tickets for locally committed objects and
local direct/group message context. It does not implement cross-domain
attachment upload delegation, full `attachment_access_grants`, object E2EE
authorization, or remote object relay.

## Code Structure

| Path | Responsibility |
| --- | --- |
| `src/awiki_open_server/protocol/anp_adapter.py` | The only ANP Python SDK adapter. Requires `anp==0.8.8`. |
| `src/awiki_open_server/service_identity.py` | HTTP Signatures, Content-Digest, service DID, and origin proof checks. |
| `src/awiki_open_server/app/` | FastAPI settings, route mounting, and realtime wiring. |
| `src/awiki_open_server/messaging/` | Direct messaging, group participant methods, local sync, and read-state handlers. |
| `src/awiki_open_server/attachments/` | Local upload slots, committed objects, and download tickets. |
| `src/awiki_open_server/user_compat/` | Local User Service compatibility surface. |
| `src/awiki_open_server/shared/runtime.py` | DID discovery, HTTP JSON, signature, object URL, and realtime helpers. |
| `src/awiki_open_server/services.py` | Compatibility facade plus remaining content, site, and DID relationship handlers. New domain logic should go into a domain package rather than back into `services.py`. |
