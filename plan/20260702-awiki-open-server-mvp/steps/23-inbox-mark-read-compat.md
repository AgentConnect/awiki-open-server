# Step 23：Inbox mark-read 兼容补齐

主 Plan：[../plan.md](../plan.md)  
Step index：23  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-with-pending-online-gate |
| Branch | 当前 worktree |
| Started | 2026-07-03 |
| Completed | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 |
| Commit | 未提交 |
| Review evidence | 已复核：`inbox.mark_read` 只更新当前 owner 的 `direct_message_views.read_at`，不可见 message id 不更新；默认 `inbox.get` 只返回未读，`include_read` 和 `direct.get_history` 投影准确 `is_read/read_at`；`read_state.mark_read` thread watermark 语义未改变；public `/anp-im/rpc` 白名单未扩大；未调用外部 User Service、Message Service 或 `awiki.info`；未修改相邻仓库 |
| Verification evidence | `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_inbox_mark_read_updates_owner_view_and_filters_default_inbox -q` 1 passed；`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q` 19 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 39 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step23-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step23-cross --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step23-rust-cli --clean` pass；`verify-public https://rwiki.info` 仍失败 404，归 Step 09 公网路由 |
| Next action | 回到 Step 09：待 `rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct Gate |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/services.py`, `awiki-open-server/tests/test_messaging_objects.py`, `awiki-open-server/README.md`, `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md` |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | focused pytest + messaging tests + compileall + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate + Rust CLI local Gate |

## 2. 目标

补齐 Message Service direct inbox 的旧 `inbox.mark_read` 兼容语义。当前本仓已有 `direct_message_views.read_at` 字段，但 handler 只是占位返回，`inbox.get` 也没有按默认未读语义过滤。

验收结果：

- `/im/rpc inbox.mark_read` 需要本地 Bearer 认证，只能标记当前 owner 可见的 direct message view。
- 成功后写入 `direct_message_views.read_at`，返回 `updated_count`、`message_ids`、`read_at`。
- 默认 `inbox.get` 只返回 `read_at IS NULL` 的 direct view；`include_read: true` 时返回全部可见消息。
- `inbox.get` 和 `direct.get_history` 的消息投影包含准确 `is_read` 与 `read_at`。
- 非 owner 或不可见 message id 不会更新别人的 view。
- public `/anp-im/rpc` 不暴露 `inbox.mark_read`，仍返回 `method_not_found`。

## 3. 设计方法

Message Service 文档把 `read_state.mark_read` 作为 thread watermark 主路径，同时保留 `inbox.mark_read(message_ids)` 作为 direct inbox 旧兼容路径。Community 版保留这两条语义分离：

- `read_state.mark_read` 继续只写 `thread_read_states`，不写未知 sync event。
- `inbox.mark_read` 只更新 direct inbox owner view 的 `read_at`，不修改消息正文、不删除历史、不跨用户标记。
- `inbox.get` 默认返回未读，避免旧客户端已读后重复看到 direct inbox 项；历史查询可通过 `direct.get_history` 或 `include_read` 查看。
- 不把 mark-read 暴露给 public peer endpoint，避免跨域服务变成本域状态管理入口。

## 4. 实现方法

1. 在 `awiki-open-server/src/awiki_open_server/services.py`：
   - 修改 `_direct_message_result(row, owner_did)`，当 row 含 `read_at` 时返回 `is_read = read_at is not None` 和 `read_at`。
   - 修改 `direct_history()` 查询，选择 `m.*` 与 `v.read_at AS read_at`。
   - 修改 `inbox_get()` 查询，默认增加 `v.read_at IS NULL`；当 `include_read` 为 true 时包含已读。
   - 新增 `inbox_mark_read(params, request)`，验证 `message_ids` list 或兼容单个 `message_id`，只更新 `owner_did = current_did` 的 view。
   - 将 `MESSAGE_HANDLERS["inbox.mark_read"]` 从 lambda 替换为真实 handler。
2. 在 `awiki-open-server/tests/test_messaging_objects.py`：
   - 新增 focused 测试覆盖 Bob 收件、mark-read、默认 inbox 为空、`include_read` 可见、history 可见已读状态。
   - 覆盖 Alice 无法标记 Bob-only view。
   - 覆盖 `/anp-im/rpc inbox.mark_read` 仍为 `method_not_found`。
3. 更新 `awiki-open-server/README.md`，说明 inbox 与 read-state 的边界。
4. 回填本 Plan 和本 Step 的 Review/验证证据。

