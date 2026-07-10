# Step 01：复跑并固化公网互通 Gate

主 Plan：[../plan.md](../plan.md)  
Step index：01  
状态：done_with_residual_risk

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done |
| Branch | `main` |
| Started | 2026-07-10T10:52:16Z |
| Completed | 2026-07-10T10:56:55Z |
| Commit | Step 01 focused commit |
| Review evidence | 未改业务代码；未放宽 public allowlist；未写入 token/private key/手机号；历史 deployment plan 保留原始失败并追加复核记录；完整 live gate 缺少有效 `awiki.info` 测试凭据，作为 residual risk 记录。 |
| Verification evidence | `verify-public` ok；`tests/test_rwiki_cn_system.py` 2 passed；`smoke-awiki-info` capability ok；`rwiki.cn` Rust CLI 本域 direct/inbox/history pass；完整 `rwiki.cn <-> awiki.info` live direct 未运行，原因是缺少有效 `awiki.info` 测试凭据，临时注册返回验证码无效或过期。 |
| Next action | Step 02：协议、错误映射和幂等性硬化 |
| Assigned agent | coordinator |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无写入型并行；只读公网检查可由 worker 报告 |
| Conflict resources | `awiki-open-server/scripts/awiki_open_cli.py`, `awiki-open-server/tests/`, `awiki-open-server/plan/20260705-rwiki-cn-deployment/plan.md` |
| Baseline commit | `5621bc4` |
| Worktree / branch | `main` |
| Merge gate | Public interop gate |
| Verification gate | verify-public + guarded public tests + live Rust CLI bidirectional gate |
| Gate status | partial_with_recorded_blocker |

状态取值：`pending`、`in_progress`、`review`、`blocked`、`committed`、`done`。

## 2. 目标

- 结果：确认 `rwiki.cn <-> awiki.info` 双向明文 direct live interop 的真实状态，并把可重复验证入口固化为脚本、测试或文档。
- 用户 / 系统可见行为：后续执行者能明确知道 `rwiki.cn` 是否已经完成与 `awiki.info` 双向互通，历史 blocker 是否过期，如何复跑。
- 非目标：不修改 `awiki.info`、`user-service`、`message-service` 源码或线上数据；不把 awiki.info 作为本仓后端。
- 完成标准：只读 public checks、guarded public tests、Rust CLI 双域 direct 证据齐全；历史部署 plan 中 stale blocker 被更新或明确保留；真实凭据不写入仓库。

## 3. 设计方法

- 设计边界：`awiki.info` 是 peer/reference，不是 fallback backend。
- 核心决策：先跑只读 DID/capability/proof 检查，再跑写入型 live direct；避免在公网不确定时先改代码。
- 契约 / API / 数据流：通过用户 DID document 发现 `ANPMessageService`，`direct.send` 走远端 `/anp-im/rpc`，业务 `origin_proof` 和服务层 HTTP Signature 都必须成立。
- 兼容性：继续保留 `/anp-im/rpc` public allowlist；不开放本域 inbox/history/sync 等 local-only 方法。
- 迁移策略：无 schema 迁移。只更新脚本/tests/docs。
- 风险控制：隔离 Rust CLI workspace，所有 token、OTP、真实用户资料只在本机运行环境中使用，不写入文档。

## 4. 实现方法

1. 记录执行前 `git status --short --branch` 和当前 commit。
2. 复跑只读检查：
   - `https://rwiki.cn/healthz`
   - `https://rwiki.cn/.well-known/did.json`
   - `https://awiki.info/.well-known/did.json`
   - `verify-public --base-url https://rwiki.cn --did-domain rwiki.cn`
3. 复跑 `AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1` 的 `tests/test_rwiki_cn_system.py`。
4. 使用隔离 `AWIKI_CLI_WORKSPACE_HOME_DIR` 或脚本临时目录，注册或复用两个测试身份，分别验证：
   - `rwiki.cn -> awiki.info` direct send 后 awiki.info inbox/history 可见。
   - `awiki.info -> rwiki.cn` direct send 后 rwiki.cn inbox/history 可见。
