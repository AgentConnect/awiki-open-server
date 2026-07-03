# Plan：awiki-open-server v0.1 MVP 目标重置与互通收敛

状态：done-public-interop  
DOC：awiki-open-server/plan/20260703-awiki-open-server-mvp-reset/  
Harness：awiki-harness  
创建时间：2026-07-03  
恢复指针：Step 01-04 已完成；`rwiki.cn` public gate 和真实 `rwiki.cn` ↔ `awiki.info` 双向 direct/inbox/history Gate 已通过。下一步只做最终全局 Review、整体验证和必要的提交边界确认。

## 1. 目标

- 任务目标：把 `awiki-open-server` 的 v0.1 目标重置为最小可互通 Community Server，停止继续横向扩展 User Service / Message Service 边缘兼容。
- 预期行为：本仓独立运行，不依赖 `awiki.info`、`user-service` 或 `message-service`；当前 Rust CLI 能连接本服务注册 DID、收发 direct、读 inbox/history；`rwiki.cn` 公网部署后能与线上 `awiki.info` 用户完成双向明文 direct 互通。
- 新增硬约束：v0.1 不使用邮件或手机号码验证过程，不引入阿里云、短信 SDK、邮件 SDK 或任何外部 contact verification provider。
- 非目标：群创建/管理、跨域群、E2EE、federation、relay、远端投影/重试、生产身份 provider、邮箱/手机号绑定、Agent runtime 托管、Site/Directory 高级能力。
- 完成标准：P0/P1/P2 边界写入 `awiki-open-server/require.md`、`awiki-open-server/README.md` 和旧主 Plan；默认 contact verification 路由返回未启用；本仓 pytest/compileall/smoke 通过；Rust CLI local gate 通过且不把 placeholder phone/otp 解释成服务端验证；`verify-public https://rwiki.cn` 和真实 `rwiki.cn` ↔ `awiki.info` 双向 Gate 作为最终线上 blocker。

## 2. Harness 上下文

| 来源 | 作用 |
|---|---|
| `awiki-harness/AGENTS.md` | 确认非平凡任务需要影响面、规则和验证证据。 |
| `awiki-harness/harness-control-plane-plan.md` | 确认 harness 只做控制面，子仓库拥有实现真相。 |
| `awiki-harness/context/00-context-map.md` | 路由到 Identity、Auth、Protocol、Message Flow 和 System Test。 |
| `awiki-harness/context/02-repo-map.md` | 确认 `awiki-open-server` 只能参考 `user-service`、`message-service`、`awiki-cli-rs2`，本目标不修改 sibling repo。 |
| `awiki-harness/context/03-cross-repo-architecture.md` | 确认 DID/Message/Auth 边界和当前 Rust CLI 权威路径。 |
| `awiki-harness/context/20-rules-index.md` | 路由到架构、文档和验证规则。 |
| `awiki-harness/context/30-tools-env.md` | 提供本仓 pytest、Rust CLI 和系统验证入口。 |
| `awiki-harness/context/40-verification.md` | 本次涉及 identity/auth/public discovery，按 L1 + L3 gate 记录证据。 |
| `awiki-harness/context/50-task-workflow.md` | 要求计划、执行台账、验证和 blocker 记录。 |
| `awiki-harness/context/nodes/auth.node.md` | 认证变更需要安全 review gate。 |
| `awiki-harness/context/nodes/identity.node.md` | DID/Profile 是身份核心；手机号/邮箱不得变成身份真相。 |
| `awiki-harness/context/nodes/message-flow.node.md` | Direct/group/sync/read-state 边界以本服务承诺子集为准。 |
| `awiki-harness/rules/architecture-principles.md` | 禁止无规划扩展服务边界。 |
| `awiki-harness/rules/ai-coding-rules.md` | 保持小 diff，优先简化，不新增无必要依赖。 |
| `awiki-harness/rules/verification-policy.md` | 每个最终报告必须列明通过、失败、未运行和剩余风险。 |

## 3. 影响分析

