# Step 06：系统测试与文档同步

主 Plan：[../plan.md](../plan.md)  
Step index：06  
状态：draft

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | pending |
| Branch | 执行时填写 |
| Started |  |
| Completed |  |
| Commit |  |
| Review evidence |  |
| Verification evidence |  |
| Next action | 等 Step 05 完成后，做 docs/system-test/global review |
| Assigned agent | coordinator |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 只读 docs review worker 可报告发现 |
| Conflict resources | `awiki-open-server/README.md`, `README.cn.md`, `deploy/`, `plan/`, possible `awiki-system-test/`, possible `awiki-harness/` |
| Baseline commit | 执行时填写 |
| Worktree / branch | 执行时填写 |
| Merge gate | Final docs and system verification gate |
| Verification gate | full local + smokes + public + docs checks |
| Gate status | pending |

## 2. 目标

- 结果：把前面步骤落地后的真实能力、边界、配置、gate 和剩余风险同步到文档和系统测试入口。
- 用户 / 系统可见行为：开发者可以按 README/runbook 复跑本地、公网、Rust CLI 和 public interop gate；Harness 或 system-test 中没有 stale 指引。
- 非目标：不把所有 open-server repo-local tests 强行上移到 `awiki-system-test`；不扩大 Community 功能边界。
- 完成标准：docs 与实现一致；必要的 cross-repo test/docs 已更新；最终全局 Review 和整体验证记录完整；所有 Step 台账关闭。

## 3. 设计方法

- 设计边界：`awiki-open-server` 子仓库 docs 记录本仓运行与配置；`awiki-harness` 只记录跨仓库摘要和入口；`awiki-system-test` 只承载跨服务 E2E。
- 核心决策：如果 public interop gate 仍主要是本仓脚本能力，先在本仓保留；只有跨服务稳定且有必要时再加到 `awiki-system-test`。
- 契约 / API / 数据流：docs 必须描述真实 `/im/rpc` 与 `/anp-im/rpc` surface、DID/auth security notes、attachment limitations、sync/realtime limitations。
- 兼容性：README 不宣称 unsupported 能力已实现；明确 `not_supported` 返回范围。
- 迁移策略：如前面步骤新增配置/schema，需要添加 upgrade/runbook notes。
- 风险控制：跨仓库修改前分别检查对应 repo `git status`，不覆盖用户改动。

## 4. 实现方法

1. 汇总 Steps 01-05 的 commits、changed paths、Review findings、verification evidence 和 residual risks。
2. 更新 `awiki-open-server/README.md` / `README.cn.md`：
   - 当前能力和边界。
   - 新增配置项。
   - public interop gate 命令。
   - attachment limits/lifecycle。
   - DID/auth security notes。
   - sync/read-state/realtime limitation。
3. 更新 `awiki-open-server/deploy/` 文档或 examples，如 public deployment env 需要新增配置。
4. 更新本 Plan 和 Step execution state：
   - 每步状态、commit hash、review evidence、verification evidence。
   - final global review section。
5. 判断是否修改 `awiki-system-test`：
   - 如果 live public interop gate 已稳定且适合跨服务 E2E，添加 guarded suite 或 docs。
   - 如果不修改，记录检查过的路径和理由。
6. 判断是否修改 `awiki-harness`：
   - 如果公开验证入口、架构摘要、repo profile 或 verification policy 需要新入口，更新对应 docs。
   - 如果不修改，记录检查过的 docs 和理由。
7. 运行最终验证：
   - full local tests。
   - local cross-domain smoke。
   - Rust CLI local smoke。
   - public verify + guarded public tests。
   - docs/harness checks 如有对应修改。
8. 做最终全局 Review：
   - diff review。
   - schema/config docs review。
   - security/privacy review。
   - uncommitted changes review。
9. 如本 Step 修改文件，创建最终聚焦 docs/system-test commit。

## 5. 路径

| 仓库 / 模块 / 文件 | 计划变更 | 备注 |
|---|---|---|
| `awiki-open-server/README.md` | 同步能力、配置、gate、限制 | 主要路径 |
| `awiki-open-server/README.cn.md` | 中文同步 | 主要路径 |
| `awiki-open-server/deploy/` | 如新增 env/config/runbook | 视前面步骤 |
| `awiki-open-server/plan/20260710-open-server-next-functions-review/` | 回填执行台账和最终 Review | 必需 |
| `awiki-open-server/plan/20260705-rwiki-cn-deployment/plan.md` | 如 Step 01 未更新完，最终补同步 | 谨慎 |
| `awiki-system-test/` | 可选 guarded public interop or docs | 只有必要时 |
| `awiki-harness/context/` | 可选入口/验证/架构摘要更新 | 只有跨仓库入口变化时 |

## 6. 依赖与并行约束

- 前置步骤：Step 01-05 均 done。
- 可并行步骤：只读 docs review worker 可检查 README/harness/system-test 并报告。
- 不可并行步骤：最终台账、docs 修改和 commit 必须由 coordinator 单写。
- 并行安全依据：最终文档依赖全部实现状态，不能提前并行写。
- 互斥资源 / 冲突路径：README、plan、harness/system-test docs。
- 外部文档或决策：是否纳入 `awiki-system-test` 由 Step 01 live gate 稳定性决定。
- 环境前提：必要时可运行 public tests；如公网不可用则记录。
- 合并前置条件：最终验证和 Review 完成。
- 合并后验证门禁：final git status clean or documented.

