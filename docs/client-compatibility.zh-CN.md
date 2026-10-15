# AWiki Open Server 客户端兼容性

[English](client-compatibility.md) | [简体中文](client-compatibility.zh-CN.md)

最后整理日期：2026-10-15。当前对齐基线为 `release/0929`；验收范围与历史证据分别说明如下。

## release/1014：关闭 P5/P6 临时兼容

本分支从 `main` 的 `09d38fd` 创建，按 2026-10-15 用户要求移除测试期间的 P5/P6 空流兼容。
相关 bootstrap 请求返回 `sync.lanes_not_supported`，`supported=[]`；delta 不接受 `lanes`
或 `p6_delivery`，不返回兼容空流；P6 delivery-context WebSocket 子协议拒绝，关闭码 4406。
旧数据库中的协商记录不会启用这些能力，普通同步重新协商会保存空的能力集合。
普通 Sync v2、Schema 3 Snapshot、明文 Direct 和普通群保留，公开 E2EE 能力继续关闭。

资料兼容响应（`get_public_profile`/`get_me`、本域 Handle lookup 的嵌入资料和 users
资料视图）同时提供规范化 `full_handle`，与 Handle 权威绑定一致。旧 `handle` 字段的
原有格式保留；不改数据库、身份或会话。新客户端优先使用 `full_handle`，避免把旧
`name@domain` 显示格式与 `name.domain` 的绑定误判为冲突。

仍强制请求 P5/P6 的 CLI/App 需要在客户端改为只协商普通同步。下面 CLI 1.0.58 和 App
0.1.38+49 的通过记录属于 `09d38fd` 的临时兼容状态，不能作为当前分支的客户端接入通过
证据；本分支以拒绝相关能力、普通明文同步及重启回归为验证范围，不运行加密成功流程。

## release/0929 对齐状态

Open Server 使用锁定的已发布 ANP Python SDK **1.0.6**。`/user-service/v1/handle/rpc` 的
`registration_check` 已实现本地名称预检查，返回 `register/existing/unavailable`，不占名、不签发
授权或回显联系方式。按可信 ASGI peer 限制每分钟 20 次，最终注册仍在事务内检查名称占用。
自托管注册不要求 Hosted Platform 的短名称邀请码。

`GET /user-service/v1/server-info` 提供 aWIKI ME 的 schema 1 发现合同：仅本地域 WBA 新建，
免联系方式验证注册；不声明真实 SMS/Email、Handle Recovery、Root Transfer、Model Proxy、
Guest Gateway 或托管 Skill Agent 能力。CLI 手机注册仍可使用本地 operator code，不证明手机号归属。
当前 aWIKI ME `release/0929` 的原始 Dart `OnboardingServerInfo` parser 已成功解析该响应，
识别免联系方式验证注册和关闭的 Recovery；这是接口合同验证，不代替真实 App 用户旅程。

历史过渡（2026-10-14 授权，release/1014 已移除）：当时 P5/P6 订阅在 bootstrap 回复成功，
delta 返回固定空流，对应 WebSocket 子协议只发送明文同步 dirty hint。该处理未实现加密
消息生产者、密文存储、prekey、KeyPackage 或加密附件业务。

正式 CLI **1.0.58**（commit `b7ed6f95f7fb90151726a96e6bed756957f6312e`，Linux x86_64
SHA-256 `459bf8737cf27c8441fd0f4d22cefdf67958a777ffefd193fef0b08126282c85`）已验证标准
两阶段注册和明文 Direct 写入。制品来自 `https://awiki.me/cli/stable/manifest.json` 指向的
正式安装包，下载摘要已校验，客户端未修改。1.0.57 已低于当前默认租户最低版本 1.0.58。
扩展后的 `smoke-rust-cli-connect` 已通过：两个身份标准注册、明文 Direct 双向收发、Inbox/History、
明文 Group create/add/send/read。

2026-10-15 在 `09d38fd` 临时兼容状态下补齐以下验收：

- 完整 `smoke-rust-cli-realtime-restart` 通过：2 次服务端启动、3 次 listener 启动、5 条明文
  消息，覆盖在线通知、listener 停机补收、服务端重启及历史读取。每次就绪检查均完成
  sync v2 bootstrap/子协议协商，`legacy_sync_used=false`。原最终 `bridge_read` 失败来自
  CLI 桥接读取未携带默认身份；门禁最后两次读取显式传入 Bob 的 `--identity`，保留全部原断言。
