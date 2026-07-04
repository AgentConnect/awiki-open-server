# Repository Guidelines

## Project Structure & Module Organization

This repository implements `awiki-open-server`, a single-process Awiki Community Server MVP. Application code lives under `src/awiki_open_server/`: `app/` contains FastAPI wiring, routes, settings, and realtime helpers; `storage/` owns SQLite access; `shared/` contains JSON-RPC, ID, and error utilities; `services.py` holds the current domain service layer. Tests are under `tests/`, local smoke tooling is in `scripts/`, deployment examples are in `deploy/`, and product/implementation plans are in `require.md` and `plan/`.

## Build, Test, and Development Commands

Install runtime and test dependencies:

```bash
python3 -m pip install -e '.[dev]'
```

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

Use `pytest` and `pytest-asyncio`. Name files `test_*.py` and test functions `test_*`. Prefer focused ASGI tests with temporary data directories before broad system tests. Cover DID registration, DID documents, profile compatibility, direct messaging, group participant boundaries, attachments, and JSON-RPC compatibility routes when changing those areas. Public `rwiki.cn` tests must remain opt-in through `AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1`.

## Commit & Pull Request Guidelines

Use short imperative commit subjects, such as `Add open server MVP implementation` or `Document local test workflow`. Pull requests should include a concise summary, affected modules, verification performed, and follow-up work. Link related issues or plan documents when available.

## Security & Configuration Tips

Do not commit `.env` files, SQLite databases, uploaded objects, generated tokens, private keys, or `.awiki-open-server/`. This server must implement Awiki capabilities locally; do not proxy to `awiki.info`, User Service, or Message Service. Preserve MVP boundaries: no phone/email verification, no Aliyun dependency, no E2EE, no federation, no group creation/management, and explicit `not_supported` responses for out-of-scope capabilities.
