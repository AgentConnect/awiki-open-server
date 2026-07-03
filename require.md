
下面是基于 `release/0526` 的建议方案。核心判断：**不要把现有 `user-service` + `message-service` 原样重写成 Python 版**，而是做一个 `awiki-open-server`：单进程、SQLite、本地对象存储、协议兼容优先、能力有边界。这样能让 `awiki-cli-rs2` 和 `awiki-me` 通过配置接入，同时把群创建/管理、E2EE、联邦服务、多租户运营、托管可靠性等复杂能力留在商业版或后续版本。

`awiki-cli-rs2` 已经把 `service_base_url`、`did_domain`、`anp_service_endpoint`、`anp_service_did` 做成配置项；`awiki-me` 也能从 `AWIKI_BASE_URL` 推导 user-service、message-service、DID domain 和 ANP endpoint，并支持高级覆盖。因此开源服务端只要兼容现有路由和 JSON-RPC 方法，就可以低成本接入两端。

边界更正：本仓是开源 server 服务端，必须自行实现线上 `awiki.info` 类服务能力，包括 DID 注册、DID 文档发布、Profile、消息公开入口、本地存储和 `/anp-im/rpc`。`awiki.info` 只能作为真实互通测试中的远端对等服务，不能作为本仓认证、消息、存储、代理、fallback 或运行时后端。

MVP 目标重新定义：第一个版本只证明独立 open server 能自托管运行、被当前 Rust CLI 连接、发布正确 DID 文档，并与线上 `awiki.info` 用户完成双向明文 direct 互通。该版本不使用邮件或手机号码验证过程，不引入阿里云或任何短信/邮件供应商依赖。现有 CLI 如果仍要求传 `--phone/--otp` 参数，这些参数只能作为旧 CLI 命令形态的占位输入，服务端不得把它们升级为认证、恢复、绑定、风控或持久化身份事实。

兼容范围解释：`awiki-open-server` 不追求完整复刻 `user-service` 或 `message-service`。兼容只覆盖 P0 主线和有当前 CLI/awiki-me 调用证据的 P1 shim；旧 User Service、Message Service、Daemon、Directory、Site、phone/email、Agent runtime 等边缘接口默认进入 P2 backlog，不能作为 v0.1 完成门槛。

## 方案 Review 结论

基于相邻项目的当前文档和实现边界，原方案方向基本正确，但需要收窄：

1. **保留单进程 Community Server 方向**：`user-service` 的 DID/Auth/Profile/Pages 与 `message-service` 的 Direct/Attachment/Realtime 可以合并到一个 Python 服务中，但代码仍应保留 identity、messaging、object、pages 等 bounded context。
2. **支持群参与，但不支持群创建/管理**：Community 版允许用户加入已有群、退出群、查看群信息/成员/消息，并在已加入群中发送普通明文群消息；不提供 `group.create`、`group.add`、`group.remove`、`group.update_profile`、`group.update_policy`、Group Host 管理、群治理或 Group E2EE。
3. **支持跨域服务，但不支持联邦服务**：Community 版应支持 DID 文档里的唯一 `ANPMessageService`、`serviceDid`、`/anp-im/rpc` 公开入口、远端 DID 发现、HTTP Signature / DID WBA 校验，以及 `direct.send` 的跨域直连。不要实现 `federation.peer_routes`、服务间 relay、远端重试队列、远端投影、跨域最终确认或跨域群组托管；群能力只做成员参与子集，不做跨域 Group Host。
4. **区分本域入口和公开跨域入口**：`/im/rpc` 服务本域客户端和 local-only 方法；`/anp-im/rpc` 只暴露 capability、跨域 `direct.send` 和必要的对象下载票据能力。

## 一、开源版应该开发哪些功能

### 1. 产品定位

建议命名为：

```text
awiki-open-server
```

定位：

```text
单机可运行的 Awiki Community Server
= DID 身份 + 明文私聊 + 跨域 Direct 服务 + 附件 + Markdown Pages + WebSocket 实时通知
= 群成员参与子集，不含群创建/管理
```

它不是生产托管平台，而是：

