# Step 18：Message payload 与 daemon heartbeat 兼容收敛

主 Plan：[../plan.md](../plan.md)  
Step index：18  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-with-pending-online-gate |
| Branch | main |
| Started | 2026-07-03 |
| Completed | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 |
| Commit | 未提交 |
| Review evidence | 已复核：direct/group 只在 ANP envelope 或显式非文本 content type 下做严格 body shape 绑定，旧 flat text CLI 路径保持兼容；`application/json` 和附件 manifest 使用 `body.payload` JSON object 并通过新 `content_type` 列持久化；daemon heartbeat no-store 只匹配精确 liveness payload；非 heartbeat agent status 仍持久化；未修改相邻仓库，public `/anp-im/rpc` 白名单未扩大 |
| Verification evidence | focused pytest 1 passed；messaging tests 16 passed；compileall pass；全量 pytest 34 passed；ASGI smoke pass；双实例本地跨域 Gate pass；Rust CLI local Gate pass |
| Next action | 继续 Step 09：待 `rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct Gate |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/services.py`、`awiki-open-server/tests/test_messaging_objects.py`、`awiki-open-server/README.md`、`awiki-open-server/plan/...` |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | focused pytest + compileall + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate |

## 2. 目标

补齐本仓仍缺的 Message Service 兼容语义：

- `direct.send` 与 `group.send` 在 ANP envelope 或显式非文本 content type 下，按 `meta.content_type` 严格绑定 `body` 字段。
- `application/json` 和 `application/anp-attachment-manifest+json` 必须使用 `body.payload` JSON object。
- 其他非文本 content type 必须使用 `body.payload_b64u` 非空字符串。
- 精确识别 daemon liveness heartbeat，并返回 `delivery_state = "ephemeral"`，不写入 `direct_messages`、`direct_message_views`、`sync_events` 或 sender-side history。
- 其他有业务意义的 `awiki.agent.status.v1` 状态消息仍然持久化。

验收标准：

- 本仓仍支持旧 Rust CLI 的 flat 文本 direct/group 调用。
- `application/json + body.payload` 在 direct/group history 中原样保留对象，不转字符串。
- 错误 body shape 返回 JSON-RPC error，不落库。
- daemon heartbeat no-store 只对 Message Service 文档列出的精确 liveness payload 生效。
- 不修改 `message-service/**`、`user-service/**`、`awiki-cli-rs2/**` 或其他相邻仓库。

## 3. 设计方法

- 以 `message-service/docs/api/ANP-client-server-api-direct.md` 和 `message-service/docs/api/ANP-client-server-api-group.md` 为协议参考。
- 对本仓历史 flat 文本调用保持兼容：未使用 ANP envelope 且未显式声明非文本 content type 时，继续把 `text` 包成 `text/plain`。
- 对 ANP envelope 请求使用 `_anp_body` 原始 body 校验并保存，避免破坏 `auth.origin_proof` 摘要。
- heartbeat no-store 仅在本地 direct 或入站 public direct 的收件人属于本仓时生效；远端出站仍要求对端返回 durable acceptance，不把 `ephemeral` 当作普通跨域 direct 成功。

## 4. 实现方法

1. 在 `awiki-open-server/src/awiki_open_server/services.py` 增加 message body 校验 helper：
   - `text/plain`：要求 `text` 存在且不能混入 `payload` / `payload_b64u`。
   - `application/json` / `application/anp-attachment-manifest+json`：要求 `payload` 是 JSON object。
   - 其他非文本：要求 `payload_b64u` 是非空字符串。
2. 在 `direct_send` 和 `group_send` 中调用 helper；local flat 文本路径保持现有行为。
3. 增加 `_is_daemon_heartbeat` 和 `_accept_ephemeral_direct`，对精确 heartbeat 只发布在线 realtime notification，不写入 SQLite 持久表。
4. 在 `awiki-open-server/tests/test_messaging_objects.py` 增加 focused test：
   - direct JSON payload 保留 `payload` 对象。
   - group JSON payload 保留 `payload` 对象。
   - direct/group 错误 JSON body shape 被拒绝。
   - daemon heartbeat 返回 `ephemeral` 且不出现在 inbox/history/sync。
   - `status_scope=run` 等非 heartbeat agent status 仍持久化。
5. 如 README 的兼容说明缺少该语义，同步补充。
6. 回填主 Plan 与本 Step 的 Review / verification evidence。

## 5. 路径

可修改路径：