- aWIKI ME **0.1.38+49**，源码 `a205a36af81d558523722d1a5cf5e50523fe8845`，以未修改的
  `lib/main.dart` 在 Linux/Xvfb 运行真实 UI。自定义 HTTPS 租户发现、标准注册、明文 Direct
  与普通群双向收发、App 重启后身份/会话/历史恢复均通过；发送结果由正式 CLI 核对 sender
  和完整正文，收信有 UI 截图。原生库由 registry Core **0.1.9** 构建并通过现有来源检查。
  `AWIKI_E2E` 仅启用现有隔离状态目录及语义标记，未注入 fake service 或编辑客户端状态。
  当前 App 留空手机号会在发出预检查前报 `phone_invalid_intl_or_cn`，本次填入专用测试号码
  走免验证码注册，无 SMS/OTP。该客户端问题未在本仓库修改；本次是聚焦 Linux UI 验收，
  不表示 App 全量或跨平台 E2E 通过。
- 独立公网 OpenServer 与真实 `awiki-info-testing`（`https://awiki.info`）完成 Direct 双向
  收发；OpenServer、MessageService 分别作为普通群 Host 时，双方发言均在对方成员端可见，
  验证签名请求、Group Receipt 与正文。使用标准公网 HTTPS/DID discovery，无 resolver 替换、
  unsigned peer 或共享服务变更。复用 `awiki-system-test` 现有身份和跨域消息 helper；成员
  就绪按可见的 `group.list` 角色等待，不要求对端本地投影包含整份 Host roster。

保留首次冲突、成员查询/等待错误、临时隧道中断和后续成功记录，不将重试写成首轮全绿。
脱敏 JSON、截图、固定制品来源及清理范围保存在工作区
`verification-runs/openserver-release0929-20261015/`。远端 User Service 身份按拥有仓库策略
保留；精确 Message 清理操作失败，残留已记录，不能宣称清理完成。本轮临时进程已停止。
没有运行加密成功流程；客户端自动提交的 prekey/KeyPackage 请求均返回 `not_supported`。
以下保留过渡前的失败事实。

2026-10-13 使用未修改的 CLI **1.0.57**（当前 release/0929 源码
`ec90c4cc772ef7a4c64809b6158affb807798df0`，Linux x86_64 SHA-256
`422955d37df9237032933ebb620dba66392145a4ce22a78c123a2b695aa9ee11`）
验证：预检查、operator code 和单设备注册落库成功；CLI 的首次接收同步失败，返回
`registration_receive_pending`，再次 `msg inbox` 返回 `sync.lanes_not_supported`。
该制品由 CLI 现有 `scripts/release/registry-build.py` 从固定提交的 Git archive 新构建，
实际解析来源均为 registry：ANP 1.0.6、Identity 0.2.5、Core 0.1.8。
CLI 和其依赖源码未修改；这是当前发布组合的接入证据，不表示已发布到 stable 渠道。
原生构建回执和脱敏失败记录分别保留于
`/tmp/openserver-release0929-cli-registry-ec90c4cc.json` 和
`/tmp/openserver-release0929-ec90c4cc-runtime/result.json`，测试进程已停止。

过渡前 Core 根据编译 feature 请求 P5/P6，并要求服务返回完全相同的 lane 集合，导致上述
`sync.lanes_not_supported`。这属于 AWiki 私有同步合同，不能据此认定 MessageService/UserService
违反 ANP。2026-10-14 曾临时使用空流兼容；release/1014 已恢复明确拒绝。

所有 Rust CLI smoke 使用标准两阶段注册，通过 `--verification-stdin` 传递验证材料，不使用
`--community`，失败日志也对 stdin 中的联系方式和 operator code 脱敏。失败门禁保持非零退出。

## 历史协议升级路径（R3，2026-09-18）

验收客户端是 `https://awiki.info/cli/stable/manifest.json` 的未修改正式 CLI：**1.0.52**，commit `dde0a9c54eebf29a2ec97089e90a1fa77ba768c5`，linux-amd64 SHA-256 `a055da8dad2969739c50cee4f2ee0bf34b45f5354ea74617f103534b239f9d1a`。不要把 candidate16、`--community` 或未发布的 1.0.53 Community 构建当作当前路径。