| 目标            | 设计选择                                                                                  |
| ------------- | ------------------------------------------------------------------------------------- |
| 让开发者能 5 分钟跑起来 | Python + FastAPI + SQLite + 本地文件对象存储                                                  |
| 让客户端能真实连接     | 兼容 `/did-auth/rpc`、`/did/profile/rpc`、`/im/rpc`、`/anp-im/rpc`、WebSocket、附件和 Pages API |
| 让项目有传播价值      | 支持 DID 注册、私聊、跨域 Direct、加入已有群、附件、Markdown 发布、基础同步                                          |
| 保护商业核心        | 不开放群创建/管理、E2EE、联邦服务、多租户运营、托管可靠性、积分、风控、商业运行时编排                                      |
| 引导商业化         | capabilities 明确声明 Community Edition，并在不支持能力的标准错误中返回升级提示                               |

现有系统中，`user-service` 的职责是账号、登录、Token、DID、Handle、Profile 和准入，`message-service` 的职责是 Direct、Group、Object Control、Federation、Outbox、本地投影和 WebSocket 通知；开源版可以把 identity、direct、group participant、object、pages 这些边界合并到一个 Python 进程里，但不实现 Group Host 管理和 Federation runtime。

### 2. 开源版必须支持的功能

| 功能域    | 开源版支持                                                                 | 商业版保留                                               |
| ------ | --------------------------------------------------------------------- | --------------------------------------------------- |
| DID 身份 | DID 注册、DID 文档发布/解析、DID WBA 验证、JWT、Profile、Handle 基础绑定                 | 多租户 Handle 体系、恢复/换绑高级流程、风控、短信/微信/邮箱生产认证             |
| 用户管理   | 本地用户、Agent 用户、Profile、session、refresh token                           | 企业账号、组织、权限、审计、风控                                    |
| 私聊     | `direct.send` 明文模式、`direct.incoming` WS、history、inbox、read state、sync、跨域 direct 直连 | Direct E2EE、prekey、ratchet、远端重试与最终确认             |
| 群参与    | 加入已有群、退出群、查看群资料/成员/消息、成员身份下发送普通群消息、群消息 WS 通知                              | 建群、加人、踢人、群资料/策略管理、Group Host、跨域群组、Group E2EE |
| 跨域服务   | DID 解析、唯一 `ANPMessageService`、`serviceDid`、`/anp-im/rpc`、跨域 `direct.send` 接收和一次性外发 | federation peer routes、relay、远端投影、跨域队列、跨域群组 |
| 附件     | 本地 slot、上传、commit、下载 ticket、明文附件 manifest                             | object-e2ee、CDN、扫描、长期存储、复杂跨域授权、配额商业策略              |
| Pages  | Handle 级 Markdown Pages，公开 `.md` 分发                                   | 租户裸域名 Site Pages、Web 页面渲染、SEO、托管域名、模板系统             |
| 同步     | `sync.delta`、`sync.thread_after`、顶层 realtime sync hint                | 多设备高级一致性、snapshot repair、长期 retention、托管备份          |
| 运行时    | 本地单进程、SQLite、WebSocket session registry                               | 多节点、HA、可观测性、托管 Runtime、Message Agent 商业编排           |
| 不支持能力  | 标准 `not_supported` + capabilities 声明                                  | 商业版入口                                               |

### 3. 开源版不应该支持的功能

这些能力建议明确不做，避免把商业护城河开源掉：

| 不支持项                        | 原因                                                                       |
| --------------------------- | ------------------------------------------------------------------------ |
| Direct E2EE：`direct.e2ee.*` | 涉及 P5、prekey、ratchet、opaque persistence、安全边界，是核心能力                       |
| 群创建/管理：`group.create`、`group.add`、`group.remove`、`group.update_profile`、`group.update_policy` | 牵涉 Group DID、Group Host、成员状态、群策略、群事件序列和跨域群 Host，不适合作为 Community MVP |
| Group E2EE：`group.e2ee.*`   | 现有文档中已经是 hidden / feature-gated / test-only 路径，不应作为 Community Edition 暴露 |
| Federation / peer routes    | 不实现固定对端路由、服务间 relay、远端重试、最终接受语义、远端投影和跨域队列；Community 只做 DID 发现后的 direct 直连 |
| 多租户生产身份体系                   | 包含风控、恢复、域名、Handle 治理、审计                                                  |
| Credits / billing           | 明确商业运营能力                                                                 |
| Mail                        | `awiki-cli` 有 mail 命令，但用户当前目标不是邮件服务，开源版应返回未启用                            |
| 手机号/邮箱验证流程                  | v0.1 不使用手机号或邮箱验证；不接短信、邮件、微信、阿里云或其他外部渠道；旧兼容路由默认未启用              |
| 高级 Message Agent 托管         | 可做 binding 占位，但不做 runtime orchestration、delegated secret 管理              |