| 领域 / 仓库 / 模块 | 影响 | 权威文档或代码 |
|---|---|---|
| `awiki-open-server` docs | 重新定义 v0.1 目标、P0/P1/P2 和 contact verification 边界。 | `awiki-open-server/require.md`, `awiki-open-server/README.md`, `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md` |
| `awiki-open-server` auth routes | 默认关闭 SMS/email/phone-bind/handle.send_otp 兼容验证流。 | `awiki-open-server/src/awiki_open_server/app/routes.py`, `awiki-open-server/src/awiki_open_server/services.py` |
| `awiki-open-server` settings | 新增显式 legacy contact verification compat 开关，默认关闭。 | `awiki-open-server/src/awiki_open_server/app/settings.py` |
| `awiki-open-server` tests/scripts | 默认禁用验证流程的回归测试；Rust CLI gate 仍用占位 phone/otp 参数。 | `awiki-open-server/tests/`, `awiki-open-server/scripts/awiki_open_cli.py` |
| Public interop | 最终仍依赖 `rwiki.cn` 路由到本服务并与 `awiki.info` 双向互通。 | `awiki-open-server/deploy/README.md`, `awiki-open-server/scripts/awiki_open_cli.py` |

## 4. 假设与开放问题

### 假设

- 当前 Rust CLI 的 `id register` 仍要求 `--phone` 或 `--email`，但传入 `--phone --otp` 时最终只调用 `/user-service/did-auth/rpc register`；本仓 `register` 不校验 OTP，不发送 SMS/email，也不保存 phone/email。
- `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false` 是 v0.1 和公网部署默认值；开启后只用于旧客户端本地兼容测试。
- `awiki.info` 只作为远端 peer；本服务不把它作为认证、消息、存储、代理或 fallback。
- 本目标只修改 `awiki-open-server`，其他仓库只读参考。

### 开放问题

- `rwiki.info` 作为旧测试域在 2026-07-03 21:09 CST 实测 `/.well-known/did.json`、`/healthz`、`/anp-im/rpc` 均为 404；当前操作域已切换为 `rwiki.cn`。
- 后续 Rust CLI 是否会支持纯 DID/handle 注册，不再要求 phone/email 参数；本计划不修改 CLI，只记录为后续协同事项。

## 5. 总体设计方法

- 设计边界：P0 只服务“独立 open server + Rust CLI + direct interop”；P1 只保留当前客户端有证据的必要 shim；P2 冻结边缘兼容。
- 关键决策：默认禁用 contact verification，不新增阿里云或任何 provider；保留 DID 注册和本地 token/ticket 兼容。
- 兼容性策略：旧 CLI 传入的 phone/otp 只作为请求字段被忽略，不进入认证流程；`send_otp`、SMS、email、phone-bind 默认返回未启用。
- 数据策略：不增加 phone/email 表，不增加手机号唯一约束、恢复流、绑定状态或 provider 配置。
- 风险控制：把真实完成标准压回 Step 04 public interop gate；本地测试不宣称线上互通完成。

## 6. 任务拆分

| Step | 标题 | 依赖 | 并行组 | Parallel-safe | 建议 Agent | 可并行对象 | 互斥资源 / 冲突路径 | 产出 | 小 Plan 文档 | Commit gate | 合并 / 验证门禁 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 01 | MVP scope freeze 文档收敛 | 无 | A | 是 | doc-worker | Step 04 只读部署审计 | `require.md`, `README.md`, `plan/20260702.../plan.md`, 本 Plan | P0/P1/P2、无手机/邮箱/阿里云约束、旧计划指针修正 | [steps/01-scope-freeze-docs.md](steps/01-scope-freeze-docs.md) | 建议 | docs review + grep audit | done |
| 02 | 默认禁用 contact verification | Step 01 可部分并行 | B | 否 | main | 无 | `src/awiki_open_server/app/settings.py`, `src/awiki_open_server/app/routes.py`, `src/awiki_open_server/services.py`, `tests/`, `scripts/` | 默认关闭 SMS/email/phone-bind/send_otp；显式兼容开关；测试更新 | [steps/02-disable-contact-verification.md](steps/02-disable-contact-verification.md) | 建议 | focused pytest + full pytest + smoke | done |
| 03 | 本仓回归与 Rust CLI gate | Step 02 | 串行 | 否 | verification-worker | 无 | 运行环境、临时目录、Rust CLI 二进制 | pytest、compileall、ASGI/cross-domain/Rust CLI local gate 证据 | [steps/03-local-verification.md](steps/03-local-verification.md) | 如有修复则建议 | 全量本仓 gate | done |
| 04 | Public rwiki.cn / awiki.info interop gate | Step 03 | A | 是 | explorer/verification-worker | Step 01 文档审计 | `deploy/`, `scripts/` 如需补 gate；公网环境 | `verify-public` 证据和真实双向 direct 通过记录 | [steps/04-public-interop-gate.md](steps/04-public-interop-gate.md) | 仅代码/文档变更时建议 | verify-public + real bidirectional gate | done |

