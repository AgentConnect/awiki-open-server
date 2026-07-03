# Step 12：Message Service 实时通知兼容补齐

主 Plan：[../plan.md](../plan.md)  
Step index：12  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-with-pending-online-gate |
| Branch | main |
| Started | 2026-07-03 |
| Completed | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 |
| Commit | 未提交 |
| Review evidence | 已复核：`/im/ws` 使用本仓 in-process `RealtimeHub` 保持连接并推送 direct/group participant 通知；direct/group RPC response 不变；public `/anp-im/rpc` 白名单不变；未引入外部 User Service / Message Service / `awiki.info` 运行依赖；`group.joined` / `group.left` 本地 sync event 兼容性已保留 |
| Verification evidence | focused WebSocket test pass；focused direct/group + WS pass；compileall pass；全量 pytest 29 passed；ASGI smoke pass；双实例本地跨域 Gate pass；`verify-public https://rwiki.info` 仍 404，归属 Step 09 |
| Next action | 继续 Step 09 公网 Gate：将 `rwiki.info` 切到本仓服务后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/app/`, `awiki-open-server/src/awiki_open_server/services.py`, `awiki-open-server/tests/`, `awiki-open-server/README.md`, `awiki-open-server/plan/...` |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | focused WebSocket tests + 全量 pytest + ASGI smoke |
| Gate status | pass/online-pending |

## 2. 目标

- 结果：把 `/im/ws` 从“连接后发送一次 sync hint 并关闭”补成极简可用的 Message Service realtime 通知入口。
- 用户 / 系统可见行为：已连接的本域用户在 direct 收件、加入/退出群状态变化、群消息到达时收到 JSON-RPC notification。
- 非目标：不实现多进程 fanout、持久 WebSocket session 表、离线推送、重连补偿、外部队列、完整 presence/typing、federation relay 或跨域群 Host。
- 完成标准：WebSocket 保持连接；本地 direct 推送 `direct.incoming`；群加入推送 `group.state_changed`；群消息推送 `group.incoming`；未连接时不影响 RPC 写入；`sync.delta` / `sync.thread_after` 仍作为补偿路径可用。

## 3. 设计方法

- 设计边界：只在 `awiki-open-server` 内实现进程内 fanout；相邻 `user-service`、`message-service`、`awiki-cli-rs2` 只读参考。
- 核心决策：新增轻量 realtime hub，按 `owner_did` 维护线程安全队列；RPC handler 写入 SQLite 后发布通知；`/im/ws` 认证后保持连接并顺序发送队列消息。
- 契约 / API / 数据流：通知使用 JSON-RPC 2.0 notification 形态，`method` 为 `direct.incoming`、`group.incoming` 或 `group.state_changed`，`params` 包含消息/群状态和 `sync` 字段；公开 `/anp-im/rpc` 白名单不变化。
- 兼容性：保留初始 `sync` hint，避免旧客户端只依赖连接成功信号；新增通知不会改变 direct/group RPC response。
- 迁移策略：不新增 SQLite schema；进程重启后实时队列丢失，由 `sync.delta` 和 `sync.thread_after` 补偿。
- 风险控制：hub 满载或发送失败不能回滚已提交消息；WebSocket 断开时清理 session；不把真实 token 或消息内容写入日志。

## 4. 实现方法

1. 新增 `awiki-open-server/src/awiki_open_server/app/realtime.py`，实现 `RealtimeHub`、`subscribe`、`unsubscribe`、`publish` 和 `notification` helper。
2. 在 `awiki-open-server/src/awiki_open_server/app/main.py` 初始化 `app.state.realtime_hub`。
3. 修改 `awiki-open-server/src/awiki_open_server/app/routes.py` 的 `/im/ws`：认证后接受连接，发送初始 `sync` hint，然后循环等待 hub 队列并发送 notification；断开时注销。
4. 修改 `awiki-open-server/src/awiki_open_server/services.py`：
   - `_store_direct_message` 在 direct 写入后向本地 sender/recipient 相关连接发布通知；recipient 收到 `direct.incoming`，sender 可收到 sync hint 或 `direct.incoming` 的 outgoing 视图。
   - `group_join` / `group_leave` 向成员发布 `group.state_changed`。
   - `group_send` 向所有当前成员发布 `group.incoming`。
5. 在 `awiki-open-server/tests/test_health.py` 或新的 focused 测试中覆盖 WebSocket direct/group 通知。
6. 更新 `awiki-open-server/README.md` 与主 Plan 的验证证据。

## 5. 路径

| 仓库 / 模块 / 文件 | 计划变更 | 备注 |
|---|---|---|
| `awiki-open-server/src/awiki_open_server/app/realtime.py` | 新增进程内 realtime hub | 不依赖外部队列 |
| `awiki-open-server/src/awiki_open_server/app/main.py` | 初始化 hub | app state |
| `awiki-open-server/src/awiki_open_server/app/routes.py` | `/im/ws` 保持连接并发送通知 | 保留 ticket/token 认证 |
| `awiki-open-server/src/awiki_open_server/services.py` | direct/group 写入后发布通知 | 不改变 RPC response |
| `awiki-open-server/tests/` | 新增 focused WebSocket tests | 覆盖 direct/group |
| `awiki-open-server/README.md` | 更新 realtime 能力边界 | 明确单进程限制 |
| `awiki-open-server/plan/20260702-awiki-open-server-mvp/` | 回填 Plan 和证据 | 只改本仓 |

## 6. 依赖与并行约束

- 前置步骤：Step 11 已完成本仓协议边缘兼容。
- 可并行步骤：无。
- 不可并行步骤：Step 09 公网 Gate 依赖本仓稳定门禁；Step 12 修改共享 app/routes/services/tests。
- 并行安全依据：不安全；同一时间只允许 main 修改。
- 互斥资源 / 冲突路径：`src/awiki_open_server/app/routes.py`、`src/awiki_open_server/services.py`、`tests/`。
- 外部文档或决策：`require.md` 要求 WebSocket 实时通知；`message-service/docs/api/` 是只读参考。
- 环境前提：本地 pytest 可运行；不需要公网 `rwiki.info`。
- 合并前置条件：focused WebSocket tests 通过。
- 合并后验证门禁：全量 pytest、compileall、ASGI smoke 通过。

## 7. 验收标准

- [x] `/im/ws` 使用 `/ws/tickets` ticket 或 token 认证后保持连接。
- [x] direct 写入本地 recipient 后，recipient WebSocket 收到 `direct.incoming`，包含 `message_id`、sender/recipient、body 和 `sync` 信息。
- [x] group join/leave 发布 `group.state_changed`。
- [x] group send 向当前成员发布 `group.incoming`，包含 `message_id`、`group_did`、sender 和 body。
- [x] 无 WebSocket 连接时 direct/group RPC 不失败。
- [x] `/anp-im/rpc` public surface 未扩大。
- [x] 本步骤不修改相邻仓库。
- [x] focused WebSocket tests、compileall、全量 pytest、ASGI smoke 通过。
- [x] Review 发现已经修复或明确记录。

## 8. 验证方式

| 检查项 | 命令 / 方法 | 运行时机 | 预期证据 | 门禁类型 |
|---|---|---|---|---|
| Focused WS | `PYTHONPATH=src python3 -m pytest tests/test_health.py::test_im_websocket_receives_direct_and_group_notifications -q` | 实现后 | direct/group notification pass | Step gate |
| Compile | `PYTHONPATH=src python3 -m compileall -q src scripts tests` | 实现后 | pass | Step gate |
| Full pytest | `PYTHONPATH=src python3 -m pytest tests -q` | 实现后 | pass | Step gate |
| ASGI smoke | `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step12-asgi` | 实现后 | pass | Step gate |
| Public Gate | `PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info` | Step 12 后可复跑 | 预期仍可能 404；若失败归属 Step 09 部署 Gate | Online gate |

本轮结果：

- `PYTHONPATH=src python3 -m pytest tests/test_health.py::test_im_websocket_receives_direct_and_group_notifications -q`：1 passed。
- `PYTHONPATH=src python3 -m pytest tests/test_health.py::test_im_websocket_receives_direct_and_group_notifications tests/test_messaging_objects.py::test_direct_group_participant_and_public_surface -q`：2 passed。
- `PYTHONPATH=src python3 -m compileall -q src scripts tests`：pass。
- `PYTHONPATH=src python3 -m pytest tests -q`：29 passed。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step12-asgi-rerun`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step12-cross --clean`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info`：failed，`/.well-known/did.json`、`/healthz`、`/anp-im/rpc` 均 404；继续归属 Step 09 公网部署 Gate。

