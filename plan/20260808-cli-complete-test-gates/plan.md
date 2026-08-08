# 真实 CLI 完整测试 Gate 补齐计划

日期：2026-08-08
状态：complete
目标仓库：`awiki-open-server`
关联计划：`plan/20260807-protocol-api-alignment/plan.md`

## 1. 目标

在不扩大 Open Server 产品范围的前提下，补齐以下可重复、可审计的测试 Gate：

1. 真实 Rust CLI Attachment：Direct 与 Community Group 的发送、可见、下载和授权。
2. 真实 Rust CLI Group members inventory：成员加入、分页、离开/移除后的投影与权限。
3. 真实 Rust CLI mark-read：单条、批量、幂等、未读过滤与重启持久化。
4. 真实 Rust CLI Realtime/restart：WebSocket 连接只作为 dirty hint，可靠事实仍由受限 Sync v2 恢复；覆盖 listener 与 Open Server 重启。
5. 真实 Rust CLI cross-domain：两个独立 Open Server、两个独立租户、双向明文 Direct，以及两个 Group Host 方向。
6. Sync v2 Group/thread-after 专项测试：Group event、batch hydration、v2 thread catch-up、权限与 cursor 边界。

计划完成后，发布报告必须能分别回答：

- 哪个 CLI commit 和哪个二进制通过；
- 哪个 Open Server commit 通过；
- 哪些场景由真实 CLI 黑盒验证；
- 哪些场景只由 ASGI/协议专项测试验证；
- 哪些能力明确 `not_supported`。

## 2. 不变边界

本计划只补测试、测试编排、必要的可观测性和测试暴露出的范围内 contract 修复，不引入新产品能力。

- Open Server 仍是单进程、SQLite、本地对象存储、小规模 Community Group。
- Direct 和 Group 只验证明文；不得增加成功 E2EE、secure-message、prekey、ratchet 或 encrypted-attachment Gate。
- `anp.sync.local.v2` 仍只支持一个 DID、恰好一个设备、一个 client instance。
- 不支持第二设备、多设备共享、跨设备 read state、snapshot recovery 或 cursor 合并。
- Group admission 只使用立即 active 的 `group.add` 和 `group.join`。
- 不实现 invitation、invite/join token、join code、pending membership 或 accept-invite。
- Attachment 只验证 Open Server 本地对象和本地消息上下文；不把跨域对象 relay、跨域上传代理或 E2EE attachment grant 纳入 Gate。
- WebSocket 通知只作为唤醒/dirty hint；可靠消息事实必须通过 `sync.delta` / `sync.thread_after` 恢复。
- 不启用生产手机号/邮箱验证；所有 smoke 显式设置 `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=0`。
- Open Server 必须本地实现能力，不得代理 `awiki.info`、User Service 或 Message Service。

## 3. 当前基线与事实来源

### 3.1 Open Server 基线

- 计划编写时 `main`：`22dbcd5 Align protocol APIs with latest contracts`。
- 默认测试：102 collected，最近记录为 100 passed、2 个公网 opt-in skipped。
- 已有 harness：
  - `smoke-asgi`
  - `smoke-local`
  - `smoke-cross-domain-local`
  - `smoke-rust-cli-connect`
  - `smoke-rust-cli-local`

### 3.2 CLI 调研基线

计划编写时相邻 CLI 工作区为：

```text
repository: ../awiki-cli-rs2
branch: feature/0807-multi-recovery
commit: 90ac0b77a19a15e382ad594c871f97dbb0a99413
version: 1.0.43
```

这只是计划调研基线，不自动成为实施时的发布基线。实施开始时必须选择并固定发布 tag 或完整 commit，重新构建二进制，记录 `awiki-cli version` 和 SHA-256。不得把“相邻工作区当前 binary”当作可追溯 artifact。

当前 CLI 已确认存在以下正式命令：

```text
awiki-cli msg send --to ... --file ... --mime-type ...
awiki-cli msg send --group ... --file ... --mime-type ...
awiki-cli msg attachment download --with ... --message-id ... --output ...
awiki-cli msg attachment download --group ... --message-id ... --output ...
awiki-cli group members --group ... --limit ... --cursor ...
awiki-cli msg mark-read [MESSAGE_ID...]
awiki-cli msg inbox --unread
awiki-cli msg inbox --mark-read
awiki-cli runtime mode set websocket
awiki-cli runtime listener status
```

CLI 还提供隐藏的 foreground listener：

```text
AWIKI_CLI_INTERNAL_ENTRY=1 awiki-cli runtime listener run
```

该入口用于测试进程，不安装 systemd/launchd/Windows service。测试必须以进程组方式启动，设置超时，并在 `finally` 中先 TERM、后限时 KILL，避免残留 listener。

