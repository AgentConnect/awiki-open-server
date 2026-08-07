# Awiki Open Server 最新协议与 API 对齐计划

状态：执行中（协议/API 基础与单设备 Sync v2 wire compatibility 已落地，最新 CLI 当前本地旅程 Gate 已通过）  
创建日期：2026-08-07  
目标仓库：awiki-open-server  
计划性质：兼容性迁移与协议收敛，不扩展产品功能范围

## 1. 目标与结论

本计划用于把 awiki-open-server 的协议、API、能力发现、安全校验和兼容路由，对齐到当前 User Service、Message Service 与 ANP 仓库的最新规范和实际实现。

本次调整只改变“如何表达、调用和验证现有能力”，不改变 Open Server 的功能边界：

- 保留单进程、SQLite、本地对象存储、小规模 Community Group、明文 Direct、明文 Group、基础附件、单设备本地同步与已读状态。
- 保留通过 DID 发现、HTTP Message Signature、持久化 outbox 和本地 projection 完成的 Direct/Group 跨域互操作。
- 不引入手机或邮箱真实验证、阿里云依赖、托管租户能力、多设备账户同步、HA、大群高并发 fanout、联邦 relay/peer-route mesh。
- 不实现 Direct E2EE、Group E2EE、secure-message、prekey、ratchet 或加密附件。相关 profile、方法和安全组合必须不发布，并明确返回 not_supported。
- ANP P4 入组继续只支持立即生效的 group.join 与 group.add；不引入邀请、邀请码、join token、join code、pending membership 或审批流程。

核心迁移判断如下：

1. ANP Messaging 1.2 是“混合 profile 版本”，不是普通消息协议整体升级到 v2。普通 Direct、Group、Attachment 与 Federation 仍使用 v1；只有不在 Open Server 范围内的 P5/P6 E2EE 使用 v2。
2. User Service 的规范化入口已收敛为 /user-service/v1/...。Open Server 只为现有兼容能力增加 canonical v1 路由，旧路由继续作为同一 handler 的兼容别名；不会借路由对齐之名补齐 User Service 的新产品能力。
3. ANP 公网入口必须立即按严格 P1 envelope、请求 ID、notification、错误模型、安全主体与 origin proof 规则校验。现有本地入口采用阶段性 dual-read，给旧的 flat params 调用一个可观测、可关闭的迁移窗口。
4. Direct/Group 的 canonical 调用即使发生在本机，也必须满足规范要求的 origin proof；不能继续把“本地调用”当成免 proof 的协议例外。
5. Group Host、projection、outbox 应成为标准 Group 的唯一事实来源；旧 participant 表只能迁移或作为只读兼容来源，不能继续形成第二套可写状态机。
6. SDK 统一升级到 anp==0.9.2。当前 Open Server 实际 pin/运行时检查为 0.8.9，而仓库指南仍写 0.8.8；实现阶段应一并修正文档漂移。
7. `anp.sync.local.v2` 仅实现最新 CLI 所需的单设备拉取 wire contract：一个 DID 只能绑定一个设备和一个 client instance；它不是 Message Service 的多设备同步实现。

## 2. 参考基线与规范优先级

### 2.1 已核实的基线

| 来源 | 分支/版本 | 已核实提交 | 用途 |
| --- | --- | --- | --- |
| awiki-open-server | main | 527875f | 当前实现与兼容面 |
| user-service | release/0714 | 8769c22 | User Service canonical 路由、contract header、兼容策略 |
| message-service | release/0714 | 1258856 | 当前 Message API、能力发布、路由与安全矩阵 |
| ANP 规范 | main | 9789640 | P1–P8 规范、混合 profile 版本策略 |
| ANP Python SDK | 0.9.2 / master | tag commit 28e29d9；master 3db6ee8 | SDK API、签名、DID、receipt proof、WNS binding |
| awiki-cli-rs2 | release/0714 | 3200847d | 最新 CLI 路由、profile、客户端版本 Header 与真实用户命令 |
| API 版本治理计划 | main | awiki-plan b491914 | User Service URL 版本与 Message profile 版本的冻结规则 |

以上仓库在计划调研时均已与对应远端同步并确认工作区无本地修改。

### 2.2 冲突时的判定顺序

不同仓库目前存在少量文档、代码和历史兼容实现不一致的情况。实现阶段按以下顺序判定：

1. 本仓库的产品边界：本计划、AGENTS.md、require.md 和用户明确要求。
2. ANP 主干的当前规范与 profile 定义。
3. User Service、Message Service 当前分支的代码、contract 定义和自动化测试。
4. User Service、Message Service 的说明文档；仅在其与前述规范和当前代码一致时采用。
5. Open Server 当前行为；只作为兼容输入和数据迁移依据，不反向定义新 canonical 协议。

已知需要按此优先级处理的漂移：

- Message Service 部分旧文档仍提到 direct.base.v2 或 attachment.v2，但当前 ANP 规范和 Message Service 代码已经回退并固定普通 Direct/Attachment 为 v1。
- User Service 历史 group 文档存在邀请码和邀请流程，但 Open Server 的 P4 边界明确禁止这些语义。
- 本仓库 AGENTS.md 写 anp==0.8.8，pyproject.toml 与 protocol/anp_adapter.py 实际要求 0.8.9；目标版本应统一为 0.9.2。

## 3. 固定范围与非目标

### 3.1 本次保留并对齐的能力

- ANP core binding、DID discovery 和 runtime capabilities。
- 明文 direct.send 与本地 Direct inbox/history。
- Community Group 的创建、查询、立即加入、立即添加、移除、离开、资料与策略更新、发消息、成员 DID rebind。
- Group Host、成员 projection、持久化 outbox、跨域标准通知。
- 附件 create_slot、对象上传、commit、abort、download ticket 和对象下载。
- 本地 inbox、sync delta、thread history、read state、WebSocket realtime dirty hints。
- 当前已有的 User Service 身份、profile、handle、关系、个人 Agent、content、site、group compatibility facade。
- 现有 REST 兼容入口和公共 DID、站点、内容读取入口。

### 3.2 明确不进入本计划的能力

- Direct/Group E2EE v2 和所有相关密码学消息流程。
- object encryption mode 非 none 的附件。
- 多设备 device registry、设备间共享/复制、一个 DID 绑定多个设备，以及 sync v2 snapshot/recovery/fanout。
- User Service 的真实短信、邮件、微信验证，账号找回、生产 push、credits 或托管运行时。
- P4 邀请、邀请码、join token、pending member、审批入组。
- federation relay 服务、peer-route mesh、独立 relay wrapper。
- 高可用、多副本一致性、大规模 fanout、外部消息队列。

新增 canonical 路由或 canonical 字段不代表新增上述能力。对超范围方法应使用稳定的 not_supported 错误，而不是创建半实现状态。

## 4. 目标 profile 与能力发布

### 4.1 标准 profile

Open Server 的公共 ANP Message Service 静态 DID 文档和 runtime capabilities 只发布实际支持的标准 profile：

