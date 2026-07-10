# Step 04：DID/Auth 注册 proof 与 token 生命周期硬化

主 Plan：[../plan.md](../plan.md)  
Step index：04  
状态：done

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done |
| Branch | `main` |
| Started | 2026-07-10T11:18:51Z |
| Completed | 2026-07-10T11:30:51Z |
| Commit | 提交后回填 |
| Review evidence | L3 Review 完成：DID/domain/e1、uploaded proof policy、token expiry/rotation、contact verification 默认禁用、public allowlist 和 token logging 均已检查；剩余风险是用户 DID document proof 只做结构校验，不做 DataIntegrity/JCS cryptographic verification。 |
| Verification evidence | identity focused 20 passed；route/auth focused 4 passed, 2 skipped；`smoke-cross-domain-local` pass；full local tests 70 passed, 2 skipped；`git diff --check` pass。 |
| Next action | 创建 Step 04 聚焦 commit，然后启动 Step 05 |
| Assigned agent | agent-identity |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/user_compat/core.py`, `storage/db.py`, auth/profile tests |
| Baseline commit | `ce40465` |
| Worktree / branch | `main` |
| Merge gate | DID/auth security gate |
| Verification gate | identity/user compat focused tests + security review |
| Gate status | pass |

## 2. 目标

- 结果：补齐 Community 版 DID 注册、更新、验证和 token 生命周期的生产安全边界。
- 用户 / 系统可见行为：非法 DID/domain/profile 被拒绝；重复 handle/DID 冲突稳定；注册/更新 DID document 能证明控制权或明确 dev-only；token refresh/expiry 行为更可靠。
- 非目标：不实现 phone/email/SMS/Aliyun、账号恢复商业流程、K1 DID、组织/企业账号、生产风控。
- 完成标准：e1/domain policy、DID document proof、duplicate/conflict、token expiry/rotation 有 tests 或明确 documented fallback；L3 security review 完成。

## 3. 设计方法

- 设计边界：`user_compat` 是本地 User Service compatibility，不是外部 user-service proxy。
- 核心决策：默认生产安全，dev shim 必须显式配置且不可在 public deployment 中默认开启。
- 契约 / API / 数据流：`did-auth.register` 创建 local user/profile/DID doc/session；`update_document` 保持主身份绑定；`verify`/`get_me`/`revoke` 使用 local token/DID WBA。
- 兼容性：旧 CLI `id register --phone/--otp` 参数只保留命令形态，不升级为认证事实。
- 迁移策略：token 表或 session 字段扩展必须允许旧 token 行；若无法安全 rotation，则先只加 expiry enforcement 和 docs。
- 风险控制：DID/auth 变更按 L3；不记录 private key、JWT、refresh token 明文到日志或 docs。

## 4. 实现方法

1. 梳理 `user_compat/core.py` 中 register/update/verify/revoke/token-refresh/token-verify 的现状和错误行为。
2. 加强 DID policy：
   - 只支持 `did:wba:<domain>:...:e1_*` 或本仓既定 e1 path。
   - 默认拒绝 K1 或 domain 不匹配输入。
   - DID document `id`、verification method、authentication、service endpoint、serviceDid 与 settings 一致。
3. 注册/更新 proof：
   - 优先要求 DID document proof 或请求签名证明控制权。
   - 如果当前客户端尚不能提供，必须把 unsigned registration 限制为 dev/local 或明确 Community MVP 风险，并新增 public deployment 负断言。
4. duplicate/conflict：
   - 重复 DID 同 payload 幂等返回或稳定 conflict。
   - handle 已占用返回稳定 conflict。
   - DID document 与 handle/profile mismatch fail closed。
5. token 生命周期：
   - access token expiry 和 refresh token expiry enforcement。
   - refresh token rotation 如数据模型允许则实现；否则记录为后续迁移，并至少保证 revoked/expired token 不可用。
   - `token-verify` 不泄露敏感 token material。
6. 保持 contact verification disabled：
   - `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false` 下 phone/email endpoints 继续返回 disabled/not_supported。
   - tests 覆盖 public deployment 默认禁用。
7. 更新 README 中 auth/security notes，如行为或配置变化。

## 5. 路径

| 仓库 / 模块 / 文件 | 计划变更 | 备注 |
|---|---|---|
| `awiki-open-server/src/awiki_open_server/user_compat/core.py` | DID policy、proof、token lifecycle、conflict errors | 主要路径 |
| `awiki-open-server/src/awiki_open_server/user_compat/http.py` | 如存在 auth HTTP helper 变化 | 按实际文件 |
| `awiki-open-server/src/awiki_open_server/app/routes.py` | 如 auth route status/compat 变化 | 注意 JSON-RPC 兼容 |
| `awiki-open-server/src/awiki_open_server/storage/db.py` | 可选 token/session schema 扩展 | 向后兼容 |
| `awiki-open-server/tests/test_user_service_compat.py` | User Service compat tests | 必需 |
| `awiki-open-server/tests/test_identity_documents.py` | DID doc/policy tests | 必需 |
| `awiki-open-server/tests/test_contact_auth_compat.py` | disabled phone/email tests | 必需 |
| `awiki-open-server/tests/test_profile_compat.py` | profile/handle mismatch tests | 如相关 |
| `awiki-open-server/README.md`, `README.cn.md` | auth/security notes | Step 06 可统一 |

## 6. 依赖与并行约束

- 前置步骤：Step 03 完成，避免 storage schema 冲突。
- 可并行步骤：无。
- 不可并行步骤：Step 05 不能同时改 shared auth/current_did side effects。
- 并行安全依据：DID/auth/security-sensitive，必须单写单审。
- 互斥资源 / 冲突路径：`user_compat/core.py`, `storage/db.py`, auth tests。
- 外部文档或决策：参考 `user-service/docs/api/did-auth.md`, `did-profile.md`, `handle.md`, `anp/AgentNetworkProtocol/chinese/03-did-wba方法规范.md`。
- 环境前提：可加载 ANP SDK 0.8.8。
- 合并前置条件：focused tests、security review。
- 合并后验证门禁：public system tests 仍确认 contact verification disabled。

## 7. 验收标准

- [x] 非 e1 DID 或 domain mismatch 默认 fail closed。
- [x] DID document id/profile/service mismatch 被拒绝或忽略展示 profile。
- [x] register/update DID document control proof 策略已实现，或 unsigned 仅 dev/local 且记录风险。
- [x] duplicate DID/handle 返回稳定 error，不产生双重身份事实。
- [x] expired/revoked token 不可通过 verify/token-verify。
- [x] contact verification 默认禁用，未引入 phone/email/Aliyun 依赖。
- [x] L3 security review 完成。
- [x] 本步骤在进入下一步之前已经创建聚焦 commit。

## 8. 验证方式

| 检查项 | 命令 / 方法 | 运行时机 | 预期证据 | 门禁类型 |
|---|---|---|---|---|
| Identity focused | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_user_service_compat.py tests/test_identity_documents.py tests/test_contact_auth_compat.py tests/test_profile_compat.py tests/test_agent_compat.py -q` | commit 前 | pass | Step gate |
| Route/auth focused | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_route_config.py tests/test_rwiki_cn_system.py -q` | commit 前，public tests 可 skip unless env | local pass/skip reason | Step gate |
| Public guarded | `cd awiki-open-server && AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_rwiki_cn_system.py -q` | final 或 public auth 改动后 | pass | Public gate |
| Full local | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests -q` | commit 前或 final | pass | Repo gate |
| Security review | 手工 Review DID/auth/token/logging/config | commit 前 | 记录 findings/fixes/risks | L3 gate |