### 3.3 已有覆盖与缺口

| 能力 | 服务端 ASGI/raw smoke | 真实 CLI | 本计划结论 |
| --- | --- | --- | --- |
| Direct send/inbox/history | 已覆盖 | 已覆盖 | 保留回归 |
| 单设备 Sync v2 Direct delta/batch | 已覆盖 | Inbox/History 间接覆盖 | 增加 Group/thread 专项 |
| Attachment | slot/upload/commit/ticket/download 已覆盖 | 未覆盖 | 新增 Direct + Group CLI Gate |
| Group members | handler/projection 已覆盖 | 未覆盖 | 新增 CLI inventory Gate |
| mark-read | handler/read state 已覆盖 | 未覆盖 | 新增 CLI 单条/批量/持久化 Gate |
| Realtime | ASGI WebSocket 已覆盖 | 未覆盖 | 新增 foreground listener + restart Gate |
| cross-domain Direct | 两 Uvicorn raw Python 已覆盖 | 未覆盖 | 新增真实 CLI 双向 Gate |
| cross-domain Group | ASGI/协议测试较完整 | 未覆盖 | 新增两个 Host 方向真实 CLI Gate |
| Sync v2 Group hydration | 未专项覆盖 | 未证明 | 新增专项测试 |
| Sync v2 thread-after profile | v1/flat 形状已覆盖 | 未证明 | 新增显式 v2 envelope 测试 |

## 4. 总体测试架构

### 4.1 不复制业务流程

扩展 `scripts/awiki_open_cli.py` 的现有 orchestration，不创建第二套重复 CLI driver。先提取共享对象/函数：

- `RustCliArtifact`：binary、version、commit、SHA-256、platform/arch。
- `OpenServerProcess`：start、ready、stop、restart、日志路径、数据目录。
- `RustCliWorkspace`：隔离 `HOME`、`AWIKI_CLI_WORKSPACE_HOME_DIR`、tenant、identity。
- `RustCliCommandResult`：command、return code、JSON envelope、脱敏 stdout/stderr。
- `wait_until`：有 deadline 的状态轮询，不使用固定长 sleep。
- `ProcessGuard`：进程组清理、TERM/KILL、日志保留。
- Attachment fixture/hash、members/message projection 的通用断言。

现有 `smoke-rust-cli-local` 保持入口稳定，内部拆成独立 scenario。新增两个聚合入口：

```text
smoke-rust-cli-realtime-restart
smoke-rust-cli-cross-domain
```

建议同时提供 `--scenario` 或 focused 子命令，使开发者能单独重跑 attachment、members、mark-read，而不复制初始化代码。

### 4.2 Gate 分层

| Gate | 运行方式 | 默认 pytest | 用途 |
| --- | --- | --- | --- |
| 协议专项 | `pytest` + ASGI 临时目录 | 是 | 精确字段、cursor、权限、错误码 |
| raw process smoke | Python driver + Uvicorn | 是或快速子集 | 服务进程、跨域协议、持久化 |
| 真实 CLI local | pinned Rust CLI + Uvicorn | opt-in/发布必跑 | 用户命令和本地投影 |
| 真实 CLI realtime | pinned CLI foreground listener | opt-in/发布必跑 | WebSocket dirty hint + durable recovery |
| 真实 CLI cross-domain | pinned CLI + 两 Uvicorn | opt-in/发布必跑 | 实际客户端跨域互操作 |

真实 CLI 测试加入 pytest 时使用显式环境变量，例如：

```text
AWIKI_RUN_RUST_CLI_SYSTEM_TESTS=1
AWIKI_CLI_BIN=/absolute/path/to/pinned/awiki-cli
```

没有 artifact 时必须明确 skip，不能假装通过；发布 Gate 脚本必须把 skip 视为失败。

### 4.3 测试证据

每个真实 CLI Gate 输出一个 JSON report，至少包含：

- `started_at` / `finished_at` / duration；
- Open Server commit；
- CLI version、commit、artifact SHA-256、platform、arch；
- Python、ANP SDK version；
- scenario 名称与每项 pass/fail/skip；
- server base URL、DID domain、脱敏后的 DID；
- message/group/operation/object ID；
- listener boot ID、连接状态和 reliable-sync 安全投影；
- restart 前后 PID/boot ID；
- 失败 command、return code、脱敏错误尾部；
- 未验证能力列表。

报告不得包含 token、私钥、完整 proof/signature、真实手机号、测试正文原文或附件敏感内容。

## 5. Phase 0：固定 artifact、环境和前置 contract

### 工作