## 7. 并行执行与多智能体分工

- 并行策略：审计类任务可并行；代码落地和全局 Plan 状态由 Coordinator 串行写入，避免文档和 route/test 冲突。
- 最大并行度：3 个 explorer + 1 个 coordinator。
- Coordinator：主执行者，负责修改文件、合并 explorer 结论、运行最终验证、更新执行台账。
- 串行原因：Step 02 同时改 settings/routes/services/tests/scripts，不能拆给多个 worker 写同一表面。

### Agent 分工

| Agent / Worker | 负责 Step | 责任边界 | 可修改路径 | 禁止修改路径 / 资源 | 交付物 | Review 责任 |
|---|---|---|---|---|---|---|
| doc-explorer | Step 01 审计 | 只读审计 scope creep、P0/P1/P2、Step 27 状态 | 无 | 全部写入路径 | 中文审计报告 | Coordinator 采纳并写文档 |
| auth-explorer | Step 02 审计 | 只读审计 phone/sms/email/aliyun 依赖 | 无 | 全部写入路径 | 中文审计报告 | Coordinator 采纳并改代码 |
| deploy-explorer | Step 04 审计 | 只读审计 public gate 和部署假设，可运行只读 `verify-public` | 无 | 不改公网状态、不改文件 | 中文审计报告和 gate 结果 | Coordinator 记录 blocker |
| main | Step 01-04 集成 | 文档、代码、测试、最终验证 | `awiki-open-server/**`，但不含 `AGENTS.md` | sibling repo、`AGENTS.md`、公网配置 | patch + 验证证据 | 自 Review |

### 并行组

| Wave / 并行组 | 可并行 Step | 可并行原因 | 共享依赖 | 写入范围 | 依赖屏障 | 合并顺序 | Group gate / 验证责任 |
|---|---|---|---|---|---|---|---|
| A | Step 01 审计、Step 04 部署审计 | 都可只读执行，互不写文件 | 当前 repo 状态 | 无 | Coordinator 写文档前收集结论 | explorer 报告 -> Coordinator 文档 patch | grep/path audit |
| B | Step 02 实现 | 不并行写代码 | Step 01 新边界 | settings/routes/services/tests/scripts | Step 02 完成后才能 Step 03 | Coordinator 直接集成 | focused pytest |

### 互斥资源

| 资源 / 路径 / 契约 | 互斥原因 | 受影响 Step | 规则 |
|---|---|---|---|
| `awiki-open-server/README.md`, `awiki-open-server/require.md`, `awiki-open-server/plan/**` | 全局目标和执行状态只能一个 writer | Step 01/02/03/04 | 由 Coordinator 写入 |
| `awiki-open-server/src/awiki_open_server/app/routes.py` | auth route 默认行为变更集中在同一文件 | Step 02 | 串行修改和 Review |
| `awiki-open-server/tests/test_identity_pages.py` | 默认禁用与 legacy compat 测试需要一起调整 | Step 02/03 | 串行修改和验证 |

并行执行约束：

- Agent / Worker 不回退或覆盖他人修改。
- 只读 explorer 不修改文件。
- 需要越界修改 sibling repo 时，记录 blocker，不执行。
- Coordinator 合并后必须跑组合 diff Review 和全量 gate。

