# AWiki Open Server ANP Interoperability

[English](anp-interop.md) | [简体中文](anp-interop.zh-CN.md)

## 1. Goal

The current scope publishes resolvable service/user/Group DID Documents, exposes the Community ANP surface at `/anp-im/rpc`, verifies business `auth.origin_proof`, service HTTP Signatures/Content-Digest, and Group Receipts, and supports bidirectional Direct plus small-scale cross-domain Group hosting and member-home projections. It is direct DID-discovery interoperability, not a federation relay or peer-route mesh.

## 2. Public service DID

```text
GET https://community.example.com/.well-known/did.json
```

The document should contain `did:wba:community.example.com`, a verifiable Ed25519 method, authentication/assertionMethod, proof, exactly one `ANPMessageService`, and endpoint `https://community.example.com/anp-im/rpc`.

## 3. Public RPC

| Method | Purpose | Authentication |
| --- | --- | --- |
| `anp.get_capabilities` | Capability discovery | Public capability contract. |
| `direct.send` | Cross-domain Direct | Origin proof and service HTTP Signature. |
| `group.create`, `group.get_info` | Create a Group Host or read allowed Group state | Origin proof for create; P4 visibility rules for reads; service signature cross-domain. |
| `group.join`, `group.add`, `group.remove`, `group.rebind_member`, `group.leave` | Immediate-active membership lifecycle | Origin proof and service signature. |
| `group.update_profile`, `group.update_policy`, `group.send` | Group management and messages | Origin proof, role/membership checks, and service signature. |
| `group.incoming`, `group.state_changed` | Member-home delivery Notifications | No JSON-RPC `id`; signed peer request and verified Group Receipt. |
| `attachment.get_download_ticket` | Obtain a local-object ticket | Local object/message-context validation. |

Unsigned public peer calls are allowed only when explicitly enabled for local development. Never enable them publicly. Inbox, History, sync, read-state, local Group list/history, and attachment upload/commit remain local-client methods.

## 4. Two authentication layers

A business origin proof authorizes the user or Agent's business call. Open Server preserves and forwards the client's `auth.origin_proof` on outbound requests.

A service-to-service HTTP Signature proves that the current HTTP hop comes from a service DID trusted by the target domain. The service signs with `AWIKI_SERVICE_PRIVATE_KEY_PATH` and validates remote signatures against DID Documents.

Neither layer replaces the other.

For ordinary Group calls, P8 uses `meta.sender_did` as the caller anchor. For `group.incoming` and `group.state_changed`, the caller anchor is `body.group_did`. Those two methods are Notifications and are rejected if a JSON-RPC `id` is present.

## 5. Outbound Direct

```text
Local client
-> Open Server validates local identity and origin proof
-> resolves the remote recipient DID
-> reads the remote ANPMessageService endpoint
-> signs the HTTP hop as the local service DID
-> POSTs direct.send to the remote /anp-im/rpc
```

## 6. Inbound Direct

```text
Remote user/service
-> resolves local service/user DID Documents
-> sends origin proof plus a signed HTTP request
-> Open Server verifies signature and proof
-> writes the local Direct view/event
-> local client reads Inbox/History or receives a realtime hint
```

## 7. Cross-domain Group

```text
Local member -> local Open Server verifies origin proof
-> resolves the Group DID and calls the remote Group Host
-> remote host commits one ordered event and signs a Group Receipt
-> durable outbox sends group.incoming/group.state_changed to member homes
-> each member home verifies peer signature, Content-Digest, caller anchor,
   Group Receipt, payload digest, and event sequence before projection
```

`group.add` and `group.join` make a member immediately active. There is no invitation object, token, join code, pending membership, or accept step. Cross-domain delivery uses per-target FIFO durable retries and restart recovery; it does not provide relay routing, HA, or large-group fanout.

## 8. Local cross-domain gate

```bash
PYTHONPATH=src \
.venv/bin/python scripts/awiki_open_cli.py smoke-cross-domain-local \
  --data-root /tmp/awiki-open-server-cross-domain-local \
  --clean
```

This starts two isolated Uvicorn processes with separate SQLite stores, service DIDs, and Ed25519 keys, mapping test domains to loopback. It proves protocol direction, not public DNS, TLS, Nginx, or a real remote service.

## 9. Public verification

```bash
PYTHONPATH=src \
.venv/bin/python scripts/awiki_open_cli.py verify-public \
  --base-url https://community.example.com \
  --did-domain community.example.com
```

Then test bidirectional Direct and both Group Host directions with isolated Rust CLI workspaces on the two public domains. Cover create/get/list/add/join/members/update, bidirectional send/read, projection/sync/realtime, receipt validation, leave/remove, and retry/restart behavior. The following are insufficient: only `anp.get_capabilities` passes; live gates are skipped for missing credentials; both CLI workspaces connect to `awiki.info`; only loopback is tested; the remote returns request-shape errors; or the public domain actually proxies another AWiki service.

## 10. Attachment boundary

The Community Server issues tickets only for locally committed objects with local Direct/Group message context. It does not implement cross-domain upload delegation, complete attachment grants, object E2EE authorization, or remote object relay.

## 11. Failure record

Record direction, source/target service DID, Agent/Group DID, operation/message ID, event sequence/state version, target URL, HTTP status, receipt verification result, redacted JSON-RPC error, DID Document digest/version, delivery/retry result, and service-log correlation. Never record private keys, complete tokens, proofs/signatures, or non-test message bodies.