1. 在实施开始时解析指定 CLI tag/commit，不使用浮动 branch HEAD。
2. 从干净工作区使用 locked dependencies 构建 CLI。
3. 运行 `awiki-cli version` 并校验输出 commit 与源码 commit 一致。
4. 计算 CLI artifact SHA-256。
5. 记录 Open Server commit；dirty worktree 时 Gate 默认拒绝，开发模式可显式允许但报告必须标记 dirty。
6. 所有 Open Server 子进程显式设置：
   - `AWIKI_ALLOW_UNSIGNED_PEER_DEV=0`
   - `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=0`
   - 独立 `AWIKI_DATA_DIR`
   - 独立 service key
   - 确定的 resolver map
7. 运行 CLI schema preflight，确认目标命令仍存在且参数未漂移。
8. 对 Realtime 先做最小握手 probe，确认 Open Server `/im/ws` 与 CLI 所需 WebSocket subprotocol/ticket/profile 相容。

### 失败策略

- CLI schema 漂移：先更新计划中的调用方式，不用兼容猜测掩盖。
- CLI 要求 Open Server 未声明的 E2EE：测试必须使用 `--secure off`，不能启用 E2EE 修复 Gate。
- Realtime 握手不相容：允许做范围内 v2 wire compatibility 修复，但不得把 WebSocket 变成可靠数据源。
- 最新 CLI 要求多设备或 snapshot recovery：明确 blocked/not_supported，不扩张 Open Server 存储模型。

### 完成标准

- report 中的 CLI commit、`version` commit 与 artifact SHA-256 可相互追溯。
- Open Server 启动环境不会继承意外启用的 contact verification 或 unsigned-peer 开关。

## 6. Phase 1：重构真实 CLI harness

### 工作

1. 将当前散落的 workspace、process、CLI JSON 调用封装为共享 helper。
2. 正向命令统一要求：退出码 0、有效 JSON、`ok=true`。
3. 负向命令统一要求：退出码非 0，并校验稳定 CLI error code 或服务端 contract；不能只断言“失败了”。若当前 CLI 屏蔽服务端 code，先记录 CLI issue，并至少校验失败阶段与服务端审计。
4. 支持启动长运行 listener，读取 status JSON，等待 ready，并安全停止。
5. 支持同一数据目录、同一端口、同一 service key 的 Open Server restart。
6. 支持两个服务器同时运行，以及单独停止/重启其中一个。
7. stdout report 与 server/listener log 分离；测试失败时保留 artifacts，成功默认清理临时目录，可用 `--keep-artifacts` 保留。
8. 为 harness helper 增加 pytest 单测：
   - artifact provenance；
   - deadline/timeout；
   - 非 JSON CLI 输出；
   - `ok=false`；
   - 进程提前退出；
   - TERM 后 KILL；
   - 日志脱敏。

### 完成标准

- 现有 connect/local smoke 继续通过。
- 新 scenario 不复制 tenant/identity/server 初始化代码。
- 任一失败都能定位到具体 CLI command 和 server instance。

## 7. Phase 2：Sync v2 Group/thread-after 专项测试

目标文件：扩展 `tests/test_sync_v2_single_device.py`，必要时增加 focused test file，但不复制 fixture。

### 7.1 Group delta 与 batch hydration

测试拓扑：一个单设备 owner、一个 peer、一个本地 Community Group。

步骤：

1. owner 使用包含恰好一个 device 的签名 DID Document 注册。
2. owner 以 `anp.sync.local.v2` 执行 `sync.bootstrap`。
3. 创建 Group，并使 owner 和 peer 都为 active member。
4. peer 发送一条明文 Group message。
5. owner 从 bootstrap cursor 调用 v2 `sync.delta`。
6. 找到对应 `message.created` event。
7. 使用 event ID 调用 v2 `message.get_batch`。

断言：

- profile 精确为 `anp.sync.local.v2`；
- event 属于正确 account；
- `recipient_device_id` 不伪造多设备定向；
- `message_kind=group_plain`；
- `thread_key` 与 Group DID 绑定；
- payload 含正确 group/message/direction/sequence 信息；
- batch hydration 返回正确 message ID、Group DID、正文/content type、sender；
- `unavailable=[]`；
- cursor 单调前进且重复 delta 不重复业务事实。

### 7.2 v2 `sync.thread_after`

步骤：

1. 在同一 Group 写入至少三条有序消息。
2. 使用显式 v2 envelope 调用 `sync.thread_after`，不是旧 flat/v1 请求。
3. 分别以 `after_server_seq=0`、中间 seq 和尾 seq 调用。
4. 使用小 limit 验证分页/continuation（若 contract 提供 cursor）。

断言：