## 8. 执行台账

状态取值：`pending`、`in_progress`、`review`、`blocked`、`blocked-public-route`、`committed`、`done`。

| Step | 状态 | Agent / Owner | 并行组 | 分支 / worktree | 基线 commit | 开始时间 | 完成时间 | Commit | Review 证据 | 验证证据 | 合并状态 | 门禁状态 | 下一步 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 01 | done | main + explorers | A | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 | 未提交 | Review：`require.md`、`README.md`、旧主 Plan 和 reset Plan 已统一 v0.1 边界；旧 Step 27 状态已修正；`AGENTS.md` 未修改；sibling repo 未修改 | `rg -n "Aliyun|阿里|短信|邮件|email|phone|otp" ...` pass：命中项均为禁止/禁用/占位说明或历史计划证据 | merged | pass | Step 02 已完成 |
| 02 | done | main | B | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 | 未提交 | Review：默认 contact verification routes 已禁用；显式 compat fixture 保留旧本地 shim；未新增 provider 依赖；Rust CLI 输出不再称为 dev phone OTP 验证 | focused pytest 4 passed；provider dependency grep 无真实 provider 依赖 | merged | pass | Step 03 已完成 |
| 03 | done | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 | 未提交 | Review：compileall、pytest、ASGI smoke、本地双域、Rust CLI local gate 均通过；Rust CLI gate 明确 phone/otp 为 placeholder | compileall pass；`pytest tests -q` 44 passed；ASGI smoke pass；cross-domain local pass；Rust CLI local pass | merged | pass | Step 04 blocked by public route |
| 04 | done | main + deploy-explorer | A | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 | 未提交 | Review：`rwiki.cn` 已由 nginx 反代到本仓服务；旧 `rwiki.info` 404 只保留为历史证据；发现 signed CLI DID document 被重写会破坏 proof，已改为 signed 文档不重写、unsigned legacy 文档继续补齐 `ANPMessageService`；后续只读 Review 又发现 signed 文档错误 service 和自定义 service DID JSON 漂移风险，已补拒绝校验；service DID `authSchemes` 已对齐并纳入 public gate | 2026-07-03 22:18 CST `verify-public --base-url https://rwiki.cn --did-domain rwiki.cn` pass；新 `rwiki.cn` 用户 DID document proof 校验通过；真实 `rwiki.cn -> awiki.info` direct/inbox/history pass，message `msg-1886f11dae554754`；真实 `awiki.info -> rwiki.cn` direct/inbox/history pass，message `msg-1886f0a64010ebc5`；2026-07-03 22:36 CST 重启 systemd 加载最新代码后 `verify-public https://rwiki.cn` pass 且包含 `anp_service_auth_schemes` 检查；2026-07-03 22:40 CST 服务形态防护后再次真实双向 direct/inbox/history pass，message `msg-1886aba5c219cefe` 和 `msg-1886abacc4c1a11e`；全量 pytest 47 passed；临时主机证据目录为系统 temp 下的 `awiki-open-server-public-interop/` | merged | pass | 最终全局 Review 与整体验证 |

## 9. Codex Goal 执行协议

- 将本 Plan 作为后续执行进度的唯一事实来源。
- 启动或恢复前，读取本 Plan、当前小 Plan、执行台账和当前 `git status --short --branch`。
- 默认一次只执行一个写入步骤；只读审计可按并行组启动多个 explorer。
- 每个步骤按小 Plan 执行、验证、Review、修复或记录风险，完成后回填执行台账。
- 本目标只允许修改 `awiki-open-server`；`user-service`、`message-service`、`awiki-cli-rs2` 和 `awiki-harness` 只读参考。
- `awiki-open-server/AGENTS.md` 已存在，不覆盖、不修改。
- 改变 P0/P1/P2、公开 API、安全验证、路由默认行为或验证 gate 前，先更新 Plan 变更记录。

## 9.1 Codex Goal 提示词

