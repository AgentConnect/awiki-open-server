# Step 06：真实跨域互通加固

返回主 Plan：[../plan.md](../plan.md)

## 执行状态

| 字段 | 值 |
|---|---|
| status | in_progress |
| branch | main |
| started | 2026-07-03 |
| completed | 2026-07-03 本地门禁完成，真实线上 Gate 待公开域名 |
| commit | 未提交 |
| review evidence | 已检查：方案边界正确，未使用 awiki.info 后端、fallback、存储或内部依赖；awiki.info 仅作为远端对端和测试 fixture；`_anp_body` 保留后 origin proof 校验和远端转发使用原始 envelope body；业务 proof 已做 sender DID document / authentication / Ed25519 签名校验；未修改相邻仓库 |
| verification evidence | focused messaging 10 passed；全量 pytest 16 passed；compileall pass；ASGI smoke pass；真实 awiki.info Gate 待本服务公开域名 |
| next action | 配置公开域名、service private key 和 Rust CLI 后执行双向 awiki.info interop Gate；若线上 awiki.info 对等服务拒绝本服务 DID/proof/signature，则记录 blocker 给用户确认 |

## 目标

把当前“本地模拟跨域 direct”收敛成真实可与线上 `awiki.info` 互通的实现。本仓仍必须自己实现 server 能力，不能把 `awiki.info` 当后端或兜底服务；`awiki.info` 只作为线上远端对端用于验证。

验收标准：

- 本服务用户发给 `awiki.info` 用户时，远端请求保留 CLI 传入的 `params.meta/auth/body/client`，尤其不能替换 `auth.origin_proof`。
- 远端 `/anp-im/rpc` POST 使用本服务 `AWIKI_SERVICE_DID` 做 hop-level HTTP Signature / DID WBA，并带 `x-anp-source-service-did`。
- 本服务 service DID document 暴露可验证的 `verificationMethod` / `authentication`，且只包含一个公开 `ANPMessageService`。
- 本服务公开 `/anp-im/rpc direct.send` 要校验业务 `origin_proof` 和服务层签名；缺失 proof 或 hop auth 时拒绝，不能成为 relay。
- 身份接口与现有 CLI 路由兼容：`register` / `update_document` 接受 `did_document`，`/handle/rpc` 和 `/user-service/...` 兼容路径可用，Profile 返回标准 alias 和 `service_endpoints`；这些兼容路径由本仓实现，不调用外部 User Service。
- 真实 Gate 使用一个 CLI 连接本服务公开域名，另一个 CLI 或已有用户连接 `awiki.info`，验证双向 direct、inbox/history。

## 设计方法

实现边界仍限定在 `awiki-open-server`。可阅读 `user-service`、`message-service`、`awiki-cli-rs2` 和 `anp` 代码作为协议依据，但不修改这些仓库。

跨域 direct 分两层认证：

- 业务主体层：CLI 已生成 `auth.origin_proof`，本服务外发时必须原样透传；本服务接收时必须校验或至少用 ANP SDK 校验失败即拒绝。
- 服务 hop 层：本服务用 bare-domain service DID 签 HTTP 请求；接收端用 `x-anp-source-service-did` 和 HTTP Signature 校验来源服务。

本步骤不实现 federation peer routes、relay、远端重试队列、远端投影、跨域群组托管或跨域 read-state ack。

## 实现方法

1. 在 `src/awiki_open_server/app/settings.py` 增加 service identity 配置，例如 `AWIKI_SERVICE_PRIVATE_KEY_PEM` / `AWIKI_SERVICE_PRIVATE_KEY_PATH`、public key id、是否允许本地 dev unsigned。
2. 在 `src/awiki_open_server/services.py` 更新 DID document 生成：service DID 和用户 DID document 均保留唯一 `ANPMessageService`，service DID document 增加 HTTP Signature 可验证的 key material。
3. 修复远端 direct 外发：`direct_send` 从 normalized params 取 `_anp_meta`、`_anp_auth`、`_anp_client`，传给 `_send_remote_direct`，`_remote_direct_payload` 不再生成 fake `community-dev-bearer` proof。
4. 更新 `_http_post_json` 或新增签名 helper：对远端 `/anp-im/rpc` 请求加入 `x-anp-source-service-did`、`Content-Digest`、`Signature-Input`、`Signature`。优先复用 `anp` Python SDK；若 SDK 不可用，要返回清晰的 `service_identity_not_configured`，不能静默降级为 unsigned 线上请求。
5. 更新公开 `/anp-im/rpc` direct 接收：检查 hop auth 和 `auth.origin_proof`；非本地 recipient 仍返回 `recipient_not_local`，避免 relay。
6. 补齐现有 CLI / User Service 路由兼容：`update_document` 接受 `did_document`；增加 `POST /handle/rpc`；`send_otp` 返回兼容字段；Profile projection 返回 `user_name`、`nick_name`、`avatar_url`、`bio`、`profile_url`、`service_endpoints` 等 alias。所有兼容接口均由本仓本地实现，不转发到外部服务。
7. 更新测试，覆盖上述契约；不要把两个 CLI 都连到 `https://awiki.info` 的测试当成本项目通过证据。

实现记录：