- 只返回指定 Group thread；
- 顺序严格递增；
- `after` 为 exclusive；
- message projection 与 `message.get_batch` 一致；
- 尾部调用返回空集合而不是 snapshot_required；
- 非成员调用返回稳定 unauthorized/not_member；
- 成员 leave/remove 后不能通过 thread-after 绕过 Group read 权限；
- direct thread 的现有行为不回归。

### 7.3 错误与恢复边界

增加以下负向用例：

- token owner 与 `meta.sender_did` 不一致；
- 错误 `stream_epoch`；
- malformed/negative `scan_seq`；
- limit 越界；
- Group event ID 与 hydration owner 不匹配；
- batch 中一部分 ID 不可见时进入 `unavailable`，不泄露消息；
- 第二 client instance 仍返回 `sync.multiple_devices_not_supported`；
- Open Server restart 后同一 device/client binding 继续有效；
- restart 后第二 client instance 仍被拒绝。

### 完成标准

- v2 Direct、Group、batch、thread-after 都有显式 profile 测试。
- 不加入 `sync.snapshot` 成功路径。
- 不引入第二设备成功 fixture。

## 8. Phase 3：真实 CLI Group members Gate

将场景加入 `smoke-rust-cli-local` 的 focused scenario。

### 步骤

1. Alice 创建 private/admin-add Group。
2. Alice `group add` Bob。
3. Alice 将 admission mode 更新为 open-join。
4. Charlie `group join`。
5. Alice、Bob、Charlie 分别运行：

```text
awiki-cli group members --group <group_did> --limit 100
```

6. 使用 `--limit 1` 和返回 cursor 遍历所有页。
7. Charlie leave，再查询 members。
8. Alice remove Bob，再查询 members。
9. Bob/Charlie 在非成员状态执行 members，验证权限 contract。

### 断言

- 初始列表包含 Alice、Bob、Charlie，且 DID、role、membership status 与服务端一致；
- 同一 DID 不重复；
- `total`、`has_more`、cursor 一致；
- 分页合并结果与非分页结果相同；
- leave/remove 后 active inventory 不再出现对应成员；
- owner 保留正确 owner/admin role；
- 非成员不能读取 private Group inventory；
- CLI 返回 auth/projection 错误时，不把失败降级为“空成员列表”。

### 额外回归

- Host-local Group 与 remote projection 在字段命名上统一为 CLI 可消费 contract。
- 不测试 pending/invited 状态，因为 Open Server 不支持该状态机。

### 完成标准

- 删除兼容文档中“members 尚未验证”的说明，并附 report evidence。
- `assert_active_member_visible` 一类 helper 真正进入执行路径。

## 9. Phase 4：真实 CLI mark-read Gate

### 9.1 单条 read

1. Alice 向 Bob 连续发送两条明文 Direct。
2. Bob 执行 `msg inbox --scope direct --unread`，确认两条均可见。
3. Bob 对第一条执行：

```text
awiki-cli msg mark-read <message_id>
```

4. 再执行 unread inbox 与 Direct history。

断言：第一条不再出现在 unread，第二条仍在；history 的 `is_read/read_at` 投影正确。

### 9.2 幂等与批量

- 对同一 message ID 重复 mark-read，结果成功且不产生重复/倒退状态。
- 一次传入多个 message ID，全部标记成功。
- `msg inbox --mark-read` 对返回页执行批量已读，再次 `--unread` 为空。
- 未知或不属于当前 DID 的 message ID 不得泄露存在性；按当前 contract 返回 unavailable/not_found。

### 9.3 Group 与持久化

- 若 CLI/Message contract 对 Group message 支持 mark-read，增加 Group message 正向用例；否则在 report 中明确 Direct-only，而不是假装 Group 已验证。
- mark-read 后停止并重启 Open Server，复用同一数据目录；Bob 再查 unread/history，read state 必须保持。
- 重启 CLI workspace 后状态保持，不依赖进程内缓存。

### 完成标准

- 单条、批量、幂等、unread filter、Open Server restart 都由真实 CLI 证明。
- read state 不跨 DID 或跨设备共享。

## 10. Phase 5：真实 CLI Attachment Gate

Attachment fixture 在临时目录动态创建，至少包含：

- UTF-8 文本文件；
- 含 NUL 和非文本字节的小型 binary 文件；
- 已知 byte length 与 SHA-256。

不提交真实用户附件或敏感文件。

### 10.1 Direct Attachment

1. Alice 执行：

```text
awiki-cli msg send --to <bob_did> \
  --text "attachment caption" \
  --file <fixture> \
  --mime-type application/octet-stream \
  --secure off
```

2. Bob 通过 Inbox/History 找到消息和 attachment metadata。
3. Bob 执行：

```text
awiki-cli msg attachment download \
  --with <alice_did> \
  --message-id <visible_or_raw_message_id> \
  --output <download_path>
```

