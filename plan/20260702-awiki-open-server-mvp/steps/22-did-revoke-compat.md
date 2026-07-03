# Step 22：DID revoke 兼容补齐

主 Plan：[../plan.md](../plan.md)  
Step index：22  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-with-pending-online-gate |
| Branch | 当前 worktree |
| Started | 2026-07-03 |
| Completed | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 |
| Commit | 未提交 |
| Review evidence | 已复核：DID revoke 由本仓 SQLite `users.revoked_at` 与 `did_documents.status/revoked_at` 实现；`did_for_token()` 不再允许 DID 字符串绕过 active 状态；token verify、DID verify、WS ticket、`get_me`、`update_document` 和 DID path 解析均拒绝 revoked DID；公开 Handle discovery 不再返回 revoked DID；public `/anp-im/rpc` 白名单未扩大；`replace_did` / `recover_handle` 仍为 `not_supported`；未调用外部 User Service、Message Service 或 `awiki.info`；未修改相邻仓库 |
| Verification evidence | `PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py::test_did_auth_revoke_marks_did_inactive_and_blocks_auth_paths -q` 1 passed；`PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py -q` 12 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 38 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step22-asgi-final` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step22-cross-final --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step22-rust-cli-final --clean` pass；`verify-public --base-url https://rwiki.info --did-domain rwiki.info` 仍失败 404，归 Step 09 公网路由 |
| Next action | 回到 Step 09：待 `rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct Gate |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/storage/db.py`, `awiki-open-server/src/awiki_open_server/services.py`, `awiki-open-server/src/awiki_open_server/app/routes.py`, `awiki-open-server/tests/test_identity_pages.py`, `awiki-open-server/README.md`, `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md` |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | focused pytest + compileall + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate + Rust CLI local Gate |

## 2. 目标

补齐 User Service DID Auth 的 `revoke` 最小兼容面。调用方用当前 DID token 调用 `/did-auth/rpc` 或 `/user-service/did-auth/rpc` 的 `revoke` 后，该 DID 在本仓标记为 revoked，后续不能再作为 active DID 完成认证。

验收结果：

- `revoke` 需要 Bearer token，成功返回 `ok: true`、`revoked: true`、`status: "revoked"`、`did` 和 `revoked_at`。
- 撤销状态持久化在本仓 SQLite；既有数据库通过幂等 schema migration 获得 `revoked_at/status` 字段。
- 撤销后 `verify`、`verify_http_request`、`get_me`、`update_document`、REST token verify、session verify、WS ticket verify、DID verify `login/refresh` 都拒绝该 DID。
- DID 字符串不能再作为 token 直通绕过 revoked 状态；只有本仓 active DID 才能通过。
- 被撤销 DID 的 DID document 不再作为 active document 从 DID path 解析返回；本仓可保留历史 row 和 profile 数据，不做物理删除。
- `replace_did` 和 `recover_handle` 仍返回 `not_supported`，不把本步骤扩展成恢复/换绑流程。

## 3. 设计方法

`user-service/docs/api/did-auth.md` 对 `revoke` 的核心语义是：撤销当前 DID，将 DID 文档状态设置为 `revoked`，撤销后该 DID 无法用于认证。Community 版不实现生产级 JWT、handle recovery 或 replacement，因此本步骤采用本仓最小闭环：

- 在 `users` 增加 `revoked_at`，在 `did_documents` 增加 `status` 与 `revoked_at`。
- `did_for_token()` 只返回 active 本地 DID；token 是 DID 字符串时也必须命中本仓 active user/document。
- `revoke()` 使用当前 active DID 认证后，原子写入 `users.revoked_at` 和 `did_documents.status='revoked'`。
- Profile、消息、附件历史数据保留，避免撤销身份时破坏审计和已有消息视图。
- 公开跨域消息入口继续只接受目标本地 active recipient；不新增 federation、relay 或恢复能力。

## 4. 实现方法

1. 在 `awiki-open-server/src/awiki_open_server/storage/db.py`：
   - `users` 增加 `revoked_at TEXT`。
   - `did_documents` 增加 `status TEXT NOT NULL DEFAULT 'active'` 和 `revoked_at TEXT`。
   - `init()` 通过 `ensure_column` 支持已有 SQLite 数据迁移。