- `awiki-open-server/src/awiki_open_server/services.py`
- `awiki-open-server/tests/test_messaging_objects.py`
- `awiki-open-server/README.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/`

只读参考路径：

- `message-service/docs/api/ANP-client-server-api-direct.md`
- `message-service/docs/api/ANP-client-server-api-group.md`
- `awiki-cli-rs2/crates/awiki-deamon/src/agent_status.rs`
- `awiki-cli-rs2/crates/awiki-deamon/src/app_bridge/message_control.rs`
- `awiki-cli-rs2/crates/awiki-deamon/src/commands/mod.rs`
- `awiki-cli-rs2/crates/im-core/src/internal/local_state/messages.rs`

禁止修改路径：

- `user-service/**`
- `message-service/**`
- `awiki-cli-rs2/**`
- `awiki-harness/**`
- 其他相邻仓库

## 6. 验证方式

Focused tests：

```bash
cd awiki-open-server
PYTHONPATH=src python3 -m pytest \
  tests/test_messaging_objects.py::test_application_json_payload_shape_and_daemon_heartbeat_no_store \
  -q
```

本仓回归：

```bash
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step18-asgi
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step18-cross --clean
```

可选 Rust CLI 本地 Gate：

```bash
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local \
  --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli \
  --data-root /tmp/awiki-open-server-step18-rust-cli --clean
```

公网 Gate 不属于本步骤完成条件，仍由 Step 09 负责。

## 7. Review 环节

Review 必须检查：

- `application/json + body.payload` 未被转换成字符串或旧 `text` 字段。
- `text/plain`、JSON、attachment manifest、二进制扩展的 body shape 校验不会破坏旧 flat 文本 CLI 调用。
- daemon heartbeat 不写入历史、inbox、sync；但仍可在收件人在线时发送 `direct.incoming`。
- 非 heartbeat `awiki.agent.status.v1` 仍写库，避免丢失 command/status/final 业务消息。
- public `/anp-im/rpc` 白名单不扩大，跨域 direct 仍不是 federation relay。
- 本步骤未修改相邻仓库。

Review 结果：

- `direct.send` 和 `group.send` 已增加 body shape 校验；ANP envelope 或显式非文本 content type 会拒绝不匹配字段。
- 旧 flat 文本调用仍生成 `text/plain` 文本消息，现有 Rust CLI local Gate 通过。
- `direct_messages` 和 `group_messages` 新增幂等 `content_type` 列，历史、inbox、sync/thread 输出可正确投影 `application/json`。
- daemon heartbeat no-store 只识别精确 `schema=awiki.agent.status.v1`、`status_scope=daemon`、`message=daemon heartbeat`、`content_type=application/json` 的 liveness payload。
- heartbeat 返回 `delivery_state=ephemeral`，不写 `direct_messages`、`direct_message_views` 或 `sync_events`；非 heartbeat `status_scope=run` 仍持久化。
- 未修改 `message-service/**`、`user-service/**`、`awiki-cli-rs2/**`；相邻仓库仅作为只读协议参考。

验证结果：

- `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_application_json_payload_shape_and_daemon_heartbeat_no_store -q`：1 passed。
- `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q`：16 passed。
- `PYTHONPATH=src python3 -m compileall -q src scripts tests`：pass。
- `PYTHONPATH=src python3 -m pytest tests -q`：34 passed。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step18-asgi`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step18-cross --clean`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step18-rust-cli --clean`：pass。

## 8. 并行安全

- parallel-safe：否。
- 原因：本步骤修改共享 `direct.send`、`group.send` 和消息测试，影响核心 Message Service 兼容契约。
- 合并策略：串行实现、串行 Review、串行验证。

## 9. 文档影响

本步骤只更新 `awiki-open-server` 计划和 README。相邻服务文档仅作为只读协议依据，不在本目标内修改。

## 10. 风险与回滚

| 风险 | 缓解措施 | 回退方案 |
|---|---|---|
| 过严 body shape 破坏旧 CLI flat 文本发送 | 严格校验只对 ANP envelope 或显式非文本 content type 生效；focused 和 Rust CLI Gate 回归 | 回退 helper 调用或放宽 flat 文本路径 |
| heartbeat no-store 被客户端当成通用 no-store | 只识别精确 daemon liveness payload；README/Plan 说明边界 | 回退 `_is_daemon_heartbeat` 分支，恢复持久化 |
| no-store 导致重要 agent status 丢失 | `status_scope != daemon` 或 message 不等于 `daemon heartbeat` 的状态仍持久化，并有测试覆盖 | 扩大测试覆盖后再调整识别条件 |
