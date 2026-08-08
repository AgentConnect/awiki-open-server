# AWiki Open Server 客户端兼容性

[English](client-compatibility.md) | [简体中文](client-compatibility.zh-CN.md)

最后整理日期：2026-08-08。兼容性应以具体客户端 version/commit、服务端 commit 和验证日期记录。

## 1. 总览

| 客户端/对端 | 当前定位 | 已知能力 | 关键限制 |
| --- | --- | --- | --- |
| `awiki-cli` | 主要兼容验证客户端 | 1.0.43 `bbeb8a5c` 已验证本地 Attachment/members/mark-read/restart、Realtime Sync v2，以及双向 Direct/Group 跨域 Gate | Sync v2 仅单设备拉取；无设备共享、第二设备、snapshot recovery 或 E2EE |
| AWiki Me | 基础产品兼容目标 | 自定义租户下的身份/消息/附件需持续验证 | Agent realm allowlist；无 E2EE；不能宣称所有 App 功能兼容 |
| 其他 ANP Peer | 选定 public methods | capability、Direct、部分 Group/Attachment | 不是完整 federation；需要 origin proof 与 service signature |
| 旧 AWiki Client | compatibility routes | User/Message Service 风格路由 | shim 不等于生产身份提供方或完整托管平台 |

## 2. awiki-cli

仓库提供的 CLI smoke 目标包括：

- DID 注册；
- Direct send、Inbox、History；
- 两个 Host 方向的 group create/get/list/add/join/members/update/send/messages/leave/remove；
- People follow/status/following/followers；
- Site root/pages；
- Attachment（按当前 smoke 与服务实现）。

这里的“目标”不等于所有未来版本天然兼容。2026-08-08 使用 `awiki-cli` 1.0.43、提交
`bbeb8a5c` 的干净构建实测：二进制 Direct/Group Attachment 逐字节下载比对、members 与 cursor
分页、幂等 mark-read 与重启持久化、`awiki.sync.changed.v2` foreground Realtime、listener/server
重启恢复，以及两个独立 TLS 域的双向明文 Direct 和两个 Group Host 方向均通过。这里的 v2 是 wire
contract 版本，不是多设备能力声明：Open Server 将一个 DID 固定到恰好一个设备和一个 client
instance，只支持 tail-only bootstrap、delta、`message.get_batch` 与 thread catch-up；第二设备或
第二 client instance 返回 `not_supported`，也不发布 snapshot recovery 或设备间状态共享。

可重复的分层验证：

```bash
# 连接 Gate：配置、注册并执行明文 Direct 写入
PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-rust-cli-connect \
  --awiki-cli-bin /path/to/pinned/awiki-cli --clean

# 完整本地 Gate；Attachment 的标准 DID 发现需要 HTTPS，脚本会创建隔离网络命名空间和测试 CA
PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-rust-cli-local \
  --awiki-cli-bin /path/to/pinned/awiki-cli --standard-https --clean

# foreground Realtime/Sync v2，以及 listener 与 OpenServer 重启恢复
PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-rust-cli-realtime-restart \
  --awiki-cli-bin /path/to/pinned/awiki-cli --clean

# 两个 TLS OpenServer 域：双向明文 Direct 与两个 Group Host 方向
PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-rust-cli-cross-domain \
  --awiki-cli-bin /path/to/pinned/awiki-cli --clean
```

基于网络命名空间的 HTTPS Gate 需要 Linux `unshare`、`mount` 和 `ip`；不会修改宿主网络，也不会安装 listener 系统服务。pytest 门禁默认跳过，显式运行方式为：

```bash
AWIKI_RUN_RUST_CLI_SYSTEM_TESTS=1 AWIKI_CLI_BIN=/path/to/pinned/awiki-cli \
PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_rust_cli_system.py -q
```

报告必须区分 `connection-and-write passed`、`single-device sync v2 passed` 和
`full local user journey passed`，并保存 CLI commit、`awiki-cli version`、artifact SHA-256、
Open Server commit 与日期。

连接示例：

```bash
awiki-cli tenant setup community \
  --backend-base-url https://community.example.com \
  --did-host community.example.com
awiki-cli init
```

安全限制：

```text
不要使用 --secure required
不要把 Contact Verification dev shim 当作真实 SMS/Email
群入组只使用立即 active 的 group.add/group.join；不要期待 invitation token、join code、pending membership 或 accept-invite
```

## 3. AWiki Me

基础租户要求：

- backend base URL 可访问；
- DID host 与服务配置一致；
- User/Message compatibility route 满足当前 App 版本；
- attachment URL 与 ticket 可访问；
- WebSocket route 与 ticket flow 匹配。

需要单独验证的用户流程：

- 注册/登录；
- Direct send/receive/history；
- unread/read；
- Group create/add/join/update/send/messages/leave/remove；
- Attachment send/download/open；
- People/Contact/Profile；
- App restart 与 local sync recovery。

### Agent/Daemon 限制

AWiki Me 当前只对精确 allowlist realm 启用 Agent/Daemon API：

```text
awiki.ai
awiki.info
anpclaw.com
```

普通自托管域名即使可以登录和发消息，Agent 页面也可能显示 unsupported 并拒绝相关 API。Open Server 提供部分 Agent compatibility route，并不自动绕过 App 的 realm policy。

### E2EE

Open Server 不实现 Direct 或 Group E2EE。AWiki Me 必须把该租户视为无 E2EE 服务，不能显示误导性的“消息已端到端加密”。

## 4. Public ANP methods

当前 `/anp-im/rpc` 公开选定方法：

- `anp.get_capabilities`；
- `direct.send`；
- `group.get_info`；
- `group.join`；
- `group.create/add/remove/rebind_member/leave/update_profile/update_policy/send`；
- 无 JSON-RPC `id` 的 `group.incoming/group.state_changed` Notification；
- `attachment.get_download_ticket`。

本地 `/im/rpc` 还包含 Inbox、History、Sync、Read State、本地 Group view 与 Attachment control。

不要把本地兼容 RPC 全部暴露为跨域 public contract。

## 5. Compatibility routes 的含义

User Service / Message Service 风格 route 在本服务内本地实现，不会代理到 `awiki.info`。它们的目的包括：

- 让当前 CLI/App 复用现有客户端形状；
- 提供本地 profile、token、DID、relationships 和消息入口；
- 在明确关闭的情况下返回 `contact_verification_not_enabled`；
- 为 Nginx `auth_request` 等集成返回本地验证 header。

Compatibility 不代表：

- 完整 AWiki Hosted Platform；
- 生产身份提供方；
- 完整 Agent orchestration；
- 大群与复杂 group governance；
- 与未来客户端永久兼容。

## 6. 验证记录模板

```text
日期：YYYY-MM-DD
Open Server commit/version：
Client name/version/commit：
Domain/base URL：
ANP SDK version：

通过：
- identity
- direct
- inbox/history
- read/sync
- Community Group v1 lifecycle 和两个跨域 Host 方向
- attachment
- people/profile/site
- websocket/restart

限制/失败：
- agent
- secure
- large-group/complex governance
- ...
```
