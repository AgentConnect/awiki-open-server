# Step 20：DID Verify JSON-RPC 兼容补齐

主 Plan：[../plan.md](../plan.md)  
Step index：20  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-with-pending-online-gate |
| Branch | 当前 worktree |
| Started | 2026-07-03 |
| Completed | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 |
| Commit | 未提交 |
| Review evidence | 已复核：`/did-verify/rpc` 与 `/user-service/did-verify/rpc` 均由本仓本地 handler 实现；`send_code` 不调用外部消息服务；`login` 只接受本仓已注册 DID 和 DID verify dev code；`refresh` 只接受本仓本地 token；DID verify 默认 `666666` 与 SMS/Handle dev OTP `123456` 边界已在 README 说明；public `/anp-im/rpc` 白名单未扩大；未修改相邻仓库 |
| Verification evidence | `PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py::test_did_verify_rpc_compat_routes -q` 1 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 36 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step20-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step20-cross --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step20-rust-cli --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info` failed，service DID document 404、healthz 404、`anp.get_capabilities` 404，继续归 Step 09 公网路由 |
| Next action | 继续 Step 09：待 `rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct Gate |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/services.py`, `awiki-open-server/src/awiki_open_server/app/routes.py`, `awiki-open-server/tests/test_identity_pages.py`, `awiki-open-server/README.md` |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | focused pytest + compileall + 全量 pytest + ASGI smoke + Rust CLI local Gate |

## 2. 目标

补齐 User Service 公开 DID 验证码登录 JSON-RPC 面：`POST /did-verify/rpc`，并提供 `/user-service/did-verify/rpc` 兼容别名。该步骤只在 `awiki-open-server` 内实现，不调用线上 `awiki.info`、相邻 `user-service` 或 `message-service`。

验收结果：

- `send_code` 接受 `did`，在 Community dev provider 下返回固定验证码提示，不发送外部短信、邮件或消息。
- `login` 接受本仓已注册 DID 和默认 DID verify dev code，返回 `access_token`、`refresh_token`、`expires_in`、`token_type`、`did`、`user_id`。
- `refresh` 接受本仓 token 作为 refresh token，返回同形态 token 响应。
- 未注册 DID、错误验证码、无效 refresh token 返回 JSON-RPC error，不自动创建外域用户，不把 `awiki.info` 当身份源。

## 3. 设计方法

User Service 文档 `user-service/docs/api/did-verify.md` 定义 `send_code`、`login`、`refresh`。开源版保持接口形态，但用本仓 SQLite 的 `users` / `did_documents` 作为本地真相源。DID verify 的 dev bypass code 使用 User Service 默认 `DEV_BYPASS_CODE=666666`；现有 SMS/Handle dev OTP `123456` 保持不变，避免改变已通过 CLI 注册流。

## 4. 实现方法

1. 在 `awiki-open-server/src/awiki_open_server/app/settings.py` 增加 DID verify dev code 配置，默认从 `AWIKI_DID_VERIFY_DEV_CODE` 或 `DEV_BYPASS_CODE` 读取，兜底 `666666`。
2. 在 `awiki-open-server/src/awiki_open_server/services.py` 增加：
   - `did_verify_send_code`
   - `did_verify_login`
   - `did_verify_refresh`
   - `DID_VERIFY_HANDLERS`
3. 在 `awiki-open-server/src/awiki_open_server/app/routes.py` 增加 `/did-verify/rpc` 和 `/user-service/did-verify/rpc`。
4. 在 `awiki-open-server/tests/test_identity_pages.py` 增加 focused 兼容测试，覆盖成功、错误验证码、未知 DID、refresh。
5. 更新 `awiki-open-server/README.md` 的 API surface 和 dev auth 说明。

## 5. 路径

可修改：

- `awiki-open-server/src/awiki_open_server/app/settings.py`
- `awiki-open-server/src/awiki_open_server/app/routes.py`
- `awiki-open-server/src/awiki_open_server/services.py`
- `awiki-open-server/tests/test_identity_pages.py`
- `awiki-open-server/README.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/steps/20-did-verify-compat.md`

禁止修改：

- `user-service/**`
- `message-service/**`
- `awiki-cli-rs2/**`
- `awiki-harness/**`
- `awiki-open-server/AGENTS.md`

## 6. 验证方式

运行：

```bash
PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py::test_did_verify_rpc_compat_routes -q
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step20-asgi
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step20-cross --clean
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step20-rust-cli --clean
```

`verify-public --base-url https://rwiki.info --did-domain rwiki.info` 仍属于 Step 09 公网部署 Gate；本步骤可复跑并记录结果，但不能用它证明本地 DID verify 兼容失败。

## 7. Review 环节

Review 必须检查：

- `/did-verify/rpc` 不调用外部 User Service、Message Service、`awiki.info` 或短信/邮件供应商。
- `login` 只允许本仓已注册 DID；未知 DID 不自动从外部创建。
- DID verify dev code 与 SMS/Handle dev OTP 边界清楚，不破坏现有 Rust CLI 注册。
- token 响应形态与 User Service 文档兼容，同时保持 Community 极简实现。
- 公开 `/anp-im/rpc` 白名单不因本步骤变化而扩大。

## 8. 风险与回滚

| 风险 | 缓解措施 | 回滚 / 回退方案 |
|---|---|---|
| DID verify dev code 与 SMS OTP 混淆 | 文档明确 `/did-verify/rpc` 默认 `666666`，SMS/Handle 仍为 `123456` | 回滚 settings 与 DID_VERIFY_HANDLERS 变更 |
| 客户端期待 refresh token rotation | Community 版记录为 token 复用，不实现生产 session rotation | 后续新增 session 表和 token rotation 步骤 |
| 未知 DID 自动创建导致外域污染 | `login` 要求 DID 已在本仓注册并存在 DID document | 保持 `did_not_found` / `did_document_not_found` 错误 |
