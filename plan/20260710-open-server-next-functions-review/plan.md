# Plan：awiki-open-server 下一阶段功能补齐 Review

状态：in_progress  
DOC：`awiki-open-server/plan/20260710-open-server-next-functions-review/`  
Harness：`awiki-harness/`  
创建时间：2026-07-10  
恢复指针：Step 04 待启动；恢复时读取 Step 04 文档和本执行台账。

## 1. 目标

- 任务目标：系统 review `awiki-open-server` 当前实现、目标边界和参考对象，明确下一步应该补齐的功能、顺序、验证门禁和文档同步要求。
- 预期行为：后续 Codex Goal 可以只读取本 Plan 和对应 Step 文档，就能按步骤补齐功能、Review、验证、提交，并记录证据。
- 非目标：本次不直接改业务代码；不把 `user-service` 和 `message-service` 全量重写成 Python 版；不把商业版、E2EE、群管理、federation、多租户、短信/邮件/Aliyun 能力纳入 Community MVP。
- 完成标准：形成主 Plan、6 个小 Plan、执行台账、并行约束、Review/验证策略、风险与回滚、Codex Goal 提示词，并保留 Community MVP 边界。

## 2. Review 结论

当前 `awiki-open-server` 的 P0/P1 Community MVP 已经基本成型：本地单进程 FastAPI、SQLite、本地对象存储、DID 文档、User Service 兼容面、明文 direct、本地 group participant、attachment、sync/read-state、Rust CLI 本地 gate 和 `rwiki.cn` 公网只读 gate 都已覆盖。

下一步不应该扩张成“完整 User Service + Message Service 复制品”。优先级应当是：

1. 先复跑并固化真实公网互通 gate，尤其是 `rwiki.cn <-> awiki.info` 双向 direct。历史部署计划中记录的 `awiki.info` 服务 DID 文档密钥不一致问题，当前公网 DID 文档看起来已经被修复，但需要用隔离 Rust CLI 工作区重新跑完整双向证据。
2. 再硬化协议契约、错误映射和幂等性，避免当前 MVP 在重复请求、HTTP status、JSON-RPC 错误码、meta/profile/security_profile 校验上形成不稳定兼容。
3. 补附件生命周期与安全：expected size/digest、ticket 过期、slot 清理、配额和 MIME 基线。
4. 补 DID/auth 的生产安全边界：e1 DID/domain 策略、注册/更新 proof、token 生命周期、冲突错误稳定性。继续默认禁用 phone/email/Aliyun。
5. 补 sync/read-state/realtime 投影质量：事件 metadata、unread/updated 统计、hint/reconnect 约束，仍不引入 read-state sync event，除非先同步客户端兼容策略。
6. 最后把公开 gate 和跨仓库验证沉淀到 `awiki-system-test` 或稳定脚本，并同步 `awiki-open-server`、`deploy/` 和必要的 `awiki-harness` 文档。

## 3. Harness 上下文

| 来源 | 作用 |
|---|---|
| `awiki-harness/AGENTS.md` | 确认非平凡 AWiki 任务的阅读顺序、权威来源和验证要求。 |
| `awiki-harness/README.md` | 确认 harness 是控制面，不替代子仓库权威文档。 |
| `awiki-harness/context/00-context-map.md` | 路由到 Identity、Auth、Protocol、Message Flow、Storage、System Test 和 Client Architecture。 |
| `awiki-harness/context/02-repo-map.md` | 确认 `user-service`、`message-service`、`awiki-cli-rs2`、`awiki-system-test` 的职责边界。 |
| `awiki-harness/context/03-cross-repo-architecture.md` | 确认 legacy 与 v2 消息服务并存，`message-service` v2 是参考方向，不能按 legacy 行为照搬。 |
| `awiki-harness/context/20-rules-index.md` | 路由到架构、文档、AI coding、验证规则。 |
| `awiki-harness/context/30-tools-env.md` | 确认本地和跨仓库验证命令入口。 |
| `awiki-harness/context/40-verification.md` | 确认 L0-L3 验证级别和安全/协议 gate。 |
| `awiki-harness/context/50-task-workflow.md` | 确认任务拆分、context pack、analysis、solution plan、verification 的记录方式。 |
| `awiki-harness/context/nodes/identity.node.md` | 确认 DID/profile/e1/handle 展示字段与安全字段边界。 |
| `awiki-harness/context/nodes/auth.node.md` | 确认 auth/JWT/DID WBA 变更属于 L3，需要 security review。 |
| `awiki-harness/context/nodes/protocol.node.md` | 确认 ANP wire semantics 以 `anp` 为权威。 |
| `awiki-harness/context/nodes/message-flow.node.md` | 确认 direct/group/sync/read-state/realtime 的 v2 约束和常见误区。 |
| `awiki-harness/context/nodes/storage.node.md` | 确认数据模型变更必须同步 docs、fixtures、tests。 |
| `awiki-harness/context/nodes/system-test.node.md` | 确认跨服务行为应沉淀到 `awiki-system-test` 或明确 gate。 |
| `awiki-harness/context/nodes/client-architecture.node.md` | 确认 `awiki-cli-rs2/crates/im-core` 是客户端消息事实源，CLI/App 不应重新拼 wire。 |
| `awiki-harness/context/repo-profiles/message-service.md` | 参考 direct/group/attachment/sync/read-state v2 API 和验证入口。 |
| `awiki-harness/context/repo-profiles/user-service.md` | 参考 DID auth/profile/handle 兼容契约。 |
| `awiki-harness/context/repo-profiles/awiki-cli-rs2.md` | 参考 Rust CLI / im-core / Dart SDK 的客户端契约和验证命令。 |
| `awiki-harness/context/repo-profiles/awiki-system-test.md` | 参考跨服务 E2E 和可靠同步/read-state focused suite。 |
| `awiki-harness/rules/architecture-principles.md` | 确认 e1 DID policy、依赖方向、E2EE 边界和变更影响策略。 |
| `awiki-harness/rules/verification-policy.md` | 确认 L0-L3 证据和安全 gate。 |