## 二、建议支持的 API

### 1. 入口路径兼容

建议开源服务端默认提供这些路径：

| 路径                                      | 类型          | 说明                                   |
| --------------------------------------- | ----------- | ------------------------------------ |
| `GET /healthz`                          | REST        | 服务健康检查                               |
| `POST /did-auth/rpc`                    | JSON-RPC    | DID 注册、认证、HTTP Signature 验证          |
| `POST /did/profile/rpc`                 | JSON-RPC    | DID Profile                          |
| `POST /content/rpc`                     | JSON-RPC    | Handle 级 Markdown Pages              |
| `GET /content/{slug}.md`                | REST        | 公开 Markdown 页面                       |
| `POST /site/rpc`                        | JSON-RPC，可选 | 未来 Site Pages，MVP 可关闭                |
| `GET /`、`GET /pages/{slug}.md`          | REST，可选     | 未来 Web / Site 页面                     |
| `POST /im/rpc`                          | JSON-RPC    | 本域客户端消息 RPC                          |
| `POST /anp-im/rpc`                      | JSON-RPC    | 公开 ANP endpoint；支持跨域 Direct 接收，不做 federation relay |
| `GET /im/ws`                            | WebSocket   | 实时消息与同步 hint                         |
| `PUT /objects/upload/{slot_id}`         | REST        | 附件上传数据面                              |
| `GET /objects/{object_id}`              | REST        | 附件下载数据面                              |
| `GET /.well-known/did.json`             | REST        | service DID 文档                       |
| `GET /{path...}/did.json`               | REST        | did:wba 路径解析                         |
| `GET /dids/resolve/{sub_path}/did.json` | REST        | 兼容现有 DID resolve                     |

现有 `message-service` 的路由里已经包含健康检查、domain RPC、WebSocket、public RPC、对象上传下载和内部路由；开源版应保留同样的外部形态，但内部实现改成 Python + SQLite。`/im/rpc` 与 `/anp-im/rpc` 的暴露面必须分开：本域同步、历史、inbox、WebSocket 等 local-only 能力只进 `/im/rpc`；公开跨域入口只进 capability、`direct.send` 和必要的附件下载票据。

### 2. 身份与用户 API

#### `/did-auth/rpc`

必须支持：

| method                | MVP 行为                                      |
| --------------------- | ------------------------------------------- |
| `register`            | 注册 DID 文档，创建 user / handle / DID record     |
| `update_document`     | 更新 DID 文档，保留主公钥不变                           |
| `verify`              | 验证 Bearer / DIDWba，返回 DID JWT               |
| `verify_http_request` | 验证 HTTP Signatures / Bearer，用于消息服务 hop auth |
| `get_me`              | 返回当前 DID 用户                                 |
| `revoke`              | 撤销本地 DID                                    |
| `replace_did`         | Phase 2 或返回 not_supported                   |
| `recover_handle`      | Community 可返回 not_supported，引导商业版           |

现有 DID Auth 文档中，`/did-auth/rpc` 已经定义了 `register`、`update_document`、`replace_did`、`verify`、`verify_http_request`、`revoke`、`get_me`、`recover_handle`；开源版建议实现核心子集，保持方法名兼容。

#### `/did/profile/rpc`

必须支持：

| method               | MVP 行为                                |
| -------------------- | ------------------------------------- |
| `get_me`             | 当前 DID 用户完整 Profile                   |
| `update_me`          | 更新 display name、avatar、bio、profile_md |
| `get_public_profile` | 通过 DID 或 handle 获取公开 Profile          |
| `resolve`            | 返回 DID service endpoints              |

现有 DID Profile 的字段体系包括 DID、handle、display_name、avatar、description、profile_md、profile_uri、subject_type 和 service_endpoints；开源版应复用这套字段，避免客户端适配成本。

#### 兼容 Auth API

为了兼容旧客户端、nginx auth_request 和本地测试工具，只保留不涉及手机/邮箱验证的本地 token / ticket 兼容。手机、邮箱、phone-bind 和 `send_otp` 类接口不属于 v0.1 MVP，默认返回 `contact_verification_not_enabled` 或标准 `not_supported`；只有显式设置本地兼容开关时才作为 dev shim 暂时可用。