4. 比较原始文件与下载文件的 byte length、SHA-256 和逐字节内容。

断言还包括 MIME type、文件名/attachment ID、object URI/message context，以及 caption 不丢失。

### 10.2 Group Attachment

1. Alice 在本地 Group 使用 `msg send --group ... --file ... --secure off`。
2. Bob 与 Charlie 作为 active member 查询 Group messages。
3. Bob 使用 `msg attachment download --group ...` 下载并比较 hash。
4. Charlie leave 后再次请求新 ticket/download，必须失败。
5. Alice remove Bob 后 Bob 再请求新 ticket/download，必须失败。

### 10.3 负向与边界

- Charlie 从未加入 Direct 会话时不能下载 Direct attachment。
- 错误 message ID / attachment ID / target kind 返回稳定错误。
- MIME override 与服务端 allowlist 不匹配时失败。
- 超过 `AWIKI_MAX_ATTACHMENT_BYTES` 的 fixture 在 slot/upload/commit 流程中失败，且不生成可下载已提交对象。
- 下载目标已存在时遵循 CLI contract，不静默覆盖用户文件；测试使用全新 output path。
- 明确不运行 `--secure required`。
- 不把跨域 attachment relay 纳入成功 Gate。

### 完成标准

- Direct 与 Group 均由真实 CLI 完成 upload-to-message-to-download 全链路。
- 至少一个 binary fixture 逐字节一致。
- 非成员/非参与者不能取得可用 download ticket。

## 11. Phase 6：真实 CLI Realtime/restart Gate

### 11.1 运行方式

不在测试机安装系统服务。对 Bob workspace：

1. `runtime mode set websocket`。
2. listener config 设为 enabled，auto-install/auto-start 关闭。
3. host-notify 使用 `file` sink，路径位于临时 artifact 目录。
4. 以独立进程组运行：

```text
AWIKI_CLI_INTERNAL_ENTRY=1 awiki-cli runtime listener run
```

5. 轮询 `runtime listener status`，直到：
   - session `connected=true`；
   - `reliable_sync.v2_subprotocol_negotiated=true`；
   - `reliable_sync.v2_bootstrap_completed=true`；
   - `last_reconcile_protocol=sync_v2`；
   - `legacy_sync_used=false`。

如果当前 Open Server WebSocket contract 不能达到这些状态，先修复 v2 wire/subprotocol compatibility；不得以强制 status 文件或跳过握手伪造通过。

### 11.2 Realtime Direct 与 Group

1. listener ready 后 Alice 向 Bob 发送一条 Direct。
2. Alice/Bob 所在 Group 再发送一条 Group message。
3. 等待 file host-notify sink 出现对应 message/group ID。
4. 不先运行会主动 HTTP reconcile 的 `msg inbox/history` 来冒充 realtime 接收。
5. host-notify 到达后，再用 Inbox/History/Group messages 验证 durable projection。

断言：WebSocket 事件只触发 dirty/reconcile；最终消息来自 Sync v2/local view，listener status 仍显示 `legacy_sync_used=false`。

### 11.3 Listener restart

1. 记录 listener PID、boot ID 与 status。
2. TERM listener 并等待退出。
3. listener 停止期间 Alice 发送 Direct 和 Group message。
4. 重新启动 foreground listener。
5. 等待新 boot ID、connected、v2 bootstrap/reconcile。
6. 验证停机期间的消息通过 durable sync 补齐，且 file sink/Inbox/History 不重复业务事实。

### 11.4 Open Server restart

1. listener 连接时停止 Open Server。
2. 观察 listener 进入 disconnected/degraded，不能仍宣称 connected。
3. 使用同一 data dir、端口、DID domain 和 service key 重启 Open Server。
4. 等待 listener 自动 reconnect，`legacy_sync_used=false`。
5. 重启后发送新 Direct/Group message并验证通知与 durable projection。
6. 再验证重启前的 Inbox、read state、Group membership、attachment metadata 仍存在。

### 11.5 超时与清理

- 每个 ready/reconnect/message wait 都有明确 deadline 和最后状态输出。
- listener/server 意外退出立即失败，不等满超时。
- 测试结束必须清理 listener、server、socket、pid；不删除用户目录，只清理本次明确创建的临时根目录。

### 完成标准

- 真实 CLI listener 证明 v2 negotiation、bootstrap、reconcile。
- Direct 和 Group 均有 realtime hint + durable projection 证据。
- listener restart 和 Open Server restart 后均能恢复，且没有 v1 fallback。

## 12. Phase 7：真实 CLI cross-domain Gate

### 12.1 拓扑

启动两个完全独立的 Open Server：

