# Step 26：Group local view 参数与 sync 权限收敛

主 Plan：[../plan.md](../plan.md)  
Step index：26  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-with-pending-online-gate |
| Branch | 当前 worktree |
| Started | 2026-07-03 |
| Completed | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 |
| Commit | 未提交 |
| Review evidence | 已复核：`group.list/list_members/list_messages` 校验可选 `meta.sender_did` / `user_did` 与当前 token DID 一致；`group.list_members` 和 `group.list_messages` 校验 `meta.target.kind=group` 与 target DID；`group.list_messages` 支持 `since_seq/since_event_seq/skip/limit` 并返回 cursor/page 字段；`sync.thread_after` group 分支先校验成员身份，非成员返回 `group.not_member`；旧 flat 调用保持兼容；public `/anp-im/rpc` 白名单未扩大；未修改相邻仓库 |
| Verification evidence | `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_group_participant_local_views_require_membership tests/test_messaging_objects.py::test_group_local_views_support_anp_params_and_pagination -q` 2 passed；`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q` 22 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 42 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step26-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step26-cross --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step26-rust-cli --clean` pass；`verify-public https://rwiki.info` 仍失败 404，归 Step 09 公网路由 |
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

补齐 Message Service / Rust CLI group local view 参数契约，并关闭 `sync.thread_after` 的群消息权限绕过路径。

验收结果：

- `group.list` 校验可选 `meta.sender_did` / `user_did` 与当前 token DID 一致，并支持 `limit`。
- `group.list_members` 校验可选 owner 字段和 `meta.target` group DID，一直要求当前 DID 是群成员，并支持 `limit`。
- `group.list_messages` 校验可选 owner 字段和 `meta.target` group DID，支持 `since_seq` / `since_event_seq`、`skip`、`limit`，返回 `next_since_seq`、`next_server_seq`、`total`、`has_more`。
- `sync.thread_after` 的 group thread 必须要求当前 DID 是群成员；非成员返回 `group.not_member`，不能绕过 `group.list_messages` 的成员限制。
- 旧 flat CLI 调用继续兼容；public `/anp-im/rpc` 白名单不扩大。

## 3. 设计方法

`message-service` 将 `group.list_messages` 定义为 local-only 群消息视图，Rust CLI 通过 `params.meta/body` 发送 `anp.group.local.v1` 请求，并使用 `since_seq` cursor。Community 版虽然不支持群创建/管理，但必须让已加入成员的本地群视图、sync repair 和 CLI 历史读取行为一致。

本步骤不引入 Group Host 管理、跨域群托管、群 E2EE 或公开成员目录，只收敛本仓已有群参与子集的只读参数和权限。

## 4. 实现方法

1. 在 `awiki-open-server/src/awiki_open_server/services.py`：
   - 增加 group local view owner/target 校验 helper，复用 direct local view 的 `meta.sender_did` 和 `user_did` 语义。
   - `group_list()` 支持 ANP envelope 展开后的 `limit`，并校验 owner。
   - `group_members()` 校验 owner、`meta.target.kind=group` 和 target DID，保留成员权限校验并支持 `limit`。
   - `group_messages()` 支持 `since_seq` / `since_event_seq`、`skip`、`limit` 和 page cursor 字段，保留成员权限校验。
   - `thread_after()` group 分支在查询消息前调用 `_require_group_member()`，并使用 `_group_message_result()` 投影返回消息。
2. 在 `awiki-open-server/tests/test_messaging_objects.py`：
   - 扩展 Step 25 focused 测试，覆盖非成员无法通过 `sync.thread_after` 读取群消息。
   - 新增 focused 测试覆盖 group local view ANP 参数、分页、owner mismatch、target mismatch、invalid since 和 limit 上限。
3. 更新 `awiki-open-server/README.md` 与主 Plan 证据。

实现结果：

- 新增 group local view owner/target 校验，复用 direct local view 的 `meta.sender_did` / `user_did` 语义。
- `group.list()` 支持 ANP envelope 展开后的 `limit` 并校验 owner。
- `group.list_members()` 校验 owner、`meta.target.kind=group` 和 target DID，保留成员权限校验并支持 `limit`。
- `group.list_messages()` 支持 `since_seq` / `since_event_seq`、`skip`、`limit`，返回 `next_since_seq`、`next_server_seq`、过滤后 `total` 和准确 `has_more`。
- `sync.thread_after()` 的 group 分支在查询前校验当前 DID 是群成员，并使用 group message projection 返回消息。
- README 已同步 group local view 参数和 `sync.thread_after` 权限边界。