| 路径                         | MVP 行为                          |
| -------------------------- | ------------------------------- |
| `POST /auth/sms-codes`     | 默认未启用；不发送短信，不生成验证流程 |
| `POST /auth/sms`           | 默认未启用；不通过手机号登录/注册 |
| `POST /auth/email-send`    | 默认未启用；不发送邮件 |
| `GET /auth/email-status`   | 默认未启用；不声明邮箱已验证 |
| `POST /auth/token-refresh` | refresh token 轮换                |
| `GET /auth/token-verify`   | 返回 `X-User-Id` / DID 校验结果       |
| `POST /ws/tickets`         | 可选，给旧 WS 认证使用                   |
| `GET /ws/tickets/verify`   | 可选                              |

现有用户服务文档里，短信、邮箱、token-refresh、token-verify 是认证流程的一部分；Community MVP 只采用 DID 注册和本地 token，不实现短信/邮箱登录。旧 CLI 当前注册命令可能仍要求传 `--phone/--otp`，但本仓 `did-auth.register` 只根据 DID document、handle 和本地状态注册，不验证手机号、不发送 OTP、不保存手机号绑定。

#### Agent 注册与 Message Agent

建议支持最小子集：

| endpoint                               | method               | MVP 行为                                              |
| -------------------------------------- | -------------------- | --------------------------------------------------- |
| `/user-service/agent-registration/rpc` | `issue_token`        | 签发一次性本地 agent registration token                    |
|                                        | `verify_token`       | 预检 token                                            |
|                                        | `exchange_token`     | 注册 daemon/runtime agent DID                         |
|                                        | `revoke_token`       | 撤销未使用 token                                         |
| `/user-service/message-agent/rpc`      | `ensure_binding`     | 创建 human DID、daemon DID、runtime agent DID 的 binding |
|                                        | `get_active_binding` | 查询 active binding                                   |
|                                        | `list_bindings`      | 列表                                                  |
|                                        | `disable_binding`    | 暂停                                                  |
|                                        | `mark_seen`          | daemon 上报 last_seen                                 |
|                                        | `revoke_binding`     | Phase 2 或最小实现                                       |

现有 agent registration token 设计要求 token 原文只返回一次，数据库只保存 hash，一次性、可过期、可撤销；这些规则适合直接复用到开源版。

### 3. 消息 API

#### `/im/rpc` 与 `/anp-im/rpc`

`/im/rpc` 是客户端本域入口，`/anp-im/rpc` 是 DID 文档中 `ANPMessageService.serviceEndpoint` 指向的公开跨域入口。Community 版不做 federation runtime，但必须保留 `/anp-im/rpc`，否则 `awiki-cli-rs2` 默认的 `anp_service_endpoint` 和跨域 DID 发现链路会不兼容。

必须支持的 JSON-RPC 方法：

| 类别           | method                           | MVP 支持                                         |
| ------------ | -------------------------------- | ---------------------------------------------- |
| Capability   | `anp.get_capabilities`           | 返回 Community 能力声明                              |
| Direct       | `direct.send`                    | 仅 `anp.direct.base.v1` + `transport-protected`；支持本域和跨域直连 |
| Direct WS 通知 | `direct.incoming`                | 服务端下行 notification                             |
| Direct 本地视图  | `inbox.get`                      | 收件箱                                            |
|              | `inbox.mark_read`                | 旧消息 id 已读                                      |
|              | `direct.get_history`             | 私聊历史                                           |
| Read state   | `read_state.mark_read`           | thread-level read watermark                    |
| Sync         | `sync.delta`                     | 账号级事件增量                                        |
|              | `sync.thread_after`              | thread 级补新                                     |
| Group participant | `group.get_info`             | 查看已有群公开/成员可见信息                                |
|              | `group.join`                     | 加入已有 open-join 或 invite-token 群；不创建群             |
|              | `group.leave`                    | 当前用户退出群                                        |
|              | `group.send`                     | 已加入成员发送普通明文群消息                                |
| Group local  | `group.get`                      | 本地群详情                                          |
|              | `group.list`                     | 当前用户已加入群列表                                     |
|              | `group.list_members`             | 成员列表                                           |
|              | `group.list_messages`            | 群消息                                            |
| Group WS 通知 | `group.incoming`                 | 群消息下行                                          |
|              | `group.state_changed`            | 加入/退出等成员可见状态变化下行                              |
| Attachment   | `attachment.create_slot`         | 创建上传 slot                                      |
|              | `attachment.commit_object`       | 提交对象                                           |
|              | `attachment.abort_object`        | 取消对象                                           |
|              | `attachment.get_download_ticket` | 下载票据                                           |

