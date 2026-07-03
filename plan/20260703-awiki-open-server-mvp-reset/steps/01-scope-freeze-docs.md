# Step 01：MVP scope freeze 文档收敛

主 Plan：[../plan.md](../plan.md)  
Step index：01  
状态：done

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done |
| Branch | 当前 worktree |
| Started | 2026-07-03 |
| Completed | 2026-07-03 |
| Commit | 未提交 |
| Review evidence | `require.md`、`README.md`、旧主 Plan 和 reset Plan 已统一 v0.1 边界；旧 Step 27 状态已修正；`AGENTS.md` 未修改；sibling repo 未修改 |
| Verification evidence | `rg -n "Aliyun|阿里|短信|邮件|email|phone|otp" README.md require.md plan/20260703-awiki-open-server-mvp-reset plan/20260702-awiki-open-server-mvp/plan.md`：命中项均为禁止/禁用/占位说明或历史计划证据 |
| Next action | Step 02 已完成；继续 Step 04 public blocker |
| Assigned agent | main + read-only explorers |
| Parallel group | A |
| Parallel safe | yes for read-only audit; no for writes |
| Parallel with | Step 04 只读部署审计 |
| Conflict resources | `awiki-open-server/README.md`, `awiki-open-server/require.md`, `awiki-open-server/plan/**` |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | docs review + grep audit |

## 2. 目标

- 结果：把 v0.1 MVP 目标写清楚，停止继续追逐完整 User Service / Message Service 兼容。
- 用户 / 系统可见行为：README/require/Plan 都明确“不使用邮件或手机号码验证过程、不引入阿里云依赖”。
- 非目标：不重写所有旧计划，不删除历史已做兼容代码，不修改 sibling repo。
- 完成标准：P0/P1/P2、contact verification 默认关闭、Step 27 状态修正、Step 09 公网 Gate 作为唯一真实互通恢复点均写入文档。

## 3. 设计方法

- 设计边界：文档先冻结目标，再允许代码继续。
- 核心决策：P0 只保留 DID、direct、公开 DID document、`/anp-im/rpc`、Rust CLI local gate 和公网双向互通；P1 只保留当前客户端必要 shim；P2 冻结。
- 契约 / API / 数据流：不改变 API 行为，行为修改归 Step 02。
- 兼容性：旧兼容项不删除，但从 MVP 完成标准移出。
- 风险控制：旧主 Plan 保留历史，新增 reset Plan 作为后续入口。

## 4. 实现方法

1. 更新 `awiki-open-server/require.md`：新增 v0.1 目标重定义、无手机/邮箱/阿里云约束、P0/P1/P2 兼容解释。
2. 更新 `awiki-open-server/README.md`：明确 Community 非目标、contact verification 默认关闭、Rust CLI phone/otp 只是占位参数。
3. 修正 `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md`：Step 27 从 `in_progress` 改为 `done-with-pending-online-gate`，恢复指针回到 Step 09 / reset Plan。
4. 维护本 reset Plan 和执行台账。

## 5. 路径

| 仓库 / 模块 / 文件 | 计划变更 | 备注 |
|---|---|---|
| `awiki-open-server/require.md` | 目标重定义 | 本仓权威需求 |
| `awiki-open-server/README.md` | 运行、配置、兼容说明 | 面向开发者 |
| `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md` | 状态修正和指针 | 历史计划保留 |
| `awiki-open-server/plan/20260703-awiki-open-server-mvp-reset/**` | 新计划 | 后续入口 |

## 6. 依赖与并行约束

- 前置步骤：无。
- 可并行步骤：Step 04 只读部署审计。
- 不可并行步骤：任何写 README/require/Plan 的步骤。
- 并行安全依据：explorer 只读；Coordinator 单写。
- 互斥资源 / 冲突路径：所有文档目标文件。
- 外部文档或决策：用户明确要求。
- 环境前提：无。
- 合并前置条件：所有 explorer 结论已吸收或记录未采纳原因。
- 合并后验证门禁：grep audit。

## 7. 验收标准

- [x] `require.md` 明确 v0.1 不使用邮件/手机号验证，不引入阿里云。
- [x] `README.md` 不再把 dev SMS/email 描述为默认 MVP 能力。
- [x] 旧主 Plan Step 27 状态与小 Plan 一致。
- [x] 恢复指针回到 Step 09 / 本 reset Plan。
- [x] Review 发现已经修复或记录。

## 8. 验证方式

| 检查项 | 命令 / 方法 | 运行时机 | 预期证据 | 门禁类型 |
|---|---|---|---|---|
| Docs grep | `rg -n "Aliyun|阿里|短信|邮件|email|phone|otp" README.md require.md plan/20260703-awiki-open-server-mvp-reset plan/20260702-awiki-open-server-mvp/plan.md` | Review 前 | 默认能力叙述符合新边界 | Step gate |
| Path check | `test -f plan/20260703-awiki-open-server-mvp-reset/plan.md` | Review 前 | 文件存在 | Step gate |

## 9. Review 环节

- Review 时机：文档 patch 完成后。
- Review 重点：是否还有 scope creep、默认 contact verification、阿里云依赖、Step 27 状态不一致。

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | README API 列表容易把 contact routes 误解为 core | 已改成 core + compatibility routes，并标明默认禁用 |
| 已修复问题 | Step 27 状态不一致；默认 MVP 边界未写入 | 已修复 |
| 剩余风险 | 旧历史计划仍保留 dev OTP 历史证据 | reset Plan 作为后续入口 |
| 新增或缺失测试 | 不适用 | 文档步骤 |
| 已更新或缺失文档 | 已更新 `require.md`、`README.md`、旧主 Plan、reset Plan |  |
| 并行安全是否仍成立 | 是 | 只读 explorer + Coordinator 单写 |

## 10. Commit 要求

- Commit 时机：Step 01 Review 和 docs grep 完成后。
- Commit 范围：只包含文档和计划修正。
- 建议消息：`docs: reset open server mvp scope`

## 11. Blocked 处理

| Blocker | 证据 | 已尝试方案 | 影响范围 | 是否影响并行组 | 是否影响合并门禁 | 下一步决策 |
|---|---|---|---|---|---|---|
| 无 |  |  |  |  |  |  |

## 12. Plan 变更记录

| 日期 | 变更 | 原因 | 主 Plan 变更记录链接 |
|---|---|---|---|
| 2026-07-03 | 新增 Step 01 | 用户要求先设计 plan 并重置目标 | `../plan.md#16-plan-变更记录` |

## 13. 风险、回滚与后续文档

- 风险：旧兼容历史较多，文档可能仍残留旧措辞。
- 并行执行风险：多个 writer 改 Plan 会冲突；由 Coordinator 单写。
- 合并冲突风险：低。
- Group gate 失败回退：继续修正文档。
- Agent 交接说明：本步骤完成后从 Step 02 继续。
- 回滚 / 回退：还原文档 patch。
- 后续文档：Step 03/04 回填验证和 blocker。
