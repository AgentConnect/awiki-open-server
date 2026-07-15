# Getting Started with AWiki Open Server

[English](getting-started.md) | [简体中文](getting-started.zh-CN.md)

## 1. Goal

This guide starts a fully local Community Server, checks health, runs ASGI or HTTP smoke, explains the data directory and development switches, and helps you choose between connecting a CLI/App and deploying a public domain.

## 2. Environment

Use Python 3.10+, venv/pip, and a local port. Development tests use `httpx`, `pytest`, and `pytest-asyncio` from `.[dev]`.

```bash
python3 --version
```

Use an explicit interpreter such as `python3.11` when the system Python is older.

## 3. Install

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e '.[dev]'
```

The dependency set pins ANP Python SDK `anp==0.8.8`; the adapter fails fast on another version. In a controlled development environment only, a sibling checkout may be used explicitly:

```bash
PYTHONPATH=../anp/anp:src \
.venv/bin/python -m pytest tests -q
```

This is not a public-deployment default.

## 4. Start

```bash
PYTHONPATH=src \
AWIKI_DATA_DIR=.awiki-open-server \
AWIKI_PUBLIC_BASE_URL=http://127.0.0.1:8765 \
AWIKI_DID_DOMAIN=localhost \
.venv/bin/python -m uvicorn 'awiki_open_server.app.main:create_app' \
  --factory --host 127.0.0.1 --port 8765
```

Local data is written to `.awiki-open-server/`; never commit that directory.

## 5. Health check

```bash
curl --noproxy '*' http://127.0.0.1:8765/healthz
```

```json
{"status":"ok","edition":"community"}
```

`--noproxy '*'` prevents a development-machine proxy from intercepting loopback requests.

## 6. First success

Run core local flows without Uvicorn:

```bash
PYTHONPATH=src \
.venv/bin/python scripts/awiki_open_cli.py smoke-asgi \
  --data-dir /tmp/awiki-open-server-cli-asgi
```

With the HTTP service running:

```bash
PYTHONPATH=src \
.venv/bin/python scripts/awiki_open_cli.py smoke-local \
  --base-url http://127.0.0.1:8765 \
  --did-domain localhost
```

Start two isolated services and verify DID discovery, origin proof, service HTTP Signatures, and bidirectional inboxes:

```bash
PYTHONPATH=src \
.venv/bin/python scripts/awiki_open_cli.py smoke-cross-domain-local \
  --data-root /tmp/awiki-open-server-cross-domain-local \
  --clean
```

This loopback resolver-map check is a local protocol gate, not a replacement for real public interoperability.

## 7. Run tests

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests -q
```

Focused areas cover the ANP SDK/signatures, routes, User Service compatibility, Direct/Group/Attachment, Sync/Read State, and guarded public-deployment system tests.

## 8. Connect awiki-cli

Use an isolated CLI workspace:

```bash
export AWIKI_CLI_WORKSPACE_HOME_DIR=/tmp/awiki-cli-open-server-workspace

awiki-cli tenant setup local-community \
  --backend-base-url http://127.0.0.1:8765 \
  --did-host localhost

awiki-cli init
```

The Rust CLI registration shape may still require `--phone` or `--email`; Open Server does not send real SMS/email or persist production contact-verification state by default.

Repeatable CLI gate:

```bash
PYTHONPATH=src \
.venv/bin/python scripts/awiki_open_cli.py smoke-rust-cli-local \
  --awiki-cli-bin /path/to/awiki-cli \
  --data-root /tmp/awiki-open-server-rust-cli-local \
  --clean
```

## 9. Important development switches

Local tests may use `AWIKI_ALLOW_UNSIGNED_PEER_DEV=true` or `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=true`. Public deployments must keep both `false`.

## 10. Next steps

- [Client Compatibility](client-compatibility.md)
- [Public Deployment](deployment.md)
- [Configuration Reference](configuration.md)
- [ANP Interoperability](anp-interop.md)
- [Data, Backup, and Operations](operations.md)