实现结果：

- `_direct_message_result()` 现在投影 row 中的 `read_at`，并据此计算 `is_read`。
- `direct_history()` 查询 owner view 的 `read_at`，历史消息保留完整但能展示 owner 视角已读状态。
- `inbox_get()` 默认过滤 `v.read_at IS NULL`；`include_read: true` 可返回已读 direct view。
- `inbox_mark_read()` 替代占位 lambda，兼容 `message_ids` list 和单个 `message_id`，只更新当前 owner 可见 view。
- README 已说明 `inbox.mark_read` 与 `read_state.mark_read` 的边界。

## 5. 路径

可修改：

- `awiki-open-server/src/awiki_open_server/services.py`
- `awiki-open-server/tests/test_messaging_objects.py`
- `awiki-open-server/README.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/steps/23-inbox-mark-read-compat.md`

禁止修改：

- `user-service/**`
- `message-service/**`
- `awiki-cli-rs2/**`
- `awiki-harness/**`
- `awiki-open-server/AGENTS.md`

只读参考：

- `message-service/docs/api/ANP-client-server-api-direct.md`
- `message-service/docs/api/ANP-client-server-api-read-state.md`

## 6. 验证方式

运行：

```bash
PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_inbox_mark_read_updates_owner_view_and_filters_default_inbox -q
PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step23-asgi
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step23-cross --clean
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step23-rust-cli --clean
```

公网 `verify-public --base-url https://rwiki.info --did-domain rwiki.info` 仍归 Step 09。若复跑仍 404，记录为公网路由未切换，不把它当成本步骤失败。

本次证据：

- `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_inbox_mark_read_updates_owner_view_and_filters_default_inbox -q`：1 passed。
- `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q`：19 passed。
- `PYTHONPATH=src python3 -m compileall -q src scripts tests`：pass。
- `PYTHONPATH=src python3 -m pytest tests -q`：39 passed。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step23-asgi`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step23-cross --clean`：pass，验证两个独立本仓实例、DID discovery、service DID Ed25519 HTTP Signature、origin proof 和双向 inbox delivery。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step23-rust-cli --clean`：pass，验证现有 Rust CLI 注册、direct inbox/history、群参与、people、site flow。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info`：failed，`/.well-known/did.json`、`/healthz`、`/anp-im/rpc` 均 404；继续归 Step 09 公网路由。

## 7. Review 环节

Review 必须检查：

- `inbox.mark_read` 是否只更新当前 owner 的 direct view，不能标记其他用户视图。
- 默认 `inbox.get` 未读过滤是否符合 Message Service 文档，且 `include_read` 保留可诊断能力。
- `direct.get_history` 是否仍返回完整历史，但投影 owner 视角的 `is_read/read_at`。
- `read_state.mark_read` 语义未被混入 direct view 或 sync event。
- public `/anp-im/rpc` 白名单没有扩大，未引入 federation、relay 或远端 read-state ack。
- 现有 Rust CLI 本地 Gate 不因默认 inbox 未读过滤回归。

Review 结论：

- 通过。`inbox.mark_read` 不调用外部 User Service、Message Service 或 `awiki.info`。
- 通过。SQL 更新条件包含 `owner_did = current_did`，不可见 message id 返回 `updated_count = 0`。
- 通过。默认 inbox 只查未读，`include_read` 和 history 能投影已读状态。
- 通过。public `/anp-im/rpc` handler whitelist 未变，`inbox.mark_read` 仍 `method_not_found`。
- 剩余风险：公网 `rwiki.info` 尚未路由到本仓，真实 `awiki.info` 双向 Gate 仍待 Step 09。

## 8. 风险与回滚

| 风险 | 缓解措施 | 回滚 / 回退方案 |
|---|---|---|
| 旧客户端依赖 `inbox.get` 返回已读消息 | 提供 `include_read: true`；history 仍可返回完整线程 | 如发现现有 CLI 依赖旧行为，优先改 smoke 参数或兼容 CLI 调用，不回退 Message Service 默认未读语义 |
| 将 read-state watermark 和 inbox read view 混淆 | 两个 handler 分开实现，Step 11 的 no-sync-event 语义保持不变 | 回滚 `inbox_mark_read` 改动，不影响 `thread_read_states` |
| 非 owner message id 被误标记 | SQL `WHERE owner_did = ? AND message_id IN (...)` 并用测试覆盖 | 回滚 handler 并保留占位会丢兼容性，但不破坏数据 |