- anp.core.binding.v1
- anp.identity.discovery.v1
- anp.direct.base.v1
- anp.group.base.v1
- anp.attachment.v1
- anp.federation.relay.v1

说明：

- anp.federation.relay.v1 是当前 P8 保留的标准 profile 名称。Open Server 的具体跨域模式仍是 did_discovery_direct_call，不实现独立 relay 或 peer-route mesh。
- 不发布 anp.direct.e2ee.v2、anp.group.e2ee.v2、普通 base.v2 或 attachment.v2。
- authSchemes 可以作为历史兼容扩展保留，但不得作为标准 service selection 的必要字段。规范选择应基于 profiles、securityProfiles、serviceDid 和 runtime capabilities。

### 4.2 本地 profile

以下 profile 只在本地受信入口的 runtime capabilities 中发布，不出现在公共跨域能力清单中：

- anp.inbox.local.v1
- anp.direct.local.v1
- anp.group.local.v1
- anp.sync.local.v1
- anp.sync.local.v2（仅单 DID/单设备拉取兼容子集）
- anp.read_state.local.v1

`anp.sync.local.v2` 只发布在本地 bearer 入口，支持 `sync.bootstrap` 的 `tail_only`、`sync.delta`、`message.get_batch` 和 `sync.thread_after`。首次游标从保留流的 `0` 开始，让唯一设备拉取本地账户事件；不支持 `sync.snapshot`、compact recovery、设备间共享、多设备游标合并或一个 DID 多设备。第二个 device/client instance 必须返回稳定 `not_supported`。WebSocket 通知仍只是 HTTP 同步与历史 API 的 dirty hint，不是数据事实来源。

### 4.3 能力响应要求

anp.get_capabilities 应返回真实运行态能力，且优先级高于 DID 文档中的静态提示。至少包括：

- service_did、profiles、security_profiles、transports。
- 每个方法所属 profile、请求或 notification 类型、允许入口、主体类型和 proof 要求。
- Direct/Group 跨域模式 did_discovery_direct_call。
- Attachment 上传、下载与 https_only 的真实配置状态。
- E2EE、relay mesh、HA、多设备和 encrypted attachment 为 disabled/not_supported。
- 支持的 vendor extension 必须逐项发布；未发布的扩展不得影响标准成功判定。

新写出的 meta 不再主动携带已废弃的 messaging/anp version 字段；读取历史数据时继续容忍旧字段。

### 4.4 API、协议与客户端版本的分层规则

版本信息包含 API 选版、profile 选版和客户端产品版本，并辅以诊断 Header；这些层必须分别表达，不能互相替代：

| 版本层 | canonical 表达 | 选版规则 | Open Server 目标 |
| --- | --- | --- | --- |
| User Service 产品 API | URL 路径 /user-service/v1/... | URL 中的 /v1 是唯一 API 版本来源 | 新客户端只使用 /v1；旧无版本路径是服务端单边 alias |
| Message/ANP wire contract | meta.profile，例如 anp.direct.base.v1 | profile 名称决定请求和结果 schema | /im/rpc 与 /anp-im/rpc 路径保持稳定，不新增 /im/v1/rpc |
| 本地 Message contract | meta.profile，例如 anp.sync.local.v1 | local profile 决定本地请求 schema | 继续复用 /im/rpc；不以 URL 或额外 api_version 字段选版 |
| 客户端产品版本 | X-AWiki-Client-Version | 只用于兼容观测与策略，不选择 API/profile | 接受、校验安全格式并记录；不得修改协议语义 |
| User Service 响应 contract | X-API-Contract: user-service.v1 | 只用于诊断，不参与选版 | canonical 与 legacy alias 响应均返回一个该 Header |

冻结规则：

- 不增加 api_version、protocol_version 或 version 请求字段作为第四个版本来源。
- JSON-RPC method 名称不增加 .v1 后缀；版本由 meta.profile 决定。
- /im/rpc、/im/ws、/anp-im/rpc 和对象数据面路径保持当前稳定名称。Message API 的版本号体现在 profile，而不是 URL。
- User Service 未来发生破坏性变化时新增 /user-service/v2/...，不得原地改变 /user-service/v1 的语义。
- Message profile 未来发生破坏性变化时新增新的 profile 名称，并通过 capabilities 协商；不能让同一个 profile 名称同时代表两套 schema。
- X-API-Contract 和 X-AWiki-Client-Version 都不是协议选版开关。
- 最新 CLI 的 X-AWiki-Client-Version 格式固定为 product/release/version[+build]，其中 product 为 awiki-cli、awiki-me 或 awiki-daemon。Open Server 对 User/Message 产品入口允许该 Header，保证每个请求最多一个，并只记录低基数版本信息。
- 公共 ANP peer 请求、DID 解析请求和对象上传/下载不依赖客户端产品版本 Header；该 Header 不进入 HTTP Signature、origin proof 或业务授权。

## 5. 目标 API 面

### 5.1 路由分层

| 路由 | 可见性 | 主要主体 | 目标行为 |
| --- | --- | --- | --- |
| /anp-im/rpc | 公网 ANP | anonymous 或已验证 peer service | 稳定无版本路径；从第一阶段起严格 P1，由 meta.profile 选协议版本 |
| /im/rpc | 本地消息入口 | bearer 对应的本地 DID | 稳定无版本路径；由 meta.profile 选版本，迁移期只对本地主体 dual-read 旧 flat params |
| /im/ws | 本地实时入口 | bearer 或短期 WS ticket 对应的本地 DID | 稳定无版本路径；profile 决定事件 contract，只发送通知和 dirty hint |
| /group/rpc | 旧本地兼容入口 | 本地 bearer DID | 复用标准 Group handler 的 legacy adapter |
| /user-service/group/rpc | 旧 User Service 兼容入口 | 现有身份规则 | 复用同一 Group domain handler，不引入邀请码语义 |
| /user-service/v1/... | User Service canonical 兼容入口 | 按现有功能的 bearer/匿名规则 | 只映射 Open 已支持的能力，返回 user-service.v1 contract header |
| /objects/upload/{slot_id} | 对象上传 | slot capability/token | 保持数据面路由，控制面按 P7 |
| /objects/{object_id} | 对象下载 | download ticket | 保持数据面路由，校验 ticket 与授权绑定 |

原则：

- canonical 与 legacy route 只允许有一份 domain handler 和一份持久化写路径。
- 旧路由隐藏于 OpenAPI schema，但保留调用；canonical 路由进入 OpenAPI。
- 公网 ANP 不接受 legacy flat params，不做静默补字段或安全降级。
- 本地 legacy adapter 必须位于协议边界，转换后再进入 canonical command；domain 层不感知两套协议。

### 5.2 公网 /anp-im/rpc 方法矩阵