## 9. Review 环节

- Review 时机：实现和 tests 完成后、commit 前。
- Review 重点：DID/domain/e1 policy、proof bypass、token leakage、dev shim 默认关闭、duplicate/conflict、route compatibility、public deployment config。
- Review 必须明确记录是否仍允许 unsigned registration；若允许，必须说明范围和后续补齐条件。

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | token refresh HTTP route 曾 catch broad `Exception`；`refresh_access_token` 需要避免新用户用 access token 当 refresh token；无效时间戳应 fail closed。 | Review 中发现并修复。 |
| 已修复问题 | HTTP route 收窄为只捕获 `InvalidParams`/`Unauthorized`；refresh query 仅在 legacy `refresh_token IS NULL` 行接受 access token；`_is_past` 对无效时间戳返回 expired。 | 已增加测试覆盖新用户 access-as-refresh 拒绝和 legacy fallback。 |
| 剩余风险 | signed uploaded DID document proof 目前只检查 proof 结构和 `verificationMethod` DID 绑定，不做 cryptographic proof verification。 | 作为 Community MVP 兼容风险记录；service endpoint/service DID 仍 fail closed。 |
| 新增或缺失测试 | 新增 DID policy、strict unsigned uploaded doc、duplicate handle/DID、token expiry、refresh rotation、stale/expired refresh、access-as-refresh 拒绝、legacy fallback tests。 | 未新增真实 DataIntegrity/JCS proof verification test，因为实现未包含 cryptographic verification。 |
| 已更新或缺失文档 | Step 文档和主 Plan 已记录行为、验证和剩余风险。 | README / deploy 配置说明按计划在 Step 06 统一同步。 |
| 并行安全是否仍成立 | 成立。 | 本步骤为串行单写；未启动并行写入。 |
| Agent 是否越界修改 | 未越界。 | 改动限于 DID/auth/token、测试 fixture、smoke DID 兼容和计划台账。 |
| 互斥资源是否被修改 | 已修改 `user_compat/core.py`、`user_compat/http.py`、`storage/db.py`。 | 均属于 Step 04 范围，schema 为 nullable 兼容列。 |
| 合并风险 | 低到中。 | 主要风险是旧客户端是否依赖 access token refresh；已保留 legacy DB fallback，但新注册用户改为 refresh token rotation。 |
| Group gate 影响 | 无 | 串行 |

