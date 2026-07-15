# AWiki Open Server 客户端兼容性

[English](client-compatibility.md) | [简体中文](client-compatibility.zh-CN.md)

最后整理日期：2026-07-14。兼容性应以具体客户端 version/commit、服务端 commit 和验证日期记录。

## 1. 总览

| 客户端/对端 | 当前定位 | 已知能力 | 关键限制 |
| --- | --- | --- | --- |
| `awiki-cli` | 主要兼容验证客户端 | 本地注册、Direct、Inbox/History、Group participant、People、Site、Attachment | 无 E2EE；完整群管理不支持；注册 contact 参数只是兼容形状 |
| AWiki Me | 基础产品兼容目标 | 自定义租户下的身份/消息/附件需持续验证 | Agent realm allowlist；无 E2EE；不能宣称所有 App 功能兼容 |
| 其他 ANP Peer | 选定 public methods | capability、Direct、部分 Group/Attachment | 不是完整 federation；需要 origin proof 与 service signature |
| 旧 AWiki Client | compatibility routes | User/Message Service 风格路由 | shim 不等于生产身份提供方或完整托管平台 |

## 2. awiki-cli

仓库提供的 CLI smoke 目标包括：

- DID 注册；
- Direct send、Inbox、History；
- open group join、send、messages；
- People follow/status/following/followers；
- Site root/pages；
- Attachment（按当前 smoke 与服务实现）。

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
不要依赖 group.create/add/remove/update
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
- Group join/send/messages；
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
- `attachment.get_download_ticket`。

本地 `/im/rpc` 还包含 Inbox、History、Sync、Read State、Group participant 与 Attachment control。

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
- 完整 group/admin policy；
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
- group participant
- attachment
- people/profile/site
- websocket/restart

限制/失败：
- agent
- secure
- group admin
- ...
```
