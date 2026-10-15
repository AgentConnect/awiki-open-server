# AWiki Open Server Client Compatibility

[English](client-compatibility.md) | [简体中文](client-compatibility.zh-CN.md)

Last reviewed: 2026-10-15. The alignment baseline is `release/0929`; current acceptance scope and historical evidence are distinguished below.

## release/1014: remove temporary P5/P6 compatibility

This branch starts from `main` commit `09d38fd`. At the user's request on 2026-10-15,
P5/P6 empty-stream compatibility is removed. Related bootstrap requests return
`sync.lanes_not_supported` with `supported=[]`. Delta rejects `lanes`/`p6_delivery` and
returns no compatibility streams. The P6 delivery-context WebSocket subprotocol is rejected
with close code 4406. Stored negotiations cannot reenable it; ordinary renegotiation saves
an empty capability set. Ordinary Sync v2, Schema 3 Snapshot, plaintext Direct, and ordinary
Groups remain available; public E2EE capabilities stay disabled.

CLI/App versions that require P5/P6 must change their requests to ordinary sync only.
The CLI 1.0.58 and App 0.1.38+49 passes below apply to temporary compatibility at `09d38fd`,
not current-branch client acceptance. Verification here covers disabled capabilities,
ordinary plaintext sync, and restart regressions, without successful encryption flows.

## release/0929 alignment status

Open Server pins published ANP Python SDK **1.0.6**. Handle `registration_check` on
`/user-service/v1/handle/rpc` returns `register/existing/unavailable` without reserving a name,
issuing authorization, or echoing contacts. Checks are limited to 20 per minute per trusted ASGI
peer; final registration still checks ownership transactionally. Self-hosted registration does
not require Hosted Platform short-name invitations.

`GET /user-service/v1/server-info` implements the App's schema 1 discovery contract: local WBA
creation and registration without contact verification. It does not advertise SMS/email delivery,
Handle Recovery, Root Transfer, Model Proxy, Guest Gateway, or hosted Skill Agent capabilities.
CLI phone registration can use a local operator code, which does not prove phone ownership.
The unmodified `release/0929` App Dart `OnboardingServerInfo` parser accepted this response,
recognizing registration without contact verification and disabled Recovery. This contract
check does not replace a real App journey.

Historical transition (authorized 2026-10-14, removed on release/1014): P5/P6 subscriptions
were acknowledged at bootstrap and returned empty streams during delta. The matching
WebSocket subprotocol emitted plaintext sync hints only. This never implemented encrypted
producers, ciphertext storage, PreKey, KeyPackage, or encrypted attachment operations.

Official CLI **1.0.58**, commit `b7ed6f95f7fb90151726a96e6bed756957f6312e`, Linux x86_64
SHA-256 `459bf8737cf27c8441fd0f4d22cefdf67958a777ffefd193fef0b08126282c85`, passed standard
registration and plaintext Direct writes. Its official installer was selected from
`https://awiki.me/cli/stable/manifest.json`, verified against its published digest, and left
unmodified. CLI 1.0.57 is now below the default tenant's minimum version 1.0.58.
The expanded `smoke-rust-cli-connect` passed standard registration, bidirectional plaintext Direct,
Inbox/History, and plaintext Group create/add/send/read.

The remaining focused gates passed on 2026-10-15 with temporary compatibility at `09d38fd`:

- The complete `smoke-rust-cli-realtime-restart` passed: two server boots, three listener boots,
  and five plaintext messages cover live notifications, listener downtime recovery, server
  restart, and history. Every readiness check completed sync v2 bootstrap/subprotocol negotiation
  with `legacy_sync_used=false`. The former final `bridge_read` failure came from a CLI bridge
  read without its default identity. The gate now explicitly selects Bob using `--identity`
  for its final two reads, retaining all original assertions.
- Real aWIKI ME **0.1.38+49**, source `a205a36af81d558523722d1a5cf5e50523fe8845`, ran the
  unmodified `lib/main.dart` on Linux/Xvfb. Custom HTTPS tenant discovery, standard registration,
  bidirectional plaintext Direct and ordinary Group messaging, and identity/conversation/history
  recovery after App restart passed. Official CLI reads checked exact sender and content; UI
  screenshots prove reception. The native library used registry Core **0.1.9** and passed the
  existing provenance guard. `AWIKI_E2E` enables existing isolated storage and semantics only;
  no fake services or client-state edits were used. This App rejects an empty phone before
  precheck with `phone_invalid_intl_or_cn`; a dedicated test number allowed contact-free
  registration without SMS/OTP. That client issue remains unchanged. This is focused Linux UI
  acceptance, not a full or cross-platform App E2E pass.
