# Step 24：Local view 参数语义兼容补齐

主 Plan：[../plan.md](../plan.md)  
Step index：24  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-with-pending-online-gate |
| Branch | 当前 worktree |
| Started | 2026-07-03 |
| Completed | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 |
| Commit | 未提交 |
| Review evidence | 已复核：`inbox.get`、`inbox.mark_read`、`direct.get_history` 均校验可选 `meta.sender_did` / `user_did` 与当前 token DID 一致；旧 flat 参数仍兼容；`inbox.get` 支持 `skip/limit`，`direct.get_history` 支持 `since_seq/since/skip/limit` 且 `since_seq` 优先；废弃 `group_did` history 路径返回明确错误；delegated local view 明确 `not_supported`；public `/anp-im/rpc` 白名单未扩大；未修改相邻仓库 |
| Verification evidence | `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_local_view_params_validate_owner_and_support_pagination -q` 1 passed；`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q` 20 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 40 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step24-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step24-cross --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step24-rust-cli --clean` pass；`verify-public https://rwiki.info` 仍失败 404，归 Step 09 公网路由 |
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

补齐 Message Service direct local view 方法的参数语义，让 `inbox.get`、`inbox.mark_read` 和 `direct.get_history` 更接近文档与现有 Rust CLI wire contract。

验收结果：

- `inbox.get`、`inbox.mark_read`、`direct.get_history` 在请求包含 `meta.sender_did` 时校验它与当前 token DID 一致。
- 请求包含 `user_did` 时校验它与当前 token DID 一致；旧 flat 参数未提供 `user_did` 时仍兼容。
- `direct.get_history` 支持 `since_seq` 优先于 `since`，支持 `skip`、`limit`，并拒绝非法负数/非数字。
- `inbox.get` 支持 `skip`、`limit`，limit 上限 100；默认仍只返回未读，`include_read` 可显示已读。
- `direct.get_history` 收到废弃 `group_did` 路径时返回明确 `direct.history_group_path_deprecated`，提示改用 `group.list_messages`。
- 不实现 delegated local view，不扩大 public `/anp-im/rpc` 暴露面。

## 3. 设计方法

本步骤只收敛本域 local-only 投影视图，不改变跨域 direct、service HTTP Signature、origin proof 或 sync/read-state watermark。

- `meta.sender_did` 与 `body.user_did` 是本地视图调用方身份字段；如果存在，必须等于 `current_did`。
- 旧 CLI / smoke 的 flat 参数仍允许，因为当前 open server 需要保持低成本兼容。
- 分页参数只影响本地查询，不进入任何 proof 或公网 endpoint。
- `direct.get_history(group_did=...)` 明确拒绝，避免客户端误用 direct history 读取群消息。

## 4. 实现方法

1. 在 `awiki-open-server/src/awiki_open_server/services.py`：
   - 增加 `_validate_local_view_owner(params, owner, prefix)`。
   - 增加 `_parse_non_negative_int()` 和 `_parse_limit()` helper。
   - `inbox_get()` 支持 `skip`、limit 上限和 `user_did/meta.sender_did` 校验。
   - `inbox_mark_read()` 增加同样 owner 校验，并要求 `message_ids` 非空。
   - `direct_history()` 支持 `since_seq/since`、`skip`、limit 上限，且对 `group_did` 返回 deprecated error。
2. 在 `awiki-open-server/tests/test_messaging_objects.py`：
   - 新增 focused 测试覆盖 local view owner mismatch、skip/since pagination、deprecated group history error、limit too large。
   - 确认旧 flat 路径仍可用。
3. 更新 `awiki-open-server/README.md` local view 说明。
4. 回填 Plan 和本 Step 证据。

实现结果：

- 新增 `_validate_local_view_owner()`，当请求包含 `meta.sender_did` 或 `user_did` 时校验当前 token DID。
- 新增 `_parse_non_negative_int()` 和 `_parse_local_view_limit()`，避免 `since_seq`、`skip`、`limit` 被静默忽略。
- `inbox_get()` 支持 `skip/limit`，保留默认未读过滤与 `include_read`。
- `inbox_mark_read()` 增加 owner 校验，并拒绝空 `message_ids`。
- `direct_history()` 支持 `since_seq/since/skip/limit`，`since_seq` 优先于 `since`；`group_did` 废弃路径返回 `direct.history_group_path_deprecated`。
- README 已同步 local view 参数边界。

## 5. 路径

可修改：

- `awiki-open-server/src/awiki_open_server/services.py`
- `awiki-open-server/tests/test_messaging_objects.py`
- `awiki-open-server/README.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/steps/24-local-view-params-compat.md`

禁止修改：

- `user-service/**`
- `message-service/**`
- `awiki-cli-rs2/**`
- `awiki-harness/**`
- `awiki-open-server/AGENTS.md`

只读参考：

- `message-service/docs/api/ANP-client-server-api-direct.md`
- `awiki-cli-rs2/crates/im-core/src/internal/wire/inbox.rs`
- `awiki-cli-rs2/crates/im-core/src/internal/wire/history.rs`

## 6. 验证方式

运行：

```bash
PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_local_view_params_validate_owner_and_support_pagination -q
PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step24-asgi
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step24-cross --clean
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step24-rust-cli --clean
```

公网 `verify-public --base-url https://rwiki.info --did-domain rwiki.info` 仍归 Step 09。

本次证据：

- `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_local_view_params_validate_owner_and_support_pagination -q`：1 passed。
- `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q`：20 passed。
- `PYTHONPATH=src python3 -m compileall -q src scripts tests`：pass。
- `PYTHONPATH=src python3 -m pytest tests -q`：40 passed。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step24-asgi`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step24-cross --clean`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step24-rust-cli --clean`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info`：failed，`/.well-known/did.json`、`/healthz`、`/anp-im/rpc` 均 404；继续归 Step 09 公网路由。

## 7. Review 环节

Review 必须检查：

- owner 校验只在 `meta.sender_did` / `user_did` 存在时收紧，不破坏旧 flat smoke。
- `since_seq` / `since` / `skip` / `limit` 不被静默忽略。
- `direct.get_history` 不继续接受废弃 `group_did` 路径。
- public `/anp-im/rpc` 白名单未变化。
- Rust CLI 本地 Gate 仍通过。

Review 结论：

- 通过。owner 校验只在请求字段存在时执行，旧 flat `peer_did/limit` 路径仍可用。
- 通过。`since_seq` 优先于 `since`，非法值返回明确 `direct.history_since_seq_invalid`。
- 通过。`group_did` direct history 路径返回 `direct.history_group_path_deprecated`，不会误读群历史。
- 通过。public `/anp-im/rpc` 白名单未扩大，local view 方法仍只在 `/im/rpc`。
- 剩余风险：delegated local view 未实现；当前按 Community MVP 返回 `not_supported`，如后续 Daemon 需要 delegated inbox/history 再单独规划。

## 8. 风险与回滚

| 风险 | 缓解措施 | 回滚 / 回退方案 |
|---|---|---|
| 现有旧客户端不传 `user_did` | 只在字段存在时校验，缺省走当前 token DID | 回滚 helper 校验，不影响底层 direct storage |
| limit 上限影响超大查询 | 按 Message Service 文档上限 100；CLI 默认 20 | 如需要管理导出，另开管理员接口 |
| since/skip 组合排序语义被误解 | history 按 ASC，inbox 按 DESC；测试覆盖可观察结果 | 如客户端需要 cursor token，另开协议步骤 |
