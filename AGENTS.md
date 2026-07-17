# Repository Guidelines

## Project Structure & Module Organization

This repository implements `awiki-open-server`, a single-process Awiki Community Server MVP. Application code lives under `src/awiki_open_server/`: `app/` contains FastAPI wiring, routes, settings, and realtime helpers; `protocol/anp_adapter.py` is the only ANP SDK adapter; `messaging/` owns direct, Group Host/projection/outbox, sync, and read-state handlers; `attachments/` owns local upload slots, object commits, and download tickets; `user_compat/` owns local User Service compatibility; `storage/` owns SQLite access; and `shared/` contains JSON-RPC, ID, error, and runtime helpers. `services.py` is a compatibility facade plus remaining content/site/DID relationship handlers, not the place for new domain logic. Tests are under `tests/`, local smoke tooling is in `scripts/`, deployment examples are in `deploy/`, and product/implementation requirements are in `require.md` and `docs/community-groups-design.zh-CN.md`.

## Build, Test, and Development Commands

Install runtime and test dependencies:

```bash
python3 -m pip install -e '.[dev]'
```

The project pins ANP Python SDK `anp==0.8.8`; the protocol adapter fails fast when another version is loaded. In this workspace, use `PYTHONPATH=../anp/anp:src` for verification if the active environment still has an older installed `anp` package.

Run the full local suite:

```bash
PYTHONPATH=src python3 -m pytest tests -q
```

Start a local server:

```bash
PYTHONPATH=src AWIKI_DATA_DIR=.awiki-open-server \
AWIKI_PUBLIC_BASE_URL=http://127.0.0.1:8765 \
AWIKI_DID_DOMAIN=localhost \
python3 -m uvicorn 'awiki_open_server.app.main:create_app' \
  --factory --host 127.0.0.1 --port 8765
```

Useful smoke checks include `scripts/awiki_open_cli.py smoke-asgi`, `smoke-local`, `smoke-cross-domain-local`, and guarded public checks with `AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1`.

## Coding Style & Naming Conventions

Use Python 3.10+ with 4-space indentation, snake_case modules/functions, PascalCase classes, and explicit type hints on public functions. Keep FastAPI route names, JSON-RPC methods, and compatibility paths stable, for example `/im/rpc`, `/anp-im/rpc`, `/user-service/did-auth/rpc`, and `direct.send`. Keep Markdown concise and use fenced blocks for commands and payload examples.

## Testing Guidelines

Use `pytest` and `pytest-asyncio`. Name files `test_*.py` and test functions `test_*`. Prefer focused ASGI tests with temporary data directories before broad system tests. Run `tests/test_protocol_anp_sdk.py` for SDK/signature changes, `tests/test_route_config.py` for route/env changes, `tests/test_user_service_compat.py` plus identity/contact/profile/agent/site files for User Service compatibility, and `tests/test_messaging_surface.py`, `tests/test_direct_messages.py`, `tests/test_group_participant.py`, `tests/test_attachments.py`, or `tests/test_sync_read_state.py` for messaging changes. Public `rwiki.cn` tests must remain opt-in through `AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1`.

`awiki-open-server` does not support end-to-end encryption. Do not add or run Direct E2EE, Group E2EE, secure-message, prekey, ratchet, or encrypted-attachment cases as Open Server acceptance or release gates. Cross-domain interoperability verification for this repository must use plaintext Direct and plaintext Community Group flows. E2EE tests belonging to Message Service, ANP SDK, or client repositories are outside the Open Server test scope and must be run only when those products are the explicit test target.

## Commit & Pull Request Guidelines

Use short imperative commit subjects, such as `Add open server MVP implementation` or `Document local test workflow`. Pull requests should include a concise summary, affected modules, verification performed, and follow-up work. Link related issues or plan documents when available.

## Security & Configuration Tips

Do not commit `.env` files, SQLite databases, uploaded objects, generated tokens, private keys, or `.awiki-open-server/`. This server must implement Awiki capabilities locally; do not proxy to `awiki.info`, User Service, or Message Service. Community Group v1 includes small-scale Group Host management and direct cross-domain interoperability through DID discovery, signed peer requests, durable delivery, and local projections. Preserve the remaining MVP boundaries: no phone/email verification, no Aliyun dependency, no Direct/Group E2EE, no federation relay or peer-route mesh, no HA, no large-group/high-concurrency fanout, and explicit `not_supported` responses for out-of-scope capabilities. Do not implement or test E2EE behavior in this repository; an explicit `not_supported` response is the only Open Server contract for such requests. ANP P4 admission is limited to immediate-active `group.join` and `group.add`; do not implement invitations, invite/join tokens, join codes, or pending membership.