2. 在 `awiki-open-server/src/awiki_open_server/services.py`：
   - 增加 `_active_did_row()` / `_is_active_did()` 等小 helper。
   - 修改 `did_for_token()`，只接受 active 本地 DID；DID 字符串直通也必须验证 active。
   - `register()` 写入 active DID document。
   - `update_document()` 只允许 active DID，更新时保持 `status='active'`。
   - `resolve_profile()`、DID path 解析相关查询只返回 active document；公开 profile 可保留但其 DID document 应为空或不作为 active endpoint。
   - 新增 `revoke()` handler，替换 `IDENTITY_HANDLERS["revoke"]` 占位。
   - `_user_exists()` 改为只认 active 本地用户，避免 revoked recipient/sender 继续参与本域消息。
   - `_did_verify_user_row()` 过滤 revoked DID，使 `did-verify login/refresh` 失败。
3. 在 `awiki-open-server/src/awiki_open_server/app/routes.py`：
   - token verify、WS ticket、auth routes 继续通过修改后的 `did_for_token()` 自动拒绝 revoked DID。
   - DID path document 查询加 active filter。
4. 在 `awiki-open-server/tests/test_identity_pages.py` 增加 focused 测试：
   - 注册 DID，验证 token 入口正常。
   - 调用 `revoke` 成功。
   - 撤销后 `verify`、`get_me`、`update_document`、REST token verify、WS ticket verify、DID verify `login/refresh` 均失败。
   - DID path document 对 revoked DID 返回 404。
   - `recover_handle` 仍 `not_supported`。
5. 更新 `README.md` DID/Auth 说明，标明 Community 版支持本地 DID revoke，但不支持 replace/recover 生产流程。

## 5. 路径

可修改：

- `awiki-open-server/src/awiki_open_server/storage/db.py`
- `awiki-open-server/src/awiki_open_server/services.py`
- `awiki-open-server/src/awiki_open_server/app/routes.py`
- `awiki-open-server/tests/test_identity_pages.py`
- `awiki-open-server/README.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/steps/22-did-revoke-compat.md`

禁止修改：

- `user-service/**`
- `message-service/**`
- `awiki-cli-rs2/**`
- `awiki-harness/**`
- `awiki-open-server/AGENTS.md`

只读参考：

- `user-service/docs/api/did-auth.md`
- `user-service/docs/database-design.md`
- `user-service/SPEC.md`

## 6. 验证方式

运行：

```bash
PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py::test_did_auth_revoke_marks_did_inactive_and_blocks_auth_paths -q
PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py -q
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step22-asgi
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step22-cross --clean
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step22-rust-cli --clean
```

公网 `verify-public --base-url https://rwiki.info --did-domain rwiki.info` 仍归 Step 09。若复跑仍 404，记录为公网路由未切换，不把它当成本步骤失败。

## 7. Review 环节

Review 必须检查：

- `revoke` 不调用外部 User Service、`awiki.info` 或相邻服务。
- `did_for_token()` 不再让 DID 字符串绕过 active/revoked 状态。
- 所有 auth_request、token verify、WS ticket、DID verify refresh/login 都通过统一 active DID 检查。
- 撤销后 DID document 不再从 active DID path 发布，避免远端把 revoked DID 当可用身份。
- 历史消息、profile 和对象数据没有被物理删除；撤销只影响认证和 active DID 发现。
- public `/anp-im/rpc` 白名单没有变化，未引入 federation、relay 或恢复/换绑能力。
- 现有 Rust CLI 注册、direct、group、site 本地 Gate 不回归。

## 8. 风险与回滚

| 风险 | 缓解措施 | 回滚 / 回退方案 |
|---|---|---|
| DID 字符串 token 直通被收紧后影响旧调试脚本 | 测试和 README 明确 Community token 应使用注册返回 token；DID 字符串也必须是本仓 active DID | 如确有旧脚本依赖，可增加显式 dev-only 开关，但默认保持 active 检查 |
| public profile 对 revoked DID 的展示语义不清 | 本步骤只保证认证和 DID document active 解析被拒绝；profile 数据可保留用于历史展示 | 若客户端要求 hidden/revoked profile，后续另开资料状态步骤 |
| `_user_exists()` 收紧为 active 用户影响历史消息查询 | 历史查询走 view 表和 current active owner；已撤销用户不能认证查看，符合 revoke 目标 | 如需管理员审计导出，另开管理接口，不在 Community MVP 中隐式支持 |
| SQLite schema 迁移影响既有本地数据 | 使用 `ensure_column` 幂等迁移，默认旧数据为 active | 回滚代码时额外列可保留，不影响旧查询 |