## 9. Review 环节

- Review 时机：代码实现和测试通过后、commit 前。
- Review 重点：WebSocket 生命周期、断开清理、通知 shape、direct/group 事务后发布、未连接时不影响写入、public surface 未扩大、无外部服务依赖、测试覆盖。

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | 已发现并修复 | 初版实现将 `group.joined` / `group.left` sync event 改为 `group.member.*`，Review 中已恢复本地成员自己的旧 event type，其他成员仍使用 member state event |
| 已修复问题 | 已修复 | 补齐断开清理、线程安全发布、direct/group notification、event type 兼容 |
| 剩余风险 | 已记录 | 多进程 fanout、外部 pub/sub、离线推送、presence/typing 非目标；公网 Gate 仍待 Step 09 |
| 新增或缺失测试 | 已新增 | `tests/test_health.py::test_im_websocket_receives_direct_and_group_notifications` 覆盖 direct/group realtime |
| 已更新或缺失文档 | 已更新 | README + Plan |
| 并行安全是否仍成立 | 否 | 串行执行 |
| Agent 是否越界修改 | 否 | 未修改相邻仓库 |
| 互斥资源是否被修改 | 是 | routes/services/tests |
| 合并风险 | 已缓解 | focused/full/smoke/cross-domain gate 均通过 |
| Group gate 影响 | 无 | 不改变 Step 09 公网 Gate |

