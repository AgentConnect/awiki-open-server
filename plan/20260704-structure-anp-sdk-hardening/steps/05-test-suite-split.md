# Step 05：测试拆分与验证矩阵收敛

主 Plan：[../plan.md](../plan.md)  
Step index：05  
状态：draft

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | pending |
| Branch | TBD |
| Started | TBD |
| Completed | TBD |
| Commit | TBD |
| Review evidence | TBD |
| Verification evidence | TBD |
| Next action | 拆分大测试文件并抽 helpers |
| Assigned agent | agent-tests |
| Parallel group | D |
| Parallel safe | yes |
| Parallel with | Step 06 |
| Conflict resources | `awiki-open-server/tests/` |
| Baseline commit | TBD |
| Worktree / branch | TBD |
| Merge gate | Full local gate |
| Verification gate | full pytest |
| Gate status | pending |

## 2. 目标

- 结果：将 `tests/test_messaging_objects.py` 和 `tests/test_identity_pages.py` 拆成按域组织的测试文件。
- 用户 / 系统可见行为：测试覆盖不减少，失败定位更清晰。
- 非目标：不借测试拆分改变业务行为。
- 完成标准：helpers 抽出；全量 pytest 通过；测试命名和 AGENTS 约定一致。

## 3. 设计方法

- 设计边界：测试只验证既有行为和前面步骤新结构；不新增未实现能力。
- 核心决策：按 identity_auth、did_documents、profiles_handles、direct_messages、group_participant、attachments、sync_read_state、protocol_anp_sdk 拆分。
- 兼容性：保留 `tests/test_rwiki_cn_system.py` opt-in 行为。
- 风险控制：先移动 helpers，再逐个文件拆分，保持 pytest 全量通过。

## 4. 实现方法

1. 新增 `tests/helpers.py` 或 `tests/fixtures_protocol.py`，放 `register`、DID keypair、origin proof、remote result 构造。
2. 拆 `test_identity_pages.py` 为多个 focused 文件。
3. 拆 `test_messaging_objects.py` 为 direct/group/attachment/sync/protocol 文件。
4. 更新 imports 和 conftest。
5. 跑 focused + full pytest。

## 5. 路径

| 仓库 / 模块 / 文件 | 计划变更 | 备注 |
|---|---|---|
| `awiki-open-server/tests/helpers.py` | 新增测试 helper | 避免重复 |
| `awiki-open-server/tests/test_identity_pages.py` | 拆分或缩小 | 可保留少量 smoke |
| `awiki-open-server/tests/test_messaging_objects.py` | 拆分或缩小 | 可保留 integration smoke |
| `awiki-open-server/tests/test_*` | 新增按域文件 | 保持 pytest 发现 |

## 6. 依赖与并行约束

- 前置步骤：Step 04。
- 可并行步骤：Step 06。
- 不可并行步骤：无，但 Step 06 最终文档证据需等本步骤命令结果。
- 并行安全依据：只改 tests；Step 06 主要改 docs。
- 互斥资源 / 冲突路径：`README.md` 若记录测试文件名，由 Step 06 最终同步。
- 合并后验证门禁：full local gate。

## 7. 验收标准

- [ ] 大测试文件被拆分或显著缩小。
- [ ] helpers 不依赖外部服务。
- [ ] public tests 仍默认 skip。
- [ ] 全量 pytest pass。
- [ ] 本步骤已创建聚焦 commit。

## 8. 验证方式

| 检查项 | 命令 / 方法 | 运行时机 | 预期证据 | 门禁类型 |
|---|---|---|---|---|
| Full pytest | `PYTHONPATH=src python3 -m pytest tests -q` | commit 前 | pass | Step gate |
| Compile | `PYTHONPATH=src python3 -m compileall -q src scripts tests` | commit 前 | pass | Step gate |

## 9. Review 环节

- Review 重点：拆分是否漏测、helpers 是否过度抽象、测试是否仍能独立运行、public tests 是否默认 skip。

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | TBD | TBD |
| 已修复问题 | TBD | TBD |
| 剩余风险 | TBD | TBD |
| 新增或缺失测试 | TBD | TBD |
| 并行安全是否仍成立 | TBD | 与 Step 06 docs 无冲突 |

## 10. Commit 要求

- Commit 范围：tests/helper 拆分，不含源码行为改动。
- 建议消息：`tests: split protocol and messaging coverage`

## 11. Blocked 处理

| Blocker | 证据 | 已尝试方案 | 影响范围 | 是否影响并行组 | 是否影响合并门禁 | 下一步决策 |
|---|---|---|---|---|---|---|
| 拆分后测试顺序依赖暴露 | pytest 失败 | 清理 fixtures/临时 data dir | 当前步骤 | 否 | 是 | 修复测试隔离 |

## 12. Plan 变更记录

| 日期 | 变更 | 原因 | 主 Plan 变更记录链接 |
|---|---|---|---|
| 2026-07-04 | 初始创建 | 降低大测试维护成本 | `../plan.md#16-plan-变更记录` |

## 13. 风险、回滚与后续文档

- 风险：机械拆分误删覆盖。
- 回滚 / 回退：回退本步骤 commit；保留旧测试文件。
- 后续文档：Step 06 更新 AGENTS 测试结构说明。