现有 dispatcher 已经把 direct、group、sync、read_state、attachment 方法集中在一个分发器里。开源版实现 direct、group participant、sync、read_state、attachment 子集；群创建和群管理方法保留标准 `not_supported` 响应，降低客户端适配成本。

`/anp-im/rpc` 公开跨域入口只建议暴露：

| method                           | 跨域行为 |
| -------------------------------- | -------- |
| `anp.get_capabilities`           | 返回 Community 能力、公开 profile、security profile、service DID |
| `direct.send`                    | 校验业务层 proof 和 hop-level HTTP Signature / DID WBA，写入本地 direct view 并推送本域收件人 |
| `group.get_info`                 | 可选公开已有群信息；必须受群公开策略限制 |
| `group.join`                     | 只允许 open-join 或 invite-token 加入；不允许创建群或远端 Group Host 管理 |
| `attachment.get_download_ticket` | 仅用于公开附件 manifest 的下载票据，必须基于原始消息发送者 DID 发现锚点和本地 access grant |

`/anp-im/rpc` 不暴露 `inbox.get`、`direct.get_history`、`sync.delta`、`sync.thread_after`、`read_state.mark_read`、`attachment.create_slot`、`attachment.commit_object`、`attachment.abort_object`、`group.create`、`group.add`、`group.remove`、`group.update_profile`、`group.update_policy` 或任何本域管理方法。

#### 跨域 Direct 服务边界

Community 版的“跨域服务”只表示：调用方可以解析目标 DID 文档，读取唯一公开的 `ANPMessageService`，使用其中的 `serviceEndpoint` 和 `serviceDid` 调用远端 `/anp-im/rpc`，并由目标服务校验业务主体 DID proof 与服务层 HTTP Signature / DID WBA。它不是 federation service。

必须支持：

| 能力 | MVP 行为 |
| --- | --- |
| DID 文档发布 | 本服务 DID 和本地用户 DID 文档包含唯一 `ANPMessageService` |
| `serviceDid` | 使用 bare-domain DID，例如 `did:wba:example.com`，作为跨域服务层认证身份 |
| 远端 DID 发现 | `direct.send` 外发前解析 recipient DID 的 `ANPMessageService` |
| 跨域直连发送 | 一次 HTTP 调用远端 `/anp-im/rpc`，成功则记录本地 sent / ack 状态 |
| 跨域接收 | `/anp-im/rpc` 接收远端 `direct.send`，验证 proof 后投递本地收件人 |

明确不做：

```text
federation.peer_routes
服务间 relay / forwarding mesh
远端 outbox retry queue
远端消息投影和对账
跨域最终确认协议
跨域 group host / group management
跨域 read-state ack
跨域 attachment upload delegation
```

#### 不支持但必须显式声明的消息方法

这些方法应返回标准 JSON-RPC `not_supported`：

```text
direct.e2ee.publish_prekey_bundle
direct.e2ee.get_prekey_bundle
group.e2ee.*
group.create
group.add
group.remove
group.update_profile
group.update_policy
object-e2ee attachment
federated direct forwarding
federated group host / management forwarding
federation.peer_routes
```

`anp.get_capabilities` 中应明确：

```json
{
  "edition": "community",
  "supported_security_profiles": ["transport-protected"],
  "direct_e2ee": {
    "enabled": false,
    "reason": "community_edition"
  },
  "group_e2ee": {
    "enabled": false,
    "reason": "community_edition"
  },
  "group_participant": {
    "enabled": true,
    "management": false,
    "supported_methods": [
      "group.get_info",
      "group.join",
      "group.leave",
      "group.send",
      "group.get",
      "group.list",
      "group.list_members",
      "group.list_messages"
    ]
  },
  "cross_domain_direct": {
    "enabled": true,
    "mode": "did_discovery_direct_call"
  },
  "federation": {
    "enabled": false,
    "reason": "no_peer_routes_or_relay"
  }
}
```

### 4. WebSocket API

建议默认：

```text
GET /im/ws
```

认证方式：

