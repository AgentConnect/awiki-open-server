# Step 04：Messaging 与 attachment 模块拆分

主 Plan：[../plan.md](../plan.md)  
Step index：04  
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
| Next action | 拆 direct/group/sync/read-state/attachment |
| Assigned agent | agent-messaging |
| Parallel group | C |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/services.py`, `awiki-open-server/src/awiki_open_server/storage/db.py` |
| Baseline commit | TBD |
| Worktree / branch | TBD |
| Merge gate | Messaging gate |
| Verification gate | messaging/attachment smoke |
| Gate status | pending |

## 2. 目标

- 结果：将 direct、group participant、sync/read-state、attachment 从 `services.py` 中拆成清晰 domain module。
- 用户 / 系统可见行为：本域 direct/group/attachment/sync API 和 public `/anp-im/rpc` 行为不变。
- 非目标：不新增 federation、E2EE、群创建/管理、远端投影、跨域群。
- 完成标准：`services.py` 明显瘦身；public handler 白名单保持 `anp.get_capabilities`、`direct.send`、`group.get_info`、`group.join`、`attachment.get_download_ticket`。

## 3. 设计方法

- 设计边界：messaging 处理 direct/group/sync/read-state；attachment 处理 slot/object/ticket；protocol 只由 Step 01 adapter 负责。
- 核心决策：先搬迁保持行为，后续再优化内部模型。
- 契约 / API / 数据流：保持 handler names 和 response shape 不变。
- 兼容性：保留 CLI local gate 所需 legacy fields。
- 迁移策略：storage schema 不破坏；sequence helper 统一到 `Store` 或 dedicated storage helper。

## 4. 实现方法

1. 新增 `awiki_open_server/messaging/`，迁移 capabilities、direct、group、sync、read-state。
2. 新增 `awiki_open_server/attachments/`，迁移 attachment slot/upload/commit/ticket/download support。
3. 将 storage `MAX(server_seq)+1` 重复逻辑统一为 helper。
4. 保留 `services.py` 中 handler map 或改为从 domain module 聚合，避免 routes 大范围改动。
5. 确认 `_publish_realtime`、`current_did`、`get_store` 等共享 helper 放入合适共享模块。
6. 跑 local smoke 和 focused tests。

## 5. 路径

| 仓库 / 模块 / 文件 | 计划变更 | 备注 |
|---|---|---|
| `awiki-open-server/src/awiki_open_server/messaging/` | 新增 messaging domain | direct/group/sync |
| `awiki-open-server/src/awiki_open_server/attachments/` | 新增 attachment domain | object/ticket |
| `awiki-open-server/src/awiki_open_server/services.py` | 搬迁并瘦身 | 保留兼容聚合 |
| `awiki-open-server/src/awiki_open_server/storage/db.py` | 统一 helper | 不做破坏性迁移 |
| `awiki-open-server/tests/` | focused messaging/attachment 调整 | 可先保留旧文件，Step 05 再拆 |

## 6. 依赖与并行约束

- 前置步骤：Step 02、Step 03。
- 可并行步骤：无。
- 不可并行步骤：Step 05/06 需等本步骤完成。
- 并行安全依据：无，`services.py` 和 storage 是共享大文件。
- 合并前置条件：Wave B group gate 通过。
- 合并后验证门禁：messaging smoke gate。

## 7. 验收标准

- [ ] `services.py` 不再承载主要 direct/group/attachment 实现。
- [ ] public `/anp-im/rpc` 白名单未扩大。
- [ ] direct cross-domain local smoke 通过。
- [ ] group participant 仍不支持 create/manage。
- [ ] attachment ticket 权限不回退。
- [ ] 本步骤在进入 Step 05/06 前已创建聚焦 commit。

## 8. 验证方式

| 检查项 | 命令 / 方法 | 运行时机 | 预期证据 | 门禁类型 |
|---|---|---|---|---|
| Focused messaging | `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q` | commit 前 | pass | Step gate |
| Cross-domain smoke | `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step04-cross --clean` | commit 前 | pass | Step gate |
| Local smoke | `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step04-asgi` | commit 前 | pass | Step gate |

## 9. Review 环节

- Review 重点：搬迁是否只改结构不改行为；sequence 生成是否一致；ticket/read-state/sync 是否保留 owner 校验；public API 未扩大。

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | TBD | TBD |
| 已修复问题 | TBD | TBD |
| 剩余风险 | TBD | TBD |
| 新增或缺失测试 | TBD | TBD |
| 并行安全是否仍成立 | 不适用 | 串行步骤 |

## 10. Commit 要求

- Commit 范围：messaging/attachment/storage helper 搬迁和必要测试。
- 建议消息：`messaging: split message and attachment services`

## 11. Blocked 处理

| Blocker | 证据 | 已尝试方案 | 影响范围 | 是否影响并行组 | 是否影响合并门禁 | 下一步决策 |
|---|---|---|---|---|---|---|
| 搬迁导致循环 import | import/pytest error | 抽 shared helper | 当前步骤 | 是 | 是 | 调整模块边界 |

## 12. Plan 变更记录

| 日期 | 变更 | 原因 | 主 Plan 变更记录链接 |
|---|---|---|---|
| 2026-07-04 | 初始创建 | 收敛 messaging/attachment 大文件职责 | `../plan.md#16-plan-变更记录` |

## 13. 风险、回滚与后续文档

- 风险：大规模搬迁产生隐藏行为差异。
- 回滚 / 回退：回退本步骤 commit；优先小块搬迁。
- 后续文档：Step 06 更新结构说明。
