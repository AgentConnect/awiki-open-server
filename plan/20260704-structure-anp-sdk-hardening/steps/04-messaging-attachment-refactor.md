# Step 04：Messaging 与 attachment 模块拆分

主 Plan：[../plan.md](../plan.md)  
Step index：04  
状态：done

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done |
| Branch | main |
| Started | 2026-07-04 11:28:14 +0800 |
| Completed | 2026-07-04 11:46:44 +0800 |
| Commit | 1b5ab25 |
| Review evidence | 本地 review + 只读 explorer：`services.py` 瘦身为兼容 facade；新增 `messaging/core.py`、`attachments/core.py`、`shared/runtime.py`；`routes.py` public allowlist 仍只暴露 5 个跨域方法；测试 monkeypatch 已跟随新模块边界；未引入 federation/E2EE/群管理/外部服务代理。 |
| Verification evidence | compileall pass；`PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_messaging_objects.py tests/test_route_config.py -q` 28 passed；`PYTHONPATH=../anp/anp:src python3 -m pytest tests -q` 64 passed, 2 skipped；smoke-asgi ok=true；cross-domain local smoke ok=true；production code forbidden dependency/domain scan pass。 |
| Next action | 进入 Step 05/06 |
| Assigned agent | agent-messaging |
| Parallel group | C |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/services.py`, `awiki-open-server/src/awiki_open_server/storage/db.py` |
| Baseline commit | 0a51905 |
| Worktree / branch | main |
| Merge gate | Messaging gate |
| Verification gate | messaging/attachment smoke |
| Gate status | pass_with_explicit_sdk_path |

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

- [x] `services.py` 不再承载主要 direct/group/attachment 实现。
- [x] public `/anp-im/rpc` 白名单未扩大。
- [x] direct cross-domain local smoke 通过。
- [x] group participant 仍不支持 create/manage。
- [x] attachment ticket 权限不回退。
- [x] 本步骤在进入 Step 05/06 前已创建聚焦 commit。

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
| 发现问题 | 测试仍 patch `services._http_get_json/_http_post_json`，拆分后不再命中新模块运行路径 | 已由 focused tests 暴露 |
| 已修复问题 | 测试改为 patch `shared.runtime._http_get_json` 和 `messaging.core._http_post_json`；补 public allowlist deny 回归；direct/group sequence 改用既有 `Store.next_seq()` | 不改公开 API |
| 剩余风险 | `messaging/core.py` 仍超过 1000 行，后续 Step 05/06 之后可再按 direct/group/read-state 分层 | 本步骤先保持搬迁不改行为 |
| 新增或缺失测试 | 新增 `/anp-im/rpc` 对 `sync.delta`、`attachment.create_slot`、`group.send`、`group.leave` 的 `method_not_found` 回归 | 全量测试通过 |
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