| 方法 | 类型 | 主体/认证 | 额外安全要求 |
| --- | --- | --- | --- |
| anp.get_capabilities | Request | anonymous 或 peer | 完整 P1 envelope；不要求 origin proof |
| direct.send | Request | 已验证 peer service | P3 origin proof 必须有效 |
| group.create | Request | 已验证 peer service | P4 origin proof；target.kind=service |
| group.get_info | Request | anonymous 或 peer，按 group policy 限制 | target.kind=group |
| group.join | Request | 已验证 peer service | P4 origin proof；立即 active |
| group.add | Request | 已验证 peer service | P4 origin proof；立即 active |
| group.remove | Request | 已验证 peer service | P4 origin proof |
| group.leave | Request | 已验证 peer service | P4 origin proof |
| group.update_profile | Request | 已验证 peer service | P4 origin proof |
| group.update_policy | Request | 已验证 peer service | P4 origin proof |
| group.send | Request | 已验证 peer service | P4 origin proof |
| group.rebind_member | Request | 已验证 peer service | 新 DID-auth proof 与 WNS generation 校验 |
| group.incoming | Notification | 已验证 peer service | P4 receipt proof；不得返回 JSON-RPC Response |
| group.state_changed | Notification | 已验证 peer service | P4 receipt proof；不得返回 JSON-RPC Response |
| attachment.create_download_ticket | Request | 已验证 peer service | P7 授权与 authoritative sender discovery |

下列方法不得公开：

- 本地 inbox/history/sync/read state。
- attachment create_slot、commit_object、abort_object。
- User Service compatibility RPC。
- 内部 outbox 管理和 projection 修复方法。

E2EE 与加密附件相关方法保持封闭 deny registry，返回稳定 not_supported；不发布为 capability。

### 5.3 本地 /im/rpc 方法矩阵

本地入口保留标准消息命令和本地读取能力：

- 标准：anp.get_capabilities、direct.send、P4 Group 请求方法、P7 Attachment 四个方法。
- 本地读取：inbox.get、inbox.mark_read、direct.get_history、group.get、group.list、group.list_members、group.list_messages。
- 同步与已读：sync.delta、sync.thread_after、read_state.mark_read。

本地安全规则：

- meta.sender_did 必须与 bearer principal 的 DID 一致。
- 本地读取方法 body.user_did 若存在，也必须与 bearer principal 一致。
- Direct/Group 的变更和 send 即使目标在本机，也必须验证规范 origin proof。
- P7 不额外要求 origin proof，但必须验证 bearer、target、slot/commit/ticket capability。
- 本地 client/device selector 是本地路由提示，不得转发到 peer，不得进入跨域签名内容。

### 5.4 User Service canonical 路由

只为 Open Server 已经支持的 compatibility handler 增加以下 canonical 别名：

- /user-service/v1/did-auth/rpc
- /user-service/v1/agent-registration/rpc
- /user-service/v1/agent-inventory/rpc
- /user-service/v1/personal-agent/rpc
- /user-service/v1/did/profile/rpc
- /user-service/v1/me/rpc
- /user-service/v1/relationships/rpc
- /user-service/v1/did/relationships/rpc
- /user-service/v1/handle/rpc
- /user-service/v1/users/rpc
- /user-service/v1/group/rpc
- /user-service/v1/content/rpc
- /user-service/v1/site/rpc
- 与当前 Open 功能等价的 profile/handle 公共读取路由

具体路由在实现前通过 User Service 的 api_contract.py 与 route tests 生成一份固定 snapshot，防止手工遗漏。

兼容策略：

- canonical 与旧路由调用相同 handler。
- canonical 和等价旧 RPC 响应增加 X-API-Contract: user-service.v1。
- 旧 /user-service/message-agent/rpc 保留，canonical 名称使用 personal-agent。
- 不增加 body.api_version 或强制请求版本 Header；URL 中的 /v1 是唯一 User Service API 选版来源。
- 接受最新 CLI 发送的单个 X-AWiki-Client-Version，只用于观测；缺少该 Header 不改变 User Service v1 的协议解释。
- 不创建 account-state、push、credits、真实验证、账号恢复、完整 DID REST 生命周期等 Open Server 不具备的 handler。
- 历史 group 邀请和 join-code 方法明确 not_supported，不因 /user-service/v1/group/rpc 的存在而启用。

## 6. P1 JSON-RPC 与协议边界

### 6.1 严格请求模型

canonical ANP 请求必须满足：

- 顶层为单个 JSON-RPC 2.0 object；batch 返回 1004 / anp.batch_not_supported。
- params 必须是 object；array 或其他类型返回 1003 / anp.invalid_params_shape。
- Request id 必须是非空 string；number、null 或空 string 返回 1000 / anp.invalid_request_id。
- Notification 不携带 id，只允许用于规范声明的一向推送方法。
- params 形状为 meta、可选 auth、body；默认 closed，profile 明确允许时才能有扩展字段。
- meta.profile、security_profile、sender、target、operation_id、message_id、content_type 按方法矩阵严格要求。
- 服务端不得为 canonical mutation 静默生成 operation_id 或 message_id。

### 6.2 错误与 HTTP 状态

- JSON parse error、invalid request、method not found、invalid params、internal error 保留 JSON-RPC 标准负数 code。
- ANP 业务/安全错误使用 1000+ code，并在 error.data.anp_code 提供稳定机器码。
- User Service compatibility RPC 继续使用其自身 contract，不被强制转换为 ANP 错误码。
- 普通 JSON-RPC 业务错误使用 HTTP 200。
- 会话或认证失败按 Message Service 当前兼容约定返回 HTTP 401，同时保留 JSON-RPC error body。
- 合法 Notification 成功不返回 JSON-RPC Response；HTTP 使用 204。
- 无法回复的非法 Notification 只通过 HTTP 状态、结构化日志和指标记录，不伪造带 id 的 Response。

### 6.3 单一方法注册表

建立集中式 method registry，至少声明：

- method 名称与 profile。
- Request 或 Notification。
- local/public 可见性。
- anonymous、local bearer、peer service 等主体类型。
- target.kind 与 target DID 规则。
- 是否要求 origin proof、receipt proof、WNS binding。
- handler 和 request/result schema。

路由 allowlist、capabilities 输出、安全校验和测试参数化均从此 registry 派生，避免四份名单继续漂移。

## 7. P2 DID 发现与 P8 跨域安全

### 7.1 DID 文档与 endpoint 选择

- 每个 DID 文档只公开一个有效的 ANPMessageService。
- 静态服务信息包含 serviceDid、profiles、securityProfiles 与 endpoint。
- endpoint 选择先验证 DID document，再请求匿名 runtime capabilities；运行态 profile 是最终依据。
- 继续保留 endpoint 缓存、过期与失败重试，但 profile 或 serviceDid 不匹配时不得回退到猜测路由。
- 保留并强化 SSRF 防护、私网地址策略、重定向限制、DNS rebinding 防护和响应大小限制。

### 7.2 HTTP Message Signature

- peer 请求必须验证 RFC 9421 HTTP Message Signature 和 Content-Digest。
- 调用者 serviceDid 从已验证 keyid/DID 文档得出，不能由 x-anp-source-service-did 等提示 header 决定。
- 提示 header 可以用于日志关联，但不参与身份或授权判断。
- signature base 必须使用规范化的真实 public request URL；反向代理部署要有明确可信 proxy 配置。
- P8 caller anchor 按方法确定：
  - 普通请求使用 meta.sender_did。
  - Group notification 使用 body.group_did。
  - Attachment ticket 使用从 authoritative message sender 解析出的 Home service。