5. 如果历史 `invalid_peer_http_signature` 不再出现，更新 `awiki-open-server/plan/20260705-rwiki-cn-deployment/plan.md`，标记该 blocker 已过期并记录复测日期、命令和脱敏证据。
6. 如果双向 gate 仍失败，记录精确失败点：DID document key、Signature headers、Content-Digest、JSON-RPC error、HTTP status、目标 endpoint、日期。
7. 视重复性决定是否扩展 `awiki-open-server/scripts/awiki_open_cli.py`，增加 guarded live interop command；不要默认启用写公网数据的测试。
8. 更新 `awiki-open-server/README.md` / `README.cn.md` 的 public interop runbook，如果实际命令或风险说明有变化。

## 5. 路径

| 仓库 / 模块 / 文件 | 计划变更 | 备注 |
|---|---|---|
| `awiki-open-server/scripts/awiki_open_cli.py` | 可选新增 guarded live bidirectional interop smoke | 不写真实凭据，不默认跑公网写入 |
| `awiki-open-server/tests/test_rwiki_cn_system.py` | 可选补只读断言或 guarded skip reason | 写入型 live direct 优先放脚本，不放默认 pytest |
| `awiki-open-server/plan/20260705-rwiki-cn-deployment/plan.md` | 更新历史 blocker 当前状态 | 保留原始历史证据，不覆盖为“从未发生” |
| `awiki-open-server/README.md` | 更新 public interop runbook | 如命令或风险说明变化 |
| `awiki-open-server/README.cn.md` | 同步中文说明 | 如 README 有实质变化 |

## 6. 依赖与并行约束

- 前置步骤：无。
- 可并行步骤：只读 public DID/capability 检查可以由 worker 并行跑并报告。
- 不可并行步骤：脚本、tests、deployment plan 更新必须由 coordinator 单写。
- 并行安全依据：写入路径少但涉及历史证据和 public gate，避免多个 writer 同时改同一 plan。
- 互斥资源 / 冲突路径：`awiki-open-server/plan/20260705-rwiki-cn-deployment/plan.md`, `awiki-open-server/scripts/awiki_open_cli.py`。
- 外部文档或决策：需要 live awiki.info 测试身份或凭据；没有凭据则记录 blocker。
- 环境前提：`awiki-cli-rs2/target/debug/awiki-cli` 可用，或先在 `awiki-cli-rs2` 构建；公网可访问 `rwiki.cn` 和 `awiki.info`。
- 合并前置条件：Review 完成，凭据未入库，证据脱敏。
- 合并后验证门禁：Public interop gate 状态已记录。

## 7. 验收标准

- [x] 已记录 `rwiki.cn` 和 `awiki.info` 当前 DID document 的 service key、endpoint、serviceDid 是否一致。
- [x] `verify-public --base-url https://rwiki.cn --did-domain rwiki.cn` 已通过，或失败原因已定位。
- [x] `AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1` 的 `tests/test_rwiki_cn_system.py` 已通过，或失败原因已记录。
- [x] Rust CLI 双域 direct gate 已通过，或 live 凭据/blocker/远端问题已明确记录。
- [x] 若历史 awiki.info DID key mismatch 已修复，`plan/20260705-rwiki-cn-deployment/plan.md` 已注明复测结论。
- [x] 脚本或文档不包含真实 OTP、token、private key、手机号、邮箱或未脱敏 DID 私密材料。
- [x] Review 发现已经修复或明确记录。
- [ ] 本步骤在进入下一步之前已经创建聚焦 commit。

## 8. 验证方式

| 检查项 | 命令 / 方法 | 运行时机 | 预期证据 | 门禁类型 |
|---|---|---|---|---|
| Public verify | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.cn --did-domain rwiki.cn` | commit 前 | `ok=true` | Step gate |
| Public pytest | `cd awiki-open-server && AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_rwiki_cn_system.py -q` | commit 前 | pass | Step gate |
| Live bidirectional | 使用隔离 Rust CLI workspace 执行 `rwiki.cn -> awiki.info` 和 `awiki.info -> rwiki.cn` direct/inbox/history | commit 前 | 双向消息可见或 blocker 证据 | Step gate |
| Local regression | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_protocol_anp_sdk.py tests/test_direct_messages.py -q` | 改脚本/测试后 | pass | Step gate |
| Docs | 检查更新后的 plan/README 中无绝对路径、无秘密、无 stale blocker | Review 前 | Review 记录 | Step gate |

