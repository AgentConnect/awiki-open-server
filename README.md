# awiki-open-server

[English](README.md) | [简体中文](README.cn.md)

Single-process Awiki Community Server MVP. It provides DID registration, public DID documents, profile APIs, Markdown Pages, plaintext direct messaging, group participant APIs, local attachment storage, sync/read-state, and a public `/anp-im/rpc` entry for cross-domain direct calls.

This server implements those capabilities itself. It is not a proxy to `awiki.info`, and it does not require `awiki.info` or sibling AWiki services to run.

The Community edition deliberately does not implement group creation or management, Direct/Group E2EE, federation peer routes, relay, remote projection, billing, production identity providers, email or phone verification flows, Aliyun integrations, or multi-tenant hosting.

## Code Structure

Application code lives under `src/awiki_open_server/`. `protocol/anp_adapter.py`
is the only ANP Python SDK adapter and requires `anp==0.8.8` at runtime;
`service_identity.py` uses it for HTTP Signatures, Content-Digest, and origin
proof checks. `app/` owns FastAPI settings, route mounting, and realtime wiring.
`messaging/` owns direct messaging, group participant methods, local sync, and
read-state handlers. `attachments/` owns local upload slots, committed objects,
and download tickets. `user_compat/` implements the local User Service
compatibility surface. `shared/runtime.py` contains cross-cutting DID discovery,
HTTP JSON, signature, object URL, and realtime helpers. `services.py` is now a
compatibility facade plus the remaining content/site/DID relationship handlers;
new domain logic should go into the domain package rather than back into
`services.py`.

## Run Locally

Use Python 3.10 or newer. If your system `python3` is older, create the
environment with an explicit interpreter such as `python3.11`:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e '.[dev]'
```

The dependency set pins ANP Python SDK `anp==0.8.8`; importing
`awiki_open_server.protocol.anp_adapter` fails fast if another SDK version is
loaded. In this workspace, local verification can use the sibling SDK checkout
with `PYTHONPATH=../anp/anp:src` when the active environment still has an older
installed `anp` package.

Start the server:

```bash
PYTHONPATH=src \
AWIKI_DATA_DIR=.awiki-open-server \
AWIKI_PUBLIC_BASE_URL=http://127.0.0.1:8765 \
AWIKI_DID_DOMAIN=localhost \
.venv/bin/python -m uvicorn 'awiki_open_server.app.main:create_app' \
  --factory --host 127.0.0.1 --port 8765
```

Verify the running server:

```bash
curl --noproxy '*' http://127.0.0.1:8765/healthz
```

The expected response is `{"status":"ok","edition":"community"}`. The
`--noproxy '*'` flag keeps local checks from being routed through a developer
machine's HTTP proxy.

Useful configuration:

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
| `AWIKI_ALLOW_UNSIGNED_PEER_DEV` | `false` | Allows unsigned `/anp-im/rpc direct.send` only for local development tests. Do not enable for real interop. |
| `AWIKI_DID_RESOLVER_BASE_URLS` | unset | Optional development resolver map such as `source.test=http://127.0.0.1:9001,target.test=http://127.0.0.1:9002` or a JSON object. Leave unset in normal public deployment. |
| `AWIKI_DID_VERIFY_DEV_CODE` | `666666` | Local `/did-verify/rpc login` dev code. Falls back to `DEV_BYPASS_CODE` if set. |
| `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT` | `false` | Enables legacy local phone/email verification shims for old client tests. Keep disabled for the MVP and public deployment. |
| `AWIKI_CONTACT_VERIFICATION_DEV_OTP` | `123456` | Local compatibility OTP used only when contact verification compatibility is explicitly enabled. |

Do not commit `.awiki-open-server/`, SQLite databases, object files, `.env`, or real tokens.

For real cross-domain direct interop, configure a stable service DID and private key:

```bash
AWIKI_PUBLIC_BASE_URL=https://rwiki.cn
AWIKI_DID_DOMAIN=rwiki.cn
AWIKI_SERVICE_DID=did:wba:rwiki.cn
AWIKI_SERVICE_PRIVATE_KEY_PATH=/secure/path/rwiki-service-ed25519.pem
AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false
```