- public principal、origin proof principal 与业务 sender 必须三方一致。

### 7.3 客户端私有字段

client、device selector、local routing hint：

- 只允许出现在本地 binding。
- 不转发到远端。
- 不参与远端 payload digest 或 HTTP Signature。
- 不持久化为对等协议事实。

## 8. P3 Direct 对齐

### 8.1 canonical direct.send

要求：

- profile 为 anp.direct.base.v1。
- auth.scheme 为 anp-rfc9421-origin-proof-v1。
- 本地和跨域调用均验证 origin proof。
- body 在 text、payload、payload_b64u 中恰好选择一个。
- 可选 conversation_id、reply_to_message_id、annotations 按 closed schema 验证。
- meta 包含 agent target、operation_id、message_id、content_type。

标准成功结果只以以下字段判定：

- accepted=true。
- message_id、operation_id 与请求一致。
- target_did 正确。
- accepted_at 存在且有效。

final_acceptance 和 conversation_ref 属于 AWiki vendor extension。只有 endpoint 明确发布对应扩展时才读取；缺少或为 false 不能推翻标准 accepted 结果。

### 8.2 收件、幂等与本地通知

- 收件写入以 sender + operation_id 和 message_id 共同防重。
- 相同 operation_id、相同 canonical digest 返回第一次结果。
- 相同 operation_id、不同 digest 返回稳定冲突错误。
- 数据落库成功后才返回 accepted。
- 本地 WebSocket direct.incoming 采用 Notification 形状，并保留经过验证的 meta/body/auth。
- daemon heartbeat 等既有行为若保留，只能声明为本地/vendor 扩展，不参与标准 peer success。

## 9. P4 Community Group 对齐

### 9.1 唯一状态机

标准 Group 的唯一可写事实来源应为：

- hosted group。
- hosted membership。
- group event log。
- local projection。
- durable outbox。

旧 groups/group_members 等 participant 兼容表不再拥有独立写状态机。迁移后：

- 新请求全部进入同一 Group Host/participant domain handler。
- 旧读取 API 从 projection 或兼容 view 读取。
- 旧数据只读回填到 hosted/projection，不能双写形成两个 sequence authority。

### 9.2 P4 语义

- group.create 的 target.kind=service，target.did=serviceDid。
- 其他 Group 方法 target.kind=group。
- group.join 和 group.add 成功后成员立即 active。
- profile/policy patch 使用 RFC 7386 merge patch 语义。
- group.rebind_member 验证新 DID-auth proof 和 WNS generation。
- 所有 mutation 与 group.send 在本地和公网都要求 origin proof。
- group.get_info 可按 public/listed policy 匿名读取。
- 禁止邀请、邀请码、pending 状态和审批。

### 9.3 sequence、通知与 outbox

- group_state_version 只在群状态或成员状态变化时增长。
- group_event_seq 在所有控制事件和消息事件上单调增长。
- 两者不得继续由同一个“消息序号”代替。
- group.incoming 和 group.state_changed 是标准 Notification，不要求 JSON-RPC acknowledgment body。
- outbox 以 HTTP 2xx/204 作为标准通知投递成功，保留重试、退避、死信和重启恢复。
- 不实现或发布 awiki.group.durable-fanout.v1/awiki.group.deliver，除非后续另立范围并完整实现其 contract。
- receipt proof、group DID、sender、event sequence 与目标 Home service 在入站时统一验证。

## 10. P7 Attachment 对齐

标准 profile 固定为 anp.attachment.v1。

### 10.1 控制面

- attachment.create_slot、commit_object、abort_object 仅本地调用。
- attachment.create_download_ticket 可由本地代理或已验证 peer service 调用。
- target.kind=service，target.did 必须与目标 serviceDid 一致。
- 不额外要求 origin proof，但仍按入口校验 local bearer 或 peer service。

canonical create_slot body：

- 调用方提供 attachment_id。
- expected_size 使用规范要求的字符串表达。
- expected_digest 为 alg=sha-256 与 value_b64u。
- mime_type、filename、intended_message_security_profile、intended_target。
- object_encryption_mode 只允许 none。

canonical commit body：

- attachment_id、slot/commit capability、实际 size、digest。
- object_encryption_mode 必须为 none。

canonical ticket body：

- 不接受调用者伪造 sender_did。
- 从已落库消息解析 authoritative sender 和发现锚点。
- message_target_did 与 group_did 按规范恰好选择一个。
- 必须校验持久化消息/附件关系、发送者、接收者或群成员授权。

### 10.2 数据面与兼容

- 继续使用 /objects/upload/{slot_id} 与 /objects/{object_id}。
- 旧 expected_sha256、平铺 ticket binding 等字段只由本地 legacy adapter 读取。
- canonical 响应只输出规范字段；必要兼容字段必须由 capability 声明。
- direct-e2ee/group-e2ee 与 object encryption 非 none 的组合统一返回 not_supported 或规范的 encryption policy error。

## 11. 本地 Inbox、Sync、Read State 与 Realtime

本地 API 保持单 DID、单设备语义，并对齐 Message Service 可复用的 v1 形状：

- anp.inbox.local.v1：inbox.get、inbox.mark_read。
- anp.direct.local.v1：direct.get_history。
- anp.group.local.v1：group.get/list/list_members/list_messages。
- anp.sync.local.v1：sync.delta、sync.thread_after。
- anp.sync.local.v2（单设备子集）：sync.bootstrap、sync.delta、message.get_batch、sync.thread_after；不含 sync.snapshot/recovery。
- anp.read_state.local.v1：read_state.mark_read。

约束：

- account event_seq 与 thread server_seq 是两个不同的水位，不能混用。
- read_state 使用 thread-local server_seq。
- Open Server 没有 Message Service v2 的账户 conversation_ref 和 device cursor；本计划不伪造这套能力。
- 若保留 peer_did/group_did selector，应在 Open contract 中明确为单 DID 兼容形式，并在 registry/capabilities 中如实表达。
- WebSocket 断线、漏通知或乱序时，客户端通过 sync/history 恢复；实时消息不承担 exactly-once。
- 不增加 presence、typing、离线 push 或多设备 fanout。

## 12. 数据库与迁移策略

### 12.1 总体原则

- 只做 additive migration，不破坏或删除旧表、旧列。
- 引入明确 schema version/migration ledger，避免继续仅靠分散的 ensure_column 推断状态。
- 迁移前要求 SQLite 一致性检查与可恢复备份。
- 每个回填步骤可重入、可断点继续，并记录完成水位。
- 先双读验证，后切单写；禁止长期双写两个 Group 状态机。

### 12.2 必需的数据调整

- operation idempotency 表记录 method、sender、operation_id、canonical request digest、result/error snapshot。
- Direct/Group message 保存标准 meta、security profile、origin proof 验证结论与 authoritative sender。
- Group event 分离 group_state_version 与 group_event_seq。
- 旧 participant group/member 数据回填 hosted group、hosted membership、event/projection；不存在的邀请字段不得生成。
- outbox 保存目标 Home serviceDid、endpoint snapshot、payload digest、重试状态；提示 header 不作为身份字段。
- Attachment 保存标准 digest 结构、message/security profile/target 授权绑定和 encryption mode=none。
- Sync/read-state 明确 account event_seq、thread server_seq 与 read watermark。

