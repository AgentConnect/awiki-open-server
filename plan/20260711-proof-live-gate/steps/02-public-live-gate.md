# Step 02：public live gate 入口与 awiki.info 凭据阻塞证据

主 Plan：[../plan.md](../plan.md)  
Step index：02  
状态：review

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | review |
| Branch | `main` |
| Started | 2026-07-11 |
| Completed | 2026-07-11 |
| Commit | 待回填（提交后由 final 台账回填） |
| Review evidence | Public gate Review 完成：`smoke-awiki-info` 只输出凭据 set/unset 和缺失字段，不打印 token/origin proof；capability-only 与 live direct 判定分离；未代理 `awiki.info`；未把 skipped direct 标记为 pass。 |
| Verification evidence | CLI smoke tests 7 passed；`verify-public --base-url https://rwiki.cn --did-domain rwiki.cn` pass；guarded public system tests 2 passed；`smoke-awiki-info --base-url https://awiki.info --did-domain rwiki.cn` capability pass，`direct_ready=false`，`live_direct_gate=skipped_missing_credentials`；full local tests 75 passed, 2 skipped；`git diff --check` pass。 |
| Next action | 创建 Step 02 聚焦 commit，然后执行 final Review |
| Assigned agent | coordinator |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/scripts/awiki_open_cli.py`, README, 本 Plan |
| Baseline commit | `b2cc11e` |
| Worktree / branch | `main` |
| Merge gate | Public gate |
| Verification gate | `verify-public`, public system tests, `smoke-awiki-info` |
| Gate status | partial_with_recorded_blocker |

## 2. 目标

- 结果：public readiness 和 `awiki.info` remote diagnostic 有明确可重复入口；有凭据时能执行 direct smoke，无凭据时输出具体缺失字段和 blocker。
- 用户 / 系统可见行为：`smoke-awiki-info` 不再只给泛泛的 direct skipped 文案，而是列出缺少哪些 `AWIKI_INFO_*`；README 明确 full live direct 需要真实远端凭据。
- 非目标：不自动生成或伪造 `awiki.info` 凭据；不把 `awiki.info` 当作后端；不把 capability-only 结果标记为双向 direct pass。
- 完成标准：public readiness 命令已运行；`smoke-awiki-info` capability 已运行；若无凭据，计划和最终回复明确 blocker；若有凭据，direct smoke 真实通过并记录 message id。

## 3. 设计方法

- 设计边界：`rwiki.cn` readiness 证明本仓公开部署可被访问；`awiki.info` smoke 证明远端 peer capability 和可选 direct send；双向 inbox/history 仍需要远端账号/CLI 或对端可验证接收证据。
- 核心决策：direct smoke 的必需输入为 token、sender DID、recipient DID、origin proof JSON；缺一不可。
- 契约 / API / 数据流：capability 使用 ANP JSON-RPC `params.meta/body`；direct 使用 `params.meta/auth/body`。
- 兼容性：保持现有 CLI flags 和 env names；只增强输出。
- 迁移策略：不改服务端 schema。
- 风险控制：不记录真实 token 或完整 origin proof；输出只记录字段 set/unset。

## 4. 实现方法

1. 如有必要增强 `scripts/awiki_open_cli.py::smoke_awiki_info`：
   - 输出 `direct_ready`；
   - 输出 `missing_credentials` 列表；
   - 有全部参数时执行 direct smoke；
   - 无参数时返回 0 但标记 `direct_skipped`，避免 capability-only 被误读。
2. 更新 README / README.cn 的 remote diagnostics 说明：
   - 环境变量名；
   - capability-only 与 live direct 的区别；
   - 当前没有凭据不能视为双向完成。
3. 运行 public readiness：
   - `verify-public --base-url https://rwiki.cn --did-domain rwiki.cn`
   - guarded `tests/test_rwiki_cn_system.py`
4. 运行 `smoke-awiki-info --base-url https://awiki.info --did-domain rwiki.cn`。
5. 若环境中存在 `AWIKI_INFO_*`，再运行 direct smoke 并记录结果；否则回填 blocker。

## 5. 路径

| 仓库 / 模块 / 文件 | 计划变更 | 备注 |
|---|---|---|
| `awiki-open-server/scripts/awiki_open_cli.py` | 可选增强 `smoke-awiki-info` 输出 | 不记录 secret |
| `awiki-open-server/README.md` | 英文 remote diagnostics 更新 | docs sync |
| `awiki-open-server/README.cn.md` | 中文 remote diagnostics 更新 | docs sync |
| `awiki-open-server/plan/20260711-proof-live-gate/` | 回填 public/live gate 证据 | 本轮计划 |

## 6. 依赖与并行约束

- 前置步骤：Step 01 完成并提交。
- 可并行步骤：无。
- 不可并行步骤：不能与 Step 01 同时修改 `scripts/awiki_open_cli.py` 和 README。
- 并行安全依据：public gate 证据依赖 Step 01 smoke 已真实签名。
- 互斥资源 / 冲突路径：见路径表。
- 外部文档或决策：README 中 public deployment / remote diagnostics。
- 环境前提：公网可访问 `https://rwiki.cn` 和 `https://awiki.info`；direct smoke 需要 `AWIKI_INFO_*` 凭据。
- 合并前置条件：public readiness/capability 运行并记录；direct 未运行时记录 blocker。
- 合并后验证门禁：final global Review。

## 7. 验收标准

