# Plan：结构收敛与 ANP SDK 0.8.8 接入

状态：done  
DOC：`awiki-open-server/plan/20260704-structure-anp-sdk-hardening/`  
Harness：`awiki-harness/`  
创建时间：2026-07-04  
恢复指针：全部步骤已完成并提交；计划结束

## 1. 目标

- 任务目标：修复当前 review 暴露的结构问题，并把 ANP 协议核心从本仓手写实现迁移到 ANP Python SDK `anp==0.8.8`。
- 预期行为：`awiki-open-server` 继续保持单进程、SQLite、本地对象存储和 Community MVP 边界；User Service 兼容路由仍由本仓本地实现，不代理、不调用、不修改相邻 `user-service`。
- 非目标：不实现手机/邮箱验证、阿里云依赖、E2EE、联邦服务、群创建/管理、多租户托管，也不迁移到 MySQL/Redis。
- 完成标准：ANP SDK 0.8.8 被作为协议权威接入；路径配置与实际路由一致；`services.py` 和 `routes.py` 的主要 User Service / messaging / attachment 职责被拆出；测试拆分；本地、Rust CLI、rwiki.cn 公网 gate 通过或记录明确 blocker。

## 2. Harness 上下文

| 来源 | 作用 |
|---|---|
| `awiki-harness/AGENTS.md` | 多仓库任务读取顺序和完成标准 |
| `awiki-harness/context/00-context-map.md` | 将任务归入 Protocol、Auth、Identity、Message Flow、Storage |
| `awiki-harness/context/02-repo-map.md` | 确认 `anp` 是协议/SDK 来源，`user-service` 是身份参考源 |
| `awiki-harness/context/03-cross-repo-architecture.md` | 确认服务不得持有客户端私钥，open-server 不应代理线上服务 |
| `awiki-harness/context/nodes/protocol.node.md` | ANP 协议细节以 `anp/` 为权威 |
| `awiki-harness/context/nodes/auth.node.md` | 身份/认证变更属于 L3，需要 security review |
| `awiki-harness/context/nodes/identity.node.md` | DID/Profile/Handle 字段边界和展示字段安全边界 |
| `awiki-harness/context/nodes/message-flow.node.md` | direct/group/sync/read-state 的消息边界 |
| `awiki-harness/rules/architecture-principles.md` | 依赖方向、协议/身份安全边界和变更影响策略 |
| `awiki-harness/rules/verification-policy.md` | L3 验证要求 |

## 3. 影响分析

| 领域 / 仓库 / 模块 | 影响 | 权威文档或代码 |
|---|---|---|
| Protocol / `anp` | 采用 `anp==0.8.8`，复用 DID WBA、HTTP Signature、origin proof、Content-Digest | `anp/anp/pyproject.toml`, `anp/anp/anp/authentication/__init__.py`, `anp/anp/anp/proof/rfc9421_origin.py` |
| Auth / User Service compat | 参考 User Service 的 DID Auth、Profile、Users、Handle shape，但本仓本地实现 | `user-service/docs/api/did-auth.md`, `user-service/docs/api/did-profile.md`, `user-service/docs/api/users.md`, `user-service/docs/api/handle.md` |
| `awiki-open-server` 路由 | 让配置路径与实际 FastAPI route 一致，避免 DID 文档指向未挂载 endpoint | `awiki-open-server/src/awiki_open_server/app/settings.py`, `awiki-open-server/src/awiki_open_server/app/routes.py` |
| `services.py` | 拆出协议 adapter、User Service compat、messaging、attachments，降低单体文件风险 | `awiki-open-server/src/awiki_open_server/services.py` |
| Storage | 保持 SQLite，不引入 MySQL/Redis；整理 schema/seed/sequence helper | `awiki-open-server/src/awiki_open_server/storage/db.py` |
| Tests | 拆分大测试文件，新增 SDK parity 和 route config tests | `awiki-open-server/tests/` |
| Docs / deploy | 同步 ANP SDK 0.8.8、路径配置、MVP 边界、验证命令 | `awiki-open-server/README.md`, `awiki-open-server/AGENTS.md`, `awiki-open-server/deploy/` |

