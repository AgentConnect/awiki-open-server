# Step 02：协议、错误映射和幂等性硬化

主 Plan：[../plan.md](../plan.md)  
Step index：02  
状态：done

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done |
| Branch | `main` |
| Started | 2026-07-10T10:58:33Z |
| Completed | 2026-07-10T11:07:17Z |
| Commit | `a8b2e3c` (`messaging: harden protocol errors and idempotency`) |
| Review evidence | direct/group 幂等边界、冲突错误、ANP profile/security 校验、JSON-RPC 兼容、public allowlist、SQLite 兼容迁移已复核；剩余风险为未新增 `operation_id` 唯一索引，继续依赖 `message_id` 主键和运行时冲突判定。 |
| Verification evidence | focused idempotency/meta tests 4 passed；Step gate 25 passed；protocol SDK 9 passed；local cross-domain smoke pass；full local tests 66 passed, 2 skipped；`git diff --check` pass。 |
| Next action | 启动 Step 03 附件生命周期与安全补齐 |
| Assigned agent | agent-protocol |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/messaging/core.py`, `shared/jsonrpc.py`, `shared/errors.py`, `storage/db.py` |
| Baseline commit | `a0afa8e` |
| Worktree / branch | `main` |
| Merge gate | Local protocol hardening gate |
| Verification gate | focused messaging tests + local cross-domain smoke |
| Gate status | pass |

## 2. 目标

- 结果：让 direct/group 的 ANP envelope、重复请求、错误码、JSON-RPC 响应和 local/public admission 更稳定。
- 用户 / 系统可见行为：客户端重复发送相同 `message_id`/`operation_id` 不会生成不可预测重复消息；错误响应可被 CLI/App 稳定处理；public `/anp-im/rpc` 仍只暴露白名单能力。
- 非目标：不支持 Direct E2EE、Group E2EE、federation、group admin；不破坏 legacy flat params 兼容。
- 完成标准：direct/group idempotency 和 error mapping 有明确 tests；JSON-RPC HTTP status 兼容策略被记录；local tests 和 cross-domain smoke 通过。

## 3. 设计方法

- 设计边界：以 `message-service` v2 direct/group API 为参考，保持 Open Server local compatibility。
- 核心决策：先写兼容测试，再修改 dispatcher/handlers；避免改变旧 CLI 依赖的 response shape。
- 契约 / API / 数据流：`meta.profile`、`meta.security_profile`、`meta.sender_did`、`target.kind/did`、`operation_id`、`message_id` 是协议稳定字段；flat params 只作为兼容输入。
- 兼容性：如果 HTTP 401 会破坏 JSON-RPC 客户端，保留 HTTP 200 + JSON-RPC error body，并只在 REST/object routes 使用 HTTP status；若决定改变，必须同步 route tests 和 README。
- 迁移策略：如需为 idempotency 增加 SQLite unique index 或 idempotency table，必须兼容已有数据。
- 风险控制：所有 new error codes 要落在 `shared/errors.py` 可解释范围，避免用 generic `server_error`。

## 4. 实现方法

1. 梳理当前 `direct.send` 和 `group.send` 对 `message_id`、`operation_id` 的行为，确认重复请求会 duplicate、conflict 还是返回既有结果。
2. 定义 idempotency 语义：
   - 相同 sender、target、message_id、operation_id、body digest：返回同一 message result 或明确 `duplicate_accepted`。
   - 相同 message_id 但 body/target/sender 不同：返回稳定 conflict error。
   - `operation_id` 可用于幂等，但不得跨 sender/target 误匹配。
3. 增加 focused tests：
   - local direct duplicate same payload。
   - local direct duplicate conflicting payload。
   - public direct duplicate same/conflict。
   - group duplicate same/conflict。
   - unsupported methods 仍返回 `not_supported`，public route 不泄露 local-only methods。
4. 修改 `messaging/core.py` 和必要的 storage helper；如需 schema，更新 `storage/db.py` 并加迁移安全说明。
5. Review `shared/jsonrpc.py`：决定是否只返回 JSON-RPC error body，或按 auth/routing 错误映射 HTTP status。任何行为变化都必须被 `tests/test_route_config.py` 或新 tests 锁住。
6. 收紧 ANP meta/security profile 校验：
   - direct 只接受 `anp.direct.base.v1` + `transport-protected`。
   - group 只接受 `anp.group.base.v1` + `transport-protected`。
   - attachment ticket 不在本 Step 改。
7. 确保 errors 包含稳定 code/message/data，不把 Python exception detail 暴露给 public callers。

## 5. 路径

| 仓库 / 模块 / 文件 | 计划变更 | 备注 |
|---|---|---|
| `awiki-open-server/src/awiki_open_server/messaging/core.py` | direct/group idempotency、meta/security validation、稳定错误 | 重点路径 |
| `awiki-open-server/src/awiki_open_server/shared/jsonrpc.py` | 可选错误映射兼容调整 | 先测试锁定策略 |
| `awiki-open-server/src/awiki_open_server/shared/errors.py` | 可选新增 conflict/idempotency errors | 保持 JSON-RPC stable |
| `awiki-open-server/src/awiki_open_server/storage/db.py` | 可选新增唯一约束或 idempotency 数据 | 必须向后兼容 |
| `awiki-open-server/tests/test_direct_messages.py` | direct idempotency/protocol tests | 必需 |
| `awiki-open-server/tests/test_group_participant.py` | group idempotency/protocol tests | 必需 |
| `awiki-open-server/tests/test_messaging_surface.py` | public/local route surface tests | 必需 |
| `awiki-open-server/tests/test_route_config.py` | JSON-RPC/HTTP status/allowlist tests | 如行为变化则必需 |

## 6. 依赖与并行约束

- 前置步骤：Step 01 完成或明确 public blocker。
- 可并行步骤：无写入型并行。
- 不可并行步骤：Step 03-05 不能同时改 `storage/db.py` 或 `messaging/core.py`。
- 并行安全依据：本 Step 修改公开协议和 shared dispatcher，必须单独 Review。
- 互斥资源 / 冲突路径：`messaging/core.py`, `shared/jsonrpc.py`, `storage/db.py`。
- 外部文档或决策：需要参考 `message-service/docs/api/ANP-client-server-api-direct.md`、`ANP-client-server-api-group.md`。
- 环境前提：本地 ANP SDK 0.8.8 可加载。
- 合并前置条件：focused tests 和 local cross-domain smoke 通过。
- 合并后验证门禁：full local tests 通过或记录未运行原因。

## 7. 验收标准

- [x] direct/group 重复请求语义已明确，并被 tests 覆盖。
- [x] conflicting duplicate 返回稳定错误，不会写入第二条不一致消息。
- [x] JSON-RPC error body/code/message/data 稳定；HTTP status 策略已通过 tests 或 docs 记录。
- [x] public `/anp-im/rpc` 仍只暴露 allowlist，不泄露 inbox/history/sync/read-state。
- [x] `not_supported` 能力边界未被误开放。
- [x] legacy flat params 兼容仍通过现有 tests。
- [x] Review 发现已经修复或明确记录。
- [x] 本步骤在进入下一步之前已经创建聚焦 commit。

## 8. 验证方式

| 检查项 | 命令 / 方法 | 运行时机 | 预期证据 | 门禁类型 |
|---|---|---|---|---|
| Direct/group focused | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_direct_messages.py tests/test_group_participant.py tests/test_messaging_surface.py tests/test_route_config.py -q` | commit 前 | pass | Step gate |
| Protocol SDK focused | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_protocol_anp_sdk.py -q` | commit 前 | pass | Step gate |
| Local cross-domain | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root .awiki-open-server/cross-domain-local --clean` | commit 前 | pass | Step gate |
| Full local | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests -q` | commit 前或 Step 06 final | pass | Repo gate |

## 9. Review 环节

- Review 时机：实现和 focused tests 完成后、commit 前。
- Review 重点：幂等性是否按 sender/target/body 隔离、错误码是否稳定、是否破坏 public allowlist、是否引入 data race 或 schema 兼容问题。
- Review 必须检查 `/anp-im/rpc` 和 `/im/rpc` 的差异没有被抹平。

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | 已处理 | focused gate 初次失败，因为旧 remote/public direct 测试夹具缺少新要求的 `profile/security_profile`；Review 还发现 `group_send` 中旧 `accepted_at` 死赋值。 |
| 已修复问题 | 已修复 | 为旧测试夹具补齐合法 ANP meta；删除 `group_send` 死赋值；拆分 direct 响应 `operation_id` 和客户端显式幂等 `operation_id`，避免 legacy flat params 无 `operation_id` 重放被误判冲突。 |
| 剩余风险 | 已记录 | 未新增 `operation_id` 唯一索引或独立 idempotency 表；本 Step 以 nullable `operation_id` + `message_id` 主键 + 运行时冲突字段判定作为兼容方案。 |
| 新增或缺失测试 | 已覆盖 | 新增 direct/group idempotency、public inbound replay/conflict、legacy flat direct replay、profile/security mismatch tests；未新增 HTTP status 变化测试，因为策略保持 JSON-RPC 200 + error body 不变。 |
| 已更新或缺失文档 | 已更新 | 已更新本 Plan 和 Step 台账；公开 README/API 文档如需汇总由 Step 06 统一处理。 |
| 并行安全是否仍成立 | 是 | 本 Step 仍为串行写入；未启动写入型并行 worker。 |
| Agent 是否越界修改 | 否 | 修改范围限于 `messaging/core.py`、`storage/db.py`、direct/group tests 和本 Plan/Step 文档。 |
| 互斥资源是否被修改 | 是，按计划修改 | 修改了 `messaging/core.py` 和 `storage/db.py`；未修改 `shared/jsonrpc.py` 或 public route allowlist。 |
| 合并风险 | 低 | Step gate、protocol SDK、cross-domain smoke、full local tests 均通过；schema 变更为 nullable 列。 |
| Group gate 影响 | 无 | 串行 |

## 10. Commit 要求

- Commit 时机：实现、验证、Review 完成后。
- Commit 范围：只包含协议/错误/幂等性相关代码、tests、必要 docs。
- Commit 前状态：`## main...origin/main [ahead 1]`，修改 `plan/20260710-open-server-next-functions-review/plan.md`、`plan/20260710-open-server-next-functions-review/steps/02-protocol-error-idempotency-hardening.md`、`src/awiki_open_server/messaging/core.py`、`src/awiki_open_server/storage/db.py`、`tests/test_direct_messages.py`、`tests/test_group_participant.py`。
- Commit 后证据：功能提交 `a8b2e3c`；提交后 `git status --short --branch` 为 `## main...origin/main [ahead 2]`，工作区 clean。
- 建议消息：`messaging: harden protocol errors and idempotency`。

