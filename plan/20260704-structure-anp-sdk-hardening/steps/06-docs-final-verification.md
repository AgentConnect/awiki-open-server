# Step 06：文档、部署示例与最终 L3 验证

主 Plan：[../plan.md](../plan.md)  
Step index：06  
状态：done

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done |
| Branch | main |
| Started | 2026-07-04 11:55:54 +0800 |
| Completed | 2026-07-04 11:59:52 +0800 |
| Commit | TBD |
| Review evidence | 本地 review + 只读 explorer：README/AGENTS/deploy 已同步 ANP SDK 0.8.8、模块结构、测试拆分、rwiki.cn 部署边界、contact verification 禁用和公网 nginx route；扫描确认生产代码未新增 `awiki.info` 代理、Aliyun、Redis/MySQL 或相邻服务依赖。 |
| Verification evidence | `PYTHONPATH=../anp/anp:src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=../anp/anp:src python3 -m pytest tests -q` 64 passed, 2 skipped；ASGI smoke ok=true；cross-domain local smoke ok=true；Rust CLI local smoke ok=true；`verify-public https://rwiki.cn` ok=true；`AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 ... tests/test_rwiki_cn_system.py -q` 2 passed；diff check pass。 |
| Next action | 提交 Step 06 后结束计划 |
| Assigned agent | agent-docs |
| Parallel group | D |
| Parallel safe | yes |
| Parallel with | Step 05 |
| Conflict resources | `awiki-open-server/README.md`, `awiki-open-server/AGENTS.md`, `awiki-open-server/deploy/*`, Plan docs |
| Baseline commit | 96e4dbf |
| Worktree / branch | main |
| Merge gate | Final L3 gate |
| Verification gate | docs + full local + Rust CLI + rwiki.cn public |
| Gate status | pass_with_explicit_sdk_path |

## 2. 目标

- 结果：README、AGENTS、deploy 示例和 Plan 台账准确描述 ANP SDK 0.8.8、结构拆分、路径配置和 MVP 边界。
- 用户 / 系统可见行为：贡献者知道如何运行、测试、验证 `rwiki.cn`，以及本仓不代理 User Service / awiki.info。
- 非目标：不修改源码行为，除非文档验证发现需要前序步骤修复。
- 完成标准：L3 final review 有证据；未运行项有原因；最终工作区干净。

## 3. 设计方法

- 设计边界：文档描述实现后的事实，不提前承诺未实现能力。
- 核心决策：明确 `anp==0.8.8`，User Service 仅作参考，不作运行时依赖。
- 兼容性：保留 no phone/email/Aliyun、no E2EE、no federation、no group management 边界。
- 风险控制：public gate 失败时记录具体 endpoint/status/body 摘要，不用本地测试替代公网互通。

## 4. 实现方法

1. 更新 README 的依赖、结构、ANP SDK、路径配置、验证命令。
2. 更新 AGENTS 的项目结构和测试说明。
3. 更新 deploy 示例中 nginx path、env 示例和 `rwiki.cn` 说明。
4. 回填本 Plan 和 Step 文档执行台账、Review 证据、验证证据。
5. 执行最终验证命令。
6. 做 final global review，确认没有相邻仓库改动。

## 5. 路径

| 仓库 / 模块 / 文件 | 计划变更 | 备注 |
|---|---|---|
| `awiki-open-server/README.md` | 同步 SDK/结构/验证 | Durable docs |
| `awiki-open-server/AGENTS.md` | 同步 contributor guide | 当前仓规则 |
| `awiki-open-server/deploy/*` | 同步 endpoint/env 示例 | rwiki.cn |
| `awiki-open-server/plan/20260704-structure-anp-sdk-hardening/` | 回填执行证据 | Goal source of truth |

## 6. 依赖与并行约束

- 前置步骤：Step 04；最终证据依赖 Step 05。
- 可并行步骤：Step 05 的测试拆分。
- 不可并行步骤：最终 commit 前必须等待 Step 05 全量测试结果。
- 并行安全依据：主要改 docs，与 Step 05 tests 分离。
- 合并前置条件：Step 05 commit 和 full pytest evidence。
- 合并后验证门禁：Final L3 gate。