## 4. 假设与开放问题

### 假设

- 使用 `anp==0.8.8` 是明确版本决策；User Service 当前 `anp==0.8.7` 仅作为历史参考，不阻止本仓升级到 0.8.8。
- `anp` 包可从 PyPI 安装，或通过 workspace sibling `anp/anp` editable source 在本地验证；发布时以 `anp==0.8.8` 为准。
- `awiki-open-server` 仍只修改本仓，不修改 `user-service`、`message-service`、`awiki-cli-rs2` 或 `anp`。

### 开放问题

- ANP SDK 0.8.8 的 HTTP Signature / origin proof 对线上 `awiki.info` 的实际兼容性需由公网 gate 验证。
- 如果 SDK 0.8.8 与 User Service 0.8.7 返回 shape 或签名细节存在差异，本计划优先保持 wire 兼容，并在 adapter 层做薄适配，不回退到手写协议核心。

## 5. 总体设计方法

- 设计边界：协议验证与签名交给 ANP SDK 0.8.8；产品边界、SQLite 持久化、Community not_supported 策略留在本仓。
- 关键决策：新增 `protocol/anp_adapter.py` 作为唯一 SDK 接入层，禁止业务模块直接散落导入 ANP SDK。
- 兼容性策略：保持现有 JSON-RPC 方法、路径和 response shape；User Service 路由使用本仓 `identity` / `user_compat` 模块实现。
- 数据与迁移策略：不做破坏性 schema 迁移；只整理 helper、seed 和序列生成位置，保留旧库可启动。
- 风险控制：每个步骤小范围提交；协议变更先跑 focused SDK parity tests，再跑全量本仓测试、Rust CLI local gate、rwiki.cn public gate。

## 6. 任务拆分

| Step | 标题 | 依赖 | 并行组 | Parallel-safe | 建议 Agent | 可并行对象 | 互斥资源 / 冲突路径 | 产出 | 小 Plan 文档 | Commit gate | 合并 / 验证门禁 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 01 | ANP SDK 0.8.8 接入与协议 adapter | 无 | A | 否 | agent-protocol | 无 | `pyproject.toml`, `service_identity.py`, `services.py` 协议函数 | SDK 依赖、adapter、parity tests | [steps/01-anp-sdk-adapter.md](steps/01-anp-sdk-adapter.md) | 必须 | SDK parity gate | done |
| 02 | 路径配置与公开 endpoint 对齐 | Step 01 | B | 是 | agent-routing | Step 03 | `app/routes.py`, `app/settings.py`, `deploy/*` | 配置路径真实挂载，文档同步 | [steps/02-route-config-alignment.md](steps/02-route-config-alignment.md) | 必须 | Route config gate | done |
| 03 | User Service 兼容模块拆分 | Step 01 | B | 是 | agent-user-compat | Step 02 | `services.py` identity/profile/handle/users/auth compat 区域 | `identity/` 或 `user_compat/` 模块 | [steps/03-user-service-compat-refactor.md](steps/03-user-service-compat-refactor.md) | 必须 | User compat gate | pending |
| 04 | Messaging 与 attachment 模块拆分 | Step 02, Step 03 | C | 否 | agent-messaging | 无 | `services.py` direct/group/sync/attachment, `storage/db.py` | `messaging/`, `attachments/`, storage helpers | [steps/04-messaging-attachment-refactor.md](steps/04-messaging-attachment-refactor.md) | 必须 | Messaging gate | pending |
| 05 | 测试拆分与验证矩阵收敛 | Step 04 | D | 是 | agent-tests | Step 06 | `tests/` | 测试按域拆分、helpers 抽取 | [steps/05-test-suite-split.md](steps/05-test-suite-split.md) | 必须 | Full local gate | pending |
| 06 | 文档、部署示例与最终 L3 验证 | Step 04 | D | 是 | agent-docs | Step 05 | `README.md`, `AGENTS.md`, `deploy/*`, Plan docs | docs 同步、rwiki.cn/public gate 证据 | [steps/06-docs-final-verification.md](steps/06-docs-final-verification.md) | 必须 | Final L3 gate | pending |