- Independent public OpenServer and real `awiki-info-testing` (`https://awiki.info`) exchanged
  Direct messages in both directions. With each service as ordinary Group Host, messages sent
  by each side were visible at the other member's Home, including signed requests, Group Receipt,
  and content checks. Public HTTPS/DID discovery was used without resolver substitution,
  unsigned peers, or shared-service changes. Existing `awiki-system-test` identity and
  cross-domain helpers were reused. Membership readiness waits for the visible `group.list`
  role rather than requiring a local member projection to contain the entire Host roster.

Initial conflict, membership query/wait failures, temporary tunnel interruption, and successful
retries remain recorded separately. Redacted JSON, screenshots, artifact provenance, and cleanup
scope are in workspace `verification-runs/openserver-release0929-20261015/`. Remote User Service
identities remain under the owning repository's retention policy. Exact Message cleanup failed
and residuals are recorded; cleanup is not claimed complete. Temporary processes were stopped.
No successful encryption flows were run. Automatic client prekey/KeyPackage requests returned
`not_supported`. Pre-transition failures follow.

On 2026-10-13, unmodified CLI **1.0.57**, current release/0929 source
`ec90c4cc772ef7a4c64809b6158affb807798df0`, Linux x86_64 SHA-256
`422955d37df9237032933ebb620dba66392145a4ce22a78c123a2b695aa9ee11`,
passed precheck and committed single-device registration, then failed initial receive sync with
`registration_receive_pending`. A subsequent `msg inbox` failed with `sync.lanes_not_supported`.
The existing CLI `scripts/release/registry-build.py` built a fresh committed Git archive and
verified registry ANP 1.0.6, Identity 0.2.5, and Core 0.1.8. CLI and dependency source remained
unchanged. This proves the current release combination's behavior, not stable publication.
The native source/dependency receipt is `/tmp/openserver-release0929-cli-registry-ec90c4cc.json`;
redacted runtime results are `/tmp/openserver-release0929-ec90c4cc-runtime/result.json`.
The test server was stopped.

Before this transition, Core requested P5/P6 from compiled features and required the same lane
set, resulting in the recorded `sync.lanes_not_supported` failure. This is an AWiki private sync
contract mismatch, not evidence of an ANP violation by MessageService or UserService. The user's
2026-10-14 empty-stream transition was temporary; release/1014 restores explicit rejection.

Rust CLI smoke gates now use standard two-step registration with `--verification-stdin`,
never `--community`. Failure diagnostics redact stdin verification material and gates retain
nonzero exits on failure.

## Historical protocol-upgrade path (R3, 2026-09-18)

Acceptance uses the official unmodified CLI from `https://awiki.info/cli/stable/manifest.json`: version **1.0.52**, commit `dde0a9c54eebf29a2ec97089e90a1fa77ba768c5`, linux-amd64 SHA-256 `a055da8dad2969739c50cee4f2ee0bf34b45f5354ea74617f103534b239f9d1a`. Do not use candidate16, `--community`, or an unreleased 1.0.53 Community build as the current path.

New identities use official `id register` with a handle plus phone verification material. Open Server does not send SMS; `send_otp` with purpose `awiki.identity.register.v1` stores a one-time local operator code under the data directory. Pass that code as `--otp`. The reliable listener requires an actual single-device Manifest/binding. At that time CLI 1.0.52 was blocked by `sync.lanes_not_supported`; release/1014 also rejects these requests, and E2EE remains unsupported. Ordinary Schema 3 Snapshot recovery is implemented for the single device. Open does not provide identity/Handle recovery or Root Transfer.

R2 unpublished CLI 1.0.53 / SHA `8169383d86a57eaed23e015dc948f8176216e9f81903d16f590dd03c513f847f` over `c61fa4b419b96fdabdbd321f1a8e47cdd7f77302` is historical only.

## 1. Historical evidence and client scope

