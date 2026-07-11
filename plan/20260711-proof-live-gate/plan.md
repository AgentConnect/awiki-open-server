# Plan：DID Document 密码学 proof 与 public live gate 收尾

状态：done_with_recorded_blocker
DOC：`awiki-open-server/plan/20260711-proof-live-gate/`  
Harness：`awiki-harness/`  
创建时间：2026-07-11  
恢复指针：本轮可在无外部凭据条件下完成的实现、Review、验证和提交已完成；若后续提供 `AWIKI_INFO_*` 凭据，从 Step 02 的 awiki.info direct smoke 命令恢复。

## 1. 目标

- 任务目标：补齐上一轮明确留下的两个风险：上传 DID Document 的 DataIntegrity/JCS 密码学 proof 验证，以及 `rwiki.cn <-> awiki.info` live direct gate 的可执行证据。
- 预期行为：带有效 `DataIntegrityProof` / `eddsa-jcs-2022` / JCS 的上传 DID Document 可以注册或更新；proof 被篡改、签名不匹配、verification method 缺失或 key 不支持时 fail closed。public live gate 在有 `awiki.info` 凭据时可执行 direct smoke；没有凭据时输出明确 skip/blocker 证据，不伪造通过。
- 非目标：不引入 phone/email/Aliyun、E2EE、federation、群创建/管理、多租户托管；不把 `awiki.info` 当作后端或代理；不实现 K1 DID 兼容。
- 完成标准：Step 01 的密码学验签实现、测试、文档和 security review 通过并提交；Step 02 的 public/public-live 命令执行并记录结果，若缺少 `awiki.info` 凭据则记录精确 blocker；最终全局 Review、整体验证和工作区状态已记录。

## 2. Harness 上下文

| 来源 | 作用 |
|---|---|
| `awiki-harness/AGENTS.md` | 确认非平凡 AWiki 任务的阅读顺序、权威来源和验证要求。 |
| `awiki-harness/README.md` | 确认 harness 是控制面，不替代子仓库实现文档。 |
| `awiki-harness/context/00-context-map.md` | 路由到 Identity、Auth、Protocol、Message Flow 和 System Test。 |
| `awiki-harness/context/02-repo-map.md` | 确认 `user-service`、`message-service`、`awiki-cli-rs2`、`awiki-system-test` 边界。 |
| `awiki-harness/context/03-cross-repo-architecture.md` | 确认 DID Document / service discovery 属于身份与协议边界，open-server 不代理外部服务。 |
| `awiki-harness/context/20-rules-index.md` | 路由到架构、文档、AI coding 和验证规则。 |
| `awiki-harness/context/30-tools-env.md` | 确认本地验证命令和 `PYTHONPATH` 使用方式。 |
| `awiki-harness/context/40-verification.md` | 确认本任务属于 L3 identity/auth/protocol/security 变更。 |
| `awiki-harness/context/50-task-workflow.md` | 确认任务记录、验证证据和 blocker 记录方式。 |
| `awiki-harness/context/nodes/identity.node.md` | 确认 DID Document 承载 verification method、service discovery 和 e1 策略。 |
| `awiki-harness/context/nodes/auth.node.md` | 确认 DID/auth 变更需要 security review。 |
| `awiki-harness/context/nodes/protocol.node.md` | 确认 ANP/DID proof 行为不能与协议来源冲突。 |
| `awiki-harness/context/nodes/message-flow.node.md` | 确认 public direct gate 需要 DID service discovery、origin proof 和 signed HTTP hop。 |
| `awiki-harness/rules/architecture-principles.md` | 确认依赖方向、e1 DID 策略和变更影响策略。 |
| `awiki-harness/rules/ai-coding-rules.md` | 确认实现前影响分析、保持小 diff、文档同步。 |
| `awiki-harness/rules/verification-policy.md` | 确认 L3 最小证据和 security gate。 |
| `awiki-harness/rules/documentation-principles.md` | 确认行为变化需要同步子仓库文档。 |

## 3. 影响分析