```text
Server A / Domain A / SQLite A / service key A
Server B / Domain B / SQLite B / service key B
```

建议使用可解析到 loopback 的两个不同测试 host，例如：

```text
source.127.0.0.1.nip.io
target.127.0.0.1.nip.io
```

两端使用不同端口，各自 resolver map 同时包含 A、B。CLI 使用两个完全隔离的 tenant/workspace：

```text
Workspace Alice -> Server A
Workspace Bob   -> Server B
```

不得让两个 CLI workspace 都连接同一个 backend；report 必须输出双方 `config show` 的解析结果并断言不同。

### 12.2 双向 Direct

1. Alice 在 A 注册，Bob 在 B 注册。
2. Alice CLI 向 Bob DID 发送明文 Direct。
3. Bob CLI Inbox/History 通过受限 Sync v2 看见该消息。
4. Bob CLI 向 Alice DID 回复。
5. Alice CLI Inbox/History 看见回复。

断言双方 DID domain、source/target service DID、message ID、origin proof、HTTP Signature delivery 与本地投影都正确。测试证据可读取脱敏 server audit/log，但业务动作必须由真实 CLI 发起和读取。

### 12.3 Group Host 方向 A -> B

1. Alice 在 A 创建 private/admin-add Group。
2. Alice 从 A 添加 Bob 的远端 DID。
3. Alice、Bob 查询 Group info/list/members。
4. Alice 和 Bob 各发送一条明文 Group message。
5. 双方 `group messages` 都看到两条消息。
6. 更新 Group profile/policy，并验证 B projection 更新。
7. Bob leave；之后发送失败且 active members 不含 Bob。

### 12.4 Group Host 方向 B -> A

1. Bob 在 B 创建 open-join Group。
2. Alice 从 A 执行 `group join`。
3. 双方查询 info/list/members。
4. 双向发送并读取消息。
5. Bob remove Alice；之后 Alice 发送失败且投影更新。

这两个方向必须分别通过，不能用同一个 Host 方向重复两次代替。

### 12.5 Outbox/restart 恢复

1. 在一个 Group Host 方向中暂时停止成员域 Server。
2. Host 产生两条按序事件/消息，使 outbox 进入 pending/retry。
3. 重启 Host 一次，确认 durable outbox 未丢失。
4. 恢复成员域 Server。
5. 验证 FIFO 投递、projection 收敛、无重复业务事件，并记录最终 delivered 状态。

### 12.6 明确不测

- 跨域 Attachment 上传/下载 relay；
- relay/peer-route mesh；
- 三方 federation routing；
- E2EE Direct/Group；
- 多设备 fanout。

### 完成标准

- 双向 Direct 由真实 CLI 发送和读取。
- A-host/B-member 与 B-host/A-member 两个 Group 方向都通过。
- members、messages、projection、leave/remove 与 retry/restart 有证据。
- 两个 workspace 的 backend、DID domain 和本地目录完全隔离。

## 13. Phase 8：pytest、文档与发布 Gate 集成

### pytest

新增或扩展：

- `tests/test_sync_v2_single_device.py`：Group/thread-after/cursor/权限/restart。
- `tests/test_cli_smoke.py`：harness 单测和 raw subprocess smoke。
- 新增真实 CLI opt-in system test 文件，例如 `tests/test_rust_cli_system.py`，统一用 marker/env gate。
- 公网 `rwiki.cn` tests 继续只受 `AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1` 控制；不要与本地 Rust CLI Gate 混用环境变量。

### 文档

验证通过后更新：

- `docs/client-compatibility.md`
- `docs/client-compatibility.zh-CN.md`
- `docs/getting-started.md`
- `docs/getting-started.zh-CN.md`
- `docs/anp-interop.md`
- `docs/anp-interop.zh-CN.md`
- `docs/release-readiness-checklist.md`
- 本计划的执行记录

文档必须把“测试目标”“协议层已验证”“真实 CLI 已验证”分栏，不再出现 Attachment/members 在开头写成已覆盖、后文又写未验证的歧义。

### 发布命令建议

```bash
# 默认快速门禁
PYTHONPATH=../anp/anp:src python3 -m pytest tests -q

# 真实 CLI local 完整门禁
PYTHONPATH=../anp/anp:src \
AWIKI_RUN_RUST_CLI_SYSTEM_TESTS=1 \
AWIKI_CLI_BIN=/absolute/path/to/pinned/awiki-cli \
python3 -m pytest tests/test_rust_cli_system.py -k local -q

# 真实 CLI realtime/restart 门禁
PYTHONPATH=../anp/anp:src \
AWIKI_RUN_RUST_CLI_SYSTEM_TESTS=1 \
AWIKI_CLI_BIN=/absolute/path/to/pinned/awiki-cli \
python3 -m pytest tests/test_rust_cli_system.py -k realtime_restart -q

# 真实 CLI cross-domain 门禁
PYTHONPATH=../anp/anp:src \
AWIKI_RUN_RUST_CLI_SYSTEM_TESTS=1 \
AWIKI_CLI_BIN=/absolute/path/to/pinned/awiki-cli \
python3 -m pytest tests/test_rust_cli_system.py -k cross_domain -q
```