The published `https://rwiki.cn/.well-known/did.json` must be served by this process and contain the matching `verificationMethod`, `authentication`, proof, and exactly one public `ANPMessageService`. Outbound remote direct requests require the client/CLI ANP envelope with `auth.origin_proof`; the server forwards that proof unchanged and signs the HTTP hop with `AWIKI_SERVICE_DID`.

Example deployment templates are in `deploy/`. They show how to run Uvicorn on
localhost and publish `https://rwiki.cn` through nginx. The important boundary
is that `rwiki.cn` must proxy to this process, not to `awiki.info`,
`user-service`, or `message-service`.

## Test And Smoke

Run the test suite:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests -q
```

Focused suites:

- ANP SDK/signature adapter: `tests/test_protocol_anp_sdk.py`
- Route and env path config: `tests/test_route_config.py`
- User Service compatibility: `tests/test_user_service_compat.py`, `tests/test_identity_documents.py`, `tests/test_contact_auth_compat.py`, `tests/test_profile_compat.py`, `tests/test_agent_compat.py`, `tests/test_site_relationships.py`
- Messaging surface: `tests/test_messaging_surface.py`, `tests/test_direct_messages.py`, `tests/test_group_participant.py`, `tests/test_attachments.py`, `tests/test_sync_read_state.py`
- Public deployment gate: `tests/test_rwiki_cn_system.py`, skipped unless `AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1`

Run an in-process CLI smoke without starting Uvicorn:

```bash
PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-asgi \
  --data-dir /tmp/awiki-open-server-cli-asgi
```

Run a local HTTP smoke against a running server:

```bash
PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-local \
  --base-url http://127.0.0.1:8765 \
  --did-domain localhost
```

Run a local two-server cross-domain smoke:

```bash
PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-cross-domain-local \
  --data-root /tmp/awiki-open-server-cross-domain-local --clean
```

This starts two independent Uvicorn processes with separate SQLite stores,
service DIDs, and Ed25519 service keys. It uses `AWIKI_DID_RESOLVER_BASE_URLS`
only to map test DID domains to loopback ports, then verifies DID discovery,
client `auth.origin_proof`, service-to-service HTTP Signature, signed
`/anp-im/rpc direct.send`, and bidirectional inbox delivery. This is a local
protocol gate; it does not replace the public `rwiki.cn` to `awiki.info`
interoperability gate.

Check that a public deployment is really serving this repository:

```bash
PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py verify-public \
  --base-url https://rwiki.cn \
  --did-domain rwiki.cn
```

`verify-public` must pass before using `rwiki.cn` for real `awiki.info`
interoperability tests. A 404 for `/.well-known/did.json`, `/healthz`, or
`/anp-im/rpc` means the public domain is not yet routed to this server.

Run the guarded public system tests against `rwiki.cn`:

```bash
AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 \
PYTHONPATH=src .venv/bin/python -m pytest tests/test_rwiki_cn_system.py -q
```

These tests are skipped by default in local and CI runs. When enabled, they
verify the public service DID document, capabilities, disabled contact
verification, DID registration, direct inbox/history, and the open group
participant boundary on `https://rwiki.cn`.

The existing Rust CLI can also connect to this server. Use an isolated `awiki-cli-rs2` worktree and temporary CLI workspace so validation does not write into a developer's active CLI checkout:

```bash
CARGO_TARGET_DIR=/tmp/awiki-cli-rs2-open-server-target \
  cargo build -p awiki-cli --bin awiki-cli --locked

AWIKI_CLI_WORKSPACE_HOME_DIR=/tmp/awiki-cli-open-server-workspace \
  /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli \
  id register --handle cli-alice --phone 13800138000 --otp 123456
```

The current Rust CLI still requires either `--phone` or `--email` on
`id register`. In this MVP those CLI arguments are placeholders for the
existing CLI command shape: the server-side `did-auth.register` path does not
send SMS, send email, call Aliyun, or persist phone/email verification state.

For a repeatable local Rust CLI compatibility gate, let this repository start
its own temporary server and create two isolated CLI workspaces:

```bash
PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-rust-cli-local \
  --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli \
  --data-root /tmp/awiki-open-server-rust-cli-local --clean
```