| 领域 / 仓库 / 模块 | 影响 | 权威文档或代码 |
|---|---|---|
| Identity / DID proof | 上传 DID Document 从结构校验升级为 DataIntegrity/JCS 密码学验签。 | `awiki-open-server/src/awiki_open_server/service_identity.py`, `awiki-open-server/src/awiki_open_server/user_compat/core.py` |
| User Service compatibility | `did-auth.register` 和 `update_document` 的 signed uploaded doc 路径需要 fail closed。 | `awiki-open-server/src/awiki_open_server/user_compat/core.py`, `awiki-open-server/tests/test_identity_documents.py` |
| CLI smoke | 本地 cross-domain smoke 当前生成假 `proofValue`，必须改为真实签名。 | `awiki-open-server/scripts/awiki_open_cli.py` |
| Tests / fixtures | `tests/helpers.py` 和 identity/direct/group/sync tests 依赖 signed helper，需要使用真实 proof。 | `awiki-open-server/tests/helpers.py`, `awiki-open-server/tests/` |
| Docs | README 中“尚未做密码学 proof 验证”的描述需要改为已验签及限制条件。 | `awiki-open-server/README.md`, `awiki-open-server/README.cn.md` |
| Public live gate | `awiki.info` direct smoke 需要 token、sender DID、recipient DID 和 origin proof；当前环境变量均未设置。 | `awiki-open-server/scripts/awiki_open_cli.py`, `awiki-open-server/README.md`, `awiki-open-server/README.cn.md` |

## 4. 假设与开放问题

### 假设

- DID Document proof 使用本仓服务 DID 文档生成逻辑已经采用的 `DataIntegrityProof`、`eddsa-jcs-2022`、JCS canonicalization 和 `sha256(proof_options) || sha256(document_without_proof)` 签名输入。
- 当前实现只要求 Ed25519 Multikey，`publicKeyMultibase` 使用 multibase `z` + multicodec `ed25519-pub` 前缀 `0xed01`。
- signed uploaded DID Document 的 `ANPMessageService` 必须继续绑定本 open-server 的 `serviceEndpoint` 和 `serviceDid`，不会被自动改写。
- `awiki.info` live direct gate 必须依赖真实远端测试凭据；凭据缺失时只可证明 capability 和本地 public readiness。

### 开放问题

- 当前执行环境没有 `AWIKI_INFO_TOKEN`、`AWIKI_INFO_SENDER_DID`、`AWIKI_INFO_RECIPIENT_DID`、`AWIKI_INFO_ORIGIN_PROOF_JSON`。若用户提供这些凭据，需要复跑 Step 02 的 direct gate。

## 5. 总体设计方法

- 设计边界：验签逻辑放在 `awiki-open-server/src/awiki_open_server/service_identity.py`，由 `user_compat` 调用；不把密码学细节散落到 route 或测试中。
- 关键决策：proof 字段必须完整、verification method 必须属于文档 DID，public key 必须可解析为 Ed25519 Multikey，签名必须覆盖 proof options 和去掉 proof 的 DID Document。
- 兼容性策略：未签名上传文档仍只在 `AWIKI_ALLOW_UNSIGNED_PEER_DEV=true` 的 dev 路径允许并会被重写 service；signed 路径不自动重写 service。
- 数据、协议、配置或迁移策略：不改 SQLite schema；不新增外部依赖，复用已有 `base58`、`jcs`、`cryptography`。
- 风险控制：错误 fail closed；新增 tamper tests；public live gate 凭据缺失只记录 blocker，不降低验证标准。

## 6. 任务拆分