### 12.3 回滚

- 应用回滚版本必须能忽略新增表/列。
- canonical 写入的数据仍保持旧读取路径可见。
- 不尝试反向删除标准 event/proof/idempotency 数据。
- Group 写流量切换后若需回滚，只回滚 handler 路由；不得重新启用双主写入。必要时暂停 Group mutation，完成 projection 修复后再恢复。

## 13. 实施分阶段计划

### Phase 0：合同冻结、SDK 和测试夹具

改动目标：

- 保存 ANP P1/P2/P3/P4/P7/P8、User Service canonical route、Message Service capability 的最小 contract snapshot。
- 保存 API 版本来源矩阵，测试 User Service 只由 URL 选版、Message 只由 meta.profile 选版。
- 将 pyproject.toml、protocol/anp_adapter.py 和仓库说明统一到 anp==0.9.2。
- 验证 adapter 当前使用的 DID、HTTP signature、digest、receipt、WNS API 在 0.9.2 下的签名。
- 建立 method registry 的数据模型，但不切换业务流。

主要文件：

- pyproject.toml
- src/awiki_open_server/protocol/anp_adapter.py
- 新的 protocol contract/registry 模块
- tests/test_protocol_anp_sdk.py
- tests/fixtures/contracts/
- AGENTS.md 与相关开发文档中的版本说明

退出条件：

- SDK fail-fast 明确要求 0.9.2。
- adapter 单测全部通过。
- contract snapshot 有来源提交、profile 与更新时间，不复制整份上游实现。

### Phase 1：P1 binding、错误模型与入口矩阵

改动目标：

- 实现 strict decoder/validator、Notification 语义、batch 拒绝和 ANP error envelope。
- public/local/user-compat 三类 JSON-RPC binding 分离。
- registry 驱动 route、principal、profile、proof policy 与 capabilities。
- /anp-im/rpc 立即 strict；/im/rpc 开启仅限本地 bearer 的 legacy flat adapter。

主要文件：

- src/awiki_open_server/shared/jsonrpc.py
- src/awiki_open_server/protocol/
- src/awiki_open_server/app/routes.py
- src/awiki_open_server/app/middleware.py
- tests/test_messaging_surface.py
- 新增 P1 参数化测试

退出条件：

- P1 正反例矩阵通过。
- Notification 无 Response，Request id/params/batch 行为与规范一致。
- 公网入口无法触发 legacy normalization。

### Phase 2：User Service v1 canonical 路由

改动目标：

- 为现有 compatibility handler 增加 /user-service/v1/... canonical aliases。
- 增加 X-API-Contract: user-service.v1。
- 接受并观测最新 CLI 的 X-AWiki-Client-Version，保证不重复输出/转发、不参与 API 选版。
- personal-agent canonical 名称与旧 message-agent 别名映射到同一实现。
- 增加 canonical/legacy 使用指标，旧路由从 schema 隐藏。

主要文件：

- src/awiki_open_server/app/routes.py
- src/awiki_open_server/user_compat/
- tests/test_route_config.py
- tests/test_user_service_compat.py
- identity/contact/profile/agent/site 相关 tests

退出条件：

- route snapshot 与 User Service 当前 contract 的“现有能力子集”一致。
- canonical 与 legacy 调用产生相同业务结果和同一份持久化状态。
- 最新 CLI 的 User Service 请求只命中 /user-service/v1/...，且每个产品请求最多携带一个格式正确的 Client Version Header。
- 未支持的 User Service 能力未被误发布。

### Phase 3：P2 discovery、capabilities 与 P8 安全

改动目标：

- 修正 DID document 的 profile 清单和唯一 ANPMessageService。
- capabilities 如实发布标准、本地与禁用能力。
- endpoint selection 使用 runtime capabilities。
- 收紧 HTTP signature、caller anchor、principal binding 和 SSRF。
- 移除对 source-service hint header 的身份依赖。

主要文件：

- src/awiki_open_server/protocol/anp_adapter.py
- src/awiki_open_server/messaging/core.py
- src/awiki_open_server/messaging/group_outbox.py
- src/awiki_open_server/services.py 中仅保留兼容 facade
- app DID/health/capability routes

退出条件：

- DID/profile/capability contract 测试通过。
- 签名、digest、重放、错误 serviceDid、错误 request URL、SSRF 负例通过。
- Open Server 与最新 Message Service 可互相发现 v1 plaintext profiles。

### Phase 4：P3 Direct

改动目标：

- strict direct.send schema、全路径 origin proof、标准结果校验。
- client/device hint 在跨域前剥离。
- 标准 accepted 结果不依赖 vendor final_acceptance。
- 统一 Direct 幂等、落库和本地 notification。

主要文件：

- src/awiki_open_server/messaging/core.py
- src/awiki_open_server/messaging/direct.py
- protocol schemas/registry
- tests/test_direct_messages.py
- tests/test_messaging_surface.py

退出条件：

- 本地和跨域 plaintext Direct 正向测试通过。
- 缺 proof、错误 sender/target、重复 operation 冲突、错误 peer result 负例通过。
- 不运行或要求任何成功 E2EE flow。

### Phase 5：P4 Group 与状态迁移

改动目标：

- 标准 Group 全部切到单一 Group Host/projection/outbox 状态机。
- 对齐 create/join/add/remove/leave/update/send/rebind 的 envelope 与 proof。
- 分离 state_version/event_seq。
- 回填 legacy group/member/message 数据。
- 严格 Notification、receipt proof 和 outbox 重试语义。

主要文件：

- src/awiki_open_server/messaging/groups.py
- src/awiki_open_server/messaging/group_participant.py
- src/awiki_open_server/messaging/group_outbox.py
- src/awiki_open_server/storage/
- tests/test_group_participant.py
- tests/test_group_host.py 或新增对应测试
- migration/restart tests

退出条件：

- P4 全生命周期、本地/跨域、重启恢复、幂等和权限矩阵通过。
- 数据库中只有一个可写 Group sequence authority。
- 邀请、邀请码、pending membership 均为 not_supported。

### Phase 6：P7 Attachment

改动目标：

- canonical digest/size/target/security profile shape。
- 本地 slot lifecycle 与 peer ticket 权限矩阵。
- authoritative sender discovery 与消息授权绑定。
- legacy flat 字段只在本地 adapter 中存在。

主要文件：

- src/awiki_open_server/attachments/
- attachment protocol schemas/registry
- tests/test_attachments.py

退出条件：

- create/upload/commit/ticket/download/abort 正向链路通过。
- 越权 ticket、篡改 digest、错误 target、错误 caller anchor 和 encryption mode 非 none 的负例通过。

### Phase 7：本地同步、已读与 realtime

改动目标：