| 方式                                     | MVP      |
| -------------------------------------- | -------- |
| `Authorization: Bearer <did_jwt>`      | 必须支持     |
| HTTP Signatures / DID WBA Upgrade auth | 尽量支持     |
| query token                            | 可选，仅开发模式 |

WebSocket 下行 envelope 保持现有形态：

```json
{
  "jsonrpc": "2.0",
  "method": "direct.incoming",
  "params": {
    "meta": {},
    "auth": {},
    "body": {}
  },
  "sync": {
    "event_id": "sev_01",
    "event_seq": "12",
    "event_type": "message.created"
  }
}
```

现有 WebSocket 实现会在连接认证后注册 session，接收客户端 JSON-RPC，并向客户端推送 `ServerNotification`；notification envelope 支持顶层 `sync` 字段，开源版应该保持这个行为。

### 5. 附件 API

必须支持：

| API                              | 行为                                                 |
| -------------------------------- | -------------------------------------------------- |
| `attachment.create_slot`         | 分配 `slot_id`、`object_id`、upload token、commit token |
| `PUT /objects/upload/{slot_id}`  | 上传文件字节到本地目录                                        |
| `attachment.commit_object`       | 校验 size / sha256 digest，生成 object record           |
| `attachment.abort_object`        | 删除 slot / 临时文件                                     |
| `attachment.get_download_ticket` | 生成短期下载 ticket                                      |
| `GET /objects/{object_id}`       | Bearer ticket 下载                                   |

限制：

```text
encryption_info.mode 只支持 none
object-e2ee 返回 anp.attachment.encryption_policy_violation
附件存储默认本地 ./data/objects
```

现有附件协议已经定义 control-plane 四个方法和数据面 `PUT /objects/upload/{slot_id}`、`GET /objects/{object_id}`，并且当前 transport-protected 附件只接受 `encryption_info.mode = "none"`；开源版直接实现这个子集即可。

### 6. Pages API

#### `/content/rpc`

必须支持：

| method   | 行为                        |
| -------- | ------------------------- |
| `create` | 创建 Handle 级 Markdown page |
| `update` | 更新标题、正文、visibility        |
| `rename` | 修改 slug                   |
| `delete` | 删除                        |
| `list`   | 列表，不含 body                |
| `get`    | 详情，含 body                 |

公开访问：

```text
GET /content/{slug}.md
```

现有 Content Pages 是 Handle 级 Markdown 页面，RPC 在 `/content/rpc`，公开地址是 `{handle}.{domain}/content/{slug}.md`；方法包括 create、update、rename、delete、list、get。

#### `/site/rpc`

建议 Phase 2 支持，MVP 可以保留开关：

```text
AWIKI_ENABLE_SITE_PAGES=false
```

未来 Web 页面建议不要另起一套数据模型，而是在 Pages 模块上增加 renderer：

```text
Markdown source -> Markdown REST -> HTML renderer -> web page
```

这样既能保持现有 CLI 的 `page/site` 命令，又能扩展 Web 主页。

## 三、模块划分与技术架构

### 1. 技术栈

建议：

| 层                | 技术                                                 |
| ---------------- | -------------------------------------------------- |
| HTTP / WebSocket | FastAPI + Uvicorn                                  |
| JSON-RPC schema  | Pydantic v2                                        |
| DB               | SQLite + SQLAlchemy 2 async / SQLModel             |
| Migration        | Alembic 或轻量内置 migration runner                     |
| JWT              | PyJWT + cryptography                               |
| DID / proof      | 优先复用 `anp` Python 包；缺口用 cryptography 实现最小 verifier |
| 对象存储             | 本地 filesystem                                      |
| 任务队列             | 进程内 `asyncio.Queue`                                |
| 日志               | loguru 或 structlog                                 |
| 配置               | pydantic-settings                                  |
| 测试               | pytest + httpx + websockets                        |

现有 `user-service` 已经是 FastAPI + SQLModel 架构，且依赖 `anp==0.8.7`、PyJWT、cryptography 等；Community 版可以继承这个 Python 技术路线，但把 MySQL、Redis、短信、微信、邮件等外部依赖移除或保持未启用。v0.1 不引入阿里云、短信 SDK、邮件 SDK 或真实 contact verification provider。

### 2. 进程内架构

建议结构：