## 7. 并行执行与多智能体分工

- 并行策略：Step 01 必须串行完成，因为它定义 ANP SDK adapter 契约。Step 02 与 Step 03 可在 Step 01 后并行。Step 04 依赖路由和 User compat 合并后串行。Step 05 与 Step 06 可在 Step 04 后并行，但最终文档需要等测试路径稳定后由 Coordinator 合并。
- 最大并行度：2。
- Coordinator：主执行者负责 Plan 状态、合并顺序、Review、最终验证和提交证据。
- 串行原因：协议 adapter、`services.py` 拆分和 storage helper 是共享契约，不允许并行修改同一大文件区域。

### Agent 分工

| Agent / Worker | 负责 Step | 责任边界 | 可修改路径 | 禁止修改路径 / 资源 | 交付物 | Review 责任 |
|---|---|---|---|---|---|---|
| agent-protocol | Step 01 | ANP SDK adapter 和协议 parity | `awiki-open-server/src/awiki_open_server/protocol/`, `pyproject.toml`, focused tests | 相邻仓库源码 | commit + parity 证据 | Coordinator 做安全 review |
| agent-routing | Step 02 | route config 对齐 | `app/routes.py`, `app/settings.py`, `deploy/*`, route tests | User compat 业务拆分 | commit + route tests | Coordinator 查 DID endpoint 一致性 |
| agent-user-compat | Step 03 | User Service compat 模块 | `identity/`, `user_compat/`, `services.py` 对应搬迁, tests | messaging/attachment 逻辑 | commit + compat tests | Coordinator 查不引入外部依赖 |
| agent-messaging | Step 04 | messaging/attachment/storage helper | `messaging/`, `attachments/`, `storage/db.py`, focused tests | User compat route shape | commit + messaging smoke | Coordinator 查 public `/anp-im/rpc` 白名单 |
| agent-tests | Step 05 | 测试拆分和 helpers | `tests/` | 源码重构 | commit + full pytest | Coordinator 查 coverage 不丢失 |
| agent-docs | Step 06 | docs 和最终验证记录 | `README.md`, `AGENTS.md`, `deploy/*`, Plan docs | 源码行为改动 | commit + docs/final evidence | Coordinator 做 L3 final review |

### 并行组

| Wave / 并行组 | 可并行 Step | 可并行原因 | 共享依赖 | 写入范围 | 依赖屏障 | 合并顺序 | Group gate / 验证责任 |
|---|---|---|---|---|---|---|---|
| A | Step 01 | 串行协议基础 | 无 | SDK adapter | 无 | 01 | SDK parity gate |
| B | Step 02, Step 03 | 路由配置与 User compat 拆分写入面可控 | Step 01 adapter | routing vs user_compat | Step 01 commit | 02 -> 03 -> group pytest | Route + User compat gate |
| C | Step 04 | 串行 shared service/storage | Step 02/03 | messaging/attachment/storage | Wave B 完成 | 04 | Messaging smoke gate |
| D | Step 05, Step 06 | 测试拆分与文档可并行，但 docs 最终证据需等测试结果 | Step 04 | tests vs docs | Step 04 commit | 05 -> 06 -> final gate | Full local + L3 gate |

### 互斥资源

