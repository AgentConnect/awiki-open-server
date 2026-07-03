# Step 02：默认禁用 contact verification

主 Plan：[../plan.md](../plan.md)  
Step index：02  
状态：done

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done |
| Branch | 当前 worktree |
| Started | 2026-07-03 |
| Completed | 2026-07-03 |
| Commit | 未提交 |
| Review evidence | 默认 contact verification routes 已禁用；显式 compat fixture 保留旧本地 shim；未新增 provider 依赖；Rust CLI 输出不再称为 dev phone OTP 验证 |
| Verification evidence | focused pytest 4 passed；provider dependency grep 无真实 provider 依赖 |
| Next action | Step 03 已完成；继续 Step 04 public blocker |
| Assigned agent | main |
| Parallel group | B |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/app/settings.py`, `awiki-open-server/src/awiki_open_server/app/routes.py`, `awiki-open-server/src/awiki_open_server/services.py`, `awiki-open-server/tests/`, `awiki-open-server/scripts/` |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | focused pytest + full repo gate |

## 2. 目标

- 结果：默认不提供手机、邮箱、OTP、phone-bind 或 `send_otp` 验证流程。
- 用户 / 系统可见行为：`/auth/sms*`、`/auth/email*`、`/auth/phone-bind-*` 默认返回 `contact_verification_not_enabled`；`/handle/rpc send_otp` 默认返回 JSON-RPC `not_supported` 风格错误。
- 非目标：不删除旧兼容路由，不修改 Rust CLI，不实现真实 provider。
- 完成标准：显式 `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=true` 时旧本地 shim 可用于兼容测试；默认关闭时本仓无手机/邮箱验证过程。

## 3. 设计方法

- 设计边界：禁用 contact verification，但保留 DID register、本地 token verify、WS ticket 等非 contact 兼容。
- 核心决策：新增显式开关，默认 false；不新增依赖和存储。
- 契约 / API / 数据流：默认 REST 返回 400 detail，JSON-RPC `send_otp` 返回 `contact_verification_not_enabled`。
- 兼容性：Rust CLI local gate 继续传 placeholder `--phone --otp`，直接进入 `did-auth.register`。
- 迁移策略：无 schema 迁移。
- 风险控制：测试同时覆盖默认禁用和显式兼容模式。

## 4. 实现方法

1. 在 `settings.py` 增加 `enable_contact_verification_compat` 和 `contact_verification_dev_otp`。
2. 在 `routes.py` 增加 contact verification gate，默认禁用 SMS/email/phone-bind REST routes。
3. 在 `services.py` 让 `send_otp` 默认抛 `contact_verification_not_enabled`。
4. 在 `tests/conftest.py` 增加显式开启兼容的 fixture。
5. 更新 `tests/test_identity_pages.py`：
   - 默认 fixture 验证 contact verification routes disabled。
   - 旧 legacy compat 测试改用显式 compat fixture。
6. 更新 `scripts/awiki_open_cli.py` 输出，避免把 Rust CLI gate 描述为 dev phone OTP 验证。

## 5. 路径

| 仓库 / 模块 / 文件 | 计划变更 | 备注 |
|---|---|---|
| `awiki-open-server/src/awiki_open_server/app/settings.py` | 新增开关 | 默认 false |
| `awiki-open-server/src/awiki_open_server/app/routes.py` | 默认禁用 REST contact verification | 不影响 token/ws ticket |
| `awiki-open-server/src/awiki_open_server/services.py` | 默认禁用 `send_otp` | JSON-RPC |
| `awiki-open-server/tests/conftest.py` | compat fixture | 显式开启 |
| `awiki-open-server/tests/test_identity_pages.py` | 默认禁用和 compat 测试 | focused gate |
| `awiki-open-server/scripts/awiki_open_cli.py` | 输出文案 | 验证语义准确 |

## 6. 依赖与并行约束

- 前置步骤：Step 01 的目标边界。
- 可并行步骤：无。
- 不可并行步骤：Step 03 依赖本步骤。
- 并行安全依据：同一文件和测试面，不能并行写。
- 互斥资源 / 冲突路径：settings/routes/services/tests/scripts。
- 外部文档或决策：用户明确约束。
- 环境前提：Python test env。
- 合并前置条件：focused tests pass。
- 合并后验证门禁：Step 03 full gate。

## 7. 验收标准

- [x] 默认设置下 SMS/email/phone-bind routes 不运行验证流程。
- [x] 默认设置下 `/handle/rpc send_otp` 返回 `contact_verification_not_enabled`。
- [x] 显式 compat fixture 仍覆盖旧本地 shim。
- [x] 没有新增 Aliyun、短信、邮件依赖。
- [x] Rust CLI smoke 描述不再宣称 dev phone OTP 验证。
- [x] Review 发现已经修复或记录。

## 8. 验证方式

| 检查项 | 命令 / 方法 | 运行时机 | 预期证据 | 门禁类型 |
|---|---|---|---|---|
| Focused pytest | `PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py::test_user_service_identity_compat_path_accepts_cli_did_document tests/test_identity_pages.py::test_contact_verification_routes_disabled_by_default tests/test_identity_pages.py::test_legacy_auth_and_ws_ticket_compat_routes tests/test_identity_pages.py::test_did_relationship_phone_bind_and_site_rpc_compat -q` | commit 前 | 4 passed | Step gate |
| Dependency grep | `rg -n "aliyun|阿里云|alibabacloud|smtp|twilio|sendgrid|boto|oss2" pyproject.toml src tests README.md require.md deploy` | Review 前 | 无真实 provider 依赖；只命中文档禁止项 | Step gate |

## 9. Review 环节

- Review 时机：focused tests 通过后。
- Review 重点：默认禁用是否完整、DID register 是否不受影响、compat 开关是否只用于本地、是否引入 provider 依赖。

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | 无阻塞 |  |
| 已修复问题 | 默认 contact verification 未关闭 | 已新增配置开关并默认关闭 |
| 剩余风险 | 旧 CLI 无 OTP 注册路径会触发 disabled `send_otp` | README/Plan 说明使用 placeholder OTP；后续 CLI 可改纯 DID/handle 注册 |
| 新增或缺失测试 | 已新增默认禁用测试和显式 compat fixture |  |
| 已更新或缺失文档 | README/require/deploy env 已同步 |  |
| 并行安全是否仍成立 | 是 | 本步骤串行 |

## 10. Commit 要求

- Commit 时机：Step 02 focused gate 和 Review 完成后。
- Commit 范围：settings/routes/services/tests/scripts 与相关 docs。
- 建议消息：`auth: disable contact verification by default`

## 11. Blocked 处理

| Blocker | 证据 | 已尝试方案 | 影响范围 | 是否影响并行组 | 是否影响合并门禁 | 下一步决策 |
|---|---|---|---|---|---|---|
| Rust CLI local gate 若失败 | Step 03 证据 | 确认是否是无 OTP send_otp 路径 | Step 03/04 | 否 | 是 | 保持 placeholder OTP 或记录 CLI 后续需求 |

## 12. Plan 变更记录

| 日期 | 变更 | 原因 | 主 Plan 变更记录链接 |
|---|---|---|---|
| 2026-07-03 | 新增 Step 02 | 用户要求 v0.1 不使用邮件/手机号验证 | `../plan.md#16-plan-变更记录` |

## 13. 风险、回滚与后续文档

- 风险：旧客户端无 OTP 注册路径会返回未启用。
- 并行执行风险：无并行写。
- 合并冲突风险：中，routes/tests 已有历史兼容改动。
- Group gate 失败回退：临时启用 compat fixture 只用于测试，不改默认。
- Agent 交接说明：Step 03 负责全量验证。
- 回滚 / 回退：移除开关和 route gate，恢复旧默认 dev shim。
- 后续文档：如 Rust CLI 支持纯 handle 注册，更新 README 去掉 placeholder phone/otp 示例。