| Step | 标题 | 依赖 | 并行组 | Parallel-safe | 建议 Agent | 可并行对象 | 互斥资源 / 冲突路径 | 产出 | 小 Plan 文档 | Commit gate | 合并 / 验证门禁 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 01 | 实现 uploaded DID Document DataIntegrity/JCS 验签 | 无 | 串行 | 否 | agent-identity | 无 | `service_identity.py`, `user_compat/core.py`, `tests/helpers.py`, `tests/test_identity_documents.py`, `scripts/awiki_open_cli.py` | 验签实现、真实签名 helper、focused tests、README 更新 | [steps/01-did-document-crypto-proof.md](steps/01-did-document-crypto-proof.md) | 必须 | Identity security gate | in_progress |
| 02 | public live gate 入口与 awiki.info 凭据阻塞证据 | Step 01 | 串行 | 否 | coordinator | 无 | `scripts/awiki_open_cli.py`, `README.md`, `README.cn.md`, 本 Plan | public readiness、credential missing evidence、direct smoke guarded 结果 | [steps/02-public-live-gate.md](steps/02-public-live-gate.md) | 必须，如有修改 | Public gate | pending |

## 7. 并行执行与多智能体分工

- 并行策略：串行。两个步骤都涉及 public/DID/auth 验证证据和 README 文档，Step 02 还依赖 Step 01 的 smoke 脚本修复。
- 最大并行度：1 个写入型执行者。
- Coordinator：主执行者负责计划台账、实现、Review、验证、提交和最终全局 Review。
- 串行原因：`scripts/awiki_open_cli.py` 和 README 是共享写入面；public gate 证据必须基于已完成的真实 proof smoke。

### Agent 分工

| Agent / Worker | 负责 Step | 责任边界 | 可修改路径 | 禁止修改路径 / 资源 | 交付物 | Review 责任 |
|---|---|---|---|---|---|---|
| agent-identity | Step 01 | proof 验签实现、测试和 smoke 签名 helper | `awiki-open-server/src/awiki_open_server/service_identity.py`, `awiki-open-server/src/awiki_open_server/user_compat/core.py`, `awiki-open-server/tests/`, `awiki-open-server/scripts/awiki_open_cli.py`, README | 不修改外部服务、不放宽 public allowlist | commit + 验证证据 | L3 security Review |
| coordinator | Step 02 和 final | public gate、凭据 blocker、docs 和最终 Review | `awiki-open-server/scripts/awiki_open_cli.py`, README, 本 Plan | 不提交 secrets，不伪造 live direct 结果 | commit 或 blocker 记录 | Public gate Review |

### 并行组

| Wave / 并行组 | 可并行 Step | 可并行原因 | 共享依赖 | 写入范围 | 依赖屏障 | 合并顺序 | Group gate / 验证责任 |
|---|---|---|---|---|---|---|---|
| 串行主线 | 无 | 共享脚本、docs 和验证证据 | DID proof / public gate | 单执行者 | Step 01 提交后进入 Step 02 | 01 -> 02 -> final | 每步 Step gate + final gate |

### 互斥资源

| 资源 / 路径 / 契约 | 互斥原因 | 受影响 Step | 规则 |
|---|---|---|---|
| `awiki-open-server/scripts/awiki_open_cli.py` | Step 01 改 DID doc 签名，Step 02 改 public live 诊断输出 | Step 01, Step 02 | 串行修改，commit 后再继续 |
| `awiki-open-server/README.md`, `awiki-open-server/README.cn.md` | proof 行为和 public gate 说明需保持一致 | Step 01, Step 02 | 每步只改对应事实，final Review 查一致性 |
| `AWIKI_INFO_*` 凭据 | 外部真实测试资源，不可伪造或提交 | Step 02 | 只读取环境变量状态，不写入仓库 |

## 8. 执行台账

状态取值：`pending`、`in_progress`、`review`、`blocked`、`committed`、`done`。

