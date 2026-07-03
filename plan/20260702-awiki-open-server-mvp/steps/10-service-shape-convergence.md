# Step 10：User / Message Service 兼容形态补齐

主 Plan：[../plan.md](../plan.md)  
Step index：10  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-with-pending-online-gate |
| Branch | main |
| Started | 2026-07-03 |
| Completed | 2026-07-03 本仓门禁与 Rust CLI 本地 Gate 完成 |
| Commit | 未提交 |
| Review evidence | 已复核：新增接口只补本仓服务形态兼容，不引入外部 `user-service` / `message-service` / `awiki.info` 运行依赖；旧字段继续保留；`/anp-im/rpc` public surface 未扩大到 local-only inbox/history/sync/read-state/group management |
| Verification evidence | `PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 26 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-agent-compat-asgi` pass；隔离 Rust CLI 本地 Gate pass：`doctor` 仅保留预期 loopback ANP endpoint error，`id register` Alice/Bob pass，Alice -> Bob direct pass，Bob `msg inbox`/`msg history` pass，Pages create/get/update/list pass，`group join`/`msg send --group`/`group messages` pass，`group.create` exit 1 且返回 `service rpc error -32010: not_supported`；新增双实例本地跨域 Gate pass 并已纳入 pytest：`tests/test_cli_smoke.py::test_smoke_cross_domain_local_subprocess` pass，验证两个独立 Uvicorn 进程、service DID Ed25519 HTTP Signature、DID discovery、origin proof、签名 `/anp-im/rpc direct.send` 和双向 inbox delivery；新增 agent-registration/message-agent 最小兼容测试 pass |
| Next action | 公网 `rwiki.info` 切到本仓后继续 Step 09；先跑 `verify-public`，再跑与线上 `awiki.info` 用户双向 direct Gate |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `src/awiki_open_server/services.py`、`src/awiki_open_server/app/routes.py`、`tests/` |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | 本仓 pytest + CLI smoke pass；Rust CLI 本地 Gate pass；真实公网 Gate 仍按 Step 09 |

## 2. 目标

按用户目标继续补齐本仓可以自行修复的 User Service / Message Service 兼容缺口，让极简开源服务器更接近现有客户端和服务文档期望的服务形态。

验收标准：

- User Service 兼容：本仓提供公开 WNS handle 解析、DID 反查、旧 auth/token/ws ticket 小接口和 handle quota/my-handle 查询。
- Agent 兼容：本仓提供 `/user-service/agent-registration/rpc` 与 `/user-service/message-agent/rpc` 最小子集，支持本地一次性 token 和 message-agent binding 状态，不实现托管 runtime。
- Message Service 兼容：`sync.delta`、`sync.thread_after`、`read_state.mark_read`、attachment control-plane 返回相邻文档要求的关键字段，同时保留旧字段。
- Realtime 兼容：提供 `/im/ws` 基础 WebSocket 入口，可用本仓 ticket 认证并发送顶层 `sync` hint。
- 不新增群创建/管理、E2EE、federation、relay、生产短信/邮件或外部服务依赖。

## 3. 设计方法

- 只补协议形态和返回字段，不扩大 Community 功能范围。
- 所有兼容路由仍走本仓 SQLite、本仓 handler 和本仓 service DID 配置。
- 标准 ANP `{meta, body, client}` 请求与旧扁平参数并存，避免破坏已有 Rust CLI Gate。
- `read_state.mark_read` 增加 thread-local watermark 响应字段，但不把它当成 `sync.delta` checkpoint。
- attachment 控制面补 `upload_uri`、`upload_headers`、`object_uri`、`committed_at`、`download_uri` 等字段，同时保持现有 `upload_token`、`download_url` 兼容。

## 4. 实现方法

已完成：