- [x] `verify-public` 对 `https://rwiki.cn` 通过，或记录网络/服务失败。
- [x] guarded public system tests 通过，或记录失败原因。
- [x] `smoke-awiki-info` capability 通过，或记录失败原因。
- [x] 缺少 `AWIKI_INFO_*` 时输出明确 missing credentials，不声明 direct pass。
- [ ] 若凭据存在，direct smoke 执行并记录 message id / 结果。
- [x] README / README.cn 没有把 capability-only 写成双向 live gate。
- [x] 没有提交 token、origin proof、private key 或个人测试账号信息。
- [ ] 本步骤完成后已经创建聚焦 commit，或记录为什么仅计划回填。

## 8. 验证方式

| 检查项 | 命令 / 方法 | 运行时机 | 预期证据 | 门禁类型 |
|---|---|---|---|---|
| Public readiness | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.cn --did-domain rwiki.cn` | Step 02 | pass | Public gate |
| Public system | `cd awiki-open-server && AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_rwiki_cn_system.py -q` | Step 02 | pass | Public gate |
| awiki.info capability | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-awiki-info --base-url https://awiki.info --did-domain rwiki.cn` | Step 02 | capability pass + direct skipped if credentials missing | Public peer gate |
| awiki.info direct | 同上，带 `AWIKI_INFO_TOKEN`、`AWIKI_INFO_SENDER_DID`、`AWIKI_INFO_RECIPIENT_DID`、`AWIKI_INFO_ORIGIN_PROOF_JSON` | 仅凭据存在时 | direct message id | Live direct gate |
| Hygiene | `cd awiki-open-server && git diff --check` | commit 前 | pass | Hygiene |

如果某个命令不能运行，必须记录原因、影响和替代证据。

## 9. Review 环节

- Review 时机：脚本/docs/计划回填完成后、commit 前。
- Review 重点：不泄露 secrets；不把 skipped direct 当成 pass；不代理 `awiki.info`；public readiness 与 live direct 判定分离；README 中凭据要求准确。
- Review 结论必须在 commit 前记录；必须修复必要问题，或明确记录剩余风险。

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | 无阻断问题 | 原脚本 direct skipped 文案不够机器可读，已增强为 `credential_status` / `missing_credentials` / `direct_ready` / `live_direct_gate`。 |
| 已修复问题 | 已修复 | README / README.cn 已说明 env vars 和 capability-only 与 live direct 的区别。 |
| 剩余风险 | 有 | 当前环境缺少 `AWIKI_INFO_TOKEN`、`AWIKI_INFO_SENDER_DID`、`AWIKI_INFO_RECIPIENT_DID`、`AWIKI_INFO_ORIGIN_PROOF_JSON`；因此不能声明 `rwiki.cn <-> awiki.info` live direct 通过。 |
| 新增或缺失测试 | 已新增 | `tests/test_cli_smoke.py` 覆盖缺凭据输出和凭据完整时 direct path 会调用。 |
| 已更新或缺失文档 | 已更新 | remote diagnostics 文档已同步。 |
| 并行安全是否仍成立 | 成立 | 未启动并行写入。 |
| Agent 是否越界修改 | 未越界 | 只改 Step 02 授权路径。 |
| 互斥资源是否被修改 | 已修改 | `scripts/awiki_open_cli.py`、README 和 CLI smoke tests。 |
| 合并风险 | 低 | 输出新增字段，不改变 flags；direct 仍需完整凭据才执行。 |
| Group gate 影响 | 无 | 串行 |

## 10. Commit 要求

- Commit 时机：public checks、Review、docs/plan 回填完成后。
- Commit 范围：public gate 脚本/docs/计划证据；不包含 secrets。
- Commit 前状态：`main...origin/main [ahead 12]`；Step 02 文件已修改。
- 纳入文件：`README.md`, `README.cn.md`, `scripts/awiki_open_cli.py`, `tests/test_cli_smoke.py`, `plan/20260711-proof-live-gate/`。
- Commit 后证据：待回填 commit hash 和 commit 后 `git status`。
- 遗留未提交变更：必须记录原因以及为什么安全。
- 建议消息：`interop: clarify awiki info live gate`

## 11. Blocked 处理

| Blocker | 证据 | 已尝试方案 | 影响范围 | 是否影响并行组 | 是否影响合并门禁 | 下一步决策 |
|---|---|---|---|---|---|---|
| 缺少 `awiki.info` live direct 测试凭据 | `AWIKI_INFO_TOKEN`、`AWIKI_INFO_SENDER_DID`、`AWIKI_INFO_RECIPIENT_DID`、`AWIKI_INFO_ORIGIN_PROOF_JSON` 均 unset；脚本默认 `auth_scheme` 可用 | 已运行 capability/readiness；脚本输出 `missing_credentials` | live direct 完成判定 | 否 | 是，live direct gate 不能 pass | 记录 blocker，不伪造完成 |

## 12. Plan 变更记录

| 日期 | 变更 | 原因 | 主 Plan 变更记录链接 |
|---|---|---|---|
| 2026-07-11 | 创建 Step 02 | 初始计划 | `../plan.md#16-plan-变更记录` |

## 13. 风险、回滚与后续文档

- 风险：public 网络或远端服务状态可能变化；需要在最终报告中使用具体日期和命令结果。
- 并行执行风险：无并行写入。
- 合并冲突风险：低。
- Group gate 失败回退：回退脚本/docs 提交；保留 Step 01 proof 变更。
- Agent 交接说明：若用户稍后提供凭据，直接从本 Step 的 direct smoke 命令恢复。
- 回滚 / 回退：回退本步骤 commit。
- 后续文档：若 future 将 live gate 放入 `awiki-system-test`，需要新计划同步 harness 和 system-test。