## 10. Commit 要求

- Commit 时机：本步骤实现、验证、Review 都完成后。
- Commit 范围：只包含 Step 12 的 realtime hub、route/service 发布点、focused tests、README/Plan 证据。
- Commit 前状态：记录 `git status`。
- 纳入文件：记录本步骤 commit 包含的文件。
- Commit 后证据：记录 commit hash 和 commit 后 `git status`。
- 遗留未提交变更：必须记录原因以及为什么安全。
- 建议消息：`message: add open server realtime notifications`

## 11. Blocked 处理

| Blocker | 证据 | 已尝试方案 | 影响范围 | 是否影响并行组 | 是否影响合并门禁 | 下一步决策 |
|---|---|---|---|---|---|---|
| 无 | 当前缺口可在本仓实现 | 不适用 | 无 | 否 | 否 | 继续实现 |

## 12. Plan 变更记录

| 日期 | 变更 | 主 Plan 变更记录链接 |
|---|---|---|
| 2026-07-03 | 新增 Step 12，补齐 `/im/ws` realtime notification 兼容面 | `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md` 第 16 节 |

## 13. 风险、回滚与后续文档

- 风险：进程内 hub 不覆盖多进程/多节点部署；这是 Community MVP 边界，生产 HA 属非目标。
- 并行执行风险：无并行执行。
- 合并冲突风险：`routes.py` 和 `services.py` 是共享热点文件，需要串行 Review。
- Group gate 失败回退：如果 WebSocket tests 失败且无法快速修复，回退到 Step 10 的基础 sync hint，并把 realtime fanout 标为后续 blocker。
- Agent 交接说明：恢复时先读本文件、主 Plan 执行台账和 `git status`，确认 Step 12 是否已完成测试证据。
- 回滚 / 回退：删除 `RealtimeHub`、恢复 `/im/ws` 一次性 sync hint、移除发布点和新增测试。
- 后续文档：若后续要支持多进程 realtime，需要新增独立步骤和外部 pub/sub 设计；本步骤不修改 Harness 或相邻仓库文档。