发布脚本必须检查 focused selection 实际运行数量大于零；0 collected 或全部 skipped 视为失败。

## 14. 实施顺序与依赖

| Step | 内容 | 依赖 | 主要产物 |
| --- | --- | --- | --- |
| 0 | 固定 CLI artifact 与 contract preflight | 无 | provenance report |
| 1 | harness 重构与安全进程管理 | Step 0 | 共享 fixture/helper |
| 2 | Sync v2 Group/thread-after 专项 | Step 1 可并行部分 | focused pytest |
| 3 | CLI members | Step 1 | local scenario |
| 4 | CLI mark-read | Step 1 | local + restart scenario |
| 5 | CLI Attachment | Step 1 | Direct/Group file scenario |
| 6 | CLI Realtime/restart | Step 1、Step 2 | foreground listener scenario |
| 7 | CLI cross-domain | Step 1、Step 3、Step 6 的稳定 helper | two-server scenario |
| 8 | 全量 Gate、文档和报告 | Step 2-7 | release evidence |

建议先完成 Step 2-5 的确定性 HTTP/SQLite 路径，再进入长运行 Realtime 和双服务器 cross-domain，以便把 contract 错误与进程竞态分开定位。

## 15. 风险与控制

| 风险 | 控制 |
| --- | --- |
| CLI branch 漂移导致“最新”不可复现 | 固定完整 commit/tag，记录 version 与 SHA-256 |
| 完整 CLI smoke 通过但 artifact provenance 缺失 | local/realtime/cross-domain 每个 report 都内置 provenance |
| listener 测试安装/修改系统服务 | 只用 foreground hidden entry，不执行 install/start system service |
| listener 子进程挂住 | deadline、process group、TERM/KILL、日志 artifacts |
| 用 Inbox 查询触发主动 sync，误判为 Realtime 成功 | 先以 listener status + file host-notify 证明 realtime，再查询 durable view |
| WebSocket 被当作可靠 checkpoint | 断言最终事实来自 Sync v2，通知只作 dirty hint |
| restart 重新创建空数据目录而假装恢复 | 明确复用同一 data dir、service key、domain 和端口 |
| cross-domain 两个 CLI 实际连到同一 backend | 对双方 `config show` 做反向断言并写 report |
| DNS/WNS 对 localhost 校验失败 | 使用两个可解析 loopback host，并预检 DID host |
| Attachment 只比较文件名、不比较内容 | byte length + SHA-256 + byte-for-byte |
| members 空列表掩盖 auth/projection 错误 | 必须断言 `ok=true`、成员集合和分页，不接受空降级 |
| mark-read 只看 command success | 前后 unread/history 与 restart 后状态三重断言 |
| 测试意外启用 contact dev shim | 子进程显式 `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=0` |
| E2EE 测试混入发布 Gate | 所有 CLI send 明确 `--secure off`，能力断言 E2EE disabled |
| 跨域 Attachment 超出范围 | 只做本地对象 Gate，report 明确 cross-domain relay not_supported |

## 16. Definition of Done

只有同时满足以下条件，才能把本计划状态改为 complete：

1. 默认完整 pytest 通过，公网 tests 仍保持 opt-in。
2. Sync v2 Group delta、batch hydration、显式 v2 thread-after 与负向权限测试通过。
3. pinned 真实 CLI 的 local Gate 通过 Attachment、members、mark-read。
4. pinned 真实 CLI foreground listener 通过 Realtime、listener restart、Open Server restart。
5. pinned 真实 CLI cross-domain Gate 通过双向 Direct 和两个 Group Host 方向。
6. report 保存 CLI/Open Server provenance、IDs、restart 和 reliable-sync 安全证据。
7. 所有长运行进程均被清理，成功和失败路径都没有残留 listener/Uvicorn。
8. `git diff --check`、compileall、focused tests、全量 tests 通过。
9. 文档兼容矩阵准确区分真实 CLI、raw protocol 和 ASGI 覆盖。
10. 没有新增 E2EE、多设备、snapshot、invitation、relay 或跨域 attachment relay 能力。

## 17. 最终验证报告模板