## 4. 目标仓库上下文

| 来源 | 作用 |
|---|---|
| `awiki-open-server/require.md` | 当前产品边界和 Community Server MVP 目标。 |
| `awiki-open-server/README.md` | 当前实现能力、边界、配置、公开部署和 smoke 命令。 |
| `awiki-open-server/README.cn.md` | 中文用户说明，后续文档同步目标之一。 |
| `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md` | 早期 MVP 总计划，作为历史背景。 |
| `awiki-open-server/plan/20260703-awiki-open-server-mvp-reset/plan.md` | v0.1 reset 后 P0/P1/P2 边界，确认不做 phone/email/E2EE/federation/group admin。 |
| `awiki-open-server/plan/20260704-structure-anp-sdk-hardening/plan.md` | ANP SDK 0.8.8 pinning、模块拆分、测试硬化已完成。 |
| `awiki-open-server/plan/20260705-rwiki-cn-deployment/plan.md` | `rwiki.cn` 部署与历史 awiki.info 反向互通 blocker 证据；需要 Step 01 复核更新。 |
| `awiki-open-server/src/awiki_open_server/app/routes.py` | FastAPI route、public `/anp-im/rpc` allowlist、object download ticket route。 |
| `awiki-open-server/src/awiki_open_server/messaging/core.py` | direct/group/sync/read-state/capabilities/not_supported 主要行为。 |
| `awiki-open-server/src/awiki_open_server/attachments/core.py` | upload slot、commit object、download ticket 和 attachment grant 行为。 |
| `awiki-open-server/src/awiki_open_server/user_compat/core.py` | DID auth/profile/handle/token/agent compat 行为。 |
| `awiki-open-server/src/awiki_open_server/storage/db.py` | SQLite schema，含 messages、sync、attachments、tokens 和 agent compat 表。 |
| `awiki-open-server/src/awiki_open_server/shared/jsonrpc.py` | JSON-RPC dispatch、params normalization、错误响应行为。 |
| `awiki-open-server/tests/` | 当前 64 个本地测试、2 个 public gate 测试、direct/group/attachment/sync/read-state 覆盖。 |
| `awiki-open-server/scripts/awiki_open_cli.py` | smoke-asgi、smoke-cross-domain-local、smoke-rust-cli-local、verify-public 等 gate。 |

## 5. 参考对象

| 参考对象 | 参考方式 | 不照搬的能力 |
|---|---|---|
| `user-service/docs/api/README.md`、`did-auth.md`、`did-profile.md`、`handle.md` | DID auth/profile/handle 字段、错误、兼容路径和身份边界。 | phone/email/SMS/Aliyun、生产恢复、组织/企业、多租户、完整账号风控。 |
| `message-service/docs/architecture/final-architecture.md`、`docs/api/` | direct/group/attachment/sync/read-state 的 v2 契约、service DID/proof 和公开入口边界。 | Direct E2EE、Group E2EE、federation peer routes、跨域 group host、生产级多节点 runtime。 |
| `awiki-cli-rs2/docs/api/im-core-interface/04-message-interface.md`、`05-cli-adapter-interface.md`、`docs/api/im-core-public-api.md` | Rust CLI / im-core 对 direct、group、attachment、sync、read-state、realtime 的客户端期望。 | 在 CLI shell 或 App 中复制 wire 逻辑；服务端也不引入客户端私钥或 E2EE 状态。 |
| `awiki-system-test/` | 跨服务 E2E 和 future public gate 的归属位置。 | 为通过测试放宽服务端 contract 或引入降级 fallback。 |

## 6. 当前验证基线

本次 review 记录的当前基线：