## 5. 路径

可修改：

- `awiki-open-server/src/awiki_open_server/services.py`
- `awiki-open-server/tests/test_messaging_objects.py`
- `awiki-open-server/README.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/steps/26-group-local-view-sync-compat.md`

禁止修改：

- `user-service/**`
- `message-service/**`
- `awiki-cli-rs2/**`
- `awiki-harness/**`
- `awiki-open-server/AGENTS.md`

只读参考：

- `message-service/docs/api/ANP-client-server-api-group.md`
- `message-service/crates/im-group/src/handlers.rs`
- `message-service/crates/im-sync/src/lib.rs`
- `awiki-cli-rs2/crates/im-core/src/internal/wire/group.rs`

## 6. 验证方式

运行：

```bash
PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_group_participant_local_views_require_membership tests/test_messaging_objects.py::test_group_local_views_support_anp_params_and_pagination -q
PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step26-asgi
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step26-cross --clean
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step26-rust-cli --clean
```

公网 `verify-public --base-url https://rwiki.info --did-domain rwiki.info` 仍归 Step 09。

本次证据：

- `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_group_participant_local_views_require_membership tests/test_messaging_objects.py::test_group_local_views_support_anp_params_and_pagination -q`：2 passed。
- `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q`：22 passed。
- `PYTHONPATH=src python3 -m compileall -q src scripts tests`：pass。
- `PYTHONPATH=src python3 -m pytest tests -q`：42 passed。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step26-asgi`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step26-cross --clean`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step26-rust-cli --clean`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info`：failed，`/.well-known/did.json`、`/healthz`、`/anp-im/rpc` 均 404；继续归 Step 09 公网路由。

## 7. Review 环节

Review 必须检查：

- `sync.thread_after` group 分支不能读取非成员群消息。
- `group.list_messages` 的 `since_seq` / `skip` / `limit` 语义与 Message Service / Rust CLI wire 一致。
- owner mismatch、target mismatch 和 limit 上限错误明确且不影响旧 flat 调用。
- public `/anp-im/rpc` 白名单未扩大。
- 群创建/管理仍 `not_supported`。
- Rust CLI 本地 Gate 仍通过。

Review 结论：

- 通过。`sync.thread_after` group 分支现在不能读取非成员群消息，非成员返回 `group.not_member`。
- 通过。`group.list_messages` 的 `since_seq` / `since_event_seq`、`skip`、`limit`、`next_since_seq`、`total`、`has_more` 与 Message Service / Rust CLI local view 语义对齐。
- 通过。owner mismatch、target mismatch 和 limit 上限都有明确错误；旧 flat `group_did` 调用仍可用。
- 通过。public `/anp-im/rpc` 白名单未扩大，群创建/管理仍 `not_supported`。
- 剩余风险：公网 `rwiki.info` 尚未路由到本仓，真实 `awiki.info` 双向 Gate 仍待 Step 09。

## 8. 风险与回滚

| 风险 | 缓解措施 | 回滚 / 回退方案 |
|---|---|---|
| 离群用户无法通过 `sync.thread_after` 拉取旧群历史 | Community 边界选择成员可见历史；离群后历史保留策略需要单独产品决策 | 如需离群后保留历史，另开步骤引入 membership tombstone / retention policy，不复用当前 active member 校验 |
| `group.list_messages` page 字段影响旧调用方 | 保留原 `messages/total/has_more/source` 字段，只追加 cursor 字段；旧 flat `group_did` 调用仍有效 | 如旧客户端依赖旧 `total=len(page)`，可在客户端侧忽略；服务端保留 total 表示过滤后总数以对齐 Message Service |
| limit 上限拒绝超大请求 | 与 Message Service 的 1..100 上限一致，避免一次读取过多本地消息 | 如 CLI 需要更大批量，应通过 cursor 分页，不扩大单页上限 |