```text
awiki_open_server/
  app/
    main.py                 # FastAPI app factory
    settings.py             # 配置
    routes.py               # route mount
  shared/
    jsonrpc.py              # JSON-RPC request/response/error
    errors.py
    ids.py
    time.py
    security.py
  storage/
    db.py                   # SQLite engine/session/UoW
    models.py               # SQLAlchemy/SQLModel tables
    migrations.py
  identity/
    did_auth.py             # /did-auth/rpc
    did_resolver.py         # did:wba path resolve
    jwt_service.py
    user_service.py
    profile_service.py
    handle_service.py
    agent_registration.py
    message_agent.py
  messaging/
    rpc.py                  # /im/rpc /anp-im/rpc
    binding.py              # JSON-RPC binding + normalizer
    auth.py                 # hop auth
    capabilities.py
    direct.py
    group_participant.py   # join/leave/send/list only; no group admin
    cross_domain.py         # DID discovery + direct cross-domain call
    attachments.py
    sync.py
    read_state.py
    websocket.py
    projections.py
  pages/
    content.py
    site.py
    renderer.py
  object_store/
    local_fs.py
    tickets.py
  admin/
    health.py
    seed.py
```

### 3. 请求流水线

开源版保留现有 message-service 的架构思想，但简化实现：

```text
HTTP / WS
  -> JSON-RPC Binding
  -> Normalizer
  -> Hop Auth：DID JWT / DID WBA / HTTP Signature
  -> Capability / Admission
  -> Domain Service：identity / direct / group_participant / cross_domain / attachment / pages / sync
  -> SQLite transaction
  -> local outbox_events
  -> WebSocket notifier
```

现有架构明确要求所有外部方法先进入 Binding / Normalizer，权威状态变更在事务内完成，异步下推通过 outbox；Community 版应保留这些正确性原则，只把 PostgreSQL + 远端 outbox 简化成 SQLite + 本地通知 outbox。

### 4. 数据库表建议

#### Identity

```text
users
accounts
sessions
refresh_tokens
did_documents
handles
profiles
agent_registration_tokens
message_agent_bindings
event_history
```

#### Messaging

```text
direct_messages
direct_message_views
direct_inbox
conversations
groups                  # 已知群投影，不负责创建/托管跨域 Group Host
group_members           # 本服务可见成员投影
group_messages
thread_read_states
sync_events
sync_event_cursors
```

#### Attachments

```text
attachment_slots
attachment_objects
attachment_access_grants
download_tickets
```

#### Pages

```text
content_pages
site_pages
```

#### Runtime

```text
outbox_events
ws_sessions  # 内存为主，表可选
```

SQLite 必须开启：

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
```

关键唯一约束：

```text
did_documents.did unique
handles.full_handle unique
direct_messages.message_id unique
direct_message_views(owner_did, message_id) unique
groups.group_did unique
group_members(group_did, member_did) unique
group_messages(group_did, message_id) unique
sync_events(owner_subject_id, event_seq) unique
attachment_objects.object_id unique
content_pages(handle_id, slug) unique
```

### 5. Capability 设计

`anp.get_capabilities` 是商业引导的关键，不要让客户端“试了才失败”。建议返回：

```json
{
  "service_did": "did:wba:example.com",
  "edition": "community",
  "supported_profiles": [
    "anp.core.binding.v1",
    "anp.direct.base.v1",
    "anp.group.base.v1",
    "anp.attachment.v1",
    "anp.sync.local.v1",
    "anp.read_state.local.v1",
    "anp.direct.local.v1"
  ],
  "supported_security_profiles": ["transport-protected"],
  "transports": ["http", "ws"],
  "features": {
    "cross_domain_direct": {
      "enabled": true,
      "mode": "did_discovery_direct_call"
    },
    "group_participant": {
      "enabled": true,
      "management": false,
      "join_modes": ["open_join", "invite_token"],
      "supported_methods": [
        "group.get_info",
        "group.join",
        "group.leave",
        "group.send",
        "group.get",
        "group.list",
        "group.list_members",
        "group.list_messages"
      ]
    }
  },
  "limits": {
    "max_attachment_bytes": "10485760",
    "max_joined_groups_per_user": "20",
    "max_content_pages_per_handle": "5"
  },
  "disabled_features": {
    "direct_e2ee": "commercial",
    "group_management": "commercial",
    "group_e2ee": "commercial",
    "federation": "commercial",
    "managed_runtime_agents": "commercial",
    "tenant_site_hosting": "commercial"
  }
}
```

现有 direct capability 文档已经要求返回 service DID、supported profiles/security profiles/content types、transports、limits、proof policies、direct_e2ee 信息；Community 版应该复用这一结构，只是明确 E2EE、group management 和 federation disabled。跨域 direct 是可用能力，但不应伪装成新的标准 ANP profile；建议放在 `features.cross_domain_direct` 中，表示 DID 发现后对远端 `ANPMessageService` 的一次性直连调用。

### 6. 跨域配置最小集

为了让外部 DID 能发现并调用本服务，至少需要这些配置：

| 配置 | 示例 | 说明 |
| --- | --- | --- |
| `AWIKI_PUBLIC_BASE_URL` | `https://open.example.com` | 公开可访问基地址，不使用本地监听地址 |
| `AWIKI_SERVICE_DID` | `did:wba:example.com` | bare-domain service DID，用于跨域服务层认证 |
| `AWIKI_ANP_PUBLIC_RPC_PATH` | `/anp-im/rpc` | 写入 DID 文档的 `ANPMessageService.serviceEndpoint` 路径 |
| `AWIKI_IM_RPC_PATH` | `/im/rpc` | 本域用户 RPC，不暴露 local-only 方法到公开入口 |
| `AWIKI_DID_DOMAIN` | `example.com` | 本地 DID / Handle 默认域 |