- 对齐 local v1，并提供受限的 local v2 单设备 wire compatibility、字段、水位和鉴权。
- 明确 account event_seq、thread server_seq、read watermark。
- WebSocket 只承担 dirty hint，断线恢复由 HTTP 完成。
- 保留单 DID、单设备边界。

主要文件：

- src/awiki_open_server/messaging/sync.py
- src/awiki_open_server/messaging/read_state.py
- src/awiki_open_server/app/realtime.py
- tests/test_sync_read_state.py
- realtime reconnect tests

退出条件：

- Direct/Group 混合增量、分页、幂等已读、重连恢复通过。
- capability 准确发布 `sync.local.v2` 的单设备拉取模式，同时明确 `multi_device=not_supported`，且 snapshot/recovery 不发布。

### Phase 8：文档、smoke、互操作与发布

改动目标：

- 更新 README、require、API 示例、部署说明和 smoke CLI。
- 所有示例使用 canonical envelope/profile；legacy 示例单独标记废弃。
- 完成最新 Message Service 的 plaintext Direct 和 Community Group 互操作。
- 使用最新正式 AWiki CLI 的普通用户命令完成 Open Server 端到端验收；允许由仓库 harness 编排真实 CLI，但 raw HTTP/JSON-RPC smoke 不能替代 CLI 用户验收。
- 发布 legacy 使用指标、关闭条件和回滚手册。

退出条件：

- 完整本地测试与 smoke 通过。
- 最新 CLI 安装产物能够从空工作区配置 Open Server tenant、注册身份并完成明文 Direct、Group、Attachment、Sync/Read 用户旅程。
- 公网系统测试仍由 AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 显式启用。
- 没有 E2EE 成功测试或 E2EE release gate。
- 形成可执行的升级、备份、验证、回滚 runbook。

## 14. 兼容迁移策略

### 14.1 公网

- /anp-im/rpc 从新版本第一天起 strict。
- 不接受 flat params、数字 id、无 proof mutation 或 legacy profile。
- 旧 peer 若不符合 P1/P3/P4/P7/P8，应得到明确协议错误，而不是被服务器猜测性修复。

### 14.2 本地

采用两个版本窗口：

1. Dual-read：/im/rpc 接受 canonical envelope；旧 flat params 只对已认证本地 bearer 生效，记录 method、client version 和 legacy reason 指标。
2. Strict-default：默认只接受 canonical；提供一个有明确删除日期的本地 rollback 开关，例如 AWIKI_LEGACY_LOCAL_RPC_COMPAT。该开关不得影响公网入口。

legacy adapter 可以映射旧字段，但不得：

- 生成或伪造 origin proof。
- 把 local client/device 字段转发给 peer。
- 允许超范围 E2EE、邀请或 pending membership。
- 改变 canonical 成功/失败判断。

### 14.3 User Service 路由

- canonical 与 legacy aliases 至少并存一个发布周期。
- 通过 structured log/metric 观察旧路由调用量。
- 删除 legacy route 必须另立版本决策，不在本次改造中顺手移除。

## 15. 测试与验证门禁

### 15.1 自动化测试矩阵

| 层级 | 重点 |
| --- | --- |
| SDK adapter | 0.9.2 fail-fast、签名 API、DID、digest、receipt、WNS |
| P1 binding | parse、batch、id、params shape、closed envelope、Request/Notification、错误码 |
| Route/contract | public/local/user canonical/legacy、contract header、OpenAPI 隐藏 |
| Capability | 静态 DID 与 runtime profile、禁用能力、method registry 一致性 |
| P8 security | HTTP Signature、Content-Digest、caller anchor、principal binding、重放、SSRF |
| Direct | 本地/跨域 plaintext、proof、幂等、结果校验、WS notification |
| Group | 全生命周期、权限、双 sequence、通知、outbox、projection、rebind、重启 |
| Attachment | slot、commit、abort、ticket、download、权限、digest、none encryption |
| Sync/read | 增量分页、thread watermark、已读幂等、重连恢复 |
| Negative scope | E2EE、加密附件、邀请/join code、multi-device、relay mesh 全部 not_supported |
| Migration | 旧数据库回填、重复执行、崩溃恢复、旧读兼容、代码回滚 |
| Latest CLI | tenant/init/register/doctor、明文 Direct、Group、Attachment、Sync/Read、Realtime 恢复 |

### 15.2 建议命令

SDK 升级完成后，使用同一 0.9.2 源验证：

~~~bash
PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_protocol_anp_sdk.py -q
~~~

分领域验证：

~~~bash
PYTHONPATH=../anp/anp:src python3 -m pytest \
  tests/test_route_config.py \
  tests/test_user_service_compat.py \
  tests/test_messaging_surface.py \
  tests/test_direct_messages.py \
  tests/test_group_participant.py \
  tests/test_attachments.py \
  tests/test_sync_read_state.py -q
~~~

完整测试：

~~~bash
PYTHONPATH=../anp/anp:src python3 -m pytest tests -q
~~~

smoke：

~~~bash
PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-asgi
PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-local \
  --base-url http://127.0.0.1:8765 --did-domain localhost
PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-cross-domain-local
PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-rust-cli-local \
  --awiki-cli-bin /path/to/pinned/awiki-cli \
  --data-root /tmp/awiki-open-server-rust-cli-local \
  --clean
~~~

前三个命令是 ASGI/raw protocol 服务端 smoke。smoke-rust-cli-local 会调用真实 Rust CLI，是 CLI 验收的现有基础；但只有在 CLI artifact 被固定和记录，并补齐下述缺口后，才能作为最终发布门禁。

### 15.3 最新 AWiki CLI 用户验收

#### 2026-08-07 实际执行记录

已从 `awiki-cli-rs2` `release/0714` 提交 `3200847d` 构建 CLI，并使用全新 Open Server
数据目录和两个隔离的 `AWIKI_CLI_WORKSPACE_HOME_DIR` 实际执行：

| 检查 | 结果 | 证据/结论 |
| --- | --- | --- |
| tenant 配置与解析 | 通过 | 使用 `127.0.0.1.nip.io` 作为本地有效 DID host；`localhost` 会被当前 WNS 校验拒绝 |
| canonical User Service 注册 | 通过 | CLI 命中 `/user-service/v1/did-auth/rpc`，Open Server 返回当前 CLI 所需 device registration contract |
| 明文 Direct 写入 | 通过 | `msg send` 返回 canonical message ID，服务端持久化成功 |
| Inbox/History | 通过 | 受限 `anp.sync.local.v2` 完成 tail-only bootstrap、delta、batch hydration；不含多设备语义 |
| Group 当前本地 CLI 旅程 | 通过 | create/get/list/add/update/join/send/messages/leave/remove 与拒绝离群成员写入均完成；独立 members/attachment/realtime 仍按发布矩阵单独验证 |

仓库新增分层 Gate：

- `smoke-rust-cli-connect` 是当前可通过的“连接与写入”证据，输出 CLI version/build 信息、artifact SHA-256、两个 DID 与 message ID。
- `smoke-rust-cli-local` 是当前仓库本地用户旅程 Gate；必须使用全新数据目录和隔离 workspace。独立 Group members inventory、Attachment、Realtime/restart 继续按发布矩阵单独验证。