| Step | 状态 | Agent / Owner | 并行组 | 分支 / worktree | 基线 commit | 开始时间 | 完成时间 | Commit | Review 证据 | 验证证据 | 合并状态 | 门禁状态 | 下一步 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 01 | done | agent-identity | 串行 | `main` | `f202c3b` | 2026-07-11 | 2026-07-11 | `b2cc11e` (`identity: verify uploaded did document proofs`) | L3 Review 完成：验签输入与本仓服务 DID 文档签名逻辑一致；`assertionMethod` 授权、Ed25519 Multikey、base64url proofValue、64 字节签名、controller 和 DID 绑定均 fail closed；signed service entry 不自动重写；dev unsigned 路径未放宽。 | identity focused 22 passed；protocol/direct/group/sync regression 30 passed；`smoke-cross-domain-local` pass；ASGI smoke pass；full local tests 73 passed, 2 skipped；`git diff --check` pass。 | done | pass | Step 02 |
| 02 | done | coordinator | 串行 | `main` | `b2cc11e` | 2026-07-11 | 2026-07-11 | `d7e7678` (`interop: clarify awiki info live gate`) | Public gate Review 完成：`smoke-awiki-info` 只输出凭据 set/unset 和缺失字段，不打印 token/origin proof；capability-only 与 live direct 判定分离；未代理 `awiki.info`；未把 skipped direct 标记为 pass。 | CLI smoke tests 7 passed；`verify-public` pass；guarded public system tests 2 passed；`smoke-awiki-info` capability pass，`direct_ready=false`，`live_direct_gate=skipped_missing_credentials`；full local tests 75 passed, 2 skipped；`git diff --check` pass。 | done | partial_with_recorded_blocker | final Review |

## 9. Codex Goal 执行协议

- 将本 Plan 作为执行进度的唯一事实来源。
- 启动或恢复前，读取本 Plan、当前小 Plan、执行台账和当前 `git status --short --branch`。
- 默认同一时间只执行一个步骤；本 Plan 没有允许写入型并行的步骤。
- 恢复时，从第一个状态不是 `done` 的步骤继续。
- 每个步骤依次执行：标记 `in_progress`、实现、验证、Review、修复 Review 发现、提交、记录证据、标记 `done`。
- 上一个依赖步骤的完成工作未提交前，不要开始下一个依赖步骤。
- 改变范围、顺序、验收标准、公开契约、验证策略或 public live 判定前，先更新本 Plan。
- 所有步骤完成后执行最终全局 Review 和整体验证。

## 9.1 Codex Goal 提示词

```text
请以 `awiki-open-server/plan/20260711-proof-live-gate/plan.md` 为唯一规划入口，按文档执行完整实现。

开始前先读取：
- `awiki-open-server/plan/20260711-proof-live-gate/plan.md`
- 当前第一个未 done 的 Step 文档
- 主 Plan 的执行台账、Codex Goal 执行协议、验证策略、Blocked 处理和 Plan 变更记录
- 当前 `git status --short --branch`

请从第一个状态不是 `done` 的步骤开始。默认一次只执行一个写入型步骤；本 Plan 没有允许并行写入。每步都要按对应小 Plan 实现、验证、Review、修复或记录 Review 发现，然后创建聚焦 commit，并回填主 Plan 执行台账和 Step 执行状态。需要改变 public gate 判定或验证策略时，先更新 Plan 变更记录。

所有步骤完成后，执行最终全局 Review 和整体验证，记录实际命令、通过/失败/跳过数量、失败或跳过原因、剩余风险和最终工作区状态。

核心注意点：uploaded DID Document proof 必须做 DataIntegrity/JCS 密码学验签；`awiki.info` 只能作为 remote peer；没有 `AWIKI_INFO_*` 凭据时不得声明 live 双向 direct 通过；保持 Community MVP 边界；验证使用 `PYTHONPATH=../anp/anp:src`。
```

## 10. 小 Plan 摘要

### Step 01：实现 uploaded DID Document DataIntegrity/JCS 验签

- 小 Plan：[steps/01-did-document-crypto-proof.md](steps/01-did-document-crypto-proof.md)
- 目标：signed uploaded DID Document 必须通过真实 Ed25519 DataIntegrity/JCS proof。
- 设计方法：复用 service DID document 的 signing-input 规则，实现对 `proofValue` 的逆向验签。
- 实现方法：在 `service_identity.py` 添加 verifier，在 `user_compat/core.py` signed 路径调用，更新测试和 smoke helper。
- 路径：`awiki-open-server/src/awiki_open_server/service_identity.py`, `awiki-open-server/src/awiki_open_server/user_compat/core.py`, `awiki-open-server/tests/`, `awiki-open-server/scripts/awiki_open_cli.py`, README。
- 验证方式：identity focused tests、protocol/messaging regressions、local cross-domain smoke、full tests。
- Review 环节：L3 security review，重点查 proof bypass、tamper fail closed、dev unsigned 边界和 secrets。
- Commit 要求：完成后聚焦提交。
- 风险：外部客户端如果继续上传假 `proofValue` 会被拒绝；这是本轮目标行为。

