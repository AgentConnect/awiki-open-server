# Step 25：Group participant 成员权限收敛

主 Plan：[../plan.md](../plan.md)  
Step index：25  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-with-pending-online-gate |
| Branch | 当前 worktree |
| Started | 2026-07-03 |
| Completed | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 |
| Commit | 未提交 |
| Review evidence | 已复核：`group.list_members` / `group.list_messages` 现在要求当前 DID 是群成员，非成员返回 `group.not_member`；`group.leave` 删除前先校验成员身份，非成员不写 sync event、不推 realtime；`group.get_info` 保留公开最小信息以支持 open-join discovery；`group.send` 既有成员校验不回归；群创建/管理仍 `not_supported`；public `/anp-im/rpc` 白名单未扩大 |
| Verification evidence | `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_group_participant_local_views_require_membership -q` 1 passed；`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q` 21 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 41 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step25-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step25-cross --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step25-rust-cli --clean` pass；`verify-public https://rwiki.info` 仍失败 404，归 Step 09 公网路由 |
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

收紧 Community 群参与子集的成员权限。本仓支持加入已有群、退出群、查看群成员/消息和发送群消息，但这些 local-only 读写操作应以当前 DID 是群成员为前提。

验收结果：

- `group.list_members` 要求当前 DID 已加入群，否则返回 `group.not_member`。
- `group.list_messages` 要求当前 DID 已加入群，否则返回 `group.not_member`。
- `group.leave` 要求当前 DID 是成员；非成员调用不删除、不写 sync event、不推 realtime，返回 `group.not_member`。
- `group.list` 继续只列当前 DID 已加入群。
- `group.get_info` 继续返回已有群公开最小信息，不暴露成员列表。
- 群创建/管理方法继续 `not_supported`；public `/anp-im/rpc` 白名单不扩大。

## 3. 设计方法

Community 版不实现 Group Host 管理，但“群参与”仍需要最小权限边界：

- local group view 是本域成员视图，不是公开目录。
- 发送群消息已有成员校验，本步骤把成员/消息读取和离群动作收敛到同一边界。
- `group.get_info` 保留公开可发现能力，用于 open-join 前读取基础资料。
- 不引入 owner/admin/role 管理、不新增群创建/加人/踢人。

## 4. 实现方法

1. 在 `awiki-open-server/src/awiki_open_server/services.py`：
   - 增加 `_require_group_member(conn, group_did, member_did)` helper。
   - `group_leave()` 删除前先校验 group 存在和当前 DID 是成员；非成员直接 `Unauthorized("group.not_member")`。
   - `group_members()` / `group_messages()` 查询前校验当前 DID 是成员。
   - 保持 `group_get_info()` 不要求成员。
2. 在 `awiki-open-server/tests/test_messaging_objects.py`：
   - 新增 focused 测试：未加入的 Bob 无法 list_members/list_messages/leave；Alice 加入并发消息后可读；Bob 加入后可读；Alice leave 后不能再读或发。
3. 更新 `awiki-open-server/README.md` 群参与说明。
4. 回填 Plan 和本 Step 证据。

实现结果：

- 新增 `_require_group_member(conn, group_did, member_did)`，统一检查群存在和当前成员身份。
- `group.list_members()` / `group.list_messages()` 查询前要求当前 DID 是群成员。
- `group.leave()` 删除前要求当前 DID 是群成员，非成员不会写 sync event 或 realtime notification。
- `group.get_info()` 保留公开最小信息，仍可用于 open-join 前 discovery。
- README 已同步群参与成员权限边界。

## 5. 路径

可修改：

- `awiki-open-server/src/awiki_open_server/services.py`
- `awiki-open-server/tests/test_messaging_objects.py`
- `awiki-open-server/README.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/steps/25-group-participant-membership-compat.md`

禁止修改：

- `user-service/**`
- `message-service/**`
- `awiki-cli-rs2/**`
- `awiki-harness/**`
- `awiki-open-server/AGENTS.md`

只读参考：

- `message-service/docs/api/ANP-client-server-api-group.md`

## 6. 验证方式

运行：

```bash
PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_group_participant_local_views_require_membership -q
PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step25-asgi
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step25-cross --clean
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step25-rust-cli --clean
```

公网 `verify-public --base-url https://rwiki.info --did-domain rwiki.info` 仍归 Step 09。

本次证据：

- `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_group_participant_local_views_require_membership -q`：1 passed。
- `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q`：21 passed。
- `PYTHONPATH=src python3 -m compileall -q src scripts tests`：pass。
- `PYTHONPATH=src python3 -m pytest tests -q`：41 passed。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step25-asgi`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step25-cross --clean`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step25-rust-cli --clean`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info`：failed，`/.well-known/did.json`、`/healthz`、`/anp-im/rpc` 均 404；继续归 Step 09 公网路由。

## 7. Review 环节

Review 必须检查：

- `group.list_members` / `group.list_messages` 不向非成员泄露成员列表或消息历史。
- `group.leave` 对非成员不产生 sync/realtime 副作用。
- `group.get_info` 仍可用于 open-join discovery，不要求登录成员。
- `group.send` 既有成员校验不回归。
- 群管理方法仍 `not_supported`。
- Rust CLI 本地 Gate 仍通过。

Review 结论：

- 通过。非成员不能调用 `group.list_members` / `group.list_messages` 读取成员列表或历史消息。
- 通过。非成员 `group.leave` 在删除前失败，不会制造离群 sync/realtime 副作用。
- 通过。`group.get_info` 仍不要求成员，用于 open-join discovery。
- 通过。群创建/管理方法仍 `not_supported`，没有扩大 Community 能力边界。
- 剩余风险：公网 `rwiki.info` 尚未路由到本仓，真实 `awiki.info` 双向 Gate 仍待 Step 09。

## 8. 风险与回滚

| 风险 | 缓解措施 | 回滚 / 回退方案 |
|---|---|---|
| 旧客户端未 join 直接 list_messages | 这是权限缺口，要求客户端先 `group.join`；现有 smoke 已如此操作 | 如需公开群预览，另开 `group.preview_messages` 或策略字段，不复用成员历史接口 |
| `group.leave` 非成员从幂等变成错误 | 明确返回 `group.not_member`，避免伪造离群事件 | 如 CLI 依赖幂等 leave，可只在 CLI 命令层处理错误，不改服务端事件语义 |