1. 在 `awiki-open-server/src/awiki_open_server/services.py` 增加 `did_for_token`、WNS handle document helper、`get_my_handle`、`get_my_handles`、`get_quota` 和 dev `send_otp` 标准响应。
2. 在 `awiki-open-server/src/awiki_open_server/app/routes.py` 增加 `/user-service/content/rpc`、`/.well-known/handle/{local_part}`、`/.well-known/handle/by-did`、旧 auth/token/ws ticket REST 入口和 `/im/ws`。
3. 收敛 Message Service local-only 响应：`sync.delta` 输出 `owner_subject_id`、string `event_seq`、`has_more`、`snapshot_required`、`warnings`；`sync.thread_after` 接受标准 `thread` 并输出 `next_after_server_seq`；`read_state.mark_read` 输出 read watermark 和 ack 字段。
4. 补齐 attachment control-plane 标准字段，且继续拒绝 object-e2ee / direct-e2ee / group-e2ee 附件能力。
5. 在 `awiki-open-server/tests/` 增加覆盖公开 handle 解析、旧 auth/ws ticket、WebSocket、标准 sync/read-state 和 attachment 响应字段的测试。
6. 在 `awiki-open-server/src/awiki_open_server/shared/jsonrpc.py` 将同步 RPC handler 放入线程池执行，修复本地双实例跨域 direct 时源服务同步 HTTP 外发阻塞事件循环、导致对端回查源服务 DID document 超时的问题。
7. 在 `awiki-open-server/src/awiki_open_server/services.py` 修复跨域 direct 转发时改写已签名 `meta` 的问题；业务 `auth.origin_proof` 覆盖的 `meta/body` 必须原样转发，service DID 只通过 HTTP Signature header 表达。
8. 在 `awiki-open-server/scripts/awiki_open_cli.py` 增加 `smoke-cross-domain-local`，启动两个独立本仓服务实例验证真实服务间 DID discovery、HTTP Signature、origin proof 和双向 direct 投递。
9. 在 `awiki-open-server/src/awiki_open_server/storage/db.py`、`services.py` 和 `routes.py` 增加 `/user-service/agent-registration/rpc` 与 `/user-service/message-agent/rpc` 最小兼容：一次性 agent registration token、token 预检/兑换/撤销、message-agent binding ensure/get/list/disable/mark_seen/revoke。

## 5. 路径

已修改路径：