| 检查 | 命令 | 结果 |
|---|---|---|
| 本地全量测试 | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests -q` | `64 passed, 2 skipped` |
| 公网 rwiki.cn system tests | `cd awiki-open-server && AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_rwiki_cn_system.py -q` | `2 passed` |
| ASGI smoke | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir .awiki-open-server/review-asgi` | pass |
| 本地双域 smoke | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root .awiki-open-server/review-cross --clean` | pass，双向 inbox delivery |
| Rust CLI local gate | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin ../awiki-cli-rs2/target/debug/awiki-cli --data-root .awiki-open-server/review-rust-cli --clean` | pass，注册、direct、group、people、site 均可用 |
| 公网部署只读验证 | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.cn --did-domain rwiki.cn` | pass |

备注：当前 workspace 中如果安装环境加载旧 `anp` 包，验证时继续使用 `PYTHONPATH=../anp/anp:src`，因为本仓 `pyproject.toml` pin `anp==0.8.8` 且 adapter 会 fail fast。

## 7. 影响分析

| 领域 / 仓库 / 模块 | 影响 | 权威文档或代码 |
|---|---|---|
| Public interop | 需要复跑 `rwiki.cn <-> awiki.info` 双向 direct，更新历史 blocker 和公开 gate 自动化。 | `awiki-open-server/plan/20260705-rwiki-cn-deployment/plan.md`, `awiki-open-server/scripts/awiki_open_cli.py` |
| Protocol / JSON-RPC | 需要稳定 ANP envelope、profile/security profile、idempotency、错误码和 HTTP status。 | `message-service/docs/api/`, `awiki-open-server/src/awiki_open_server/shared/jsonrpc.py`, `awiki-open-server/src/awiki_open_server/messaging/core.py` |
| Messaging | direct/group 需要重复请求、local/public admission、not_supported、cross-domain proof 更硬的测试。 | `awiki-open-server/src/awiki_open_server/messaging/core.py`, `awiki-open-server/tests/test_direct_messages.py`, `awiki-open-server/tests/test_group_participant.py` |
| Attachments | 需要补 digest/size 校验、ticket/slot 过期、quota/MIME、download route 过期判断。 | `awiki-open-server/src/awiki_open_server/attachments/core.py`, `awiki-open-server/src/awiki_open_server/app/routes.py`, `awiki-open-server/tests/test_attachments.py` |
| DID/Auth | 需要补 e1/domain policy、document proof、token 生命周期、冲突错误稳定性。 | `user-service/docs/api/did-auth.md`, `awiki-open-server/src/awiki_open_server/user_compat/core.py` |
| Sync/Read-state/Realtime | 需要对齐 v2 metadata projection、unread_count/updated_count、hint-only realtime 和 reconnect/backpressure。 | `message-service/docs/api/ANP-client-server-api-sync.md`, `ANP-client-server-api-read-state.md`, `awiki-open-server/src/awiki_open_server/messaging/core.py`, `awiki-open-server/src/awiki_open_server/app/realtime.py` |
| Cross-repo verification/docs | 需要把公共互通或 open-server gate 沉淀到稳定脚本、`awiki-system-test` 或 docs。 | `awiki-system-test/README.md`, `awiki-harness/context/40-verification.md`, `awiki-open-server/README.md` |

## 8. 假设与开放问题

### 假设

- `awiki-open-server` 继续定位为单进程 Community Server，不变成 hosted production platform。
- `awiki.info` 只作为真实 peer 和参考对象，不作为本仓认证、消息、存储、代理、fallback 或 runtime 后端。
- `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false` 仍是公网和默认配置；旧 CLI 的 phone/otp 参数只保留命令形态兼容。
- 当前阶段只要求 `e1` DID/profile。K1 输入应 fail closed 或明确 unsupported。
- Direct/group E2EE、federation、group creation/admin、Aliyun、phone/email verification、multi-tenant hosting 均保持 `not_supported` 或 disabled。

### 开放问题

- `rwiki.cn <-> awiki.info` 双向 live gate 需要可用的真实测试身份、OTP/token 或现有测试账号。若执行者无法取得这些凭据，Step 01 应记录 blocker，并先完成只读公开 DID/proof 检查。
- 是否把 public bidirectional interop 纳入 `awiki-system-test` 远端 suite，还是先保留在 `awiki-open-server/scripts/awiki_open_cli.py` 的 guarded smoke？本 Plan 默认先脚本固化，再在 Step 06 判断是否上移。
- JSON-RPC auth 失败是否要在所有 RPC route 上用 HTTP 401，还是保持 JSON-RPC 200 + error body 兼容旧客户端？Step 02 必须先做兼容性 Review，不能直接破坏 CLI/App。
- Attachment quota 和 MIME policy 的默认值需要选择保守配置。Step 03 默认以 Community 本地安全为主，不引入扫描/CDN/商业配额。
- Token refresh rotation 是否做为本轮必做，取决于现有 `user_compat` token 数据模型能否无迁移安全扩展；不能安全扩展时先记录为后续迁移。

## 9. 总体设计方法

- 设计边界：以 `require.md` 的 Community MVP 为上限，以 `message-service` v2 和 `user-service` API 文档作为参考契约，不复制商业能力。
- 关键决策：先补证据和 contract，再补安全生命周期；每个补齐项必须有 focused tests 和 Review，不以“能跑通 happy path”为完成标准。
- 兼容性策略：保留现有 `/im/rpc`、`/anp-im/rpc`、User Service compatibility paths、Rust CLI command shape 和 public allowlist。任何 JSON-RPC/HTTP status 变化都必须用兼容测试证明。
- 数据、协议、配置或迁移策略：SQLite schema 变化优先向后兼容，必要时增加轻量 migration/versioning；不删除已有 runtime 数据；公开配置新增项必须同步 README/deploy 示例。
- 风险控制：涉及 DID/auth/proof/public endpoint 的步骤按 L3 处理；涉及跨服务互通的步骤必须有 live 或 guarded public evidence；涉及 storage 的步骤需要数据安全和回滚说明。

## 10. 任务拆分

| Step | 标题 | 依赖 | 并行组 | Parallel-safe | 建议 Agent | 可并行对象 | 互斥资源 / 冲突路径 | 产出 | 小 Plan 文档 | Commit gate | 合并 / 验证门禁 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 01 | 复跑并固化公网互通 Gate | 无 | 串行 | 否 | coordinator | 只读公网检查可并行 | `scripts/awiki_open_cli.py`, `tests/`, `plan/20260705-rwiki-cn-deployment/plan.md` | live gate 证据、脚本/测试或文档更新 | [steps/01-public-interop-gate-refresh.md](steps/01-public-interop-gate-refresh.md) | 必须 | Public interop gate | done_with_residual_risk |
| 02 | 协议、错误映射和幂等性硬化 | Step 01 | 串行 | 否 | agent-protocol | 无 | `messaging/core.py`, `shared/jsonrpc.py`, `shared/errors.py`, storage schema | direct/group idempotency、错误/status 兼容测试 | [steps/02-protocol-error-idempotency-hardening.md](steps/02-protocol-error-idempotency-hardening.md) | 必须 | Local tests + cross-domain smoke | done |
| 03 | 附件生命周期与安全补齐 | Step 02 | 串行 | 否 | agent-attachments | 无 | `attachments/core.py`, `app/routes.py`, `storage/db.py` | digest/size、expiry、cleanup、quota/MIME tests | [steps/03-attachment-lifecycle-security.md](steps/03-attachment-lifecycle-security.md) | 必须 | Attachment focused tests | done |
| 04 | DID/Auth 注册 proof 与 token 生命周期硬化 | Step 03 | 串行 | 否 | agent-identity | 无 | `user_compat/core.py`, `storage/db.py`, route/auth tests | e1/domain policy、proof、token/冲突稳定性 | [steps/04-did-auth-token-hardening.md](steps/04-did-auth-token-hardening.md) | 必须 | Identity/auth focused tests + security review | pending |
| 05 | Sync、Read-state、Realtime 契约打磨 | Step 04 | 串行 | 否 | agent-sync | 无 | `messaging/core.py`, `app/realtime.py`, sync/read-state tests | metadata projection、unread 统计、hint/reconnect 行为 | [steps/05-sync-readstate-realtime-polish.md](steps/05-sync-readstate-realtime-polish.md) | 必须 | Sync/read-state/realtime focused tests | pending |
| 06 | 系统测试与文档同步 | Step 05 | 串行 | 否 | coordinator | 只读 docs review 可并行 | `README.md`, `README.cn.md`, `deploy/`, `plan/`, possible `awiki-system-test/`, possible `awiki-harness/` | 最终 docs、cross-repo gate、global review evidence | [steps/06-system-test-docs-sync.md](steps/06-system-test-docs-sync.md) | 必须，如有修改 | Final local + public + docs gates | pending |

## 11. 并行执行与多智能体分工

- 并行策略：实现阶段默认串行。当前补齐项共享公开协议、SQLite schema、`messaging/core.py`、`storage/db.py`、JSON-RPC 错误语义和 public gate 证据，过早并行会让 Review 和回归归因变差。
- 最大并行度：1 个写入型执行者。允许启动只读 review/验证 worker，但其不得修改文件。
- Coordinator：主执行者负责修改 Plan 状态、分配任何只读 worker、合并证据、Review、提交和最终台账。
- 串行原因：Step 02 和 Step 05 都触碰 `messaging/core.py`；Step 02/03/04 都可能触碰 `storage/db.py` 和公开错误语义；Step 06 依赖所有实际变更稳定后再同步文档和系统测试。

### Agent 分工

| Agent / Worker | 负责 Step | 责任边界 | 可修改路径 | 禁止修改路径 / 资源 | 交付物 | Review 责任 |
|---|---|---|---|---|---|---|
| coordinator | Step 01, Step 06, 全局集成 | 公开 gate、计划台账、最终 Review、docs sync | Step 文档指定路径 | 未经计划变更不得修改其他仓库代码 | commit + 验证证据 | 全局 Review |
| agent-protocol | Step 02 | direct/group/JSON-RPC/protocol hardening | Step 02 指定路径 | attachment lifecycle 和 auth token 之外路径 | focused commit + tests | 协议/兼容 Review |
| agent-attachments | Step 03 | attachment lifecycle/security | Step 03 指定路径 | DID/auth 和 sync 之外路径 | focused commit + tests | 安全/数据生命周期 Review |
| agent-identity | Step 04 | DID/auth/token hardening | Step 04 指定路径 | messaging sync 和 attachment 之外路径 | focused commit + tests | L3 security Review |
| agent-sync | Step 05 | sync/read-state/realtime polish | Step 05 指定路径 | Step 02 未完成前不得修改 shared protocol behavior | focused commit + tests | message-flow Review |

### 并行组

| Wave / 并行组 | 可并行 Step | 可并行原因 | 共享依赖 | 写入范围 | 依赖屏障 | 合并顺序 | Group gate / 验证责任 |
|---|---|---|---|---|---|---|---|
| 串行主线 | 无写入型并行 Step | 写入范围和公开契约重叠 | 公开协议、SQLite、JSON-RPC、Rust CLI gate | 单执行者逐步提交 | 每个 Step commit 完成后再启动下一 Step | 01 -> 02 -> 03 -> 04 -> 05 -> 06 | 每步 Step gate + 最终全局 gate |
| 只读辅助 | 任意 Step 的文档/测试证据复核 | 不修改文件，仅报告发现 | 当前 commit | 无写入 | Coordinator 明确授权 | 不合并代码 | Coordinator 记录发现并决定是否改 Plan |

### 互斥资源

| 资源 / 路径 / 契约 | 互斥原因 | 受影响 Step | 规则 |
|---|---|---|---|
| `awiki-open-server/src/awiki_open_server/messaging/core.py` | direct/group/sync/read-state 共享行为，冲突风险高 | Step 02, Step 05 | 同一时间只能一个写入型执行者修改 |
| `awiki-open-server/src/awiki_open_server/storage/db.py` | SQLite schema 和 migration/compat 风险 | Step 02, Step 03, Step 04 | 修改前必须更新当前 Step 的数据安全说明 |
| `awiki-open-server/src/awiki_open_server/shared/jsonrpc.py` | 公开 JSON-RPC/HTTP 兼容行为 | Step 02, Step 04 | 需要兼容 Review 和 CLI/public tests |
| `awiki-open-server/plan/20260705-rwiki-cn-deployment/plan.md` | 历史部署证据，不应被多个 Step 同时改写 | Step 01, Step 06 | Step 01 更新事实，Step 06 只做最终同步 |
| `awiki-harness/` 和 `awiki-system-test/` | 跨仓库 docs/test 需要稳定实现后再同步 | Step 06 | 只有 Step 06 可写，且要记录跨仓库 git status |

并行执行约束：

- 每个 Agent / Worker 只修改自己拥有的文件、模块或验证表面，不回退或覆盖其他 Agent 的修改。
- 只读 Worker 必须回报检查内容、命令、结果、阻塞和剩余风险，不得改文件。
- 需要越界修改、改变顺序、改变 public contract 或增加新仓库写入时，先更新本 Plan 的变更记录。
- Coordinator 在每步 commit 前后检查 `git status --short --branch`，并在最终阶段做组合 diff Review。

## 12. 执行台账

状态取值：`pending`、`in_progress`、`review`、`blocked`、`committed`、`done`。

| Step | 状态 | Agent / Owner | 并行组 | 分支 / worktree | 基线 commit | 开始时间 | 完成时间 | Commit | Review 证据 | 验证证据 | 合并状态 | 门禁状态 | 下一步 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 01 | done | coordinator | 串行 | `main` | `5621bc4` | 2026-07-10T10:52:16Z | 2026-07-10T10:56:55Z | Step 01 focused commit | Review 完成：未改业务代码；未放宽 public allowlist；未写入 token/private key/手机号；历史 deployment plan 保留原始失败并追加复核记录；完整 live gate 缺少有效 `awiki.info` 测试凭据，作为 residual risk 记录。 | `curl https://rwiki.cn/healthz` ok；`curl https://rwiki.cn/.well-known/did.json` ok；`curl https://awiki.info/.well-known/did.json` 显示 `did:wba:awiki.info#key-1=z6MkiwA2psGssYjWkUBdDkRpNWoaKJxDqQvvSx8dufNhxgry`；`verify-public` ok；`tests/test_rwiki_cn_system.py` 2 passed；`smoke-awiki-info` capability ok；`rwiki.cn` Rust CLI 本域 direct/inbox/history pass；完整 `rwiki.cn <-> awiki.info` live direct 未运行，原因是缺少有效 `awiki.info` 测试凭据。 | ready_for_next_step | partial_with_recorded_blocker | 启动 Step 02 |
| 02 | done | agent-protocol | 串行 | `main` | `a0afa8e` | 2026-07-10T10:58:33Z | 2026-07-10T11:07:17Z | `a8b2e3c` (`messaging: harden protocol errors and idempotency`) | Review 完成：direct/group 同 `message_id` 重放返回既有结果并带 `idempotent_replay`，不会写入重复消息或 sync event；冲突重复返回 `message_id_conflict` / `-32009` 且包含冲突字段；ANP envelope 明确校验 direct/group `profile` 和 `security_profile`；JSON-RPC HTTP 200 + error body 策略未改变；public `/anp-im/rpc` allowlist 和 unsupported 能力边界未放宽；SQLite 仅新增 nullable `operation_id` 列，兼容旧数据。剩余风险：未增加 `operation_id` 唯一索引，继续以 `message_id` 主键和运行时冲突判定为幂等边界。 | focused idempotency/meta tests 4 passed；`tests/test_direct_messages.py tests/test_group_participant.py tests/test_messaging_surface.py tests/test_route_config.py` 25 passed；`tests/test_protocol_anp_sdk.py` 9 passed；`smoke-cross-domain-local` pass；`tests -q` 66 passed, 2 skipped；`git diff --check` pass。 | ready_for_next_step | pass | 启动 Step 03 |
| 03 | done | agent-attachments | 串行 | `main` | `459f17e` | 2026-07-10T11:09:52Z | 2026-07-10T11:15:57Z | `0520718` (`attachments: enforce object lifecycle checks`) | Review 完成：slot 记录 expected size/digest/content_type/expires_at；upload/commit 均校验 slot 状态和过期；commit 校验 size、sha256、MIME allowlist 和 max bytes；download route 强制 ticket 未过期；cleanup helper 只清理 expired 非 committed slots 和 expired tickets；upload route 错误映射为 HTTP 4xx；未引入 E2EE、CDN、扫描或远端 object relay。剩余风险：新增 `AWIKI_MAX_ATTACHMENT_BYTES` 和 `AWIKI_ATTACHMENT_ALLOWED_MIME_TYPES` 配置尚未同步 README/deploy，按计划交给 Step 06。 | `tests/test_attachments.py` 6 passed；`tests/test_direct_messages.py tests/test_group_participant.py` 19 passed；`smoke-asgi --data-dir .awiki-open-server/attachment-asgi` pass；`tests -q` 68 passed, 2 skipped；`git diff --check` pass。 | ready_for_next_step | pass | 启动 Step 04 |
| 04 | pending | agent-identity | 串行 | 执行时填写 | 执行时填写 |  |  |  |  |  | not_started | pending | 等 Step 03 done |
| 05 | pending | agent-sync | 串行 | 执行时填写 | 执行时填写 |  |  |  |  |  | not_started | pending | 等 Step 04 done |
| 06 | pending | coordinator | 串行 | 执行时填写 | 执行时填写 |  |  |  |  |  | not_started | pending | 等 Step 05 done |