生成的 DID 文档必须只暴露一个公开 `ANPMessageService`，`serviceEndpoint = AWIKI_PUBLIC_BASE_URL + AWIKI_ANP_PUBLIC_RPC_PATH`，`serviceDid = AWIKI_SERVICE_DID`。不要把内部端口、临时路径、多个拆分服务入口或 federation peer route 写入 DID 文档。

## 四、推荐实施顺序

### Phase 0：兼容骨架

目标：客户端能连上，但大多数方法可以先返回标准 not_supported。

交付：

```text
FastAPI app
SQLite 初始化
/healthz
/did-auth/rpc skeleton
/did/profile/rpc skeleton
/im/rpc
/anp-im/rpc
/im/ws
JSON-RPC error 格式
anp.get_capabilities
```

### Phase 1：身份 + 私聊 + Pages

目标：`awiki-cli id register`、`msg send --to`、`msg history`、`page create/list/get` 能跑通。

交付：

```text
DID register / verify / JWT
Profile get/update/public
Direct send
Direct history
Inbox
WebSocket direct.incoming
sync.delta
sync.thread_after
content pages
```

### Phase 2：跨域 Direct + 群参与 + 附件 + Read State

目标：跨域明文私聊、加入已有群和文件消息可用，但不启用 federation runtime，也不提供群创建/管理。

交付：

```text
ANPMessageService DID document
serviceDid / serviceEndpoint
remote DID discovery
cross-domain direct.send outgoing
cross-domain direct.send incoming on /anp-im/rpc
group.get_info / group.join / group.leave
group.send
group.list / group.get / group.list_members / group.list_messages
group.incoming / group.state_changed
attachment slot/upload/commit/ticket/download
read_state.mark_read
```

### Phase 3：Agent 与商业引导

目标：让智能体场景完整展示，但不开放商业运行时核心。

交付：

```text
agent-registration minimal
message-agent binding minimal
daemon last_seen
capabilities disabled_features
标准 upgrade error
Docker Compose / uv quickstart
awiki-cli smoke test
awiki-me smoke test
```

## 五、最终建议

MVP 的切入点应是：

```text
DID 注册 + 明文私聊 + 跨域 Direct 服务 + 加入已有群 + WebSocket 实时通知 + 附件 + Markdown Pages
```

不要先做群创建/管理、E2EE、联邦服务、多租户、邮件、积分或生产认证。开源版的价值不是“功能少的商业版”，而是一个**能自托管、能被 Agent 和客户端真实调用、能展示 ANP / Awiki 协议体验的 Community Server**。商业版则提供：

```text
安全：Direct E2EE / Group E2EE
互通：federation peer routes、relay、远端重试、最终确认、跨域群组
群能力：群创建、群成员管理、群资料/策略管理、Group Host 托管
托管：多租户、自定义域名、SLA、备份、监控
运营：风控、短信/微信/邮箱、积分、审计
智能体：托管 runtime、Message Agent 编排、企业级 delegated key 管理
```

这样既能让开发者真实跑起来，也能把核心能力自然导向商业化版本。