- `awiki-open-server/src/awiki_open_server/services.py`
- `awiki-open-server/src/awiki_open_server/app/routes.py`
- `awiki-open-server/src/awiki_open_server/app/settings.py`
- `awiki-open-server/src/awiki_open_server/shared/jsonrpc.py`
- `awiki-open-server/src/awiki_open_server/storage/db.py`
- `awiki-open-server/scripts/awiki_open_cli.py`
- `awiki-open-server/README.md`
- `awiki-open-server/tests/test_identity_pages.py`
- `awiki-open-server/tests/test_messaging_objects.py`
- `awiki-open-server/tests/test_health.py`
- `awiki-open-server/tests/test_cli_smoke.py`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/`

只读参考路径：

- `user-service/docs/api/did-auth.md`
- `user-service/docs/api/handle.md`
- `user-service/docs/api/did-profile.md`
- `message-service/docs/api/ANP-client-server-api-sync.md`
- `message-service/docs/api/ANP-client-server-api-read-state.md`
- `message-service/docs/api/ANP-client-server-api-attachment.md`
- `message-service/docs/api/ANP-client-server-api-direct.md`

禁止修改路径：

- `user-service/**`
- `message-service/**`
- `awiki-cli-rs2/**`
- `awiki-cli-rs2-release-0.1.61/**`
- `awiki-harness/**`
- 其他相邻仓库

## 6. 验证方式

本仓回归：

```bash
cd awiki-open-server
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step10-asgi
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-cross-domain-local-final --clean
```

已运行结果：

- compileall：pass。
- pytest：26 passed。
- ASGI smoke：`{"ok": true, "mode": "asgi", ...}`。
- 双实例本地跨域 Gate：pass，验证两个独立 Uvicorn 进程、独立 SQLite store、service DID document、Ed25519 HTTP Signature、开发 resolver 映射、origin proof 验签、签名 `/anp-im/rpc direct.send` 和双向 inbox delivery。
- pytest 子进程 Gate：`PYTHONPATH=src python3 -m pytest tests/test_cli_smoke.py::test_smoke_cross_domain_local_subprocess -q` pass，确保双实例本地跨域 Gate 纳入常规自动化回归。
- Agent 兼容：`PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py::test_agent_registration_and_message_agent_minimal_compat -q` pass，覆盖 token issue/verify/exchange/revoke 和 binding ensure/get/list/mark_seen/disable/revoke。
- 隔离 Rust CLI 本地 Gate：pass。
  - 服务：`AWIKI_PUBLIC_BASE_URL=http://127.0.0.1:8765`、`AWIKI_DID_DOMAIN=localhost`、`AWIKI_ALLOW_UNSIGNED_PEER_DEV=1`。
  - CLI：`HOME=/tmp/awiki-cli-home-step10`、`AWIKI_CLI_WORKSPACE_HOME_DIR=/tmp/awiki-cli-open-server-step10`、`/tmp/awiki-cli-rs2-release-open-server-target/debug/awiki-cli`。
  - `doctor`：命令返回 `ok: true`；唯一 blocking issue 是 `anp_service_endpoint must not use a loopback address`，这是本地 Gate 的预期限制，不影响本仓 User/Message 兼容验证。
  - `id register --handle step10alice1783049975 --phone 13800138000 --otp 123456`：pass。
  - `id register --handle step10bob1783049998 --phone 13800138000 --otp 123456`：pass。
  - `id use step10alice1783049975` + `msg send --to step10bob1783049998.localhost --text 'hello bob from step10 rerun'`：pass。
  - `id use step10bob1783049998` + `msg inbox` / `msg history --with step10alice1783049975.localhost`：pass，均返回该 direct 消息。
  - `page create/get/update/list --slug step10-rerun`：pass。
  - `group join --group did:wba:localhost:groups:open`、`msg send --group did:wba:localhost:groups:open`、`group messages --group did:wba:localhost:groups:open`：pass。
  - `group create --name 'Should Not Create'`：预期失败，exit 1，错误为 `service rpc error -32010: not_supported`。

仍需运行：

- Step 09 公网 Gate：`verify-public --base-url https://rwiki.info --did-domain rwiki.info` 通过后，再跑与 `awiki.info` 用户双向 direct/inbox/history。

## 7. Review 环节

Review 必须检查：

- 新增旧 auth/token/ws ticket 入口是否只使用本仓 dev token，不接生产短信/邮件或外部服务。
- Agent registration token 是否只保存 hash，token 原文只在 issue 响应返回一次；exchange 后状态为 used，revoke 后状态为 revoked。
- Message-agent binding 是否只是 Community 最小 binding 状态，不实现托管 runtime orchestration 或 delegated secret 管理。
- `/im/ws` 是否只提供基础 sync hint，不误宣称完整实时 fanout 已完成。
- 同步 JSON-RPC handler 在线程池运行后，是否避免阻塞事件循环，同时不破坏现有 handler 的 request/store 访问。
- 跨域 direct 出站是否原样转发 origin proof 覆盖的 `meta/body`，不能在转发前追加或改写已签名字段。
- `sync.delta` / `read_state.mark_read` 字段是否和 local-only 语义一致，不把 thread `server_seq` 当账号级 checkpoint。
- attachment control-plane 是否继续拒绝 object-e2ee 和 E2EE 附件控制面。
- `/anp-im/rpc` public handler 白名单是否仍未暴露 inbox/history/sync/read-state/group management。

## 8. 并行安全

- parallel-safe：否。
- 原因：该步骤修改共享 service handler、routes 和测试，影响 Rust CLI / Python smoke 的公共门禁。
- 合并策略：串行完成，先 pytest，再 ASGI smoke，再 Rust CLI 本地 Gate。

## 9. Blocker 判定

可以记录 blocker 的条件：

- 本仓 pytest、ASGI smoke、Rust CLI 本地 Gate 通过。
- `verify-public` 已通过，证明 `rwiki.info` 已由本仓服务发布 DID document 和 `/anp-im/rpc`。
- 真实 `awiki.info` 双向 direct 失败，且错误证据指向线上 `awiki.info` 或相邻 User Service / Message Service 的接受策略或协议实现差异。

不能记录 blocker 的情况：

- 本仓新增兼容路径测试失败。
- Rust CLI 本地 Gate 失败且原因是本仓响应缺字段或字段语义错误。
- `rwiki.info` 未路由到本仓，或 service DID document 不可验证。

## 10. 文档影响

本步骤只更新 `awiki-open-server` 计划和本仓实现。若后续发现相邻服务文档与真实线上行为不一致，只在本 Plan 中记录证据，等待用户确认是否修改相邻服务。