## 13. Codex Goal 执行协议

- 将本 Plan 作为执行进度的唯一事实来源。
- 启动或恢复前，读取本 Plan、当前小 Plan、执行台账和当前 `git status --short --branch`。
- 默认同一时间只执行一个写入型步骤；本 Plan 当前没有允许写入型并行的 Step。
- 恢复时，从第一个状态不是 `done` 的步骤继续。
- 每个步骤依次执行：标记 `in_progress`、实现、验证、Review、修复 Review 发现、提交、记录证据、标记 `done`。
- 上一个依赖步骤的完成工作未提交前，不要开始下一个依赖步骤。
- 改变范围、顺序、验收标准、公开契约、数据模型、验证策略或跨仓库写入范围前，先更新本 Plan。
- 每个完成步骤创建一个聚焦 commit；commit 前后都记录 `git status` 和纳入文件。
- 所有步骤完成后执行最终全局 Review 和整体验证。

## 13.1 Codex Goal 提示词

```text
请以 `awiki-open-server/plan/20260710-open-server-next-functions-review/plan.md` 为唯一规划入口，按文档执行完整实现。

开始前先读取：
- `awiki-open-server/plan/20260710-open-server-next-functions-review/plan.md`
- 当前第一个未 done 的 Step 文档
- 主 Plan 的执行台账、Codex Goal 执行协议、验证策略、Blocked 处理和 Plan 变更记录
- 当前 `git status --short --branch`

请从第一个状态不是 `done` 的步骤开始。默认一次只执行一个写入型步骤；本 Plan 当前没有允许写入型并行的 Step，只允许只读复核 worker 在 coordinator 授权下并行报告证据。每步都要按对应小 Plan 实现、验证、Review、修复或记录 Review 发现，然后创建一个聚焦 commit，并回填主 Plan 执行台账和 Step 执行状态。需要改变范围、顺序、验收标准、公开契约、数据模型、parallel-safe 标记、跨仓库写入范围或验证策略时，先更新 Plan 变更记录。

所有步骤完成后，执行最终全局 Review 和整体验证，记录实际命令、通过/失败/跳过数量、失败或跳过原因、剩余风险和最终工作区状态。

核心注意点：保持 Community MVP 边界，不引入 phone/email/Aliyun、E2EE、federation、群创建/管理或多租户托管；`awiki.info` 只能作为互通 peer；公网与 DID/auth/proof 变更按 L3 做 security review；验证时在本 workspace 优先使用 `PYTHONPATH=../anp/anp:src`；涉及跨仓库契约时同步 `awiki-open-server` docs，并检查是否需要更新 `awiki-system-test` 和 `awiki-harness`。
```

