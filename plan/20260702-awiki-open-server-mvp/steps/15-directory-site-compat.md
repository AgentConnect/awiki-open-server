# Step 15：Directory / Site 兼容面补齐

主 Plan：[../plan.md](../plan.md)  
Step index：15  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-with-pending-online-gate |
| Branch | main |
| Started | 2026-07-03 |
| Completed | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 |
| Commit | 未提交 |
| Review evidence | 已检查：DID relationship、phone bind、site RPC 均由本仓本地 SQLite / handler 实现，不代理外部 `awiki.info`、`user-service` 或 `message-service`；DID relationship 只允许本域本地用户；`/site/rpc` 只管理 `AWIKI_DID_DOMAIN` 的 raw Markdown 页面，不扩展为生产 tenant hosting |
| Verification evidence | focused directory/site pytest 1 passed；compileall pass；全量 pytest 31 passed；ASGI smoke pass；双实例本地跨域 Gate pass；`verify-public https://rwiki.info` 仍 404，归属 Step 09 |
| Next action | 继续 Step 09 公网 Gate：待 `rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/storage/db.py`、`awiki-open-server/src/awiki_open_server/services.py`、`awiki-open-server/src/awiki_open_server/app/routes.py`、`awiki-open-server/tests/`、`awiki-open-server/README.md`、`awiki-open-server/plan/...` |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | focused pytest + 全量 pytest + smoke Gate |

## 2. 目标

补齐现有 Rust CLI 和 User Service 文档暴露出的三个本仓可自行修复的兼容缺口：

- DID relationships：`/did/relationships/rpc` 与 `/user-service/did/relationships/rpc`。
- phone bind dev 兼容：`/auth/phone-bind-send`、`/user-service/auth/phone-bind-send`、`/auth/phone-bind-verify`、`/user-service/auth/phone-bind-verify`。
- Tenant Site Pages 轻量兼容：`/site/rpc`、`GET /`、`GET /pages/{slug}.md`。

本步骤仍只修改 `awiki-open-server`。`user-service`、`message-service`、`awiki-cli-rs2` 只作为只读协议参考。

## 3. 设计方法

- DID relationship 按 User Service DID relationship 语义实现本域用户关注、取消关注、关注列表、粉丝列表和状态查询；`user_id` 在 Community server 中继续映射为 DID。
- phone bind 使用 dev provider 和默认 OTP `123456`，只做本地认证兼容，不承诺生产短信或手机号唯一性治理。
- `/site/rpc` 只支持本服务配置的 `AWIKI_DID_DOMAIN`，存储裸域名 Markdown root/page；这不是生产 tenant hosting，也不支持跨域 site 管理。
- 公网 `rwiki.info` 路由和真实 `awiki.info` 双向互通仍归 Step 09，不用本步骤的本地验证替代。

## 4. 实现方法

1. 在 SQLite schema 中新增 `did_relationships` 和 `site_pages`。
2. 在 `services.py` 中增加 DID relationship handlers、site page handlers、公开 site Markdown helper。
3. 在 `routes.py` 中挂载新增 RPC、REST 和 phone bind dev 路由。
4. 在测试中覆盖：
   - follow/unfollow/status/followers/following。
   - 外域 DID follow 被拒绝、自关注被拒绝。
   - phone bind send/verify 使用 `123456`。
   - site root 懒创建、set root、page CRUD、公开 Markdown、外域 site 管理拒绝。
5. 更新 README 和主 Plan，明确这些是本仓本地实现，不是外部服务转发。

## 5. 路径

可修改：

- `awiki-open-server/src/awiki_open_server/storage/db.py`
- `awiki-open-server/src/awiki_open_server/services.py`
- `awiki-open-server/src/awiki_open_server/app/routes.py`
- `awiki-open-server/tests/test_identity_pages.py`
- `awiki-open-server/README.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/steps/15-directory-site-compat.md`

禁止修改：

- `user-service/**`
- `message-service/**`
- `awiki-cli-rs2/**`
- `awiki-harness/**`
- nginx/systemd 真实配置

## 6. 验证方式

必跑：

```bash
PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py::test_did_relationship_phone_bind_and_site_rpc_compat -q
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step15-asgi
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step15-cross --clean
```

可选公网预检：

```bash
PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info
```

当前预期：如果 `rwiki.info` 尚未路由到本仓，该命令继续 404，仍归 Step 09。

已运行证据：

- `PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py::test_did_relationship_phone_bind_and_site_rpc_compat -q`：1 passed。
- `PYTHONPATH=src python3 -m compileall -q src scripts tests`：pass。
- `PYTHONPATH=src python3 -m pytest tests -q`：31 passed。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step15-asgi`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step15-cross --clean`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info`：failed，`/.well-known/did.json`、`/healthz`、`/anp-im/rpc` 仍为 404；继续归属 Step 09 公网路由 blocker。

## 7. Review 环节

Review 重点：

- 新增路由是否全部由本仓本地 SQLite / handler 实现，没有转发到外部 User Service、Message Service 或 `awiki.info`。
- DID relationship 是否只允许本域本地用户，避免变成跨域社交图或 relay。
- `/site/rpc` 是否只管理本服务 DID domain，避免误承诺生产 tenant hosting。
- phone bind 是否清楚标记为 dev provider，不泄露真实短信能力承诺。
- 新增 `GET /` 是否不遮挡 DID document、content、object、well-known 等已有路由。
- README 和主 Plan 是否同步说明新增能力和非目标。

Review 结论：

- 新增 relationship、phone bind、site RPC 均在 `awiki-open-server/src/awiki_open_server/services.py` 和 `awiki-open-server/src/awiki_open_server/app/routes.py` 本地处理，不调用外部服务。
- `DID_RELATIONSHIP_HANDLERS` 只允许 `target_did` 属于 `AWIKI_DID_DOMAIN` 且在本地 `users` 表存在；自关注、外域关注都被拒绝。
- phone bind 只返回 dev provider 和默认 OTP `123456`，不写入生产手机号状态，不承诺真实短信。
- `/site/rpc` 只允许当前 `AWIKI_DID_DOMAIN`，公开 `GET /` 和 `GET /pages/{slug}.md` 返回 raw Markdown；README 已写明不是生产 tenant hosting。
- 新增 `GET /` 不遮挡 `/.well-known`、`/content`、`/objects`、`/dids/resolve` 或 `/{sub_path}/did.json` 等既有路由。

## 8. 风险与回滚

| 风险 | 缓解措施 | 回滚 / 回退方案 |
|---|---|---|
| `/site/rpc` 被误解为完整 tenant hosting | README 和 Plan 明确只是本域 Markdown 兼容面 | 删除 `/site/rpc` 与 `site_pages` 使用面，保留 `/content/rpc` |
| DID relationship 接受外域 DID 造成边界扩大 | 实现中校验 `target_did` domain 等于 `AWIKI_DID_DOMAIN` 且本地存在 | 回退 relationship handlers |
| phone bind 被误用为生产认证 | 返回 `provider=dev` 和 `dev_otp=123456`，文档写明非生产 | 后续接入真实 provider 前保持 dev-only |
| 新增 schema 影响旧数据 | 使用 `CREATE TABLE IF NOT EXISTS` | 删除未使用表或保留空表 |