| Client/peer | Position | Known capabilities | Key limitations |
| --- | --- | --- | --- |
| `awiki-cli` | Primary compatibility client | 1.0.43 `bbeb8a5c`: local Attachment/members/mark-read/restart, Realtime Sync v2, and bidirectional Direct/Group cross-domain gates verified | Sync v2 is single-device pull only; no device sharing, second device, or E2EE. Ordinary Schema 3 Snapshot recovery is implemented for that device. |
| AWiki Me | Basic product compatibility target | Identity/messages/attachments on a custom tenant require continuous validation | Agent realm allowlist, no E2EE, and no claim of every app feature. |
| Other ANP peer | Selected public methods | Capability, Direct, selected Group/Attachment | Not complete federation; origin proof and service signature required. |
| Legacy AWiki client | Compatibility routes | User/Message Service-shaped routes | Shims are not production identity providers or a complete hosted platform. |

## 2. awiki-cli

Repository and public gates cover DID registration; Direct send, Inbox, and History; Group create/get/list/add/join/members/update/send/messages/leave/remove in both host directions; People follow/status/following/followers; Site root/pages; and attachments as implemented.

Those are gate targets, not a claim that every future client passes automatically. A clean `awiki-cli` 1.0.43 build at commit `bbeb8a5c` was verified on 2026-08-08. The real-CLI gates cover binary Direct/Group Attachment download with byte comparison, members and cursor pagination, idempotent mark-read and restart persistence, foreground Realtime with `awiki.sync.changed.v2`, listener/server restart recovery, and two independent TLS domains with bidirectional plaintext Direct and a Community Group hosted in each direction. The v2 sync profile is a wire-version contract, not a multi-device claim: Open Server binds one DID to exactly one device and one client instance and rejects additional devices/instances. Empty accounts may use tail-only bootstrap; log gaps and expired cursors recover through Schema 3 paged Snapshot (`awiki.message-sync.explicit-negotiation.v1`, `sync.snapshot_paging.v1`), then ordinary delta. Release/1014 rejects P5/P6 negotiation; clients must request ordinary sync only. Encrypted operations remain rejected. Cross-device state sharing is not provided.

Run the gates separately:

```bash
# Connection gate: configure, register, and perform a plaintext Direct write.
uv run --locked python scripts/awiki_open_cli.py smoke-rust-cli-connect \
  --awiki-cli-bin /path/to/pinned/awiki-cli --clean

# Complete local gate. Standard HTTPS is required for attachment DID discovery;
# the script creates an isolated Linux network namespace and test CA.
uv run --locked python scripts/awiki_open_cli.py smoke-rust-cli-local \
  --awiki-cli-bin /path/to/pinned/awiki-cli --standard-https --clean

# Foreground Realtime/Sync v2 plus listener and OpenServer restart recovery.
uv run --locked python scripts/awiki_open_cli.py smoke-rust-cli-realtime-restart \
  --awiki-cli-bin /path/to/pinned/awiki-cli --clean

# Two TLS OpenServer domains, bidirectional plaintext Direct and both Group Host directions.
uv run --locked python scripts/awiki_open_cli.py smoke-rust-cli-cross-domain \
  --awiki-cli-bin /path/to/pinned/awiki-cli --clean
```

The namespace-backed HTTPS gates require Linux `unshare`, `mount`, and `ip`. They do not alter the host network or install a listener service. The opt-in pytest wrapper is:

```bash
AWIKI_RUN_RUST_CLI_SYSTEM_TESTS=1 AWIKI_CLI_BIN=/path/to/pinned/awiki-cli \
uv run --locked python -m pytest tests/test_rust_cli_system.py -q
```

Reports must distinguish `registration-and-plaintext-messaging passed`, `single-device sync v2 passed`, and `full local user journey passed`. Record the CLI commit, `awiki-cli version`, artifact SHA-256, Open Server commit, and date.