## 14. 小 Plan 摘要

### Step 01：复跑并固化公网互通 Gate

- 小 Plan：[steps/01-public-interop-gate-refresh.md](steps/01-public-interop-gate-refresh.md)
- 目标：复跑 `rwiki.cn <-> awiki.info` live gate，确认历史反向互通 blocker 是否已修复，并固化可重复验证入口。
- 设计方法：先只读验证 DID docs/capabilities，再用隔离 Rust CLI workspaces 做双向 direct；证据更新后再决定是否新增 guarded script/test。
- 实现方法：更新 smoke 脚本或文档，必要时更新 `plan/20260705-rwiki-cn-deployment/plan.md` 的 stale blocker。
- 路径：`awiki-open-server/scripts/awiki_open_cli.py`, `awiki-open-server/tests/`, `awiki-open-server/plan/20260705-rwiki-cn-deployment/plan.md`, `awiki-open-server/README.md`
- 建议 Agent：coordinator
- 并行组：串行
- Parallel-safe：否
- 验证方式：`verify-public`、guarded public tests、Rust CLI 双域 direct。
- Review 环节：检查公网证据、凭据脱敏、脚本不写真实 token。
- Commit 要求：一个聚焦 commit。
- 风险：live awiki.info 凭据不可用时只能记录 blocker，不得伪造通过。

