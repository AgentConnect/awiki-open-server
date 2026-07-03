# Step 14：User Service Profile REST/RPC 与 Message Service health 兼容补齐

主 Plan：[../plan.md](../plan.md)  
Step index：14  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-with-pending-online-gate |
| Branch | main |
| Started | 2026-07-03 |
| Completed | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 |
| Commit | 未提交 |
| Review evidence | 已复核：旧 profile 入口均由本仓本地 profile 表实现，`user_id` 在 Community 版中等同 DID；`/im/healthz` 只复用本仓 health response，不代理外部 Message Service；`/anp-im/rpc` public 白名单未扩大；`delete_me` 保持 `not_supported` |
| Verification evidence | focused profile/health pytest 2 passed；compileall pass；全量 pytest 30 passed；ASGI smoke pass；双实例本地跨域 Gate pass；`verify-public https://rwiki.info` 仍 404，归属 Step 09 |
| Next action | 继续 Step 09 公网 Gate：待 `rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/services.py`、`awiki-open-server/src/awiki_open_server/app/routes.py`、`awiki-open-server/tests/`、`awiki-open-server/README.md`、`awiki-open-server/plan/...` |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | focused/full pytest + ASGI smoke + 双实例本地跨域 Gate；公网 Gate 仍归 Step 09 |
| Verification gate | pass/online-pending |

## 2. 目标

补齐本仓仍可自行实现的 User Service / Message Service 兼容缺口：

- User Service 旧 Profile 入口：`GET /me`、`PATCH /me`、`POST /me/rpc`、`GET /profiles/{user_id}`、`GET /user-service/profiles/{user_id}`、`GET /users/{user_id}/profile`、`GET /user-service/users/{user_id}/profile`。
- Message Service 健康检查别名：`GET /im/healthz`。
- 所有新增入口只使用本仓 SQLite profile / DID document / settings，不调用 `awiki.info`、`user-service` 或 `message-service`。

非目标：

- 不实现生产账号删除、组织/关系、搜索、算法邀请码注入、生产 Profile 托管。
- 不修改 `user-service/**`、`message-service/**`、`awiki-cli-rs2/**` 或 nginx/systemd。

## 3. 设计方法

- 旧 User Service `user_id` 在本仓 Community 版中等同 DID。
- `nick_name` / `avatar_url` / `bio` / `profile_url` 映射到现有 profile 字段 `display_name` / `avatar_uri` / `description` / `profile_uri`。
- `/me/rpc` 复用现有 profile handler，并增加 `user_id` 参数到 `did` 的兼容转换。
- REST Markdown 分发只返回公开 profile 内容和 DID/handle 信息，不注入算法邀请码。
- `/im/healthz` 复用本仓 health response，证明消息入口由本仓进程提供。

## 4. 实现方法

1. 在 `awiki-open-server/src/awiki_open_server/services.py` 增加 profile 兼容帮助函数：
   - `legacy_profile_view`
   - `legacy_public_profile`
   - `profile_markdown`
   - `update_me` 接受 `nick_name`、`avatar_url`、`bio`、`profile_url` 别名。
   - `public_profile` 接受 `user_id`。
2. 在 `awiki-open-server/src/awiki_open_server/app/routes.py` 增加：
   - `/im/healthz`
   - `/me`
   - `/me/rpc`
   - `/profiles/{user_id}`
   - `/user-service/profiles/{user_id}`
   - `/users/{user_id}/profile`
   - `/user-service/users/{user_id}/profile`
3. 在 `tests/test_health.py` 和 `tests/test_identity_pages.py` 增加 focused coverage。
4. 更新 `awiki-open-server/README.md` 的 API Surface 和兼容说明。
5. 更新主 Plan 台账、验证证据和变更记录。

## 5. 路径

可修改路径：

- `awiki-open-server/src/awiki_open_server/services.py`
- `awiki-open-server/src/awiki_open_server/app/routes.py`
- `awiki-open-server/tests/test_health.py`
- `awiki-open-server/tests/test_identity_pages.py`
- `awiki-open-server/README.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/`

禁止修改路径：

