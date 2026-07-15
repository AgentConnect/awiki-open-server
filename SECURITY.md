# AWiki Open Server Security Policy

[English](SECURITY.md) | [简体中文](SECURITY.zh-CN.md)

## Current security position

AWiki Open Server is a single-node Community Server MVP. It does not provide Direct or Group E2EE. The server processes and persists message payloads, so it is not suitable for highly sensitive communication without additional protection.

## Reporting a vulnerability

Do not disclose unpatched vulnerabilities, service keys, tokens, user messages, or exploitation steps in public issues, README comments, messages, or public interoperability tests.

<!-- TODO(security-contact): Enable GitHub Private Vulnerability Reporting or add the organization's official security email/form. -->

Include the affected commit/version, deployment mode and redacted configuration, minimal reproduction, impact, whether identity/messages/attachments/signatures/tokens are involved, and suggested mitigation.

## High-risk assets

- Service Ed25519 private key
- Access and refresh tokens
- WebSocket tickets
- Attachment upload tokens and download tickets
- Origin-proof and HTTP-Signature context
- Identity, message, and relationship data in SQLite
- Committed object files
- `.env` and public routing configuration

These assets must never enter Git, public logs, screenshots, issues, or test fixtures.

## Mandatory public configuration

```text
AWIKI_ALLOW_UNSIGNED_PEER_DEV=false
AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false
```

Prefer `AWIKI_SERVICE_PRIVATE_KEY_PATH=/secure/path/service-ed25519.pem` to an inline private-key environment variable.

## Authentication and signatures

- Uploaded DID Documents require a valid proof by default.
- The verification method must belong to the DID and be properly authorized.
- Public Direct and Group Join require both a business origin proof and a service-to-service HTTP Signature.
- The Contact Verification shim is not a production identity provider.
- Revocation must invalidate related tokens, DID verification, WebSocket access, and active DID routes.

## Data protection

- Back up SQLite and object files consistently.
- Back up the service key separately with encryption and access controls.
- Do not log complete message bodies, tokens, or signing material by default.
- Validate attachment MIME type, size, and digest.
- Single-process realtime provides no HA guarantee.
- Public deployments require TLS, least privilege, and a clear reverse-proxy boundary.

## Unsupported security assumptions

The current release does not guarantee server-blind messages, multi-node consistency or failover, production SMS/email identity verification, complete federation trust management, remote-object E2EE/relay, complete group policy/administration, or automatic secure upgrades/online migration. Adopters must assess risk against these boundaries.