### Step 02：协议、错误映射和幂等性硬化

- 小 Plan：[steps/02-protocol-error-idempotency-hardening.md](steps/02-protocol-error-idempotency-hardening.md)
- 目标：补 direct/group 重复请求语义、JSON-RPC/HTTP 错误兼容、meta/profile/security_profile 校验和稳定错误码。
- 设计方法：参考 `message-service` v2 API，先锁定兼容策略，再改服务端和 tests。
- 路径：`awiki-open-server/src/awiki_open_server/messaging/core.py`, `shared/jsonrpc.py`, `shared/errors.py`, `storage/db.py`, `tests/`
- Parallel-safe：否
- 验证方式：direct/group focused tests、route tests、本地 cross-domain smoke。
- Review 环节：重点看兼容性、错误码、重复 message/operation id 的数据一致性。

### Step 03：附件生命周期与安全补齐

- 小 Plan：[steps/03-attachment-lifecycle-security.md](steps/03-attachment-lifecycle-security.md)
- 目标：补 expected size/digest、download ticket expiry、slot expiry/cleanup、quota/MIME。
- 路径：`awiki-open-server/src/awiki_open_server/attachments/core.py`, `app/routes.py`, `storage/db.py`, `tests/test_attachments.py`
- Parallel-safe：否
- 验证方式：attachment focused tests、negative tests、full local tests。
- Review 环节：重点看 object access grant、过期票据、明文附件边界和无 E2EE secrets。