## 7. 验收标准

- [ ] README/README.cn 描述与当前实现、capabilities、unsupported 边界一致。
- [ ] public interop runbook 可复跑，且凭据/secret 未入库。
- [ ] 新增配置项已同步 deploy examples 或记录无需更新。
- [ ] `awiki-system-test` 是否需要更新已有明确结论；若更新已跑对应 gate。
- [ ] `awiki-harness` 是否需要更新已有明确结论；若更新已跑 docs checks。
- [ ] 所有 Step 执行台账已回填 commit、review、verification、residual risks。
- [ ] 最终全局 Review 已完成，必要问题已修复或记录。
- [ ] 最终 `git status --short --branch` 已记录。
- [ ] 本步骤如修改文件，已创建聚焦 commit。

## 8. 验证方式

| 检查项 | 命令 / 方法 | 运行时机 | 预期证据 | 门禁类型 |
|---|---|---|---|---|
| Full local | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests -q` | final 前 | pass | Final gate |
| ASGI smoke | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir .awiki-open-server/final-asgi` | final 前 | pass | Final gate |
| Cross-domain local | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root .awiki-open-server/final-cross --clean` | final 前 | pass | Final gate |
| Rust CLI local | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin ../awiki-cli-rs2/target/debug/awiki-cli --data-root .awiki-open-server/final-rust-cli --clean` | final 前 | pass | Final gate |
| Public verify | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.cn --did-domain rwiki.cn` | final 前 | pass | Public gate |
| Public tests | `cd awiki-open-server && AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_rwiki_cn_system.py -q` | final 前 | pass or explicit skip reason | Public gate |
| Harness docs | `cd awiki-harness && python scripts/validate-docs.py && python scripts/check-drift.py` | 如果修改 harness，或 final docs audit 需要 | pass | Docs gate |
| System-test | `cd awiki-system-test && ...` focused command | 如果修改 system-test | pass | Cross-repo gate |

## 9. Review 环节

- Review 时机：docs/system-test 变更完成、final verification 完成后、commit 前。
- Review 重点：文档是否过度承诺、配置是否可复现、验证证据是否真实、跨仓库 docs 是否漂移、Plan 台账是否能支持恢复、是否有未提交敏感文件。
- Review 必须覆盖所有 changed repositories 的 `git status`。

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | 执行时填写 |  |
| 已修复问题 | 执行时填写 |  |
| 剩余风险 | 执行时填写 |  |
| 新增或缺失测试 | 执行时填写 |  |
| 已更新或缺失文档 | 执行时填写 |  |
| 并行安全是否仍成立 | 执行时填写 |  |
| Agent 是否越界修改 | 执行时填写 |  |
| 互斥资源是否被修改 | 执行时填写 |  |
| 合并风险 | 执行时填写 |  |
| Group gate 影响 | 无 | 串行 |

## 10. Commit 要求

- Commit 时机：最终 docs/system-test/global review 完成后。
- Commit 范围：只包含最终同步文档、系统测试入口、plan 台账更新。
- Commit 前状态：记录所有受影响 repo 的 `git status --short --branch`。
- Commit 后证据：记录 commit hash 和 commit 后状态。
- 建议消息：`docs: sync open server hardening gates`。

## 11. Blocked 处理

| Blocker | 证据 | 已尝试方案 | 影响范围 | 是否影响并行组 | 是否影响合并门禁 | 下一步决策 |
|---|---|---|---|---|---|---|
| Public tests 网络或 peer 不稳定 | 执行时填写 | verify-public、local cross-domain、记录 HTTP/DID error | final public gate | 是 | 可阻塞 release | 记录未验证风险并请用户确认是否接受 |
| `awiki-system-test` 环境不可用 | 执行时填写 | repo-local smoke、docs-only runbook | cross-repo gate | 是 | 视修改范围 | 如果改了 system-test 必须解决或回退 |
| harness docs check 失败 | 执行时填写 | 修 docs links/drift | docs gate | 是 | 是 | 修复后重跑 |

## 12. Plan 变更记录

| 日期 | 变更 | 原因 | 主 Plan 变更记录链接 |
|---|---|---|---|
| 2026-07-10 | 创建 Step 06 | 初始计划 | `../plan.md#20-plan-变更记录` |

## 13. 风险、回滚与后续文档

- 风险：最终 docs 可能与前面代码实现不完全同步。
- 并行执行风险：只读 worker 发现需要改 docs 时必须交给 coordinator 单写。
- 合并冲突风险：README/plan 容易和其他 docs 改动冲突。
- Group gate 失败回退：回退 Step 06 docs/system-test commit，不影响业务代码。
- Agent 交接说明：完成后主 Plan 应成为最终执行证据索引。
- 回滚 / 回退：回退 docs/system-test changes；保留业务步骤 commits。
- 后续文档：如未来改 Community 边界，必须新建 plan，不在本 Step 偷改范围。