```text
请以 `awiki-open-server/plan/20260703-awiki-open-server-mvp-reset/plan.md` 为唯一规划入口，按文档执行完整实现。

开始前先读取：
- `awiki-open-server/plan/20260703-awiki-open-server-mvp-reset/plan.md`
- 当前第一个未 done 的 Step 文档
- 主 Plan 的执行台账、Codex Goal 执行协议、验证策略、Blocked 处理和 Plan 变更记录
- 当前 `git status --short --branch`

请从第一个状态不是 `done` 的步骤开始。默认一次只执行一个写入步骤；只有主 Plan 的并行组明确标记为只读或 parallel-safe 时，才启动多个 Agent / Worker。每步都要按对应小 Plan 实现、验证、Review、修复或记录发现，并回填执行台账。所有步骤完成后执行最终全局 Review 和整体验证。

核心注意点：只修改 `awiki-open-server`，不要修改 sibling repo 或 `AGENTS.md`；v0.1 不使用邮件/手机号验证，不引入阿里云；`awiki.info` 只能作为远端互通 peer；P2 兼容项不得阻塞 Step 04 公网 direct interop gate。
```

## 10. 小 Plan 摘要

### Step 01：MVP scope freeze 文档收敛

- 小 Plan：[steps/01-scope-freeze-docs.md](steps/01-scope-freeze-docs.md)
- 目标：文档统一到 v0.1 P0/P1/P2，并修正旧 Step 27 状态。
- 路径：`awiki-open-server/require.md`、`awiki-open-server/README.md`、`awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md`、本 Plan。
- 验证方式：`rg` 检查手机/邮箱/阿里云默认能力表述；Review scope creep。

### Step 02：默认禁用 contact verification

- 小 Plan：[steps/02-disable-contact-verification.md](steps/02-disable-contact-verification.md)
- 目标：默认不提供 SMS/email/phone-bind/send_otp 验证流程。
- 路径：`awiki-open-server/src/awiki_open_server/app/settings.py`、`awiki-open-server/src/awiki_open_server/app/routes.py`、`awiki-open-server/src/awiki_open_server/services.py`、`awiki-open-server/tests/`、`awiki-open-server/scripts/`。
- 验证方式：focused pytest + full pytest + smoke。

### Step 03：本仓回归与 Rust CLI gate

- 小 Plan：[steps/03-local-verification.md](steps/03-local-verification.md)
- 目标：证明默认禁用 contact verification 不破坏 DID 注册、direct、group、attachment、Rust CLI local gate。
- 路径：只读运行命令；如失败，仅修本仓。
- 验证方式：compileall、pytest、ASGI smoke、cross-domain local、Rust CLI local。

### Step 04：Public rwiki.cn / awiki.info interop gate

- 小 Plan：[steps/04-public-interop-gate.md](steps/04-public-interop-gate.md)
- 目标：公网路由就绪后完成 `verify-public` 和真实双向 direct。
- 路径：`awiki-open-server/deploy/`、`awiki-open-server/scripts/`，必要时补本仓 gate。
- 验证方式：`verify-public`、真实 `rwiki.cn` ↔ `awiki.info` direct/inbox/history。

## 11. Review 策略

- 每步骤 Review：优先检查目标边界、默认行为、兼容风险、安全/隐私和测试覆盖。
- 并行组 Review：只读 explorer 结论由 Coordinator 统一吸收，不允许 explorer 写文件。
- 合并后 Review：检查 README/require/Plan/code/tests 叙述一致。
- 全局 Review：确认无 Aliyun/短信/邮件依赖，无默认 phone/email verification 路径，无 sibling repo 修改。

## 12. 验证策略

