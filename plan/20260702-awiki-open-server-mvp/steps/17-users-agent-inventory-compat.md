# Step 17：Users RPC 与 Agent Inventory 兼容补齐

主 Plan：[../plan.md](../plan.md)  
Step index：17  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-with-pending-online-gate |
| Branch | main |
| Started | 2026-07-03 |
| Completed | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 |
| Commit | 未提交 |
| Review evidence | 已复核：`/users/rpc`、`/user-service/users/rpc`、`/user-service/agent-inventory/rpc` 均由本仓本地 SQLite/profile/binding/status 表实现；未引入外部 User Service / Message Service / `awiki.info` 运行依赖；agent inventory 只做 daemon 兼容最小状态、controller scope、sender check、authorization、archive/policy 字段，不实现商业托管 runtime；public `/anp-im/rpc` 白名单未扩大 |
| Verification evidence | focused pytest 2 passed；compileall pass；全量 pytest 33 passed；ASGI smoke pass；双实例本地跨域 Gate pass；Rust CLI local Gate pass；`verify-public https://rwiki.info` 仍 404，归属 Step 09 |
| Next action | 继续 Step 09：待 `rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct Gate |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `src/awiki_open_server/services.py`、`src/awiki_open_server/app/routes.py`、`src/awiki_open_server/storage/db.py`、`tests/test_identity_pages.py` |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | focused pytest + compileall + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate |

## 2. 目标

补齐本仓仍缺的 User Service 兼容面：

- `/users/rpc` 和 `/user-service/users/rpc`：支持 `get_me`、`get_by_did`、`get_by_dids`、`get_by_handle`。
- `/user-service/agent-inventory/rpc`：支持 `awiki-cli-rs2` daemon 实际调用的 `update_latest_status`、`sync_controller_scope`、`verify_controller_sender`、`authorize_agent_invocation`、`archive_agent`，并提供 `list_agents`、`update_display_name`、`get_invocation_policy`、`update_invocation_policy`、`unbind_agent` 的 Community 最小形态。

验收标准：

- 所有新增路由都由本仓 SQLite / profile / binding 数据本地实现。
- `/users/rpc` 返回 User Service `UserProfile` 兼容字段，包括 `did`、`user_name`、`nick_name`、`display_name`、`avatar_uri`、`bio`、`description`、`subject_type`、`tags`、`profile_md`、`profile_uri`、`created_at`、`handle`、`handle_domain`。
- agent inventory 响应满足 `awiki-cli-rs2/crates/awiki-deamon/src/registration/mod.rs` 的字段解析要求。
- 不实现商业托管 runtime、delegated secret、完整策略引擎、生产级 agent governance。
- 不修改 `user-service/**`、`message-service/**`、`awiki-cli-rs2/**` 或其他相邻仓库。

## 3. 设计方法

- Users RPC 复用 `profiles`、`users` 和现有 `_split_handle` / profile view 逻辑，避免新增账号模型。
- Agent inventory 以 `message_agent_bindings` 作为 controller/daemon/runtime agent 的最小事实源；必要时新增轻量 status 表保存 daemon latest status。
- DID-auth 在 Community 版中保持宽松兼容：Bearer token 可认证本地 DID，daemon DID 可用 DID 字符串作为 dev token；不做生产 HTTP Signature 鉴权扩展。
- 授权模型最小化：仅允许 controller DID 或本地已知 sender；不提供完整商业 invocation policy。

## 4. 实现方法

1. 在 `awiki-open-server/src/awiki_open_server/storage/db.py` 增加最小 agent inventory 状态表，用于 `update_latest_status` 和 `list_agents`。
2. 在 `awiki-open-server/src/awiki_open_server/services.py` 增加：
   - `USERS_HANDLERS`
   - `/users/rpc` profile 投影 helper
   - `AGENT_INVENTORY_HANDLERS`
   - controller scope、sender verification、invocation authorization、archive/status/list/policy 最小 handler
3. 在 `awiki-open-server/src/awiki_open_server/app/routes.py` 挂载：
   - `POST /users/rpc`
   - `POST /user-service/users/rpc`
   - `POST /user-service/agent-inventory/rpc`
4. 在 `awiki-open-server/tests/test_identity_pages.py` 添加 focused tests：
   - `/users/rpc` 四个方法和错误行为。
   - agent inventory daemon 方法和 CLI 解析所需字段。
5. 如 README 的 API surface 缺少新增路由，同步 `awiki-open-server/README.md`。
6. 回填主 Plan 与本 Step 的 Review / verification evidence。

## 5. 路径

可修改路径：

- `awiki-open-server/src/awiki_open_server/storage/db.py`
- `awiki-open-server/src/awiki_open_server/services.py`
- `awiki-open-server/src/awiki_open_server/app/routes.py`
- `awiki-open-server/tests/test_identity_pages.py`
- `awiki-open-server/README.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/`

只读参考路径：

- `user-service/docs/api/users.md`
- `user-service/src/user_service/app/users/rpc_handlers.py`
- `user-service/src/user_service/app/agent_inventory/rpc_handlers.py`
- `awiki-cli-rs2/crates/awiki-deamon/src/registration/mod.rs`

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
  tests/test_identity_pages.py::test_users_rpc_compat_routes \
  tests/test_identity_pages.py::test_agent_inventory_minimal_compat_routes \
  -q
```

本仓回归：

```bash
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step17-asgi
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step17-cross --clean
```

可选 Rust CLI 本地 Gate：

```bash
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local \
  --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli \
  --data-root /tmp/awiki-open-server-step17-rust-cli --clean
```

公网 Gate 不属于本步骤完成条件，仍由 Step 09 负责。

## 7. Review 环节

Review 必须检查：

- `/users/rpc` 字段与 User Service 文档兼容，且不泄露本地 token。
- agent inventory 返回字段满足 `awiki-cli-rs2` daemon 解析，不把缺失业务误报为完整商业 runtime。
- `/user-service/agent-inventory/rpc` 不调用外部 `user-service`，不依赖 `awiki.info`。
- archive/unbind/update policy 只改变本仓最小状态，不影响 direct/group/site 行为。
- 新增表迁移幂等，旧 SQLite 数据可启动。
- public `/anp-im/rpc` 白名单不扩大。

Review 结果：

- `/users/rpc` 使用本仓 `profiles`/`users` 表投影 User Service `UserProfile` 字段，不返回 token。
- `/user-service/agent-inventory/rpc` 使用本仓 `message_agent_bindings` 和 `agent_inventory_statuses` 表，满足 `awiki-cli-rs2` daemon 解析字段。
- 新增路由均是本仓 dispatch；没有外部 User Service / Message Service / `awiki.info` 后端、proxy、fallback。
- Community 边界已在 README 和 Plan 中说明：agent inventory 不是完整商业托管 runtime。
- `public_handlers` 未新增 local-only 方法，`/anp-im/rpc` 暴露面不变。

验证结果：

- `PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py::test_users_rpc_compat_routes tests/test_identity_pages.py::test_agent_inventory_minimal_compat_routes -q`：2 passed。
- `PYTHONPATH=src python3 -m compileall -q src scripts tests`：pass。
- `PYTHONPATH=src python3 -m pytest tests -q`：33 passed。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step17-asgi-final`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step17-cross-final --clean`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step17-rust-cli --clean`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info`：failed，`/.well-known/did.json`、`/healthz`、`/anp-im/rpc` 均为 404；继续归属 Step 09 公网路由 blocker。

## 8. 并行安全

- parallel-safe：否。
- 原因：本步骤修改共享服务 handler、schema、routes 和 identity tests，和现有兼容面共享同一 SQLite schema 与 JSON-RPC error shape。
- 合并策略：串行实现、串行 Review、串行验证。

## 9. 文档影响

本步骤只更新 `awiki-open-server` 计划和 README。相邻服务文档如需同步，只记录为后续事项，不在本目标内修改。

## 10. 风险与回滚

| 风险 | 缓解措施 | 回退方案 |
|---|---|---|
| agent inventory 最小实现被误解为商业托管 runtime | README 和 Plan 明确 Community 边界 | 保留接口，能力声明为 minimal/local |
| DID-auth dev 兼容过宽 | 仅用于 Community/local interop；生产 Gate 仍依赖 service DID proof | 后续单独加严 auth，不影响本步骤路由形态 |
| 新 schema 影响旧数据 | `CREATE TABLE IF NOT EXISTS` 幂等迁移 | 回滚新增表和 handlers，保留旧表不动 |
