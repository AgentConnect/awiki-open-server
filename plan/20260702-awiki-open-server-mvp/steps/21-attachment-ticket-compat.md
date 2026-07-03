# Step 21：Attachment ticket ANP 兼容补齐

主 Plan：[../plan.md](../plan.md)  
Step index：21  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-with-pending-online-gate |
| Branch | 当前 worktree |
| Started | 2026-07-03 |
| Completed | 2026-07-03 15:43 CST 本仓门禁完成；公网 Gate 仍待 Step 09 |
| Commit | 未提交 |
| Review evidence | 已复核：`attachment.get_download_ticket` 的 ANP 请求/响应兼容由本仓本地 SQLite 和 handler 实现；保留本地 owner `object_id/object_uri` 路径；public `/anp-im/rpc` 白名单没有扩大，upload/commit/abort 仍不公开；不调用外部 Message Service、`awiki.info` 或远端 object service；不实现跨域上传代理、完整 `attachment_access_grants`、E2EE 授权或远端 object relay；未修改相邻仓库 |
| Verification evidence | `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_attachment_roundtrip tests/test_messaging_objects.py::test_attachment_download_ticket_accepts_anp_body_shape -q` 2 passed；`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q` 18 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 37 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step21-asgi-rerun` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step21-cross-rerun --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step21-rust-cli-rerun --clean` pass |
| Next action | 继续 Step 09：待 `rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct Gate |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/storage/db.py`, `awiki-open-server/src/awiki_open_server/services.py`, `awiki-open-server/src/awiki_open_server/app/routes.py`, `awiki-open-server/tests/test_messaging_objects.py`, `awiki-open-server/README.md`, `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md` |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | focused pytest + compileall + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate + Rust CLI local Gate |

## 2. 目标

补齐 Message Service 附件下载票据的最小兼容面，让本仓 `attachment.get_download_ticket` 能接受 ANP envelope 中的 `body.object_uri`、`attachment_id`、`sender_did`、`requester_did`、`message_id`、`message_security_profile`、`message_target_did` 或 `group_did`，并返回 Message Service 期望的 `download_ticket_b64u` 和 `ticket_binding`。

验收结果：

- 保留现有本地 `object_id + Bearer owner` ticket 路径，不破坏现有 Rust CLI 本地 Gate。
- ANP direct ticket 请求要求 `message_id`、`message_security_profile` 和 `message_target_did`，且 `message_target_did == requester_did`。
- ANP group ticket 请求要求 `message_id`、`message_security_profile` 和 `group_did`，且 requester 必须仍是本仓该群 active member。
- 对本仓本地 committed object，`object_uri`/`attachment_id` 必须匹配本仓持久化对象元数据；不匹配返回 JSON-RPC error。
- 响应同时包含旧字段 `ticket/download_uri/download_url` 和新字段 `download_ticket_b64u/ticket_binding`。
- `GET /objects/{object_id}` 同时接受旧 `?ticket=` 和 Message Service 文档要求的 `Authorization: Bearer <download_ticket>`。
- 不实现跨域附件上传 delegation、完整 `attachment_access_grants`、Direct/Group E2EE 附件授权或 object key 管理。

## 3. 设计方法

`message-service/docs/api/ANP-client-server-api-attachment.md` 将 `attachment.get_download_ticket` 建模为 attachment control-plane 方法，ticket issuer 根据 persisted object/grant 和 requester context 发票据。本仓 Community 版没有完整 grant 表，也不做 E2EE，因此本步骤采用保守兼容：

- 在 `attachment_slots` / `attachment_objects` 中保存 `attachment_id` 与 `object_uri`，作为本地对象权威绑定。
- 本地 owner 仍可用旧 `object_id` 调用获取票据。
- ANP direct 请求只允许对象 owner 或 message target requester 获取本仓对象票据；group 请求只允许已加入该群的本地成员获取票据。
- 仅对本仓对象签发本仓 download ticket，不代理远端对象，不上传或转存远端附件。

## 4. 实现方法