| 资源 / 路径 / 契约 | 互斥原因 | 受影响 Step | 规则 |
|---|---|---|---|
| `awiki-open-server/src/awiki_open_server/services.py` | 大文件拆分源，容易冲突 | Step 01, 03, 04 | 同一时间只能一个步骤修改相同函数区段 |
| ANP wire contract | 影响 DID/auth/direct public interop | Step 01, 04, 06 | 需要 L3 review 和公网 gate |
| `awiki-open-server/tests/conftest.py` / helpers | 测试基础设施共享 | Step 05 与所有 step | Step 05 前只做必要 focused 添加 |
| `README.md` API/命令说明 | docs 需反映最终行为 | Step 02, 06 | Step 06 统一收敛最终文档 |

## 8. 执行台账

| Step | 状态 | Agent / Owner | 并行组 | 分支 / worktree | 基线 commit | 开始时间 | 完成时间 | Commit | Review 证据 | 验证证据 | 合并状态 | 门禁状态 | 下一步 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 01 | done | agent-protocol | A | main | 2b7c467 | 2026-07-04 10:26:58 +0800 | 2026-07-04 10:42:05 +0800 | 6d8c1cf | 本地 review + 并行 reviewer 通过：SDK import 集中在 adapter；未扩大 `/anp-im/rpc` 白名单；未引入手机/邮箱/Aliyun/E2EE/federation/group management；删除旧手写 HTTP Signature / origin proof helper；已补 HTTP signature SDK 异常映射和负例测试。 | `PYTHONPATH=../anp/anp:src python3 -m pytest tests -q` 56 passed, 2 skipped；compileall pass；cross-domain local smoke ok=true。标准 `PYTHONPATH=src` 被本机 `anp 0.6.8` 阻断，安装 0.8.8 受 PyPI SSL / hatchling 限制。 | committed | pass_with_explicit_sdk_path | 进入 Step 02/03 Wave B |
| 02 | done | agent-routing | B | main | ec6b8d6 | 2026-07-04 10:49:36 +0800 | 2026-07-04 10:53:13 +0800 | db7f6e8 | 本地 review 通过：Settings 路径驱动 route 注册；public 白名单未扩大；README/env 示例同步。 | `PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_route_config.py -q` 4 passed；smoke-asgi ok=true；全量 tests 60 passed, 2 skipped；cross-domain smoke ok=true。 | committed | pass_with_explicit_sdk_path | 等待 Step 03 |
| 03 | done | agent-user-compat | B | main | d0102d0 | 2026-07-04 11:10:42 +0800 | 2026-07-04 11:24:23 +0800 | ada9e42 | 本地 review + 只读 explorer：`user_compat/core.py` handler maps 覆盖完整；新增 `user_compat/http.py` 修复 package import 阻塞；`routes.py` 只保留 HTTP 薄转发；`services.py` 删除重复 User Service compat 实现并 re-export `user_compat.core` 身份表面；未引入生产短信/邮件、Aliyun、Redis/MySQL 或外部 User Service 调用；public `/anp-im/rpc` 白名单未变。 | `PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_user_service_compat.py tests/test_identity_pages.py -q` 19 passed；compileall pass；`PYTHONPATH=../anp/anp:src python3 -m pytest tests -q` 64 passed, 2 skipped；smoke-asgi ok=true；cross-domain local smoke ok=true。 | committed | pass_with_explicit_sdk_path | 进入 Step 04 |
| 04 | done | agent-messaging | C | main | 0a51905 | 2026-07-04 11:28:14 +0800 | 2026-07-04 11:46:44 +0800 | 1b5ab25 | 本地 review + 只读 explorer：`services.py` 瘦身为兼容 facade；新增 `messaging/core.py`、`attachments/core.py`、`shared/runtime.py`；`routes.py` public allowlist 仍只暴露 `anp.get_capabilities`、`direct.send`、`group.get_info`、`group.join`、`attachment.get_download_ticket`；测试 monkeypatch 已跟随新模块边界；未引入 federation/E2EE/群管理/外部服务代理。 | compileall pass；`PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_messaging_objects.py tests/test_route_config.py -q` 28 passed；`PYTHONPATH=../anp/anp:src python3 -m pytest tests -q` 64 passed, 2 skipped；smoke-asgi ok=true；cross-domain local smoke ok=true；production code forbidden dependency/domain scan pass。 | committed | pass_with_explicit_sdk_path | 进入 Step 05/06 |
| 05 | done | agent-tests | D | main | 436be5d | 2026-07-04 11:48:30 +0800 | 2026-07-04 11:54:17 +0800 | b1cff01 | 本地 review：旧 `test_identity_pages.py` 和 `test_messaging_objects.py` 已按域拆分；`tests/helpers.py` 只包含本地测试构造 helper；`tests/test_rwiki_cn_system.py` 仍默认 skip 并改用 helper 导入；未修改源码行为。 | compileall pass；`PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_messaging_surface.py tests/test_direct_messages.py tests/test_group_participant.py tests/test_attachments.py tests/test_sync_read_state.py tests/test_identity_documents.py tests/test_contact_auth_compat.py tests/test_profile_compat.py tests/test_agent_compat.py tests/test_site_relationships.py -q` 39 passed；`PYTHONPATH=../anp/anp:src python3 -m pytest tests -q` 64 passed, 2 skipped。 | committed | pass_with_explicit_sdk_path | 进入 Step 06 |
| 06 | done | agent-docs | D | main | 96e4dbf | 2026-07-04 11:55:54 +0800 | 2026-07-04 11:59:52 +0800 | 6a3cd4b | 本地 review + 只读 explorer：README/AGENTS/deploy 已同步 ANP SDK 0.8.8、模块结构、测试拆分、rwiki.cn 部署边界、contact verification 禁用和公网 nginx route；扫描确认生产代码未新增 `awiki.info` 代理、Aliyun、Redis/MySQL 或相邻服务依赖。 | compileall pass；`PYTHONPATH=../anp/anp:src python3 -m pytest tests -q` 64 passed, 2 skipped；ASGI smoke ok=true；cross-domain local smoke ok=true；Rust CLI local smoke ok=true；`verify-public https://rwiki.cn` ok=true；public system tests 2 passed；diff check pass。 | committed | pass_with_explicit_sdk_path | 计划结束 |

