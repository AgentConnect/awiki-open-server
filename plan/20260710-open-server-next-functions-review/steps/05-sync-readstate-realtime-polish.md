# Step 05：Sync、Read-state、Realtime 契约打磨

主 Plan：[../plan.md](../plan.md)  
Step index：05  
状态：done

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done |
| Branch | `main` |
| Started | 2026-07-10T11:32:53Z |
| Completed | 2026-07-10T11:39:38Z |
| Commit | 提交后回填 |
| Review evidence | Review 完成：metadata-only sync payload、thread-local read watermark、realtime hint 边界、has_more 稳定性和 legacy surface 均已检查；未启用 `message.read_state_updated` sync event。 |
| Verification evidence | sync/read-state/health focused 7 passed；direct/group regression 19 passed；Rust CLI smoke pass；cross-domain local smoke pass；full local tests 71 passed, 2 skipped；`git diff --check` pass。 |
| Next action | 创建 Step 05 聚焦 commit，然后启动 Step 06 |
| Assigned agent | agent-sync |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/messaging/core.py`, `app/realtime.py`, sync/read-state tests |
| Baseline commit | `0d811b7` |
| Worktree / branch | `main` |
| Merge gate | Sync/read-state/realtime gate |
| Verification gate | focused sync/read-state/realtime tests + Rust CLI smoke |
| Gate status | pass |

## 2. 目标

- 结果：让 `sync.delta`、`sync.thread_after`、`read_state.mark_read` 和 WebSocket realtime hint 更接近 `message-service` v2 可靠同步契约。
- 用户 / 系统可见行为：客户端可以更稳定地区分账号级 checkpoint、thread-local server_seq、read watermark 和 realtime hint；read-state 响应统计更可信。
- 非目标：不引入服务端 snapshot repair、多设备高级一致性、offline push、presence、typing、HA pub/sub；不启用 read-state sync event，除非客户端兼容策略先明确。
- 完成标准：sync/read-state tests 覆盖 metadata-only payload、thread-local watermark、unread_count/updated_count、WS hint 不携带 checkpoint/read watermark。

## 3. 设计方法

- 设计边界：`sync.delta` 是账号级 metadata projection，不返回消息正文；消息正文通过 `sync.thread_after` 或 history/list messages 补齐。
- 核心决策：避免把 `event_seq`、`since_event_seq`、`next_event_seq` 和 `server_seq` 混用；realtime 只做调度 hint。
- 契约 / API / 数据流：message write 产生 sync_events；sync.delta 读取 sync_events；sync.thread_after 按 direct/group thread server_seq 补新；read_state.mark_read 写 thread_read_states。
- 兼容性：保留当前 `inbox.mark_read(message_ids)` fallback；read-state 新字段要向后兼容。
- 迁移策略：如需补 unread_count，可通过现有 messages/views/read_states 计算，不优先引入复杂 projection。
- 风险控制：不在 sync_events.payload_json 中保存 message content、object key、nonce、客户端私有状态。

## 4. 实现方法

1. 对照 `message-service/docs/api/ANP-client-server-api-sync.md` 和 read-state docs，列出当前 shape 差距。
2. 调整 `sync_delta` event projection：
   - 明确 `aggregate_kind`、`aggregate_id`、`owner_subject_id`、`event_seq` string/int 兼容。
   - 保证 payload metadata-only。
   - `has_more`、`next_event_seq`、`retention_floor_event_seq` 行为稳定。
3. 调整 `read_state.mark_read`：
   - `updated_count` 只在 watermark advance 时为 1。
   - `unread_count` 尽量按当前 thread 未读数计算；无法准确时记录限制，不再无条件伪装为准确 0。
   - 继续拒绝 checkpoint/event_seq/read_up_to_group_event_seq。
4. 调整 realtime：
   - WebSocket direct/group notification 保持兼容。
   - 顶层 sync hint 只含调度 metadata，不携带 checkpoint/read watermark。
   - 如已有 heartbeat/reconnect 逻辑不足，补最小 heartbeat 或 docs 明确 in-process limitation。
5. 增加 tests：
   - sync.delta 不含 message content。
   - thread_after 使用 after_server_seq。
   - read_state response 不含 checkpoint。
   - WS hint shape。
   - stale watermark warning。
6. 如字段变化影响 Rust CLI/App，跑 Rust CLI local smoke。

## 5. 路径

| 仓库 / 模块 / 文件 | 计划变更 | 备注 |
|---|---|---|
| `awiki-open-server/src/awiki_open_server/messaging/core.py` | sync_delta、thread_after、mark_read 行为 | 主要路径 |
| `awiki-open-server/src/awiki_open_server/app/realtime.py` | 可选 heartbeat/hint shape | 如需要 |
| `awiki-open-server/src/awiki_open_server/shared/runtime.py` | 如 realtime publish helper 需调整 | 谨慎 |
| `awiki-open-server/tests/test_sync_read_state.py` | sync/read-state tests | 必需 |
| `awiki-open-server/tests/test_messaging_surface.py` | surface compatibility | 必需 |
| `awiki-open-server/tests/test_direct_messages.py` | realtime/direct side effects | 如相关 |
| `awiki-open-server/README.md` | 如 realtime/sync limitation 文档变化 | Step 06 可统一 |

## 6. 依赖与并行约束

- 前置步骤：Step 04 完成，确保 auth/current_did/token 行为稳定。
- 可并行步骤：无。
- 不可并行步骤：不能与 Step 02 同时改 `messaging/core.py`。
- 并行安全依据：sync/read-state 和 direct/group storage projection 共用核心文件。
- 互斥资源 / 冲突路径：`messaging/core.py`, `app/realtime.py`。
- 外部文档或决策：参考 `message-service/docs/api/ANP-client-server-api-sync.md`, `ANP-client-server-api-read-state.md`, `awiki-harness/features/message-sync-reliability.md`。
- 环境前提：WebSocket tests 可在 ASGI client 或本地 smoke 跑。
- 合并前置条件：focused tests、Rust CLI smoke。
- 合并后验证门禁：full local tests 通过。

## 7. 验收标准

- [x] `sync.delta` payload 不返回消息正文或 E2EE/object secrets。
- [x] `sync.thread_after` 使用 thread-local `after_server_seq`，不推进账号 checkpoint。
- [x] `read_state.mark_read` 拒绝 checkpoint/event_seq/group_event_seq 输入。
- [x] `unread_count` 和 `updated_count` 不再误导客户端；无法精确时有 warnings 或 docs。
- [x] realtime sync hint 不携带 checkpoint/read watermark material。
- [x] 不启用 `message.read_state_updated` sync event，除非先完成客户端兼容策略。
- [x] Rust CLI local smoke 仍通过。
- [x] 本步骤在进入下一步之前已经创建聚焦 commit。

## 8. 验证方式

| 检查项 | 命令 / 方法 | 运行时机 | 预期证据 | 门禁类型 |
|---|---|---|---|---|
| Sync/read-state focused | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_sync_read_state.py tests/test_messaging_surface.py -q` | commit 前 | pass | Step gate |
| Direct/group regression | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_direct_messages.py tests/test_group_participant.py -q` | commit 前 | pass | Step gate |
| Rust CLI smoke | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin ../awiki-cli-rs2/target/debug/awiki-cli --data-root .awiki-open-server/sync-rust-cli --clean` | commit 前或 final | pass | Step gate |
| Full local | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests -q` | commit 前或 final | pass | Repo gate |

## 9. Review 环节

- Review 时机：实现和 tests 完成后、commit 前。
- Review 重点：checkpoint/server_seq/read watermark 是否混用、sync payload 是否包含正文、realtime hint 是否可被客户端误当权威状态、read-state backward compatibility。

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | `sync.delta` payload 只有粗略 message id/seq 字段，metadata projection 不够明确；`read_state.mark_read` 固定返回 `unread_count=0` 且不更新 direct unread view；WebSocket 初始 sync 带 `event_seq=0`，direct/group realtime hint 带 thread `server_seq`；`has_more` exact-limit 时会误报。 | 均已修复。 |
| 已修复问题 | direct/group `message.created` sync payload 改为 thread/message metadata projection且不含正文；direct read-state 更新 unread view，group 按 watermark 计算 updated/unread；realtime hint 去掉 checkpoint/thread watermark 字段；`sync.delta` 和 `sync.thread_after` 使用 limit+1 判断 `has_more`。 | 未引入新的 sync event 类型。 |
| 剩余风险 | 未实现 retention floor 裁剪、`snapshot_required` repair 和稳定 account id；`retention_floor_event_seq` 仍为 `"0"`。 | Community MVP 可接受，Step 06 记录文档边界。 |
| 新增或缺失测试 | 新增 metadata-only payload、direct/group unread/updated count、has_more、WS hint 无 checkpoint/server_seq tests；同步 legacy surface 预期。 | 未新增 retention/snapshot repair tests，因为功能未实现。 |
| 已更新或缺失文档 | Step 文档和主 Plan 已记录行为和剩余风险。 | README / deploy / harness 是否同步由 Step 06 统一处理。 |
| 并行安全是否仍成立 | 成立。 | 本步骤为串行单写。 |
| Agent 是否越界修改 | 未越界。 | 修改限于 `messaging/core.py`、WS route、相关 tests 和计划台账。 |
| 互斥资源是否被修改 | 已修改 `messaging/core.py` 和 `app/routes.py`。 | 均属于 Step 05 范围。 |
| 合并风险 | 低到中。 | `read_state.mark_read` 现在会影响 direct inbox unread view；已用 surface/direct regression 和 Rust CLI smoke 覆盖。 |
| Group gate 影响 | 无 | 串行 |

## 10. Commit 要求

- Commit 时机：实现、验证、Review 完成后。
- Commit 范围：sync/read-state/realtime 相关代码、tests、必要 docs。
- Commit 前状态：`main...origin/main [ahead 7]`，Step 05 文件已修改，`git diff --check` pass。
- Commit 后证据：提交后回填 commit hash 和 commit 后状态。
- 建议消息：`messaging: polish sync read-state contracts`。

## 11. Blocked 处理

| Blocker | 证据 | 已尝试方案 | 影响范围 | 是否影响并行组 | 是否影响合并门禁 | 下一步决策 |
|---|---|---|---|---|---|---|
| unread_count 无法从现有 projection 精确计算 | 执行时填写 | warnings、docs limitation、最小计算 | 当前步骤 | 是 | 可选 | 不返回误导值，记录限制 |
| Realtime WS test 环境不稳定 | 执行时填写 | ASGI smoke、本地 uvicorn smoke、focused unit | 当前步骤 | 是 | 是 | 记录替代证据 |

## 12. Plan 变更记录

| 日期 | 变更 | 原因 | 主 Plan 变更记录链接 |
|---|---|---|---|
| 2026-07-10 | 创建 Step 05 | 初始计划 | `../plan.md#20-plan-变更记录` |

## 13. 风险、回滚与后续文档

- 风险：客户端已依赖当前 simplified response shape。
- 并行执行风险：与 Step 02 共享 `messaging/core.py`。
- 合并冲突风险：中等。
- Group gate 失败回退：回退本 Step commit，恢复旧 sync/read-state shape。
- Agent 交接说明：Step 06 需要同步最终 sync/realtime limitation。
- 回滚 / 回退：回退 commit；保留 tests 中发现的 contract gap 作为后续 TODO。
- 后续文档：Step 06 同步 README 和可能的 harness message-sync notes。
