# AWiki Open Server README Asset Plan

[English](screenshot-plan.md) | [简体中文](screenshot-plan.zh-CN.md)

Server assets should provide evidence from a real running system and communicate boundaries clearly. Do not invent an administration-dashboard screenshot.

## 1. Hero GIF: local community smoke

- File: `open-server-local-smoke.gif`
- Length: 25-40 seconds
- Recommended size: 1400x800
- Flow: start Uvicorn, call `healthz`, run `smoke-local`, show the success summary
- Use `localhost` and a temporary data directory.
- Do not show local usernames, real paths, tokens, or internal domains.

## 2. Two-domain interoperability terminal

- File: `open-server-cross-domain-smoke.png` or GIF
- Show two services, DID discovery, and bidirectional inbox success from `smoke-cross-domain-local`.
- Never show service private keys or complete signature headers.
- Prefer this in the ANP interoperability guide rather than necessarily in the main README.

## 3. Architecture diagram

Use README Mermaid as the source of truth. A Social Preview may export `open-server-architecture.png` showing Clients to FastAPI to SQLite/Object Files to a remote ANP domain, clearly labeled `single process` and `no E2EE`, without every compatibility route.

## 4. Public verification result (optional)

- File: `open-server-public-verify.png`
- Show passing DID Document, health, capability, and federation-disabled checks.
- Use a dedicated demo/public test domain.
- Do not expose real tokens, recipients, or private server paths.

## 5. Social Preview

- File: `open-server-social-preview.png`
- Size: 1280x640
- Main text: `Self-hosted AWiki Community Server`
- Subtitle: `DID identity · Messaging · Attachments · ANP interop`
- Clearly mark `v0.1 MVP / No E2EE`.

## 6. Capture checklist

- [ ] Use the current main commit.
- [ ] Use temporary demo data directories only.
- [ ] Show no private key, token, OTP, or internal IP.
- [ ] Do not enable a development bypass in a public example.
- [ ] Keep terminal output readable.
- [ ] Verify a business flow, not health alone.
- [ ] Describe the actual verification in alt text.