## 9. Codex Goal 执行协议

- 将本 Plan 作为执行进度的唯一事实来源。
- 启动或恢复前，读取本 Plan、当前小 Plan、执行台账和当前 `git status --short --branch`。
- 默认同一时间只执行一个步骤；只有任务拆分表和并行分工同时标记 parallel-safe 的步骤，才启动多个 Agent / Worker 并行处理对应 Wave。
- 并行执行时，Coordinator 必须分配清晰的文件 / 模块 / 验证所有权，要求每个 Agent / Worker 不回退或覆盖他人修改，并在合并前收集变更路径、命令、测试结果、阻塞和剩余风险。
- 每个步骤依次执行或在 parallel-safe Wave 内并行执行：标记 `in_progress`、实现、验证、Review、修复 Review 发现、提交、记录证据、标记 `done`。
- 改变范围、顺序、验收标准、公开契约、数据模型或验证策略前，先更新本 Plan。

## 9.1 Codex Goal 提示词

```text
请以 `awiki-open-server/plan/20260704-structure-anp-sdk-hardening/plan.md` 为唯一规划入口，按文档执行完整实现。

开始前先读取主 Plan、当前第一个未 done 的 Step 文档、执行台账、Codex Goal 执行协议、验证策略、Blocked 处理、Plan 变更记录，并运行 `git status --short --branch`。

请从第一个状态不是 `done` 的步骤开始。默认一次只执行一个步骤；只有主 Plan 明确标记 parallel-safe 的 Wave 才尽量启动多个 Agent / Worker，并分配清晰文件/模块/验证所有权。每步都要按对应小 Plan 实现、验证、Review、修复或记录发现，然后创建一个聚焦 commit，并回填主 Plan 执行台账和 Step 执行状态。并行 Wave 完成后由 Coordinator 做组合 diff Review、冲突检查、必要集成验证和证据归档。

核心注意点：
- 目标版本固定为 ANP Python SDK `anp==0.8.8`。
- 只修改 `awiki-open-server`；`anp`、`user-service`、`message-service`、`awiki-cli-rs2` 仅可只读参考。
- User Service 兼容能力必须本地实现，不代理、不调用 `awiki.info` 或相邻 User Service。
- 不引入手机/邮箱验证、阿里云依赖、E2EE、联邦服务、群创建/管理。
- public `/anp-im/rpc` 白名单不得扩大，跨域 direct 必须继续校验 origin proof 与服务层 HTTP Signature。
- 所有协议/身份/auth 改动按 L3 执行 security review、Rust CLI gate 和 rwiki.cn public gate。
```