## 11. Blocked 处理

| Blocker | 证据 | 已尝试方案 | 影响范围 | 是否影响并行组 | 是否影响合并门禁 | 下一步决策 |
|---|---|---|---|---|---|---|
| HTTP status 兼容性无法确定 | 执行时填写 | 跑 Rust CLI smoke、保留 JSON-RPC 200、增加兼容 flag | 当前步骤 | 是 | 是 | 记录策略并避免破坏 |
| schema 唯一约束与旧数据冲突 | 执行时填写 | 用 query-level idempotency 或兼容迁移 | 当前步骤/后续 storage | 是 | 是 | 更新 Plan 数据策略 |

## 12. Plan 变更记录

| 日期 | 变更 | 原因 | 主 Plan 变更记录链接 |
|---|---|---|---|
| 2026-07-10 | 创建 Step 02 | 初始计划 | `../plan.md#20-plan-变更记录` |

## 13. 风险、回滚与后续文档

- 风险：错误/status 改动可能破坏旧 CLI/App。
- 并行执行风险：与 Step 05 同时修改 `messaging/core.py` 会产生冲突。
- 合并冲突风险：中等。
- Group gate 失败回退：回退本 Step commit，恢复旧 message send 行为。
- Agent 交接说明：Step 03 启动前必须确认 storage schema 变更已提交并记录。
- 回滚 / 回退：回退 commit；若 schema 已变更，必须保留向后兼容或写迁移回退说明。
- 后续文档：如 public contract 改变，Step 06 同步 README/API notes。