1. 在 `awiki-open-server/src/awiki_open_server/storage/db.py` 为 `attachment_slots` 增加 `attachment_id/object_uri`，为 `attachment_objects` 增加 `source_attachment_id/object_uri`，并通过 `ensure_column` 支持既有 SQLite 迁移。
2. 在 `attachment_create_slot` 写入 `attachment_id/object_uri`。
3. 在 `attachment_commit` 将 slot 的 `attachment_id/object_uri` 持久化到 object row，并返回规范 `digest`。
4. 重写 `attachment_ticket` 的参数归一与校验：
   - 支持 `object_id` 或 `object_uri` 定位本仓对象。
   - 支持 ANP envelope 归一后的 `_anp_body`/`_anp_meta`。
   - 校验 direct/group ticket context。
   - 生成 ticket 后返回兼容字段和 `ticket_binding`。
5. 在 `awiki-open-server/src/awiki_open_server/app/routes.py` 让 `GET /objects/{object_id}` 支持 Bearer download ticket。
6. 增加 focused pytest 覆盖 ANP direct/group ticket、binding mismatch、非成员 group requester、本地旧路径回归和 Bearer 下载。
7. 更新 `README.md` 附件说明，标明 Community 版 ticket 兼容范围和非目标。

## 5. 路径

可修改：

- `awiki-open-server/src/awiki_open_server/storage/db.py`
- `awiki-open-server/src/awiki_open_server/services.py`
- `awiki-open-server/src/awiki_open_server/app/routes.py`
- `awiki-open-server/tests/test_messaging_objects.py`
- `awiki-open-server/README.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/steps/21-attachment-ticket-compat.md`

禁止修改：

- `user-service/**`
- `message-service/**`
- `awiki-cli-rs2/**`
- `awiki-harness/**`
- `awiki-open-server/AGENTS.md`

只读参考：

- `message-service/docs/api/ANP-client-server-api-attachment.md`
- `message-service/docs/api/ANP-client-server-api-attachment-schema-examples.md`
- `message-service/crates/im-attachment/src/handlers.rs`
- `message-service/crates/im-storage/migrations/202604090001_p7_v050_attachment_alignment.sql`

## 6. 验证方式

运行：

```bash
PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_attachment_download_ticket_accepts_anp_body_shape -q
PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_attachment_roundtrip -q
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step21-asgi
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step21-cross --clean
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step21-rust-cli --clean
```

公网 `verify-public --base-url https://rwiki.info --did-domain rwiki.info` 仍归 Step 09。若复跑仍 404，记录为公网路由未切换，不把它当成本步骤失败。

## 7. Review 环节

Review 必须检查：

- `attachment.get_download_ticket` 没有调用外部 `message-service`、`awiki.info` 或远端 object service。
- public `/anp-im/rpc` 白名单没有新增 upload/commit/abort 或 inbox/history/sync。
- `object_uri` 与 `attachment_id` mismatch 会被拒绝，避免给错误对象签票据。
- Bearer download ticket 与 query ticket 使用同一张本仓 `download_tickets` 表，不引入外部 object service。
- direct request 的 `requester_did` 与 `message_target_did` 关系正确；group request 要求本地 active member。
- E2EE 和完整 grant collector 仍是非目标，未通过字段名误导为已支持。
- 现有本地 owner `object_id` ticket 路径和 Rust CLI 本地 Gate 不回归。

## 8. 风险与回滚

| 风险 | 缓解措施 | 回滚 / 回退方案 |
|---|---|---|
| Community 兼容被误解为完整 Message Service grant model | README 和 Plan 标明仅做本地 committed object 与成员/owner 最小授权，不实现完整 `attachment_access_grants` | 回滚 Step 21 代码和文档，保留旧 owner-only ticket |
| 新增 SQLite 列影响既有本地数据 | 使用 `ensure_column` 幂等迁移；旧对象缺少 `object_uri/source_attachment_id` 时由 `object_id` fallback | 回滚新增列使用逻辑，SQLite 额外列可保留不影响旧代码 |
| group ticket 放宽为任意用户可拿 | 测试覆盖非成员拒绝；只对本仓 group membership 通过者签票据 | 回滚 group branch 或改为 `not_supported` |
| public route 被滥用为跨域 object relay | 仅对本仓已提交 object 签本仓 ticket，不代理远端 `object_uri` | 保持 `/anp-im/rpc` 白名单不变，并拒绝非本仓对象 |
