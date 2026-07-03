# Step 13：User Service auth_request 与 dev 登录兼容补齐

主 Plan：[../plan.md](../plan.md)  
Step index：13  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-with-pending-online-gate |
| Branch | main |
| Started | 2026-07-03 13:05 CST |
| Completed | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 |
| Commit | 未提交 |
| Review evidence | 已复核：新增 health/auth/session/ws-ticket 兼容别名均由本仓本地实现；`/auth/sms` dev OTP 只创建或复用本地 SQLite DID 用户；token/ticket verify 返回 `X-User-Id` / `X-DID` header；未引入外部 User Service / Message Service / `awiki.info` 运行依赖；README 已标注 dev auth 边界 |
| Verification evidence | focused health/auth compat pass；compileall pass；全量 pytest 29 passed；ASGI smoke pass；双实例本地跨域 Gate pass；`verify-public https://rwiki.info` 仍 404，归属 Step 09 |
| Next action | 继续 Step 09 公网 Gate：待用户确认/执行 nginx/systemd 切换后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/app/routes.py`、`awiki-open-server/tests/test_identity_pages.py`、`awiki-open-server/README.md`、`awiki-open-server/plan/...` |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | focused/full pytest + ASGI smoke + 双实例本地跨域 Gate；公网 Gate 仍归 Step 09 |
| Verification gate | pass/online-pending |

## 2. 目标

补齐本仓可自行修复的 User Service 兼容缺口，让极简 open server 在切到现有 nginx/User Service 集成形态时不会因为认证验证路由或响应 header 缺失而失败。

- 结果：本仓提供 User Service 常见 `auth_request` 验证别名，并返回 `X-User-Id` / `X-DID` header。
- 用户 / 系统可见行为：`/auth/sms` 和 `/user-service/auth/sms` 可用默认 dev OTP `123456` 登录或注册本地 DID 用户；`/user-service/auth/verify`、`/user-service/auth/token-verify`、`/sessions/verify`、`/user-service/auth/ws-ticket/verify`、`/user-service/ws/tickets/verify` 均可作为 nginx auth_request 上游使用。
- 非目标：不接入真实短信、邮件、微信、Turnstile、生产 JWT 公私钥体系或线上 User Service。
- 完成标准：新增兼容路径由本仓本地实现；不引入 `awiki.info` / `user-service` / `message-service` 运行依赖；测试覆盖创建/复用 dev 用户、token verify header、session verify header 和 WS ticket header 验证。

## 3. 设计方法

- 设计边界：保留 Community dev auth；只补路由别名和响应 shape，不改变 DID/Auth JSON-RPC 主流程。
- 核心决策：`/auth/sms` 在没有现有 token 时使用 dev OTP 创建或复用本地 DID 账号；token/ticket verify 使用本仓 SQLite token 查找。
- 契约 / API / 数据流：验证成功返回 JSON body，同时通过 header 暴露 `X-User-Id` 和 `X-DID`，兼容 User Service 文档中的 nginx `auth_request` 使用方式。
- 兼容性：保留旧路径 `/auth/token-verify`、`/ws/tickets/verify`，新增 `/auth/verify`、`/sessions/verify`、`/user-service/auth/ws-ticket/verify` 等别名。
- 风险控制：dev OTP 固定为 `123456`，仅作为开源本地兼容实现；README 和 Plan 明确不等价于生产身份提供方。

## 4. 实现方法

1. 在 `awiki-open-server/src/awiki_open_server/app/routes.py` 增加 health、auth verify、session verify、ws-ticket verify 别名。
2. 在 token/ticket verify 响应中返回 `X-User-Id` / `X-DID` header。
3. 将 `/auth/sms` / `/user-service/auth/sms` 补成 dev OTP 登录/注册；相同手机号再次登录复用同一 token。
4. 在 `awiki-open-server/tests/test_identity_pages.py` 扩展 legacy auth 测试，覆盖新增路径和 header。
5. 更新 `awiki-open-server/README.md` 和本 Plan，说明这些能力仍由本仓实现，不代理线上 User Service。

## 5. 路径

| 仓库 / 模块 / 文件 | 计划变更 | 备注 |
|---|---|---|
| `awiki-open-server/src/awiki_open_server/app/routes.py` | 新增 dev login 与 auth_request 路由别名、header 响应 | 本仓唯一代码修改面 |
| `awiki-open-server/tests/test_identity_pages.py` | 扩展 legacy auth/ws ticket 测试 | 覆盖新增兼容面 |
| `awiki-open-server/README.md` | 记录 User Service auth_request 兼容能力 | 防止误解为外部依赖 |
| `awiki-open-server/plan/20260702-awiki-open-server-mvp/` | 更新执行台账、变更记录和公网 blocker 证据 | 只改本仓计划 |

禁止修改 `user-service/**`、`message-service/**`、`awiki-cli-rs2/**`、`awiki-harness/**` 和其他相邻仓库。

## 6. 依赖与并行约束

- 前置步骤：Step 12 本地 realtime 兼容已完成。
- 可并行步骤：无。
- 不可并行步骤：Step 09 公网 Gate 依赖单一域名和 nginx 路由，不能与本步骤并行改配置。
- 并行安全依据：本步骤修改共享 routes/tests/docs，串行更清晰。
- 环境前提：本地 pytest 可运行；公网 `rwiki.info` 仍可能未路由到本仓。
- 合并后验证门禁：focused/full pytest、ASGI smoke、双实例本地跨域 Gate。

## 7. 验收标准

- [x] `/user-service/auth/sms` 使用 `otp_code=123456` 可创建本地域 DID 用户。
- [x] 同手机号再次通过 `/auth/sms` 登录复用同一 token。
- [x] `/user-service/auth/token-verify`、`/user-service/auth/verify`、`/sessions/verify` 成功时返回 `X-User-Id`。
- [x] `/user-service/auth/ws-ticket/verify` 支持 `X-WS-Ticket` header 并返回 `X-User-Id`。
- [x] 全量本仓门禁通过，或记录失败原因。
- [x] `verify-public https://rwiki.info` 仍失败时记录为 Step 09 公网路由 blocker，不误判为本步骤失败。

## 8. 验证方式

| 检查项 | 命令 / 方法 | 运行时机 | 预期证据 | 门禁类型 |
|---|---|---|---|---|
| Focused auth compat | `PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py::test_legacy_auth_and_ws_ticket_compat_routes -q` | 修改后 | pass | Step gate |
| Compile | `PYTHONPATH=src python3 -m compileall -q src scripts tests` | Review 前 | pass | Step gate |
| Full pytest | `PYTHONPATH=src python3 -m pytest tests -q` | Review 前 | pass | Step gate |
| ASGI smoke | `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step13-asgi` | Review 前 | pass | Step gate |
| Local cross-domain | `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step13-cross --clean` | Review 前 | pass | Step gate |
| Public precheck | `PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info` | Review 前 | 预期仍可能 404；若失败归 Step 09 | Online gate |

实际验证证据：

- `PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py::test_legacy_auth_and_ws_ticket_compat_routes -q`：1 passed。
- `PYTHONPATH=src python3 -m pytest tests/test_health.py::test_healthz tests/test_identity_pages.py::test_legacy_auth_and_ws_ticket_compat_routes -q`：2 passed。
- `PYTHONPATH=src python3 -m compileall -q src scripts tests`：pass。
- `PYTHONPATH=src python3 -m pytest tests -q`：29 passed。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step13-asgi`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step13-cross --clean`：pass，验证两个独立本仓实例、service DID Ed25519 HTTP Signature、DID discovery、origin proof、签名 `/anp-im/rpc direct.send` 和双向 inbox delivery。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info`：failed，`/.well-known/did.json`、`/healthz`、`/anp-im/rpc` 仍为 404；继续归属 Step 09 公网路由 blocker。

## 9. Review 环节

- Review 时机：本步骤代码实现完成后、commit 前。
- Review 重点：认证别名是否仍本地实现；是否泄漏真实 token；dev OTP 是否被误写为生产能力；响应 header 是否覆盖 nginx auth_request；是否破坏 Rust CLI 注册/direct/group Gate。

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | 无新的本仓阻塞 | 公网路由仍属于 Step 09 |
| 已修复问题 | 补齐 auth_request header/别名、WS ticket header 验证、dev SMS 登录/注册 | 不修改相邻服务 |
| 剩余风险 | dev auth 不等价于生产身份；公网 `rwiki.info` 仍未切到本仓 | README/Plan 已标注 |
| 新增或缺失测试 | 已新增 focused legacy auth 测试；全量 pytest 通过 | 无已知缺失 |
| 已更新或缺失文档 | README 和 Plan 已更新 | 无已知缺失 |

## 10. Commit 要求

- Commit 时机：本步骤实现、验证、Review 都完成后。
- Commit 范围：只包含 Step 13 的路由、测试、README 和 Plan 更新。
- 建议消息：`compat: add user-service auth request aliases`

## 11. Blocked 处理

| Blocker | 证据 | 已尝试方案 | 影响范围 | 是否影响并行组 | 是否影响合并门禁 | 下一步决策 |
|---|---|---|---|---|---|---|
| `rwiki.info` 未路由到本仓 | `verify-public` 404；当前 nginx `rwiki.info.conf` 只代理部分路径到 `user-service`，缺少 `/healthz`、`/anp-im/rpc`、`/im/rpc` 等本仓路由 | 本仓已提供 `deploy/` 模板和 `verify-public`；本步骤继续补本仓兼容面 | 真实线上 Gate | 否 | 否，本步骤本地门禁可完成 | 继续 Step 09，待用户确认是否切换线上 nginx/systemd |

## 12. Plan 变更记录

| 日期 | 变更 | 原因 | 主 Plan 变更记录链接 |
|---|---|---|---|
| 2026-07-03 | 新增 Step 13 | 继续对照 User Service 文档和当前 nginx 形态后，发现本仓可自行补齐 auth_request header/别名与 dev SMS 登录兼容 | 主 Plan `## 16. Plan 变更记录` |

## 13. 风险、回滚与后续文档

- 风险：dev auth 只适合本地/Community，不能作为生产身份承诺。
- 回滚 / 回退：如新增别名造成冲突，可移除别名并保留原 `/auth/token-verify`、`/ws/tickets/verify`。
- 后续文档：公网 Step 09 切换前应复核 nginx 是否把 `rwiki.info` 路由到本仓，而不是当前 `user-service`。