### Step 04：DID/Auth 注册 proof 与 token 生命周期硬化

- 小 Plan：[steps/04-did-auth-token-hardening.md](steps/04-did-auth-token-hardening.md)
- 目标：补 e1/domain policy、DID document proof、token/refresh 生命周期、duplicate/conflict 稳定错误。
- 路径：`awiki-open-server/src/awiki_open_server/user_compat/core.py`, `user_compat/http.py`, `app/routes.py`, `storage/db.py`, `tests/test_user_service_compat.py`, `tests/test_identity_documents.py`
- Parallel-safe：否
- 验证方式：identity/user compat focused tests、public rwiki.cn tests、security review。
- Review 环节：L3 security review，确保不引入 phone/email/Aliyun。

### Step 05：Sync、Read-state、Realtime 契约打磨

- 小 Plan：[steps/05-sync-readstate-realtime-polish.md](steps/05-sync-readstate-realtime-polish.md)
- 目标：对齐 sync metadata projection、read-state 统计和 realtime hint/reconnect 行为。
- 路径：`awiki-open-server/src/awiki_open_server/messaging/core.py`, `app/realtime.py`, `tests/test_sync_read_state.py`
- Parallel-safe：否
- 验证方式：sync/read-state focused tests、WebSocket tests、Rust CLI smoke。
- Review 环节：确认不把 checkpoint/read watermark 混用，不把 message content 放进 sync event payload。

### Step 06：系统测试与文档同步

- 小 Plan：[steps/06-system-test-docs-sync.md](steps/06-system-test-docs-sync.md)
- 目标：把补齐后的 gate、边界和剩余风险同步到 docs，必要时纳入 `awiki-system-test` 或 stable guarded scripts。
- 路径：`awiki-open-server/README.md`, `README.cn.md`, `deploy/`, `plan/`, possible `awiki-system-test/`, possible `awiki-harness/`
- Parallel-safe：否
- 验证方式：full local tests、public tests、smokes、docs checks、必要的 harness validation。
- Review 环节：最终全局 Review 和整体验证。

## 15. Review 策略

- 每步骤 Review：代码完成后、commit 前执行，优先看 correctness、regression、contract compatibility、missing tests、docs drift。
- 合并后 Review：每个 Step commit 后检查 `git status`、commit 范围和下一步依赖是否仍成立。
- 全局 Review：所有 Step 完成后，跨 `awiki-open-server`、可能的 `awiki-system-test`、可能的 `awiki-harness` 做组合 diff Review。
- 契约 / 安全 / 隐私 Review：Step 02、Step 04、public `/anp-im/rpc`、DID/auth/proof、attachment ticket 属于重点。
- 文档 Review：确保 docs 只记录 Community 真实能力，不把 unsupported 能力说成已实现。

## 16. 验证策略

| 层级 | 适用 Step / 并行组 | 命令 / 检查 | 运行时机 | 预期证据 | 门禁结果 |
|---|---|---|---|---|---|
| Step focused | Step 01 | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.cn --did-domain rwiki.cn` | Step 01 commit 前 | `ok=true` | pending |
| Step focused | Step 01 | Rust CLI 隔离 workspace 做 `rwiki.cn <-> awiki.info` 双向 direct | Step 01 commit 前 | 两边 inbox/history 可见消息，或 blocker 证据 | pending |
| Step focused | Step 02 | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_direct_messages.py tests/test_group_participant.py tests/test_messaging_surface.py tests/test_route_config.py -q` | Step 02 commit 前 | 25 passed | pass |
| Step focused | Step 03 | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_attachments.py -q` | Step 03 commit 前 | 6 passed | pass |
| Step focused | Step 04 | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_user_service_compat.py tests/test_identity_documents.py tests/test_profile_compat.py tests/test_agent_compat.py -q` | Step 04 commit 前 | pass | pending |
| Step focused | Step 05 | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_sync_read_state.py tests/test_messaging_surface.py -q` | Step 05 commit 前 | pass | pending |
| Repo local | Steps 02-06 | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests -q` | 每个代码 Step 或 final 前 | Step 03：68 passed, 2 skipped | pass_for_step_03 |
| Smoke | Steps 02, 05, 06 | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root .awiki-open-server/cross-domain-local --clean` | 相关 Step commit 前或 final | Step 02：pass，双向 inbox delivery | pass_for_step_02 |
| Rust CLI smoke | Steps 02-06 | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin ../awiki-cli-rs2/target/debug/awiki-cli --data-root .awiki-open-server/rust-cli --clean` | final 前，或影响 CLI 契约时 Step 前 | pass | pending |
| Public system | Steps 01, 06 | `cd awiki-open-server && AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_rwiki_cn_system.py -q` | Step 01 / final | pass | pending |
| Docs | Step 06 | `cd awiki-harness && python scripts/validate-docs.py && python scripts/check-drift.py` | 如果 Step 06 修改 harness 或最终 docs sync 前 | pass 或记录未改 harness 的原因 | pending |
| Cross-repo | Step 06 | `cd awiki-system-test && ...` focused gate | 只有实际纳入 `awiki-system-test` 时 | pass 或具体 skip/blocker | pending |