Candidate connection example, after configuring [CLI identity secret storage](https://github.com/AgentConnect/awiki-cli-rs2/blob/c61fa4b419b96fdabdbd321f1a8e47cdd7f77302/docs/architecture/identity-secret-storage.md):

```bash
awiki-cli tenant create open \
  --backend-base-url https://open.example.com \
  --did-host open.example.com
awiki-cli tenant use open
awiki-cli id register --handle alice --phone +15550000001
awiki-cli id register --handle alice --phone +15550000001 --otp <local-operator-code>
```

Do not use `--secure required` or treat the Contact Verification development shim as real SMS/email. Group admission is immediate-active `group.add` or `group.join`; clients must not expect invitation tokens, join codes, pending membership, or an accept-invite command.

## 3. AWiki Me

A basic tenant needs a reachable backend base URL, matching DID host, compatibility routes for the app version, reachable attachment URLs/tickets, and matching WebSocket route/ticket flow.

Verify registration/login; Direct send/receive/history; unread/read; Group create/add/join/update/send/messages/leave/remove; attachment send/download/open; People/Contact/Profile; and app restart/local sync recovery.

### Agent/Daemon limitation

Capability-aware AWiki Me uses the versioned Server Info contract for Agent and
Daemon availability. Open Server declares both complete products unsupported;
partial compatibility routes do not enable them. Older App releases may still
use a tenant-domain allowlist and require a client upgrade to consume this
contract. The server declaration does not depend on its domain or client platform.

### E2EE

Open Server implements neither Direct nor Group E2EE. AWiki Me must treat it as a non-E2EE tenant and must not show a misleading end-to-end-encrypted state.

## 4. Public ANP methods

Public `/anp-im/rpc` exposes `anp.get_capabilities`, `direct.send`, the Community Group Host methods (`group.create/get_info/join/add/remove/rebind_member/leave/update_profile/update_policy/send`), the `group.incoming` and `group.state_changed` Notifications, and `attachment.get_download_ticket`. Local `/im/rpc` additionally contains Inbox, History, Sync, Read State, local Group views, and attachment-control methods. Do not expose all local compatibility RPC as a cross-domain contract.

## 5. Meaning of compatibility routes

User Service/Message Service-shaped routes are implemented locally and do not proxy `awiki.info`. They let current clients reuse existing shapes, provide local profile/token/DID/relationship/message entry points, return `contact_verification_not_enabled` when appropriate, and provide local verification headers for integrations such as Nginx `auth_request`.

Compatibility does not mean a complete hosted platform, production identity provider, complete Agent orchestration, large-group/complex governance, or permanent compatibility with every future client.

## 6. Verification record

```text
Date: YYYY-MM-DD
Open Server commit/version:
Client name/version/commit:
Domain/base URL:
ANP SDK version:

Passed:
- identity
- direct
- inbox/history
- read/sync
- Community Group v1 lifecycle and both cross-domain host directions
- attachment
- people/profile/site
- websocket/restart

Limitations/failures:
- agent
- secure
- large-group/complex governance
- ...
```

Custom tenants do not automatically discover another tenant’s legacy credentials. Explicitly import with `awiki-cli --migration id import-v1 --name <name> --credentials-dir <legacy-credentials-directory>`. The source override applies only to this import; it does not change tenant configuration or enable the reliable listener.

## 后端能力发现（合同 v1）

`GET /user-service/v1/server-info?capabilities_version=1` 保留外层
`schema_version: 1`，回显 `capabilities_version: 1`。未携带版本时保留旧手机号免验证
发现形状；新版使用 `handle_only`，不要求无业务用途的手机号或邮箱。未知合同版本返回
422。`client_platform` 不改变服务器事实，发现没有注册、写入身份或发送验证码的副作用。

身份声明明确关闭多设备、设备撤销、能力升级、管理权转移；找回 methods 为空。
账户同步、完整 Agent/Daemon/Skill 产品、邮件、Model Proxy、Guest 和托管关闭。
基础内容和站点仍开放，内容数量限制为 5；不将部分 Agent 兼容路由声明成完整产品。
更新政策明确不提供，客户端不得据此改用官方租户的更新源或清除已缓存最低版本。

已认证 `/im/rpc` 的 `anp.get_capabilities` 增加 `awiki_local`：普通私聊、群聊、附件、
历史、已读、普通 Sync v2、Schema 3 Snapshot、开放加入和管理员添加可用。
P5/P6、所有加密、邀请及审批关闭；附件大小来自运行配置，群成员/加入数量为既有实际限制。
匿名兼容发现及公共 `/anp-im/rpc` 不返回此本域扩展；公共 ANP 发现及认证边界不变。
客户端须请求空扩展通道集合，不能退回隐式 bootstrap 或把加密请求改为明文。

公开字段合同由 AWiki IM Core API 文档维护；本仓运行、安装和测试不依赖该仓。
本地验证：`uv run pytest tests/test_registration_discovery.py tests/test_messaging_surface.py tests/test_standard_sync_asgi.py -q`。