This verifies current Rust CLI registration through the local DID registration path,
direct send/inbox/history, group join/send/messages, people
follow/status/following/followers, and site root/page commands against this
server. It is a local User Service / Message Service compatibility gate; it
does not replace the public `rwiki.cn` to `awiki.info` interoperability gate.

The server exposes compatibility routes used by the Rust CLI, including `/user-service/did-auth/rpc`, `/user-service/did/profile/rpc`, and `/user-service/handle/rpc`. These routes are implemented locally by this repository and do not forward to an external User Service.

It also exposes minimal `/user-service/agent-registration/rpc`,
`/user-service/message-agent/rpc`, and `/user-service/agent-inventory/rpc`
compatibility routes for current daemon status, controller scope, sender
checks, invocation authorization, archive, and local policy fields. These cover
local one-time agent registration tokens, message-agent binding state, and
daemon compatibility only; they do not implement hosted runtime orchestration,
delegated secret management, or a production policy engine.

The MVP does not use phone or email verification. Legacy contact-verification
routes such as `/auth/sms`, `/auth/sms-codes`, `/auth/email-send`,
`/auth/email-status`, and phone-bind routes return
`contact_verification_not_enabled` by default. They can be enabled only for
local compatibility tests with `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=true`;
even then they remain in-process dev shims and never call SMS, email, Aliyun,
`awiki.info`, User Service, or Message Service. Token and WebSocket ticket
verification routes remain local compatibility helpers and return `X-User-Id`
/ `X-DID` headers for nginx `auth_request` integrations.

For User Service DID verification compatibility, `/did-verify/rpc` and
`/user-service/did-verify/rpc` expose `send_code`, `login`, and `refresh`.
This is a local dev provider: `send_code` does not call an external message
service, `login` accepts the DID verify dev code `666666` by default, and
tokens are the local Community tokens already stored for registered DIDs.
Override the DID verify code with `AWIKI_DID_VERIFY_DEV_CODE` or
`DEV_BYPASS_CODE`. This is DID verify compatibility only and does not enable
phone or email verification.

DID Auth supports local `revoke` for registered DIDs. Revocation marks the
local user and DID document inactive; the same token or DID string can no
longer pass token verification, DID verify login/refresh, WebSocket ticket
verification, `get_me`, or `update_document`. The profile and historical
message data remain stored, but the active DID document route returns 404.
`replace_did` and `recover_handle` remain unsupported in the Community server.

For older User Service profile clients, the server also exposes local profile
compatibility routes: `/me`, `/me/rpc`, `/profiles/{user_id}`,
`/user-service/profiles/{user_id}`, `/users/{user_id}/profile`, and
`/users/rpc`. In this Community server, `user_id` is the local DID, and profile
fields are mapped onto the local DID profile record. These routes do not call
an external User Service.

Remote capability diagnostics can call the online `awiki.info` service, but `awiki.info` is a remote peer for interoperability testing, not this server's backend:

```bash
PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-awiki-info \
  --base-url https://awiki.info \
  --did-domain rwiki.cn
```

To send a direct test message, also provide `--token`, `--sender-did`, `--recipient-did`, and `--origin-proof-json`. Remote capability uses ANP JSON-RPC `params.meta/body`; remote direct uses `params.meta/auth/body`. A `missing params.meta` response means the request shape is wrong and is not a passing remote check.

For real interoperability validation, run this server on its own reachable base URL with a service private key configured, and configure the Rust CLI for that URL. The remote side should be an existing or test user on `awiki.info`. A valid test proves both directions:

- local open-server user -> `awiki.info` user: this server resolves the remote DID document, preserves the CLI `auth.origin_proof`, signs the HTTP hop as `AWIKI_SERVICE_DID`, and POSTs `direct.send` to the remote `ANPMessageService.serviceEndpoint`.
- `awiki.info` user -> local open-server user: `awiki.info` resolves this server's DID document and POSTs signed `direct.send` to this server's `/anp-im/rpc`.

Do not treat two CLI workspaces that both point at `https://awiki.info` as validation for this repository; that only verifies the online service itself.

## API Surface

Core and compatibility routes. Contact-verification compatibility routes are
mounted for old clients but return `contact_verification_not_enabled` unless
`AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=true` is explicitly set for local
testing:

- `GET /healthz`
- `GET /health`
- `GET /user-service/health`
- `GET /im/healthz`
- `POST /did-auth/rpc`
- `POST /user-service/did-auth/rpc`
- `POST /did-verify/rpc`
- `POST /user-service/did-verify/rpc`
- `POST /did/profile/rpc`
- `POST /user-service/did/profile/rpc`
- `GET /me`
- `PATCH /me`
- `POST /me/rpc`
- `GET /user-service/me`
- `PATCH /user-service/me`
- `POST /user-service/me/rpc`
- `GET /profiles/{user_id}`
- `GET /user-service/profiles/{user_id}`
- `GET /users/{user_id}/profile`
- `GET /user-service/users/{user_id}/profile`
- `POST /users/rpc`
- `POST /user-service/users/rpc`
- `POST /handle/rpc`
- `POST /user-service/handle/rpc`
- `POST /did/relationships/rpc`
- `POST /user-service/did/relationships/rpc`
- `POST /user-service/agent-registration/rpc`
- `POST /user-service/agent-inventory/rpc`
- `POST /user-service/message-agent/rpc`
- `POST /auth/sms-codes`
- `POST /user-service/auth/sms-codes`
- `POST /auth/sms`
- `POST /user-service/auth/sms`
- `POST /auth/email-send`
- `POST /user-service/auth/email-send`
- `GET /auth/email-status`
- `GET /user-service/auth/email-status`
- `POST /auth/phone-bind-send`
- `POST /user-service/auth/phone-bind-send`
- `POST /auth/phone-bind-verify`
- `POST /user-service/auth/phone-bind-verify`
- `POST /auth/token-refresh`
- `POST /user-service/auth/token-refresh`
- `GET /auth/token-verify`
- `GET /user-service/auth/token-verify`
- `GET /auth/verify`
- `GET /user-service/auth/verify`
- `GET /sessions/verify`
- `GET /user-service/sessions/verify`
- `POST /ws/tickets`
- `POST /user-service/ws/tickets`
- `GET /ws/tickets/verify`
- `GET /user-service/ws/tickets/verify`
- `GET /auth/ws-ticket/verify`
- `GET /user-service/auth/ws-ticket/verify`
- `POST /content/rpc`
- `POST /user-service/content/rpc`
- `GET /content/{slug}.md`
- `POST /site/rpc`
- `GET /`
- `GET /pages/{slug}.md`
- `POST /im/rpc` by default, or `AWIKI_IM_RPC_PATH`
- `POST /anp-im/rpc` by default, or `AWIKI_ANP_PUBLIC_RPC_PATH`
- `PUT /objects/upload/{slot_id}` by default, or `AWIKI_OBJECT_UPLOAD_PATH/{slot_id}`
- `GET /objects/{object_id}` by default, or `AWIKI_OBJECT_DOWNLOAD_PATH/{object_id}`
- `GET /.well-known/did.json`
- `GET /dids/resolve/{sub_path}/did.json`
- `GET /{sub_path}/did.json`

`/im/rpc` is the local client entry and exposes inbox, history, sync, read-state, group participant, and attachment control methods. `/anp-im/rpc` is the public cross-domain entry and only exposes `anp.get_capabilities`, `direct.send`, `group.get_info`, `group.join`, and `attachment.get_download_ticket`. Public `direct.send` and `group.join` require a business `auth.origin_proof` and a service-to-service HTTP Signature unless `AWIKI_ALLOW_UNSIGNED_PEER_DEV` is enabled for local tests.

Direct and group messages preserve Message Service payload shapes. `text/plain`
uses `body.text`; `application/json` and
`application/anp-attachment-manifest+json` use `body.payload` as a JSON object;
other non-text content types use `body.payload_b64u`. The server rejects
ANP-envelope messages whose body fields do not match `meta.content_type`, while
keeping older flat text CLI calls compatible.

Local message views (`inbox.get`, `direct.get_history`, `group.list_messages`,
and `sync.thread_after`) project those stored bodies with Message Service
semantics: text messages return `type=text`, JSON payloads return `type=json`,
attachment manifests return `type=attachment_manifest`, and other non-text
payloads return `type=binary`. The original `body` and `content_type` are still
included for clients that need the raw ANP shape.