如果某个命令不能运行，执行者必须记录原因、影响和替代证据，不能把未运行命令写成通过。

## 17. 文档更新

- Harness 文档：只有当 public gate、跨仓库架构、验证入口或 repo map 发生变化时，Step 06 才修改 `awiki-harness/`；否则记录检查过的文档和“不需要更新”的理由。
- 子仓库文档：`awiki-open-server/README.md`、`README.cn.md`、`deploy/README.md` 或相关 deployment plan 需要同步真实 gate、配置、边界和残余风险。
- 本次生成的任务文档：本目录的 `plan.md` 和 `steps/*.md` 是后续执行台账和 evidence 入口。

## 18. Commit 计划

- 每个完成、验证、Review 通过的步骤创建一个聚焦 commit。
- Commit 前记录 `git status --short --branch` 和纳入文件。
- Commit 后记录 commit hash 和工作区状态。
- 不把所有步骤的修改积累到一个最终大 commit。
- 如果某步需要跨仓库修改，先检查对应仓库 `git status --short --branch`，只提交该 Step 聚焦范围。
- 只有最终集成确实修改文件时才创建最终集成 commit。

## 19. Blocked 处理

| Blocker | Step | Agent | 并行组 | 证据 | 已尝试方案 | 影响范围 | 是否暂停同组 | 下一步决策 |
|---|---|---|---|---|---|---|---|---|
| live awiki.info 凭据不可用 | 01 | coordinator | 串行 | 执行时填写 | 只读 DID/proof 检查、capability smoke | 当前步骤 | 是 | 记录 blocker；继续只做不依赖凭据的脚本/docs 改进需先更新 Step 01 |
| JSON-RPC HTTP status 破坏旧 CLI/App | 02 | agent-protocol | 串行 | 执行时填写 | 兼容测试、feature flag 或保持 200 + error body | 当前步骤/公开契约 | 是 | 先固定兼容策略，再改实现 |
| SQLite schema 变更无法安全迁移 | 02-04 | 对应 agent | 串行 | 执行时填写 | 增加兼容列、轻量 migration 或降级为 runtime 校验 | 当前步骤/后续步骤 | 是 | 更新 Plan 和数据安全说明 |
| Public gate 失败但本地 pass | 01/06 | coordinator | 串行 | 执行时填写 | 区分远端 peer、DNS/proxy、service DID/proof、本仓 regression | 当前步骤或整体发布 | 是 | 记录根因和是否阻塞下一步 |

- 只有依赖允许且风险已记录时，才继续另一个 pending 步骤。
- 如果 blocker 影响共享契约、shared schema、public gate 或 commit 顺序，必须暂停后续步骤。
- 只有没有安全假设、回退方案或独立下一步时，才询问用户。

## 20. Plan 变更记录

| 日期 | 变更 | 原因 | 影响步骤 | 是否需要 Review |
|---|---|---|---|---|
| 2026-07-10 | 创建下一阶段功能补齐 review plan | 用户要求系统 review 下一步补齐功能 | 全部 | 是 |

## 21. 风险与回滚

| 风险 | 缓解措施 | 回滚 / 回退方案 |
|---|---|---|
| 为追齐参考服务而越过 Community MVP 边界 | 每步列明非目标和 unsupported 能力；Review 检查 capabilities/not_supported | 回退新增能力或改为 explicit `not_supported` |
| JSON-RPC/HTTP status 改动破坏旧 CLI/App | 先补兼容测试，必要时保持旧行为并只稳定 error payload | 回退 status 行为，保留新增错误码测试 |
| SQLite schema 改动损坏现有数据 | 向后兼容列、迁移测试、备份说明 | 回退迁移，保留旧表和 runtime 校验 |
| Public gate 依赖外部 peer 状态 | 区分本仓回归和远端问题，记录日期、DID doc、签名、错误 | 保留本地 cross-domain smoke 和只读 public verify 作为替代证据 |
| Attachment ticket/digest hardening 破坏历史对象 | 过期/校验只应用到新 ticket/slot 或提供兼容路径 | 回退新策略，保留安全测试为后续 |
| Auth proof/token hardening 破坏开发兼容 | 保持 dev compat config 明确 disabled/enabled，默认生产安全 | 通过配置回退 dev-only shim，不改变公网默认 |

## 22. 最终全局 Review 与整体验证

- 触发条件：所有 Step 完成、Review、验证并提交后执行。
- Review 范围：全部变更仓库、公开 API、SQLite schema、配置、tests、docs、执行台账、残余风险、工作区状态。
- 重点关注：Community MVP 边界、public `/anp-im/rpc` allowlist、DID/auth/proof 安全、attachment access grant、sync/read-state checkpoint 边界、Rust CLI 和 public interop 兼容、文档漂移。
- 并行执行审计：确认没有写入型并行越界；如使用只读 worker，记录其报告和 coordinator 处理结果。
- 整体验证命令 / 检查：至少运行 `awiki-open-server` full tests、local cross-domain smoke、Rust CLI smoke、public guarded tests；如果修改 `awiki-system-test` 或 `awiki-harness`，运行对应验证命令。
- Review 发现：执行时填写。
- 已修复问题：执行时填写。
- 剩余风险：执行时填写。
- 最终证据：执行时填写。
- 最终 `git status`：执行时填写。
- 如果本阶段修改文件：记录 Review、验证和最终集成 commit。