| 层级 | 适用 Step / 并行组 | 命令 / 检查 | 运行时机 | 预期证据 | 门禁结果 |
|---|---|---|---|---|---|
| Docs | Step 01 | `rg -n "Aliyun|阿里|短信|邮件|email|phone|otp" README.md require.md plan/20260703-awiki-open-server-mvp-reset plan/20260702-awiki-open-server-mvp/plan.md` | Step 01 Review | 默认能力表述均符合新边界 | pass |
| Focused Unit | Step 02 | `PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py::test_user_service_identity_compat_path_accepts_cli_did_document tests/test_identity_pages.py::test_contact_verification_routes_disabled_by_default tests/test_identity_pages.py::test_legacy_auth_and_ws_ticket_compat_routes tests/test_identity_pages.py::test_did_relationship_phone_bind_and_site_rpc_compat -q` | Step 02 commit 前 | 4 passed；默认禁用，显式 compat 可用 | pass |
| Repo Local | Step 03/04 | `PYTHONPATH=src python3 -m compileall -q src scripts tests` + `PYTHONPATH=src python3 -m pytest tests -q` | Step 03 和最终 Review | compileall pass；Step 03 44 passed；Step 04 补 DID document 校验后 47 passed | pass |
| Smoke | Step 03 | `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-mvp-reset-asgi` | Step 03 | pass | pass |
| Cross-domain Local | Step 03 | `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-mvp-reset-cross --clean` | Step 03 | pass | pass |
| Rust CLI Local | Step 03 | `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-mvp-reset-rust-cli --clean` | Step 03 | pass；phone/otp 仅占位 | pass |
| Public Gate | Step 04 | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.cn --did-domain rwiki.cn` | `rwiki.cn` 配置后 | 2026-07-03 22:36 CST pass：service DID document 200，single `ANPMessageService`，endpoint/serviceDid/authSchemes pass，healthz 200，capability pass，cross_domain_direct enabled，federation disabled | pass |
| Real Interop | Step 04 | 两个隔离 CLI workspace 分别连接 `https://rwiki.cn` 和 `https://awiki.info`，双向 direct/inbox/history | `verify-public` 后 | 2026-07-03 22:19-22:20 CST 双向 pass：`rwiki.cn -> awiki.info` message `msg-1886f11dae554754`；`awiki.info -> rwiki.cn` message `msg-1886f0a64010ebc5`。2026-07-03 22:40 CST 服务形态防护后复跑双向 pass：`rwiki.cn -> awiki.info` message `msg-1886aba5c219cefe`；`awiki.info -> rwiki.cn` message `msg-1886abacc4c1a11e`；两侧 inbox/history 均可见测试消息 | pass |

## 13. 文档更新

- Harness 文档：本次只读，不修改；如需要更新跨仓库摘要，记录后续事项。
- 子仓库文档：更新 `awiki-open-server/README.md`、`awiki-open-server/require.md`、旧主 Plan 和本 reset Plan。
- 本次生成的任务文档：`awiki-open-server/plan/20260703-awiki-open-server-mvp-reset/plan.md` 与 `steps/*.md`。

## 14. Commit 计划

- 每个完成、验证、Review 通过的步骤建议创建一个聚焦 commit。
- 当前工作区已有大量未提交 scaffold 和历史步骤变更；提交前必须先由用户确认是否要提交以及提交边界。
- 不把 sibling repo 变更纳入任何 commit。

## 15. Blocked 处理

| Blocker | Step | Agent | 并行组 | 证据 | 已尝试方案 | 影响范围 | 是否暂停同组 | 下一步决策 |
|---|---|---|---|---|---|---|---|---|
| 旧域 `rwiki.info` 未路由到本仓 | 04 | deploy-explorer/main | A | 2026-07-03 21:09 CST 复跑 `verify-public`：`/.well-known/did.json`、`/healthz`、`/anp-im/rpc` 404 | 只读运行 public gate | 历史证据，不再作为当前操作域 | 否 | 当前改用 `rwiki.cn` 配置和验证 |

## 16. Plan 变更记录

| 日期 | 变更 | 原因 | 影响步骤 | 是否需要 Review |
|---|---|---|---|---|
| 2026-07-03 | 创建 v0.1 MVP reset plan | 用户要求新增“不使用邮件/手机号验证、不引入阿里云”，并按 MVP 原则收敛后续开发 | 全部 | 是 |
| 2026-07-03 | Step 04 当前公网域从 `rwiki.info` 切换为 `rwiki.cn` | 用户确认 `rwiki.cn` 证书已配置到 nginx、解析已到本机，并要求使用该域名测试 | Step 04、deploy、README、scripts、tests | 是 |
| 2026-07-03 | Step 04 增加 signed DID document proof 修复 | 真实互通发现远端拒绝 peer auth；根因是注册时重写 CLI 已签名 DID document，导致 proof 失效 | Step 04、identity、messaging tests | 是 |
| 2026-07-03 | Step 04 增加 DID service shape 防护 | 只读 Review 发现 signed 用户 DID 文档可保留错误 service、自定义 service DID JSON 可漂移；补拒绝校验和 public gate `authSchemes` 检查 | Step 04、identity、CLI smoke、tests | 是 |

