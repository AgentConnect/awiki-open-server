# Step 19：ANP envelope meta 必填字段收敛

主 Plan：[../plan.md](../plan.md)  
Step index：19  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-with-pending-online-gate |
| Branch | main |
| Started | 2026-07-03 |
| Completed | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 |
| Commit | 未提交 |
| Review evidence | 已复核：ANP envelope meta 校验只对 `_anp_body` / `_anp_meta` 生效；direct/group 缺少 `sender_did`、`target`、`operation_id`、`message_id`、`content_type` 或 target kind/did 不一致会被拒绝；旧 flat text CLI 路径保持兼容；public `/anp-im/rpc` 白名单未扩大；未修改相邻仓库 |
| Verification evidence | focused pytest 1 passed；messaging tests 17 passed；compileall pass；全量 pytest 35 passed；ASGI smoke pass；双实例本地跨域 Gate pass；Rust CLI local Gate pass |
| Next action | 继续 Step 09：待 `rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct Gate |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/services.py`、`awiki-open-server/tests/test_messaging_objects.py`、`awiki-open-server/README.md`、`awiki-open-server/plan/...` |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | focused pytest + compileall + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate + Rust CLI local Gate |

## 2. 目标

对 `direct.send` 和 `group.send` 的 ANP envelope 请求补齐 Message Service meta 兼容约束：

- `meta.sender_did` 必须存在。
- `meta.target.kind` 和 `meta.target.did` 必须存在。
- `meta.operation_id`、`meta.message_id`、`meta.content_type` 必须存在。
- direct 的 target 必须是 `kind=agent` 且 `did=recipient_did`。
- group 的 target 必须是 `kind=group` 且 `did=group_did`。
- 旧 flat text CLI 路径继续兼容，不要求这些 meta 字段。

验收标准：

- 缺少必填 meta 字段的 ANP envelope 返回明确 JSON-RPC error，不生成 fallback id。
- target kind 或 did 与实际投递目标不一致时拒绝。
- 已有 Rust CLI 生成的 direct/group envelope 能继续通过。
- public `/anp-im/rpc` 暴露面不扩大，不实现 federation 或 relay。
- 不修改 `message-service/**`、`user-service/**`、`awiki-cli-rs2/**` 或其他相邻仓库。

## 3. 设计方法

- 只在请求包含 `_anp_body` 或 `_anp_meta` 时启用严格 meta 校验；本地旧式 `{"to": "...", "text": "..."}` 和 `{"group_did": "...", "text": "..."}` 不受影响。
- 校验发生在 `message_id` / `operation_id` fallback 生成之前，避免 envelope 请求绕过协议必填字段。
- target 一致性基于 normalize 后的 `recipient_did` 或 `group_did`，确保 body/flat extra 参数不能覆盖 meta target。
- `group.join` 不套用本步骤校验；它仍按 Step 11 的 proof/signature 规则处理。

## 4. 实现方法

1. 在 `awiki-open-server/src/awiki_open_server/services.py` 增加 ANP envelope 判定与 meta 校验 helper。
2. 在 `direct_send` 中对 envelope 请求校验 `agent` target 和 `recipient_did`。
3. 在 `group_send` 中对 envelope 请求校验 `group` target 和 `group_did`。
4. 在 `awiki-open-server/tests/test_messaging_objects.py` 增加 focused test：
   - direct 缺 `message_id` 被拒绝。
   - direct 缺 `content_type` 被拒绝。
   - direct target kind mismatch 被拒绝。
   - direct target did mismatch 被拒绝。
   - group 缺 `operation_id` 或 `content_type` 被拒绝。
   - group target did mismatch 被拒绝。
   - valid direct/group envelope 与旧 flat text 路径仍通过。
5. 回填本 Step 和主 Plan 的 Review / verification evidence。

## 5. 路径

可修改路径：

- `awiki-open-server/src/awiki_open_server/services.py`
- `awiki-open-server/tests/test_messaging_objects.py`
- `awiki-open-server/README.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/`

只读参考路径：

- `message-service/docs/api/ANP-client-server-api-direct.md`
- `message-service/docs/api/ANP-client-server-api-group.md`
- `awiki-cli-rs2/crates/im-core/src/internal/wire/direct.rs`
- `awiki-cli-rs2/crates/im-core/src/internal/wire/group.rs`

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
  tests/test_messaging_objects.py::test_anp_envelope_meta_required_fields_and_target_validation \
  -q
```

本仓回归：

```bash
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step19-asgi
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step19-cross --clean
```

Rust CLI 本地 Gate：

```bash
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local \
  --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli \
  --data-root /tmp/awiki-open-server-step19-rust-cli --clean
```

公网 Gate 不属于本步骤完成条件，仍由 Step 09 负责。

## 7. Review 环节

Review 必须检查：

- 严格 meta 校验只影响 ANP envelope，不破坏旧 flat text CLI 路径。
- 错误 envelope 不会落库，也不会生成 fallback `message_id` / `operation_id`。
- target kind/did mismatch 在 direct/group 两条路径都被拒绝。
- public `/anp-im/rpc` 白名单未扩大，仍不是 federation relay。
- 本步骤未修改相邻仓库。

Review 结果：

- 新增 `_is_anp_envelope`、`_require_meta_string` 和 `_validate_send_envelope_meta`，只在 ANP envelope 请求中收紧 meta 校验。
- `direct.send` envelope 必须携带 `meta.sender_did`、`meta.target.kind=agent`、`meta.target.did=recipient_did`、`meta.operation_id`、`meta.message_id`、`meta.content_type`。
- `group.send` envelope 必须携带 `meta.sender_did`、`meta.target.kind=group`、`meta.target.did=group_did`、`meta.operation_id`、`meta.message_id`、`meta.content_type`。
- 校验发生在 fallback `message_id` / `operation_id` 生成前，错误 envelope 不落库。
- 旧 flat text direct/group 路径不触发严格 meta 校验，Rust CLI local Gate 已通过。
- public `/anp-im/rpc` 白名单未扩大；本步骤未修改 `user-service/**`、`message-service/**`、`awiki-cli-rs2/**` 或其他相邻仓库。

验证结果：

- `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_anp_envelope_meta_required_fields_and_target_validation -q`：1 passed。
- `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q`：17 passed。
- `PYTHONPATH=src python3 -m compileall -q src scripts tests`：pass。
- `PYTHONPATH=src python3 -m pytest tests -q`：35 passed。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step19-asgi`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step19-cross --clean`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step19-rust-cli --clean`：pass。

## 8. 并行安全

- parallel-safe：否。
- 原因：本步骤修改共享 `direct.send`、`group.send` 和消息测试，影响核心 Message Service 兼容契约。
- 合并策略：串行实现、串行 Review、串行验证。

## 9. 文档影响

本步骤只更新 `awiki-open-server` 计划；如 README 缺少 envelope meta 说明，则同步补充。相邻服务文档仅作为只读协议依据，不在本目标内修改。

## 10. 风险与回滚

| 风险 | 缓解措施 | 回退方案 |
|---|---|---|
| 过严 meta 校验破坏旧 CLI | 只对 `_anp_body` / `_anp_meta` envelope 生效；Rust CLI Gate 回归 | 放宽 helper 判定或回退 helper 调用 |
| target mismatch 判断误伤正常 envelope | 使用 Message Service 和 Rust CLI wire 作为参考；focused 覆盖 direct/group valid path | 调整 expected target 来源 |
| public direct 入站错误顺序变化 | 只改变协议 shape 错误；proof/signature 校验仍在同一路径执行 | 根据线上错误证据调整错误顺序 |