用户随后明确授权受限 `anp.sync.local.v2`。该授权只覆盖单设备拉取与本地投影，不扩大到多设备同步、设备间共享、一个 DID 多设备、snapshot/recovery 或 E2EE。验证报告仍应把 `connection-and-write passed`、`single-device sync v2 passed` 与 `full local user journey passed` 分开记录。

本次实现验证结果（2026-08-07）：

- `PYTHONPATH=../anp/anp:src python3 -m pytest tests -q`：100 passed，2 个公网 opt-in tests skipped。
- `smoke-asgi`：通过。
- 启动真实 Uvicorn 后执行 `smoke-local --base-url ...`：通过，包含 identity、Direct、Group、Attachment。
- `smoke-cross-domain-local`：通过，两个独立进程双向明文 Direct、DID discovery、origin proof 与 HTTP Signature 均验证。
- 从干净 `3200847d` 工作区重新构建的 CLI 执行 `smoke-rust-cli-connect`：通过；Gate 输出 artifact SHA-256、DID 与 message ID。
- 同一源码构建的 CLI 执行 `smoke-rust-cli-local`：通过；Direct inbox/history 经单设备 sync v2 水合，当前 Community Group（不含独立 members/attachment/realtime Gate）与 People/Site 本地流程通过。

验证盘点与剩余 Gate：

- `scripts/awiki_open_cli.py` 已扩展既有 `smoke-rust-cli-local`，不另起重复 harness。
- 它会启动临时 Open Server，创建 Alice、Bob、Charlie 三个隔离 CLI workspace，并通过真实 `awiki-cli` 覆盖 tenant 配置、canonical `/user-service/v1/...` 身份注册、Direct send/inbox/history、Group create/get/list/add/update/join/send/messages/leave/remove、People 和 Site。
- Open Server 已注册本次范围内的 `/user-service/v1/...` canonical 子集；最新 CLI `3200847d` 的本地连接与当前用户旅程已经实测通过。
- Gate 输出 CLI version/build、artifact SHA-256、DID 和 message ID；`X-AWiki-Client-Version` 只用于观测，不能替代 URL/profile 的协议选择。
- 独立 Group members inventory、Attachment、mark-read、Realtime/restart 尚未纳入本轮真实 CLI Gate；跨域 smoke 目前仍由 raw Python 请求完成而不是真实 CLI。验证报告不得把这些项目写成已由最新 CLI 证明。

后续应在现有 harness 上增加真实 CLI 的 cross-domain Gate，并补齐 members inventory、Attachment 与 Realtime/restart；不新建第二套相同业务逻辑的 CLI 测试驱动。

验收基线：

- CLI 仓库使用 release/0714 当前远端最新提交；计划调研时为 3200847d。
- 测试开始时重新解析 origin/release/0714 或指定发布 tag，记录完整 commit。
- 最终门禁使用从该 commit 构建并可安装的 awiki-cli artifact，不只使用 library test、system_test_probe 或手工 JSON-RPC。
- 记录 CLI channel、语义版本、commit、artifact SHA-256、平台/架构和 Open Server commit。
- 运行 awiki-cli version 和版本一致性检查，确保报告值与 artifact provenance 相同。

验收环境：

- 使用临时 AWIKI_CLI_WORKSPACE_HOME_DIR，禁止复用开发者已有身份、token、数据库或租户配置。
- 启动一个全新的 Open Server 数据目录完成同域用户旅程。
- 另启动两个不同 DID domain 的 Open Server 实例完成跨域旅程。
- 每个用户使用独立 CLI workspace，避免一个 workspace 的本地缓存掩盖服务端缺陷。
- tenant 通过最新版 CLI 正常创建，例如 tenant setup，并只提供 backend_base_url 与 did_host；不手工修改 CLI 数据库或注入私有 RPC。
- Message 路径仍为 /im/rpc、/im/ws、/anp-im/rpc；User Service 请求必须使用 /user-service/v1/...。
- 所有正向消息命令显式或默认使用 secure=off；不得让 CLI 自动回退到 E2EE，也不得以开启 E2EE 作为 Open Server 成功条件。

同域用户旅程至少覆盖：

1. 安装 artifact，执行 version、tenant setup、tenant current、init、config show 和 doctor。
2. Alice 与 Bob 在两个干净 workspace 中通过最新 CLI 注册本地域身份；验证 DID document 的 ANPMessageService 指向该 Open Server。
3. Alice 执行明文 msg send；Bob 通过 msg inbox 和 msg history 读到同一个 canonical message ID 与内容。
4. Bob 执行 msg mark-read 或 inbox --mark-read；重新同步后 unread/read watermark 一致。
5. Alice 使用 group create --secure off 创建群，Bob 通过标准立即生效的 join 或 Alice add 加入。
6. 验证 group get/list/members，发送明文群消息，并通过 group messages 或 inbox 读取。
7. 在允许的角色矩阵下验证 group update、remove、leave；不调用 join-code/invite/pending 流程。
8. Alice 使用 msg send --file --secure off 发送附件；Bob 通过 CLI 下载，并对比文件 SHA-256 与原始字节。
9. 启动 CLI realtime listener，验证消息通知；主动断开后通过 inbox/sync/history 补齐，证明 WebSocket 只是 dirty hint。
10. 若本次发布包含 People/Site compatibility 改动，再用最新 CLI 对对应现有能力执行 focused 用户旅程；不把不在 Open Server 范围内的 CLI 命令纳入成功门禁。

跨域用户旅程至少覆盖：

1. Alice CLI 只连接 Open Server A，Bob CLI 只连接 Open Server B。
2. 两端 DID 文档和 runtime capabilities 通过公开 ANP endpoint 发现，禁止测试配置直接写死对端内部地址。
3. 完成 A 到 B、B 到 A 的 plaintext Direct，并在接收端 CLI inbox/history 可见。
4. 在一个 Home 创建 Community Group，让另一 Home 的成员立即加入或被添加，完成双向群消息、成员列表与历史读取。
5. 覆盖 Attachment ticket/download 和 Open Server 重启后的 outbox/projection 恢复。
6. 证明 local client/device hint 未跨域转发，peer 身份来自 HTTP Signature 而不是提示 Header。

版本与 wire 断言：

- 最新 CLI 的所有 User Service 产品请求只请求 /user-service/v1/...，失败时不 fallback 到无版本路径。
- Open Server 对 canonical 与 legacy User route 都只输出一个 X-API-Contract: user-service.v1。
- CLI 产品请求最多携带一个 X-AWiki-Client-Version，值与实际 artifact 一致。
- /im/rpc 和 /anp-im/rpc 不增加 URL v1；每个 JSON-RPC 请求通过 meta.profile 声明准确版本。
- CLI 不发送普通 direct.base.v2、group.base.v2 或 attachment.v2。
- 公共 ANP、DID discovery 和对象数据面不依赖 X-AWiki-Client-Version。

负向验收：