Direct inbox read state follows the Message Service compatibility split:
`inbox.mark_read` marks the current user's visible direct message ids in
`direct_message_views.read_at`, default `inbox.get` returns unread messages
only, and `inbox.get {"include_read": true}` or `direct.get_history` can show
read messages with `is_read` and `read_at`. `read_state.mark_read` remains a
thread watermark API and does not emit account-level sync events.

Local view methods accept the Message Service `params.meta/body` shape and
older flat params. When present, `meta.sender_did` and `body.user_did` must
match the authenticated local DID. `inbox.get` supports `skip` and `limit`;
`direct.get_history` supports `peer_did`, `since_seq`/`since`, `skip`, and
`limit`. The deprecated direct-history `group_did` path is rejected; use
`group.list_messages` for group history.

The server recognizes only the documented daemon liveness heartbeat payload
(`application/json`, `body.payload.schema = awiki.agent.status.v1`,
`status_scope = daemon`, `message = daemon heartbeat`) as no-store. It returns
`delivery_state = ephemeral` and may notify an online recipient, but it does not
write that heartbeat to inbox, history, sync events, or sender-side history.
Other daemon/App status payloads, including run and snapshot statuses, remain
durable messages.

Supported group methods are participant-only: `group.get_info`, `group.join`,
`group.leave`, `group.send`, `group.get`, `group.list`, `group.list_members`,
and `group.list_messages`. `group.get_info` exposes minimal existing-group
information for discovery and open join. Member list, group messages, leave,
and send require the current DID to be a group member. Management methods such
as `group.create`, `group.add`, `group.remove`, `group.update_profile`, and
`group.update_policy` return `not_supported`. The seeded open-join group DID
follows `AWIKI_DID_DOMAIN`, for example `did:wba:localhost:groups:open`
locally and `did:wba:rwiki.cn:groups:open` in public deployment.
Group local views accept the Message Service `params.meta/body` shape, validate
the optional local owner fields, and support `limit`, `skip`, and `since_seq`
pagination for `group.list_messages`. `sync.thread_after` applies the same
member check for group threads, so it cannot be used to read a group after
leaving it.

`/im/ws` accepts a local ticket from `/ws/tickets` or `/user-service/ws/tickets`. It keeps the connection open, sends an initial sync hint, and then publishes in-process realtime notifications for local direct and group participant activity: `direct.incoming`, `group.incoming`, and `group.state_changed`. This is a single-process Community runtime feature; multi-process fanout, external pub/sub, offline push, presence, typing indicators, and HA realtime delivery are not implemented. Clients should still use `sync.delta` and `sync.thread_after` as the durable recovery path.

Attachment upload slots return both a legacy `upload_token` and `upload_headers`. The data plane accepts either `PUT /objects/upload/{slot_id}?token=...` or the returned `X-ANP-Upload-Token` header. `attachment.get_download_ticket` accepts the local `object_id` owner flow and the Message Service ANP body shape with `object_uri`, `attachment_id`, `requester_did`, `sender_did`, `message_id`, `message_security_profile`, and either `message_target_did` or `group_did`. Responses include both legacy `ticket/download_uri` fields and `download_ticket_b64u/ticket_binding`. `GET /objects/{object_id}` accepts `?ticket=...` and `Authorization: Bearer <download_ticket>`. This Community server only issues tickets for locally committed objects and local direct/group message context; it does not implement cross-domain attachment upload delegation, full `attachment_access_grants`, object E2EE authorization, or remote object relay.

`/did/relationships/rpc` and `/user-service/did/relationships/rpc` provide the minimal local DID relationship methods used by current CLI directory flows: `follow`, `unfollow`, `get_following`, `get_followers`, and `get_status`. They only operate on users registered in this server's configured DID domain.

`/site/rpc` provides a small Markdown site compatibility surface for the configured local domain: `get_root`, `set_root`, `list_pages`, `get_page`, `create_page`, `update_page`, `rename_page`, and `delete_page`. Public `GET /` and `GET /pages/{slug}.md` return raw Markdown. This is not production tenant hosting; cross-domain site management, templates, SEO rendering, and tenant admin policy are outside the Community MVP.