### Step 02：public live gate 入口与 awiki.info 凭据阻塞证据

- 小 Plan：[steps/02-public-live-gate.md](steps/02-public-live-gate.md)
- 目标：固化 `rwiki.cn` public readiness 和 `awiki.info` direct smoke 的可执行入口；凭据缺失时明确 blocker。
- 设计方法：`smoke-awiki-info` capability 可无凭据运行，direct 必须有 token、sender DID、recipient DID、origin proof；输出缺失字段。
- 实现方法：如有必要增强脚本 JSON 输出和 README，运行 public readiness / capability 命令。
- 路径：`awiki-open-server/scripts/awiki_open_cli.py`, README, 本 Plan。
- 验证方式：`verify-public`、guarded public system tests、`smoke-awiki-info`；有凭据时运行 direct smoke。
- Review 环节：确认没有提交 secrets、没有把 skipped direct 标记为 passed、没有代理到 `awiki.info`。
- Commit 要求：如有脚本或 docs 修改则聚焦提交；若只有 blocker 记录，可在计划台账提交。
- 风险：没有有效 awiki.info 凭据时 live 双向 direct 仍不能完成。

## 11. Review 策略

- 每步骤 Review：实现完成后、commit 前检查正确性、兼容性、回归、测试覆盖、文档漂移和安全边界。
- 全局 Review：两个步骤完成后检查 proof verifier、smoke 脚本、README、计划台账、public gate 证据和最终 `git status`。
- 契约 / 安全 / 隐私 Review：重点检查 private key/token/origin proof 不被写入仓库；无凭据时不伪造 live direct。
- 文档 Review：README/README.cn 与实际实现一致，计划中的 blocker 与命令输出一致。

## 12. 验证策略

| 层级 | 适用 Step / 并行组 | 命令 / 检查 | 运行时机 | 预期证据 | 门禁结果 |
|---|---|---|---|---|---|
| Step Unit | Step 01 | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_identity_documents.py tests/test_user_service_compat.py tests/test_contact_auth_compat.py tests/test_profile_compat.py tests/test_agent_compat.py -q` | Step 01 commit 前 | 22 passed | pass |
| Step Integration | Step 01 | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root .awiki-open-server/proof-cross --clean` | Step 01 commit 前 | pass，双向 inbox delivery | pass |
| ASGI Smoke | Step 01 | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir .awiki-open-server/proof-asgi` | Step 01 commit 前 | pass | pass |
| Regression | Step 01 / final | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests -q` | Step 01 和 Step 02 | Step 01：73 passed, 2 skipped；Step 02：75 passed, 2 skipped | pass |
| CLI Smoke Unit | Step 02 | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_cli_smoke.py -q` | Step 02 | 7 passed | pass |
| Public Readiness | Step 02 | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.cn --did-domain rwiki.cn` | Step 02 | pass | pass |
| Public System | Step 02 | `cd awiki-open-server && AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_rwiki_cn_system.py -q` | Step 02 | 2 passed | pass |
| awiki.info Capability / Direct | Step 02 | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-awiki-info --base-url https://awiki.info --did-domain rwiki.cn` | Step 02 | capability pass；`direct_ready=false`，`live_direct_gate=skipped_missing_credentials` | partial_with_recorded_blocker |
| Hygiene | 全部 | `cd awiki-open-server && git diff --check` | commit 前 / final | pass | pass |

## 13. 文档更新

- Harness 文档：本轮不改变跨仓库架构；只在本 Plan 记录 execution evidence。若后续把 public live gate 上移到 `awiki-system-test`，再同步 harness。
- 子仓库文档：更新 `awiki-open-server/README.md` 和 `awiki-open-server/README.cn.md` 中 proof 与 remote diagnostic 说明。
- 本次生成的任务文档：`awiki-open-server/plan/20260711-proof-live-gate/plan.md` 和 `steps/`。

