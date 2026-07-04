# Step 03：User Service 兼容模块拆分

主 Plan：[../plan.md](../plan.md)  
Step index：03  
状态：draft

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | pending |
| Branch | TBD |
| Started | TBD |
| Completed | TBD |
| Commit | TBD |
| Review evidence | TBD |
| Verification evidence | TBD |
| Next action | 拆出本仓 User Service compat 模块 |
| Assigned agent | agent-user-compat |
| Parallel group | B |
| Parallel safe | yes |
| Parallel with | Step 02 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/services.py` identity/profile/handle/users/auth compat 区域 |
| Baseline commit | TBD |
| Worktree / branch | TBD |
| Merge gate | User compat gate |
| Verification gate | focused compat tests |
| Gate status | pending |

## 2. 目标

- 结果：把 DID Auth、Profile、Handle、Users、legacy auth/token/ws ticket 兼容逻辑从 `routes.py` / `services.py` 中拆到本仓清晰模块。
- 用户 / 系统可见行为：现有 `/user-service/*` 和非 prefixed compat route 行为不变。
- 非目标：不调用或代理相邻 `user-service`，不引入 MySQL、Redis、阿里云、短信、邮件、微信、Cloudflare Turnstile。
- 完成标准：User Service compat 有独立模块、独立测试；contact verification 默认仍 disabled。

## 3. 设计方法

- 设计边界：参考 `user-service` 的 response shape 和方法名，但实现留在本仓 SQLite/local token。
- 核心决策：`user-service` 是兼容形态参考，不是运行时依赖。
- 契约 / API / 数据流：DID Auth 方法保持 `register`、`verify`、`verify_http_request`、`update_document`、`revoke`、`get_me`；`replace_did` / `recover_handle` 继续 `not_supported` 或 Community disabled。
- 兼容性：Rust CLI 所需 phone/otp 参数只能作为占位输入，不形成身份事实。
- 风险控制：所有 phone/email/auth compat route 默认返回 `contact_verification_not_enabled`，本地 dev shim 仍需显式开关。

## 4. 实现方法

1. 新增 `awiki_open_server/identity/` 或 `awiki_open_server/user_compat/` 包。
2. 从 `services.py` 搬迁 DID/token/profile/handle/users/relationship/agent compat 函数，先搬迁不改行为。
3. 从 `routes.py` 搬迁 `/auth/*`、token verify/refresh、ws ticket 逻辑到 compat service 函数。
4. 保留 handler map，但将 map 放到对应 domain module 并由 `routes.py` import。
5. 参考 User Service docs 校验 response fields：DID Auth、DID Profile、Users、Handle。
6. 新增或调整 focused tests：contact verification disabled、did-auth register/update/revoke、profile/users/handle shape、token/ws ticket headers。

## 5. 路径

| 仓库 / 模块 / 文件 | 计划变更 | 备注 |
|---|---|---|
| `awiki-open-server/src/awiki_open_server/user_compat/` | 新增 User Service compat 包 | 名称可由执行者最终确定 |
| `awiki-open-server/src/awiki_open_server/services.py` | 搬出身份兼容函数 | 保留过渡 import 不改行为 |
| `awiki-open-server/src/awiki_open_server/app/routes.py` | route 调用 compat service | route 变薄 |
| `awiki-open-server/tests/test_user_service_compat.py` | 新增 / 拆分 tests | 覆盖 route shape |

## 6. 依赖与并行约束

- 前置步骤：Step 01。
- 可并行步骤：Step 02。
- 不可并行步骤：Step 04 需等本步骤完成。
- 并行安全依据：Step 02 负责 route path，Step 03 负责 compat 业务；修改 `routes.py` 时只调整调用导入。
- 互斥资源 / 冲突路径：`routes.py` import 区域需和 Step 02 协调。
- 合并后验证门禁：Wave B group pytest。

## 7. 验收标准

- [ ] User Service compat 逻辑不再主要堆在 `routes.py` 内。
- [ ] `services.py` identity/profile/handle/users 区域明显瘦身。
- [ ] 没有引入短信/邮件/Aliyun/Redis/MySQL 依赖。
- [ ] contact verification 默认 disabled。
- [ ] Focused compat tests pass。
- [ ] 本步骤在进入 Step 04 前已创建聚焦 commit。

## 8. 验证方式

| 检查项 | 命令 / 方法 | 运行时机 | 预期证据 | 门禁类型 |
|---|---|---|---|---|
| User compat | `PYTHONPATH=src python3 -m pytest tests/test_user_service_compat.py tests/test_identity_pages.py -q` | commit 前 | pass | Step gate |
| No forbidden deps | 检查 `pyproject.toml` 不含 Aliyun/SMS/email provider | Review 前 | pass | Step gate |
| CLI smoke | `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step03-asgi` | commit 前 | pass | Step gate |

## 9. Review 环节

- Review 重点：是否误把 User Service 生产依赖带入本仓；phone/email 是否成为认证事实；response shape 是否兼容。

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | TBD | TBD |
| 已修复问题 | TBD | TBD |
| 剩余风险 | TBD | TBD |
| 新增或缺失测试 | TBD | TBD |
| 并行安全是否仍成立 | TBD | 与 Step 02 route path 无冲突 |

## 10. Commit 要求

- Commit 范围：User Service compat module、相关 imports、focused tests。
- 建议消息：`compat: split user service handlers`

## 11. Blocked 处理

| Blocker | 证据 | 已尝试方案 | 影响范围 | 是否影响并行组 | 是否影响合并门禁 | 下一步决策 |
|---|---|---|---|---|---|---|
| Rust CLI 依赖某个 legacy field | smoke 失败 | 保持 field projection | 当前步骤 | 否 | 是 | 补兼容测试 |

## 12. Plan 变更记录

| 日期 | 变更 | 原因 | 主 Plan 变更记录链接 |
|---|---|---|---|
| 2026-07-04 | 初始创建 | 收敛 User Service compat 结构 | `../plan.md#16-plan-变更记录` |

## 13. 风险、回滚与后续文档

- 风险：搬迁函数时造成 handler map 漏项。
- 回滚 / 回退：回退本步骤 commit；避免同时改变行为和结构。
- 后续文档：Step 06 标注 User Service 仅作参考，不作后端。
