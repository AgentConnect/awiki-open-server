# Contributing to AWiki Open Server

[English](CONTRIBUTING.md) | [简体中文](CONTRIBUTING.zh-CN.md)

Thank you for improving AWiki Open Server. The project intentionally remains a readable, self-contained Community Server MVP with explicit boundaries. Contributions must not quietly turn it into a proxy for AWiki hosted services or an unbounded compatibility layer.

## Before you start

- Search existing issues and pull requests.
- Open an issue before changing APIs, identity, signatures, database schemas, sync, attachments, or public deployment.
- State whether the change belongs to MVP core, compatibility, ANP interoperability, or development tooling.
- Do not introduce hidden dependencies on `awiki.info`, User Service, or Message Service.
- Do not mix unrelated routes, formatting, and deployment-environment changes in one pull request.

## Environment

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e '.[dev]'
```

## Testing

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests -q
```

Add the relevant smoke checks:

```bash
PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-asgi \
  --data-dir /tmp/awiki-open-server-asgi

PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-cross-domain-local \
  --data-root /tmp/awiki-open-server-cross-domain --clean
```

Public changes require `verify-public` and guarded system tests. Client compatibility changes require the corresponding CLI/App smoke.

## Architecture rules

- `protocol/anp_adapter.py` is the centralized ANP Python SDK adapter boundary.
- Keep service identity and signature logic centralized.
- Put new domain logic in an explicit domain package instead of the monolithic facade.
- Implement local compatibility routes locally; never proxy silently to hosted services.
- Expose only explicit methods through public `/anp-im/rpc`.
- A realtime hint is not a durable checkpoint.
- Keep SQLite and object-storage semantics consistent.

## Security rules

Never commit `.awiki-open-server/`, SQLite/object files, `.env`, access/refresh tokens, service private keys, real origin proofs or HTTP Signatures, user messages, or private public-server paths and credentials.

Public defaults must remain:

```text
AWIKI_ALLOW_UNSIGNED_PEER_DEV=false
AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false
```

The lack of E2EE is an explicit boundary and must not be hidden through wording or compatibility shims.

Report security issues privately according to [SECURITY.md](SECURITY.md).

## Pull request description

```text
User/deployer problem
Affected API or data model
Local vs public surface
Security/interop impact
Backward compatibility
Tests and smoke run
Deployment/backup implications
Known limitations
```