## 10. 小 Plan 摘要

### Step 01：ANP SDK 0.8.8 接入与协议 adapter

- 小 Plan：[steps/01-anp-sdk-adapter.md](steps/01-anp-sdk-adapter.md)
- 目标：新增统一 SDK adapter，替代手写 DID WBA / HTTP Signature / origin proof 核心。
- Parallel-safe：否。
- 验证方式：SDK parity focused tests、compileall、focused protocol tests。

### Step 02：路径配置与公开 endpoint 对齐

- 小 Plan：[steps/02-route-config-alignment.md](steps/02-route-config-alignment.md)
- 目标：让 `AWIKI_ANP_PUBLIC_RPC_PATH` 等配置与实际 route 挂载一致。
- Parallel-safe：是，可与 Step 03 并行。

### Step 03：User Service 兼容模块拆分

- 小 Plan：[steps/03-user-service-compat-refactor.md](steps/03-user-service-compat-refactor.md)
- 目标：将 `/user-service/*`、DID Auth、Profile、Handle、Users compat 从 `routes.py` / `services.py` 中收敛为本仓模块。
- Parallel-safe：是，可与 Step 02 并行。

### Step 04：Messaging 与 attachment 模块拆分

- 小 Plan：[steps/04-messaging-attachment-refactor.md](steps/04-messaging-attachment-refactor.md)
- 目标：拆 direct/group/sync/read-state/attachment，保持 public `/anp-im/rpc` 暴露面不扩大。
- Parallel-safe：否。

### Step 05：测试拆分与验证矩阵收敛

- 小 Plan：[steps/05-test-suite-split.md](steps/05-test-suite-split.md)
- 目标：拆大测试文件，抽 helpers，补 route config 和 SDK parity 覆盖。
- Parallel-safe：是，可与 Step 06 并行。

### Step 06：文档、部署示例与最终 L3 验证

- 小 Plan：[steps/06-docs-final-verification.md](steps/06-docs-final-verification.md)
- 目标：同步 README/AGENTS/deploy/Plan，执行最终 security review 与 rwiki.cn gate。
- Parallel-safe：是，可与 Step 05 并行，但最终证据依赖 Step 05 结果。

## 11. Review 策略

- 每步骤 Review：优先检查行为回归、公开契约、User Service compat shape、SDK adapter 使用边界、测试覆盖。
- 并行组 Review：检查路径所有权、函数搬迁冲突、导入循环、重复协议逻辑。
- 全局 Review：检查 `services.py` 是否明显瘦身，`routes.py` 是否回到薄适配，ANP SDK 是否集中接入。
- 安全 Review：检查 token/DID、origin proof、HTTP Signature、download ticket、contact verification disabled、private key 不落库。
- 文档 Review：检查 README/AGENTS/deploy 与实际配置一致，plan 台账有证据。

## 12. 验证策略