## 17. 风险与回滚

| 风险 | 缓解措施 | 回滚 / 回退方案 |
|---|---|---|
| 默认禁用 contact verification 影响旧 CLI 无 OTP 注册路径 | Rust CLI local gate 使用 placeholder `--phone --otp` 直接进入 DID register；无 OTP 的 send_otp 路径返回未启用 | 临时设置 `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=true` 仅做本地兼容测试 |
| 旧 README/API 清单仍让人误判本仓要全量复刻 User Service | README/require/Plan 明确 P0/P1/P2 和 P2 冻结 | 继续把边缘能力移到 Compatibility Appendix |
| 公网 Gate 长期 404 导致无法验收 | `rwiki.cn` 已通过 public gate；下一风险转为真实对端互通 | 如真实 `awiki.info` 拒绝，请记录 RPC error body 和服务日志 |
| 真实 awiki.info 拒绝本服务 signature/proof | 已发现 signed CLI DID document 被重写导致 proof 失效；已修复并通过双向互通 | 若复发，优先检查 DID document proof、service DID document、HTTP Signature 和 origin proof 透传 |

## 18. 最终全局 Review 与整体验证

- 触发条件：Step 01-04 本仓完成，或 Step 04 明确 blocked。
- Review 范围：目标文档、auth 默认行为、无 Aliyun/短信/邮件依赖、Rust CLI local gate、public interop 证据、signed DID document proof 保真。
- 重点关注：P0/P1/P2 一致性、contact verification 默认禁用、安全/隐私、无 sibling repo 修改、`AGENTS.md` 未修改。
- 整体验证命令 / 检查：见第 12 节。
- Review 发现：旧域 `rwiki.info` 公网路由未指向本仓，用户已要求改用 `rwiki.cn`；README API 列表原先仍易误读 contact routes 为 core，已改成 core + compatibility routes 并标明默认禁用；真实互通暴露 signed CLI DID document 被重写后 proof 失效，远端 `awiki.info` 因 peer auth 不成立拒绝。
- 已修复问题：文档目标已增加无邮件/手机号/阿里云约束；默认禁用 contact verification；旧 Step 27 状态不一致已修正；本地 gate 均通过；`rwiki.cn` 已配置为本仓公网域；signed CLI DID document 保持不变且必须只包含一个指向本服务的 `ANPMessageService`；unsigned legacy DID document 仍补齐 `ANPMessageService`；service DID document `authSchemes` 对齐 `bearer` / `didwba` 并纳入自定义 JSON 启动校验和 `verify-public` 检查；真实双向 direct/inbox/history 已通过。
- 剩余风险：真实互通依赖公网 DNS/nginx/systemd 和外部 `awiki.info` 可用性，环境变化后需要复跑 Step 04 gate；临时 CLI workspace 和消息证据不进入仓库；公共部署必须保持 `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false`。
- 最终证据：focused pytest 7 passed；compileall pass；全量 pytest 47 passed；ASGI smoke pass；cross-domain local pass；Rust CLI local pass；2026-07-03 22:36 CST public `verify-public https://rwiki.cn` pass；2026-07-03 22:19-22:20 CST 和 22:40 CST 两轮真实 `rwiki.cn` ↔ `awiki.info` 双向 direct/inbox/history pass。
- 最终 `git status`：`## main...origin/main`; modified `.gitignore`, `README.md`; untracked `AGENTS.md`, `deploy/`, `plan/`, `pyproject.toml`, `require.md`, `scripts/`, `src/`, `tests/`。`AGENTS.md` 未修改；未修改 sibling repo。