如果 live 凭据不可用，必须记录“未运行”的具体原因、影响范围和替代证据。

## 9. Review 环节

- Review 时机：脚本/docs/test 变更完成后、commit 前。
- Review 重点：公网证据真实性、脱敏、安全边界、是否错误放宽 `/anp-im/rpc` public allowlist、是否把 awiki.info 当作后端、是否误删历史部署证据。
- Review 结论必须记录在主 Plan 台账。

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | 无业务代码问题 | 完整 live bidirectional direct 未运行，原因是缺少有效 `awiki.info` 测试凭据；这不是本仓回归证据。 |
| 已修复问题 | 已修复文档漂移 | 旧部署 plan 中的非 portable workspace 命令占位已改为 workspace-relative；追加 2026-07-10 复核记录。 |
| 剩余风险 | 存在 | `rwiki.cn <-> awiki.info` 双向 direct/inbox/history 仍需有效 `awiki.info` 测试身份后复跑。 |
| 新增或缺失测试 | 未新增测试 | 本步只更新文档证据；已运行 existing public tests 和 CLI smoke。 |
| 已更新或缺失文档 | 已更新 | `plan/20260705-rwiki-cn-deployment/plan.md`、本 Plan、Step 01 执行状态。 |
| 并行安全是否仍成立 | 是 | 只有 coordinator 写文档。 |
| Agent 是否越界修改 | 否 | 只修改 Step 01 允许的 plan/docs 路径。 |
| 互斥资源是否被修改 | 是 | 修改 `plan/20260705-rwiki-cn-deployment/plan.md`，符合 Step 01 授权。 |
| 合并风险 | 低 | 文档变更；无 runtime 行为变化。 |
| Group gate 影响 | 无 | 串行 |

## 10. Commit 要求

- Commit 时机：public gate 证据、Review 和必要 docs/script/test 更新完成后。
- Commit 范围：只包含 Step 01 的脚本、测试、README/plan 变更。
- Commit 前状态：记录 `git status --short --branch`。
- 纳入文件：执行时填写。
- Commit 后证据：记录 commit hash 和 commit 后 `git status --short --branch`。
- 建议消息：`docs: refresh public interop gate evidence` 或 `test: add public interop smoke gate`。

## 11. Blocked 处理

| Blocker | 证据 | 已尝试方案 | 影响范围 | 是否影响并行组 | 是否影响合并门禁 | 下一步决策 |
|---|---|---|---|---|---|---|
| awiki.info 测试凭据不可用 | 执行时填写 | 只读 DID/capability/proof 检查 | 当前步骤 | 是 | 是 | 记录 blocker，等待用户提供凭据或保留脚本/docs 改进 |
| 双向 gate 失败 | 执行时填写 | 区分 DID doc、HTTP signature、origin proof、recipient local、CLI config | 当前步骤 / 后续协议步骤 | 是 | 是 | 若为本仓 regression，先修；若为 peer 问题，记录后进入 Step 02 需用户确认 |

## 12. Plan 变更记录

| 日期 | 变更 | 原因 | 主 Plan 变更记录链接 |
|---|---|---|---|
| 2026-07-10 | 创建 Step 01 | 初始计划 | `../plan.md#20-plan-变更记录` |
| 2026-07-10 | 记录公网复核结果 | `awiki.info` 公网 DID 文档当前 key 已与历史 message-service 实际 key 一致；live 双向 direct 因缺少有效 `awiki.info` 测试凭据未运行 | `../plan.md#20-plan-变更记录` |

## 13. 风险、回滚与后续文档

- 风险：公网 peer 状态和凭据可能不稳定，导致 gate 失败与本仓无关。
- 并行执行风险：多个 writer 同时修改历史部署 plan 会让证据混乱。
- 合并冲突风险：低，主要在 README/plan/scripts。
- Group gate 失败回退：保持本地 cross-domain smoke 和 public verify 作为替代证据，live gate 标记 blocked。
- Agent 交接说明：下一步 Step 02 只能在 Step 01 证据记录完成或明确 blocker 后启动。
- 回滚 / 回退：回退脚本/test/docs 变更，不影响 runtime。
- 后续文档：Step 06 最终统一同步 README/deploy/harness/system-test。