新身份使用正式 `id register`，需要 Handle 和手机验证材料。Open Server 不发送短信；`send_otp`（purpose `awiki.identity.register.v1`）把一次性本地操作码写到数据目录，再用 `--otp` 完成注册。可靠 listener 需要真实单设备 Manifest/绑定。当时正式 CLI 1.0.52 请求 P5/P6 后被 `sync.lanes_not_supported` 阻断；release/1014 同样拒绝此类协商，E2EE 业务未实现。该设备的普通 Schema 3 Snapshot 恢复已实现。Open 不提供身份/Handle 找回或 Root Transfer。

R2 未发布 CLI 1.0.53 / SHA `8169383d86a57eaed23e015dc948f8176216e9f81903d16f590dd03c513f847f`（基于 `c61fa4b419b96fdabdbd321f1a8e47cdd7f77302`）只作历史记录。

## 1. 历史证据与客户端定位

| 客户端/对端 | 当前定位 | 已知能力 | 关键限制 |
| --- | --- | --- | --- |
| `awiki-cli` | 主要兼容验证客户端 | 1.0.43 `bbeb8a5c` 已验证本地 Attachment/members/mark-read/restart、Realtime Sync v2，以及双向 Direct/Group 跨域 Gate | Sync v2 仅单设备拉取；无设备共享、第二设备或 E2EE。该设备的普通 Schema 3 Snapshot 恢复已实现 |
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
instance；第二设备或第二 client instance 返回 `not_supported`。空账号可以 tail-only
bootstrap；日志缺口和过期 cursor 走 Schema 3 分页 Snapshot
（`awiki.message-sync.explicit-negotiation.v1`、`sync.snapshot_paging.v1`），再接普通
delta。release/1014 拒绝 P5/P6 协商，客户端必须只请求普通同步；加密业务继续拒绝。
不提供设备间状态共享。

可重复的分层验证：

```bash
# 连接 Gate：配置、注册并执行明文 Direct 写入
uv run --locked python scripts/awiki_open_cli.py smoke-rust-cli-connect \
  --awiki-cli-bin /path/to/pinned/awiki-cli --clean

# 完整本地 Gate；Attachment 的标准 DID 发现需要 HTTPS，脚本会创建隔离网络命名空间和测试 CA
uv run --locked python scripts/awiki_open_cli.py smoke-rust-cli-local \
  --awiki-cli-bin /path/to/pinned/awiki-cli --standard-https --clean

# foreground Realtime/Sync v2，以及 listener 与 OpenServer 重启恢复
uv run --locked python scripts/awiki_open_cli.py smoke-rust-cli-realtime-restart \
  --awiki-cli-bin /path/to/pinned/awiki-cli --clean

# 两个 TLS OpenServer 域：双向明文 Direct 与两个 Group Host 方向
uv run --locked python scripts/awiki_open_cli.py smoke-rust-cli-cross-domain \
  --awiki-cli-bin /path/to/pinned/awiki-cli --clean
```

基于网络命名空间的 HTTPS Gate 需要 Linux `unshare`、`mount` 和 `ip`；不会修改宿主网络，也不会安装 listener 系统服务。pytest 门禁默认跳过，显式运行方式为：

```bash
AWIKI_RUN_RUST_CLI_SYSTEM_TESTS=1 AWIKI_CLI_BIN=/path/to/pinned/awiki-cli \
uv run --locked python -m pytest tests/test_rust_cli_system.py -q
```

报告必须区分 `registration-and-plaintext-messaging passed`、`single-device sync v2 passed` 和
`full local user journey passed`，并保存 CLI commit、`awiki-cli version`、artifact SHA-256、
Open Server commit 与日期。

候选连接示例（先按 [CLI 身份密钥存储说明](https://github.com/AgentConnect/awiki-cli-rs2/blob/c61fa4b419b96fdabdbd321f1a8e47cdd7f77302/docs/architecture/identity-secret-storage.md) 配置密钥存储）：

```bash
awiki-cli tenant create open \
  --backend-base-url https://open.example.com \
  --did-host open.example.com
awiki-cli tenant use open
awiki-cli id register --handle alice --phone +15550000001
awiki-cli id register --handle alice --phone +15550000001 --otp <local-operator-code>
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

自定义租户不会自动发现其他租户的旧凭据。显式导入旧身份时使用 `awiki-cli --migration id import-v1 --name <name> --credentials-dir <旧凭据目录>`；此参数仅指定本次导入来源，不更改租户配置，也不启动可靠 listener。