| 层级 | 适用 Step / 并行组 | 命令 / 检查 | 运行时机 | 预期证据 | 门禁结果 |
|---|---|---|---|---|---|
| Step Unit | Step 01 | `PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_protocol_anp_sdk.py -q` | Step 01 commit 前 | SDK parity pass；标准 `PYTHONPATH=src` 需环境安装 `anp==0.8.8` | pass_with_explicit_sdk_path |
| Step Unit | Step 02 | route config focused tests | Step 02 commit 前 | custom ANP path 和 DID document endpoint 一致 | pending |
| Step Unit | Step 03 | User compat focused tests | Step 03 commit 前 | DID/Auth/Profile/Handle/Users shape 不变 | pending |
| Step Integration | Step 04 | `PYTHONPATH=src python3 -m pytest tests/test_direct_messages.py tests/test_group_participant.py tests/test_attachments.py -q` | Step 04 commit 前 | messaging/attachment pass | pending |
| Full Local | Step 05 | `PYTHONPATH=src python3 -m pytest tests -q` | Step 05 commit 前 | 全量 pass；当前本机需先安装 `anp==0.8.8`，否则版本断言失败 | pending |
| CLI Local | Final | `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin <bin> --data-root /tmp/awiki-open-server-anp-sdk-rust --clean` | Final | Rust CLI pass 或记录 blocker | pending |
| Public | Final | `AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 PYTHONPATH=src python3 -m pytest tests/test_rwiki_cn_system.py -q` | Final | rwiki.cn public pass 或记录 blocker | pending |
| Public | Final | `PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.cn --did-domain rwiki.cn` | Final | ok=true | pending |
| Docs | Final | Markdown path/link spot check | Final | 文档路径存在 | pending |

## 13. 文档更新

- Harness 文档：本计划不直接修改 harness；若实现后跨仓库架构或 repo map 发生变化，再单独更新。
- 子仓库文档：更新 `awiki-open-server/README.md`、`awiki-open-server/AGENTS.md`、`awiki-open-server/deploy/README.md`。
- 本次生成的任务文档：`awiki-open-server/plan/20260704-structure-anp-sdk-hardening/`。

## 14. Commit 计划

- 每个完成、验证、Review 通过的步骤创建一个聚焦 commit。
- Commit 前记录 `git status` 和纳入文件。
- Commit 后记录 commit hash 和工作区状态。
- 并行步骤仍保持“一步一个聚焦 commit”；不得把多个 Agent 的完成工作合并成一个大 commit，除非先记录原因并更新 Plan。

## 15. Blocked 处理

| Blocker | Step | Agent | 并行组 | 证据 | 已尝试方案 | 影响范围 | 是否暂停同组 | 下一步决策 |
|---|---|---|---|---|---|---|---|---|
| SDK 0.8.8 与线上 awiki.info 签名不兼容 | 01/06 | TBD | A/D | 公网 gate 错误 | adapter 兼容层、最小复现 | 整体计划 | 是 | 记录 blocker，等待协议决策 |
| Rust CLI 当前仍要求 phone/otp 参数 | 03/06 | TBD | B/D | CLI 命令失败 | 保持占位参数不进入服务端验证事实 | CLI gate | 否 | 记录兼容说明 |
| route path config 改动影响 nginx | 02/06 | TBD | B/D | verify-public 404 | 同步 deploy 示例和 README | public gate | 是 | 修正配置后重跑 |

## 16. Plan 变更记录

| 日期 | 变更 | 原因 | 影响步骤 | 是否需要 Review |
|---|---|---|---|---|
| 2026-07-04 | 初始创建，固定 ANP SDK 版本为 `anp==0.8.8` | 用户明确要求使用 0.8.8 | 全部 | 是 |
| 2026-07-04 | Step 01 验证策略记录环境限制：本机已安装 `anp==0.6.8`，标准 `PYTHONPATH=src` 会失败；使用只读 sibling `anp/anp` 0.8.8 源码路径完成本地 gate | PyPI SSL 与缺少 `hatchling` 阻止本机安装 0.8.8；代码仍以 `pyproject.toml` 的 `anp==0.8.8` 为长期依赖 | 01/最终验证 | 是 |

## 17. 风险与回滚