## 7. 验收标准

- [x] README/AGENTS/deploy 与实际结构、配置和命令一致。
- [x] 文档明确 ANP SDK `anp==0.8.8`。
- [x] 文档明确 User Service compat 本地实现，不代理、不调用相邻服务。
- [x] Final L3 验证命令有结果或明确 skip/blocker。
- [x] `git status --short --branch` 干净。

## 8. 验证方式

| 检查项 | 命令 / 方法 | 运行时机 | 预期证据 | 门禁类型 |
|---|---|---|---|---|
| Compile | `PYTHONPATH=src python3 -m compileall -q src scripts tests` | final 前 | pass | Final gate |
| Full pytest | `PYTHONPATH=src python3 -m pytest tests -q` | final 前 | pass | Final gate |
| ASGI smoke | `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-final-asgi` | final 前 | pass | Final gate |
| Cross-domain smoke | `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-final-cross --clean` | final 前 | pass | Final gate |
| Rust CLI local | `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin <bin> --data-root /tmp/awiki-open-server-final-rust --clean` | final 前 | pass 或 blocker | Final gate |
| Public verify | `PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.cn --did-domain rwiki.cn` | final 前 | ok=true | Final gate |
| Public tests | `AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 PYTHONPATH=src python3 -m pytest tests/test_rwiki_cn_system.py -q` | final 前 | pass 或 blocker | Final gate |
| Workspace | `git status --short --branch` | final 后 | clean | Final gate |

## 9. Review 环节

- Review 重点：ANP SDK 版本、docs 与实际命令一致、MVP 非目标仍清楚、public route 白名单、安全边界、相邻仓库未改。

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | README/AGENTS 未描述当前模块拆分；deploy README 缺少 venv/install 和 contact verification 禁用说明；nginx 示例未列 root-level auth/ws ticket 兼容路由 | 只读 explorer + 本地 review |
| 已修复问题 | 补 README Code Structure、SDK 0.8.8、focused test map 和 API route；更新 AGENTS 结构/测试指南；更新 deploy checklist；补 nginx route proxy | 不改源码行为 |
| 剩余风险 | 本机默认安装的 `anp==0.6.8` 仍会阻断标准 `PYTHONPATH=src`，本次验证使用 sibling `../anp/anp` 0.8.8 源码路径；生产安装需 `pip install -e .` 拉取 `anp==0.8.8` | 已在 README/AGENTS 说明 |
| 新增或缺失测试 | 未新增测试；执行最终 full/local/Rust/public gates | 全部通过 |
| 已更新或缺失文档 | README、AGENTS、deploy README、nginx 示例和 Plan 台账已更新 | harness 文档未改，因只修改本仓 |
| 并行安全是否仍成立 | 是 | Step 05 已完成提交 |

## 10. Commit 要求

- Commit 范围：docs/deploy/Plan evidence。
- 建议消息：`docs: document anp sdk hardening`

## 11. Blocked 处理

| Blocker | 证据 | 已尝试方案 | 影响范围 | 是否影响并行组 | 是否影响合并门禁 | 下一步决策 |
|---|---|---|---|---|---|---|
| rwiki.cn public gate 失败 | verify-public 输出 | 检查 nginx/DID doc/app health | Final | 是 | 是 | 记录 blocker，等待部署修复 |
| Rust CLI bin 不存在 | shell error | 记录未运行原因 | Final CLI evidence | 否 | 否 | 使用已构建 bin 或记录 skip |

## 12. Plan 变更记录

| 日期 | 变更 | 原因 | 主 Plan 变更记录链接 |
|---|---|---|---|
| 2026-07-04 | 初始创建 | L3 文档与最终验证 | `../plan.md#16-plan-变更记录` |

## 13. 风险、回滚与后续文档

- 风险：公网环境不受代码提交完全控制。
- 回滚 / 回退：文档 commit 可独立回退；public blocker 不应通过扩大本地 API 绕过。
- 后续文档：若实现改变跨仓库架构，再单独更新 harness repo profile/context。