- 已新增 `awiki-open-server/src/awiki_open_server/service_identity.py`，实现 Ed25519 service DID document、DataIntegrityProof、RFC 9421 HTTP Signature 生成与本地校验。
- 已接入 `AWIKI_SERVICE_PRIVATE_KEY_PEM`、`AWIKI_SERVICE_PRIVATE_KEY_PATH`、`AWIKI_SERVICE_DID_DOCUMENT_JSON`、`AWIKI_ALLOW_UNSIGNED_PEER_DEV`。
- 远端 direct 外发现在要求 `auth.origin_proof`，`normalize_params` 保留原始 ANP envelope `body` 为 `_anp_body`，`direct_send` 使用原始 `meta/body` 做 origin proof 校验、远端转发和本地存储。
- 公开 `/anp-im/rpc direct.send` 现在要求 `auth.origin_proof` 和 peer HTTP Signature；dev unsigned 只能显式开启。
- 业务 `auth.origin_proof` 现在会解析 sender DID document，检查 proof `keyid` 属于 `meta.sender_did` 且位于 `authentication`，并验证 RFC9421 origin proof Ed25519 签名；新增无效签名拒绝测试。
- 已补齐 `/handle/rpc`、`update_document.did_document`、`send_otp` 兼容响应、Profile alias 和 `service_endpoints`；这些接口使用本仓 SQLite 状态，不依赖线上 `awiki.info` 或相邻服务。

## 路径

可修改路径：

- `awiki-open-server/src/awiki_open_server/app/settings.py`
- `awiki-open-server/src/awiki_open_server/app/routes.py`
- `awiki-open-server/src/awiki_open_server/services.py`
- `awiki-open-server/src/awiki_open_server/shared/jsonrpc.py`
- `awiki-open-server/tests/`
- `awiki-open-server/scripts/awiki_open_cli.py`
- `awiki-open-server/README.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/`

只读参考路径：

- `user-service/docs/api/did-auth.md`
- `user-service/docs/api/did-profile.md`
- `user-service/docs/api/handle.md`
- `message-service/docs/architecture/anp-service-discovery.md`
- `message-service/docs/architecture/identity-auth-proof-architecture.md`
- `message-service/crates/im-app/src/dispatch.rs`
- `message-service/crates/im-direct/src/service.rs`
- `message-service/crates/im-identity/src/service_identity.rs`
- `awiki-cli-rs2/crates/im-core/src/internal/identity_wire/mod.rs`
- `awiki-cli-rs2/crates/im-core/src/internal/message_runtime/direct.rs`
- `anp/anp/anp/authentication/`

禁止修改路径：

- `user-service/**`
- `message-service/**`
- `awiki-cli-rs2/**`
- `awiki-harness/**`
- 其他相邻仓库

## 验证方式

本地必跑：

```bash
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-interop-hardening-asgi
```

本轮结果：

- `PYTHONPATH=src python3 -m compileall -q src scripts tests`：pass。
- `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q`：10 passed。
- `PYTHONPATH=src python3 -m pytest tests -q`：16 passed。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-interop-hardening-asgi-proof`：pass。
- 此前 `origin_proof_content_digest_mismatch` 已通过保留 `_anp_body` 修复。

服务启动后必跑：

```bash
AWIKI_PUBLIC_BASE_URL=<本服务公开 URL> \
AWIKI_DID_DOMAIN=<本服务 DID 域> \
AWIKI_SERVICE_DID=did:wba:<本服务 DID 域> \
python3 -m uvicorn awiki_open_server.app.main:create_app --factory --host 0.0.0.0 --port 8765
```

Rust CLI Gate：

- 一个 CLI profile 指向本服务公开 URL，注册本服务域用户。
- 一个 CLI profile 指向 `https://awiki.info`，使用线上允许的测试手机号/OTP 或已有测试用户。
- 执行双向 `msg send`、`msg inbox`、`msg history`。

如果公网域名、DNS、TLS 或线上服务拒绝导致无法完成真实 Gate，要记录具体 URL、DID、请求方向、错误响应、已排除的本仓问题，并把它作为本目标之外的 blocker 交给用户决策；本目标内不修改其他服务。

## Review 环节

Review 必须检查：

- `awiki.info` 没有被用作本服务后端、fallback、存储或内部依赖。
- 远端 direct 不再生成 fake origin proof，也不丢失 CLI envelope。
- HTTP Signature headers 与 service DID document key id 对齐。
- `/anp-im/rpc` 不暴露 local-only 方法，不 relay 非本地 recipient。
- CLI/User Service 兼容字段由本仓返回，不会引入外部服务依赖，也不会破坏现有本地测试。
- 无密钥、token、SQLite DB、上传对象或线上测试数据被提交。

## 并行安全

- parallel-safe：否。
- 原因：本步骤同时修改 identity、direct、HTTP 签名、公开路由和测试，写入面重叠且协议必须整体一致。
- 合并策略：串行完成后做一次 focused Review 和全量验证，再回填主 Plan 台账。

## 文档影响

本步骤应更新 `awiki-open-server/README.md` 的真实互通配置说明，明确：

- `awiki.info` 是远端对端，不是后端依赖。
- `rwiki.info` 或其他域名是本服务用户 DID 域时，服务本身仍必须由本仓实现并公开 DID document 与 `/anp-im/rpc`。
- dev unsigned / dev proof 只能用于本地测试，不能作为线上互通证据。

不修改 Harness 或相邻仓库文档；如发现它们与实际协议冲突，只在主 Plan 的风险或 blocker 中记录。