## 14. Commit 计划

- Step 01：`identity: verify uploaded did document proofs`
- Step 02：`interop: clarify awiki info live gate` 或计划/docs 事实提交。
- 每个提交前记录 `git status` 和纳入文件；提交后记录 commit hash 和工作区状态。

## 15. Blocked 处理

| Blocker | Step | Agent | 并行组 | 证据 | 已尝试方案 | 影响范围 | 是否暂停同组 | 下一步决策 |
|---|---|---|---|---|---|---|---|---|
| 缺少 `awiki.info` live direct 测试凭据 | 02 | coordinator | 串行 | `AWIKI_INFO_TOKEN`、`AWIKI_INFO_SENDER_DID`、`AWIKI_INFO_RECIPIENT_DID`、`AWIKI_INFO_ORIGIN_PROOF_JSON` 均 unset；脚本默认 `auth_scheme` 可用 | 已运行 `verify-public`、guarded public tests 和 `smoke-awiki-info` capability；脚本输出 `missing_credentials` | 仅 live direct 完成判定 | 否 | 不声明 live direct pass；记录 blocker |

## 16. Plan 变更记录

| 日期 | 变更 | 原因 | 影响步骤 | 是否需要 Review |
|---|---|---|---|---|
| 2026-07-11 | 创建本轮两步 Plan | 用户要求继续完成两个剩余风险 | Step 01, Step 02 | 是 |

## 17. 风险与回滚

| 风险 | 缓解措施 | 回滚 / 回退方案 |
|---|---|---|
| 真实验签拒绝旧假 proof 测试或客户端 | 更新本仓测试和 smoke helper；文档说明签名要求 | 回退 Step 01 commit 可恢复结构校验，但不满足用户目标 |
| proof 验证字段过宽或过窄 | 增加有效、篡改、缺 key、坏 proofValue、update tamper 测试 | 调整 verifier 并复跑 focused/full tests |
| public live gate 缺凭据 | 记录 precise blocker；保留 capability/readiness 证据 | 用户提供 `AWIKI_INFO_*` 后复跑 |

## 18. 最终全局 Review 与整体验证

- 触发条件：Step 01 和 Step 02 完成、Review、验证并提交后执行。
- Review 范围：proof verifier、User Service compatibility 路径、测试 helper、smoke 脚本、README、计划台账、public gate 证据和最终工作区状态。
- 重点关注：fail closed、安全/隐私、dev unsigned 边界、没有 secret、没有 public gate 假通过、Community MVP 边界。
- 整体验证命令 / 检查：见第 12 节，全部本地和 public readiness gate 通过；awiki.info live direct 因凭据缺失记录 blocker。
- Review 发现：未发现需要继续修改的代码问题；确认 `service_identity.py` 的 verifier 没有绕过 `assertionMethod` 授权，`smoke-awiki-info` 不泄露 secret 值。
- 已修复问题：上传 DID Document 已从结构 proof 校验升级为 Ed25519 DataIntegrity/JCS 验签；脚本已能机器可读地区分 capability-only、direct-ready 和 missing credentials。
- 剩余风险：`AWIKI_INFO_TOKEN`、`AWIKI_INFO_SENDER_DID`、`AWIKI_INFO_RECIPIENT_DID`、`AWIKI_INFO_ORIGIN_PROOF_JSON` 缺失，导致 `rwiki.cn <-> awiki.info` live direct 仍不能声明通过。后续提供凭据后应复跑 Step 02 的 direct smoke，并补对端 inbox/history 证据。
- 最终证据：`b2cc11e` 完成 DID proof 验签；`d7e7678` 完成 awiki.info gate 输出和文档；full tests 75 passed, 2 skipped；public readiness pass；public system tests 2 passed；awiki.info capability pass with recorded credential blocker。
- 最终 `git status`：最终台账提交前为 `main...origin/main [ahead 13]`，工作区仅有本 Plan 回填修改；最终台账提交后由最终报告记录。