## 10. Commit 要求

- Commit 时机：实现、验证、L3 Review 完成后。
- Commit 范围：DID/auth/token 相关代码、tests、必要 docs。
- Commit 前状态：`main...origin/main [ahead 5]`，Step 04 文件已修改，`git diff --check` pass。
- Commit 后证据：提交后回填 commit hash 和 commit 后状态。
- 建议消息：`identity: harden DID auth token lifecycle`。

## 11. Blocked 处理

| Blocker | 证据 | 已尝试方案 | 影响范围 | 是否影响并行组 | 是否影响合并门禁 | 下一步决策 |
|---|---|---|---|---|---|---|
| 当前客户端无法提供注册 proof | 执行时填写 | dev-only unsigned、public disabled、更新 CLI contract issue | 当前步骤/客户端兼容 | 是 | 是 | 记录风险并限制范围 |
| token rotation 需要破坏性 schema | 执行时填写 | 只 enforce expiry/revoke，rotation 留后续迁移 | 当前步骤 | 是 | 可选 | 更新 Plan 和 docs |

## 12. Plan 变更记录

| 日期 | 变更 | 原因 | 主 Plan 变更记录链接 |
|---|---|---|---|
| 2026-07-10 | 创建 Step 04 | 初始计划 | `../plan.md#20-plan-变更记录` |

## 13. 风险、回滚与后续文档

- 风险：过严 proof policy 可能破坏当前 Rust CLI registration。
- 并行执行风险：auth route/storage 与其他 Step 冲突。
- 合并冲突风险：中等。
- Group gate 失败回退：回退本 Step commit，保留旧 dev-compatible auth 行为。
- Agent 交接说明：Step 05 启动前确认 `current_did`、token verify 行为未破坏 messaging tests。
- 回滚 / 回退：回退 auth hardening commit；如 schema 扩展存在，保持 nullable 兼容。
- 后续文档：Step 06 同步 README security notes 和 public deployment guidance。