- `user-service/**`
- `message-service/**`
- `awiki-cli-rs2/**`
- `awiki-harness/**`
- 其他相邻仓库

## 6. 验证方式

Focused gate：

```bash
cd awiki-open-server
PYTHONPATH=src python3 -m pytest \
  tests/test_health.py::test_healthz \
  tests/test_identity_pages.py::test_legacy_me_profile_and_message_health_compat_routes -q
```

本仓回归：

```bash
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi \
  --data-dir /tmp/awiki-open-server-step14-asgi
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local \
  --data-root /tmp/awiki-open-server-step14-cross --clean
```

公网预检：

```bash
PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public \
  --base-url https://rwiki.info \
  --did-domain rwiki.info
```

预期：本步骤不要求公网 Gate 通过。若 `verify-public` 仍是 404，继续归 Step 09。

实际验证证据：

- `PYTHONPATH=src python3 -m pytest tests/test_health.py::test_healthz tests/test_identity_pages.py::test_legacy_me_profile_and_message_health_compat_routes -q`：2 passed。
- `PYTHONPATH=src python3 -m compileall -q src scripts tests`：pass。
- `PYTHONPATH=src python3 -m pytest tests -q`：30 passed。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step14-asgi-rerun`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step14-cross-rerun --clean`：pass，验证两个独立本仓实例、service DID Ed25519 HTTP Signature、DID discovery、origin proof、签名 `/anp-im/rpc direct.send` 和双向 inbox delivery。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info`：failed，`/.well-known/did.json`、`/healthz`、`/anp-im/rpc` 仍为 404；继续归属 Step 09 公网路由 blocker。

## 7. Review 环节

Review 必须检查：

- 新增 `/me` / profile 路由是否只读写本仓本地 profile 表。
- `PATCH /me` 是否只更新 Community profile 字段，不误删或创建外部账号状态。
- `delete_me` 若暴露为 JSON-RPC 必须保持 `not_supported` 或安全占位，不做不可恢复删除。
- `/im/healthz` 是否只是本仓 health 别名，不隐含外部 Message Service 存活。
- `/anp-im/rpc` public 白名单是否未扩大。
- 测试是否覆盖 REST、RPC、Markdown 和 health 形态。

Review 结果：

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | REST profile 路由最初未映射自定义异常到 HTTP 状态码 | 已补 `_http_error`，未认证 `/me` 返回 401，未知 profile Markdown 返回 404 |
| 已修复问题 | 补齐旧 profile REST/RPC、Markdown 分发和 `/im/healthz` | 不修改相邻服务 |
| 剩余风险 | 旧 profile 兼容只映射 Community 字段，不实现算法邀请码、生产账号删除或搜索 | `delete_me` 保持 `not_supported` |
| 新增或缺失测试 | 已新增 focused profile/health 测试；全量 pytest 通过 | 覆盖成功和基础错误路径 |
| 已更新或缺失文档 | README 和 Plan 已更新 | 无已知缺失 |

## 8. 并行安全

- parallel-safe：否。
- 原因：本步骤修改共享 routes、profile handlers、tests 和 Plan 台账，且依赖 Step 13 的 auth/token 兼容。
- 合并策略：串行实现、验证、Review 后回填主 Plan。

## 9. Blocker 判定

本步骤可在本仓内完成。以下不属于本步骤 blocker：

- `rwiki.info` 仍未路由到本仓。
- 线上 `awiki.info` 尚未完成双向互通验证。

只有在本仓已实现并通过本地门禁后，若真实 `awiki.info` 互通失败且证据指向相邻服务协议差异，才由 Step 09 记录 blocker 并等待用户确认是否修改相邻服务。

当前 blocker 归属：

- `rwiki.info` 未路由到本仓：`verify-public` 仍返回 service DID document、healthz 和 `/anp-im/rpc` 404，继续归 Step 09，不影响本步骤本地完成。

## 10. 文档影响

- 更新 `awiki-open-server/README.md`，说明旧 profile 路由由本仓本地兼容实现。
- 不修改 Harness 或相邻仓库文档；如后续发现跨仓库文档需要同步，记录到主 Plan 后续风险。