- msg send --secure required、secure Group 和 encrypted Attachment 对 Open Server 返回稳定 not_supported/unsupported capability，且 CLI 不静默降级为明文。
- group join-code/invite 类命令保持未实现或得到 not_supported。
- 不把这些预期负向结果计为 CLI 无法连接 Open Server。

发布判定：

- 仓库内 pytest 和 Python smoke 通过，但真实 CLI 用户旅程失败：不得发布。
- 现有 smoke-rust-cli-local 若只因 legacy route 仍可用而通过，但没有证明 canonical /user-service/v1 请求：不得发布。
- 真实 CLI 只有通过预置数据库、旧 workspace、raw RPC 或 system-test probe 才成功：不得发布。
- 测试必须保留脱敏后的命令、exit code、JSON envelope、服务端 trace ID 与版本记录；不得保存 token、私钥或原始 proof。
- 若失败源于 CLI 与最新规范不一致，应在 CLI 修复并以新 commit/artifact 重跑；Open Server 不通过放宽公网安全校验适配旧客户端。

跨域 acceptance 只覆盖：

- plaintext Direct。
- plaintext Community Group。
- none encryption 的 Attachment。
- DID discovery、HTTP signature、outbox/projection 和重启恢复。

当前系统 Python 环境加载的是旧 anp 0.6.8，而 Open Server 现有 adapter 要求 0.8.9，因此调研阶段的 PYTHONPATH=src 全量测试在 collection 前按设计 fail-fast。实现 Phase 0 后使用 sibling ANP 0.9.2 或干净的 0.9.2 环境重新建立完整基线。

## 16. 发布与回滚

建议采用小步发布，不做一次性大爆炸切换：

1. 发布 SDK、registry 和只读 capabilities，对比旧行为。
2. 公网 strict P1/P8；本地 dual-read。
3. 发布 User Service canonical aliases。
4. 分别切 Direct、Group、Attachment canonical writer。
5. 完成 Group 数据回填并关闭旧 writer。
6. 切 Sync/Read/Realtime contract。
7. 观察 legacy route/flat params 指标后进入 strict-default。

每次发布前：

- 备份 SQLite 与对象目录。
- 在数据副本上运行 migration 和 restart test。
- 检查 DID 文档、runtime capability 与 public URL。
- 使用最新 Message Service 完成 plaintext Direct/Group 互操作。

需要监控：

- JSON-RPC/ANP error code 分布。
- legacy route 与 flat params 调用量。
- origin/receipt proof 失败原因。
- discovery/cache/HTTP signature 失败。
- Direct/Group idempotency 冲突。
- outbox pending/retry/dead-letter。
- projection lag 与 sequence gap。
- attachment ticket 越权/失效。
- sync cursor 与 WS reconnect。
- X-AWiki-Client-Version 的 product/release/version 分布，以及无版本 User route 调用量。

回滚优先级：

1. 回退单个 domain handler 或关闭新 writer。
2. 保留 additive schema 和新数据。
3. 恢复本地 legacy compatibility 开关。
4. 公网安全校验不得通过回滚开关降级；若互操作故障无法安全兼容，应暂停相关公网 mutation。

## 17. 风险与待评审决策

### 17.1 本地 origin proof 的客户端影响

规范要求 Direct/Group mutation 在本地也有 origin proof。旧 Open 客户端可能只发送 flat params 且没有 proof。

建议：

- 公网立即严格。
- 本地先 dual-read，但无 proof 的旧 mutation 只保留明确期限和指标。
- 客户端升级完成后 strict-default；不由服务器生成 proof。

### 17.2 Group 双状态模型迁移

这是风险最高的实现阶段。必须先做数据库 fixture、回填 dry-run、sequence 对账和崩溃恢复测试，再切 writer。若无法证明一一对应，宁可暂停 mutation，也不能长期双写。

### 17.3 profile 名称容易误解

anp.federation.relay.v1 的名称包含 relay，但本服务器不实现 relay mesh。文档和 capabilities 必须同时标注 did_discovery_direct_call 和 relay_mesh=false。

### 17.4 上游文档与实现漂移

对普通 base.v2、attachment.v2 和 User Service group invite 的冲突已经通过“规范优先级”解决。实现 PR 中应引用固定上游 commit 和 contract fixture，避免再次跟随旧文档误改。

### 17.5 local sync 与 Message Service v2

Message Service 的多设备 sync v2 仍超出 Open Server 范围。本计划仅增加同名 profile 的单设备 wire compatibility：tail-only bootstrap、delta、message batch hydration 与 thread catch-up。snapshot/recovery、多个 device/client instance、设备间共享和 fanout 均不支持；未来若需要这些能力，必须单独评审存储模型、鉴权、cursor 和 realtime fanout。

## 18. 完成标准

只有同时满足以下条件，本次对齐才算完成：

- SDK、文档和运行时检查统一为 anp==0.9.2。
- DID document 与 runtime capabilities 只发布真实支持的 mixed-version profiles。
- /anp-im/rpc 全量符合 P1/P2/P3/P4/P7/P8 的适用规则。
- /im/rpc 有明确的 canonical contract、legacy 观测窗口和 strict-default 路线。
- User Service 当前功能子集具备 /user-service/v1/... canonical 路由，旧路由仍兼容且不产生第二份状态。
- API 版本来源没有歧义：User Service 由 URL /v1 选版，Message 由 meta.profile 选版，Header 只用于诊断和客户端观测。
- 最新可安装 AWiki CLI 从干净 workspace 能连接 Open Server 并完成同域与跨域 plaintext 用户旅程。
- Direct 与 Community Group 可与最新 Message Service 完成明文跨域互操作。
- Group 只有一个可写状态机，state_version/event_seq、projection 与 outbox 可在重启后恢复。
- Attachment 只支持 transport-protected + object_encryption_mode=none，授权与 digest 规则符合 P7。
- Sync/read/realtime 保持单 DID、单设备；local v2 仅表示 wire contract 版本，不冒充多设备能力。
- 所有 E2EE、加密附件、邀请、join code、pending membership、relay mesh、多设备能力均不发布并返回稳定 not_supported。
- 全量 pytest、plaintext smoke、迁移/回滚测试通过；公网测试仍保持显式 opt-in。

## 19. 建议的 PR 拆分

为降低 shared route/storage 文件冲突，建议顺序合并，不并行改写同一 writer：

1. PR-1：contract fixtures、SDK 0.9.2、method registry skeleton。
2. PR-2：P1 binding/error/route principal matrix。
3. PR-3：User Service v1 canonical aliases 与 contract telemetry。
4. PR-4：P2/P8 DID、capabilities、signature/discovery。
5. PR-5：P3 Direct。
6. PR-6A：Group additive schema、migration、read-side projection。
7. PR-6B：P4 Group writer/outbox 切换。
8. PR-7：P7 Attachment。
9. PR-8：local sync/read/realtime。
10. PR-9：文档、Python smoke、最新 CLI 用户验收、互操作与 legacy strict-default。

每个 PR 都应包含：

- 影响模块。
- contract/source commit。
- 正向与负向验证。
- 数据兼容说明。
- 回滚方式。
- 明确声明未扩大 Open Server 功能边界。