```text
日期：
Open Server commit/dirty：
ANP SDK version：
CLI repository/tag/commit：
CLI version：
CLI artifact SHA-256：
OS/arch：

默认 pytest：
Sync v2 Group/thread-after：
真实 CLI local：
  - members：
  - mark-read：
  - Direct Attachment：
  - Group Attachment：
真实 CLI Realtime：
  - v2 subprotocol：
  - v2 bootstrap/reconcile：
  - Direct/Group notification：
  - listener restart：
  - Open Server restart：
真实 CLI cross-domain：
  - A -> B Direct：
  - B -> A Direct：
  - A-host Group：
  - B-host Group：
  - outbox/restart：

明确未支持：
  - E2EE
  - 多设备/设备共享
  - snapshot recovery
  - invitation/join token/pending membership
  - relay/peer-route mesh
  - cross-domain attachment relay

失败/限制与复现命令：
artifact/log/report 路径：
```

## 18. 实施与验证结果（2026-08-08）

状态：**已完成**。

### 固定基线

| 项目 | 实际值 |
| --- | --- |
| Open Server 基线 commit | `22dbcd5dbec0056fcf5e11f3432ffb7e9194738c` |
| ANP Python SDK | `anp==0.9.2`；验证使用 `PYTHONPATH=../anp/anp:src` |
| 真实 CLI | `awiki-cli 1.0.43` |
| CLI commit | `bbeb8a5c67810bd40443fb803279336eb876d6a5` |
| CLI artifact SHA-256 | `22a201691b1af077b37157d2307e9af9619c94495e4f8e4e1f8638f996de97f4` |

每个真实 CLI Gate 的 JSON report 还会在运行时重新记录 CLI version/commit、artifact SHA-256，以及当次 Open Server commit、dirty 状态和 changed-path 数量。开发工作树运行时 `dirty=true` 属于预期；发布候选应在提交后重新运行并保存 clean report。

### 已实现并通过的场景

- `Sync v2 Group/thread-after`：Group delta、batch hydration、显式 `thread-after`、cursor 推进，以及非成员权限拒绝。
- `Attachment`：真实 CLI Direct/Group 二进制上传、消息绑定、下载、逐字节与 SHA-256 校验；Open Server restart 后仍可下载；成员 leave/remove 后下载拒绝。
- `members`：真实 CLI 全量成员、cursor 分页、leave/remove 收敛、非成员查询拒绝。
- `mark-read`：真实 CLI 单条、批量、幂等、越权拒绝、unread/history 投影与 restart 持久化。当前 CLI 明确声明 `msg inbox --mark-read` page side effect 为 `unsupported_capability`，Gate 如实断言该结果，再用 `msg mark-read` 验证服务端能力。
- `Realtime/restart`：真实 CLI foreground listener、Bearer WebSocket、`awiki.sync.changed.v2` 协商、Sync v2 bootstrap/reconcile、Direct/Group dirty hint、listener downtime 补偿、Open Server 同 data dir/key/domain/port restart，以及受测试监督的 foreground listener 重启恢复；没有 legacy sync fallback。
- `cross-domain`：隔离 network namespace 中两个独立 TLS Open Server、两个独立 CLI workspace、双向明文 Direct、A-host/B-host Community Group、远端成员发消息、leave/remove 收敛与离组后发送拒绝。
- Open Server 显式设置 `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=0`；CLI 的 phone/OTP 仅为当前命令行必填占位参数，服务端没有模拟手机号、验证码或真实联系信息验证。

### 最终命令与结果

```bash
# 语法/导入检查
PYTHONPATH=../anp/anp:src python3 -m compileall -q src scripts tests

# 默认完整门禁
PYTHONPATH=../anp/anp:src python3 -m pytest tests -q
# 104 passed, 5 skipped

# 真实 CLI 三项系统门禁
AWIKI_RUN_RUST_CLI_SYSTEM_TESTS=1 \
AWIKI_CLI_BIN=/home/ecs-user/awiki-space/awiki-cli-rs2/target/debug/awiki-cli \
PYTHONPATH=../anp/anp:src \
python3 -m pytest tests/test_rust_cli_system.py -q
# 3 passed

# diff 格式检查
git diff --check
```

默认的 5 个 skip 包括 3 个需显式启用的真实 CLI Gate 和既有的受保护外部/系统检查；公网 `rwiki.cn` 测试仍未被默认执行。

### 明确边界

本次没有新增或成功测试 E2EE、多设备/设备共享、一个 DID 绑定多个设备、snapshot recovery、invitation/join token/pending membership、relay/peer-route mesh、跨域 Attachment relay。cross-domain Gate 验证的是在线直连与成员状态收敛，不把跨域 outbox crash/restart 单独宣称为已覆盖；Open Server restart 专项证据位于 local 与 Realtime Gate。