| 风险 | 缓解措施 | 回滚 / 回退方案 |
|---|---|---|
| SDK 0.8.8 与既有手写实现存在细节差异 | 先 adapter + parity tests，业务层不直接散落调用 SDK | 回退到 adapter 内兼容 shim，不恢复散落手写逻辑 |
| 大文件拆分引入导入循环 | 按协议、User compat、messaging、attachment 分层，先搬函数不改行为 | 回退当前 step commit |
| 公开互通失败 | 保留 `verify-public`、public system test、Rust CLI gate | 记录 blocker，不扩大 API 或绕过签名 |
| 引入 ANP SDK 拉入额外依赖 | 明确依赖来源和版本，更新 docs | 只保留必要 SDK import，避免 api/e2ee optional 能力 |

## 18. Step 01 执行记录

- 2026-07-04 10:26:58 +0800：启动 Step 01。
- 2026-07-04 10:42:05 +0800：完成实现、Review 和本地验证。
- 变更摘要：新增 `awiki-open-server/src/awiki_open_server/protocol/anp_adapter.py`，固定 `anp==0.8.8`，将 service HTTP Signature、Content-Digest、origin proof 验证切到 adapter，并补充 `awiki-open-server/tests/test_protocol_anp_sdk.py`，并补充 HTTP signature 负例测试。
- 验证证据：`PYTHONPATH=../anp/anp:src python3 -m pytest tests -q` 56 passed, 2 skipped；`PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step01-cross --clean` ok=true。
- 环境风险：当前机器默认 `anp==0.6.8`，标准 `PYTHONPATH=src` 被 adapter 版本断言阻断；安装 `anp==0.8.8` 的 PyPI 和本地 build 路径分别受 SSL 与 `hatchling` 限制。

## 19. 最终全局 Review 与整体验证

- 触发条件：所有步骤完成、Review、验证并提交后执行。
- Review 范围：源码结构、SDK adapter、User Service compat、本域/公开路由、storage helper、测试拆分、README/AGENTS/deploy、Plan 台账。
- 重点关注：跨步骤一致性、ANP SDK 0.8.8 集中使用、无相邻仓库修改、无手机/邮箱/Aliyun 依赖、public `/anp-im/rpc` 白名单未扩大、`rwiki.cn` endpoint 正确。
- 整体验证命令 / 检查：见第 12 节。
- Review 发现：README/AGENTS/deploy 与 Step 01-05 后的实际模块结构和测试拆分存在文档漂移；nginx 示例未列 root-level auth/ws ticket 兼容 route；历史 plan 文档仍保留旧测试文件名作为当时执行证据。
- 已修复问题：README 补 Code Structure、ANP SDK 0.8.8、focused test map 和缺失 API routes；AGENTS 补模块边界和 focused test guidance；deploy README 补 venv/install、contact verification 禁用和 no-proxy checklist；nginx 示例补 root-level auth/ws ticket proxy route；本次主 Plan 和 Step 06 已回填证据。
- 剩余风险：当前机器默认安装 `anp==0.6.8`，标准 `PYTHONPATH=src` 会被 adapter 版本断言阻断；所有最终 gate 使用 `PYTHONPATH=../anp/anp:src` 指向 0.8.8 sibling SDK。生产部署需按 README/deploy 通过 `pip install -e .` 安装 `anp==0.8.8`。
- 最终证据：`PYTHONPATH=../anp/anp:src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=../anp/anp:src python3 -m pytest tests -q` 64 passed, 2 skipped；`smoke-asgi` ok=true；`smoke-cross-domain-local` ok=true；`smoke-rust-cli-local --awiki-cli-bin ../awiki-cli-rs2/target/debug/awiki-cli` ok=true；`verify-public --base-url https://rwiki.cn --did-domain rwiki.cn` ok=true；`AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 ... tests/test_rwiki_cn_system.py -q` 2 passed；`git diff --check` pass；forbidden dependency/domain scan pass.
- 最终 `git status`：Step 06 commit `6a3cd4b` 后仅剩 Plan commit hash 回填改动；回填提交后需再次确认 clean。
