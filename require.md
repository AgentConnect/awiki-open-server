# AWiki Open Server Community v1 Requirements

本文档描述当前 `awiki-open-server` 的产品与实现要求。它是一个单进程、SQLite、小规模自托管的 AWiki Community Server，不依赖 `awiki.info`、User Service、Message Service 或其它 AWiki 服务作为运行时后端。

协议语义以 ANP 规范为准，尤其是：

- `../anp/AgentNetworkProtocol/chinese/message/04-群组基础语义.md`；
- `../anp/AgentNetworkProtocol/chinese/message/08-联邦与跨域.md`；
- 本仓库 `docs/community-groups-design.zh-CN.md`。

相邻仓库用于验证兼容契约，不构成本服务的运行时依赖。若相邻文档与 ANP P4/P8 冲突，以 P4/P8 为最高优先级。

## 1. 产品定位

Community v1 必须让用户在自己的域名部署一个可独立工作的服务，支持：

- 本地域身份、DID Document、Handle、Profile 和本地会话；
- 本域及跨域明文 Direct；
- 小规模群创建、管理、成员加入和跨域群消息互通；
- 本地附件、Markdown 内容与站点；
- sync、read-state 和单进程 WebSocket realtime hint；
- 当前 CLI 和客户端所需的 User Service / Message Service 兼容路由。

Community v1 不是商业集群的缩小部署包。基础群能力和标准跨域互通必须真实可用；商业版差异主要在 E2EE、容量、高可用、复杂治理、审计和托管运维。

## 2. 明确边界

必须保持以下限制：

- 单进程、SQLite、本地文件对象存储；
- 面向少量用户和小群，不承诺高并发或大规模 fanout；
- 不支持 Direct E2EE、Group E2EE 或 MLS；
- 不支持 Redis、Kafka、PostgreSQL、分布式事务或多区域复制；
- 不支持 federation relay、peer-route mesh 或任意多跳路由；
- 不支持 HA realtime、外部 pub/sub、presence、typing 或离线 push；
- 不支持自定义群角色、所有权迁移、审批流、归档或复杂治理；
- 不提供真实短信、邮箱、Aliyun 或商业身份验证；
- 不提供计费、多租户托管或商业 Runtime 编排；
- 不实现跨域附件 upload delegation、完整 access-grant relay 或远程对象 relay。

超出范围的方法必须返回明确的 `not_supported`，不能静默降级或伪造成功。

## 3. 运行边界

本服务必须在本地实现所有 Community 能力：

- 不得代理到 `awiki.info`、User Service 或 Message Service；
- 不得把远端服务当作失败回退；
- 调用由远端 Agent DID 或 Group DID 发现的 Group Host 属于标准跨域互通，不是后端代理；
- 公网验证必须使用公共 HTTPS、DID discovery 和公开 ANP endpoint；
- 不得使用内部端口、固定 resolver、进程内调用、直接数据库写入或 unsigned peer 绕过公网 Gate。

## 4. 外部接口

稳定入口包括：

| 入口 | 用途 |
| --- | --- |
| `POST /im/rpc` | 本域客户端 JSON-RPC；包含 local-only history、sync、read-state 和对象控制 |
| `POST /anp-im/rpc` | DID Document 指向的公开 ANP endpoint |
| `GET /im/ws` | 本地认证 WebSocket 与 realtime hint |
| `POST /group/rpc` | 旧 Message Service 群兼容 façade |
| `POST /user-service/group/rpc` | 旧 User Service 群兼容 façade |
| `GET /.well-known/did.json` | Service DID Document |
| `GET /healthz` | 无敏感诊断信息的公开存活检查 |
| `GET /operations/status` | 可选、独立 Bearer 保护的聚合运维状态 |

兼容 façade 只能转换字段与错误，不能建立第二套群权威状态，也不能绕过 origin proof 或直接写群表。

## 5. Community Group v1

### 5.1 权威模型

Group Host 是群状态唯一权威。每个托管群必须具有：

- 独立 Group DID；
- 群级 Ed25519 私钥，保存在 `AWIKI_DATA_DIR/group-keys`；
- 可公开解析和验证的 Group DID Document；
- `owner`、`admin`、`member` 固定角色；
- `open-join` 或 `admin-add` 策略；
- 单调递增的 `group_state_version` 和 `group_event_seq`；
- 对群状态和群消息接受结果签名的 Group Receipt；
- 幂等 operation/message 记录、成员投影、消息历史和状态事件。

群领域逻辑应位于 `messaging/groups/`；`services.py` 只保留兼容 façade 和尚未拆分的其它领域逻辑。

### 5.2 标准方法

必须支持：

| 方法 | 要求 |
| --- | --- |
| `group.create` | 本域用户创建托管群并成为 owner |
| `group.get_info` | 按可见性返回 profile、policy、成员和版本信息 |
| `group.join` | `open-join` 下调用者立即成为 active |
| `group.add` | 有权限角色直接添加目标，成功后目标立即 active |
| `group.remove` | 有权限角色移除成员，立即撤销发送权限 |
| `group.leave` | 当前成员退出，立即撤销发送权限 |
| `group.rebind_member` | Handle binding generation 变化后安全重绑定 DID |
| `group.update_profile` | 有权限角色更新群名、描述等 profile |
| `group.update_policy` | owner 更新标准群策略 |
| `group.send` | active 成员发送本地或跨域普通群消息 |
| `group.get/list/list_members/list_messages` | 本地或远端投影读取 |

`group.add` 与 `group.join` 的成功结果就是最终成员资格，不存在后续确认步骤。

### 5.3 禁止的邀请扩展

ANP P4 标准入群只有 `group.join` 和 `group.add`。Community v1：

- 不实现 invitation 或 `invitation_id`；
- 不实现 `group.invite` 或 `group.accept_invite`；
- 不实现 invite token、join token 或 join code；
- 不实现 pending membership、邀请接受状态或入群审批状态；
- `refresh_join_code` 和 `get_join_code` 必须返回 `not_supported`；
- 请求含 `invite_token`、`join_token` 或 `join_code` 时必须拒绝；
- 旧 schema 中的 invite token 必须清除，不得迁移成新协议凭据。

产品界面的“邀请成员”只能是 `group.add` 的交互名称。

### 5.4 身份与权限

必须支持 DID-only membership 和 Handle-backed membership。

Handle-backed 加入必须校验 WNS 归一化、active 状态、双向绑定和 binding generation，并保存当前 DID、Handle 与 generation。`group.rebind_member` 必须验证新 binding 后迁移成员身份，不能允许第三方劫持或复用旧 generation。

所有读取、更新、发送操作必须执行角色、成员状态和对象可见性校验。leave/remove 后不得继续读取成员专属状态或发送消息。

### 5.5 幂等与顺序

- mutation 使用 `operation_id` 幂等；
- send 使用 `message_id` 幂等；
- 相同 ID 和相同规范请求返回原结果；
- 相同 ID 和不同请求必须冲突；
- `group_event_seq` 在 Group Host 内严格单调；
- `group_state_version` 仅随权威状态变化递增；
- 消息和状态投影必须按 event sequence 可恢复；
- receipt 中的 event sequence、message ID 和 payload digest 必须与接受事实一致。

## 6. 跨域群互通

跨域模式是 `did_discovery_direct_call`：解析远端 Agent DID 或 Group DID 的 `ANPMessageService`，直接调用远端公开 endpoint。它不建立 federation relay。

### 6.1 公共群方法

`/anp-im/rpc` 必须公开：

- `group.create`、`group.get_info`；
- `group.join`、`group.add`、`group.remove`、`group.rebind_member`、`group.leave`；
- `group.update_profile`、`group.update_policy`、`group.send`；
- `group.incoming`、`group.state_changed` Notification。

Inbox、History、sync、read-state、local list 和 attachment upload/commit 等本地视图不得因此整体公开。

### 6.2 Member Home projection

远端群成员所在域必须维护本地投影，使客户端可通过本地域服务完成：

- 群列表、详情、成员列表与消息历史；
- sync delta 和 thread backfill；
- read-state；
- realtime hint；
- 远端群命令路由与标准错误传播。

投影不是群权威状态。冲突时以 Group Host 的已验证通知和 Receipt 为准。

### 6.3 Durable outbox

跨域 fanout 必须使用 SQLite durable outbox，并具备：

- transaction 内 enqueue；
- 每目标 FIFO；
- operation/delivery 幂等与接收端去重；
- 指数或有界退避重试；
- pending、retry、delivered、dead 状态；
- 背压上限；
- worker 单轮异常隔离；
- 进程重启恢复；
- 一个离线目标不阻塞其它目标。

内部 delivery ID、attempt、trace 或 route hint 不得加入标准 wire 对象。

## 7. 协议安全

### 7.1 Origin proof

除 P4 允许的 `group.get_info` 读取场景外，所有群 mutation 和 `group.send` 必须校验 `auth.origin_proof`。本域 bearer token 只识别本地会话，不能替代业务 origin proof。

服务端不得代替用户生成 origin proof。跨域路由必须原样保留 proof，并验证 proof 的 method、caller anchor、target、nonce/timestamp 和 payload binding。

### 7.2 P8 hop security

公网跨域请求必须验证：

- RFC 9421 HTTP Signature；
- `Content-Digest`；
- peer service DID 与 DID Document；
- endpoint 和目标域一致性；
- Group Receipt 的签名、Group DID、payload digest 和 event sequence。

普通群请求以 `meta.sender_did` 作为 P8 caller anchor。`group.incoming` 和 `group.state_changed` 以 `body.group_did` 作为 caller anchor，并且必须是没有 JSON-RPC `id` 的 Notification。

### 7.3 DID discovery

DID discovery 必须限制 scheme、host、port、重定向和地址类别，防止 loopback、私网、link-local、metadata endpoint、DNS rebinding 与跨域 endpoint 注入。公开环境必须 fail closed；测试 resolver map 只能用于显式本地测试。

### 7.4 日志与秘密

日志、错误和测试报告不得输出：

- access/refresh/operations token；
- 私钥或完整公钥材料集合；
- 完整 origin proof、HTTP Signature 或 Group Receipt proof；
- 非测试消息正文；
- 带敏感 query 的对象下载 URL。

仅记录 method、脱敏 DID/对象 ID、状态、错误类别、attempt 和时间等必要诊断信息。

## 8. 数据与运维

`AWIKI_DATA_DIR` 是 SQLite、对象和群密钥之外业务数据的持久化边界。SQLite 必须启用 WAL、foreign keys 和 busy timeout，并通过安全 migration 升级。

备份必须一致地包含 SQLite/WAL、对象和 group-key 目录；Service DID 私钥单独以更严格权限备份。恢复后必须验证 DID、群 receipt、数据库 integrity、smoke 与跨域互通。

`/operations/status` 默认关闭。启用时必须使用独立 `AWIKI_OPERATIONS_TOKEN` 或优先使用 `AWIKI_OPERATIONS_TOKEN_FILE`，并聚合输出：

- hosted group 和 active member 数；
- outbox pending/retry/delivered/dead；
- oldest pending age；
- worker heartbeat、age 和 last drain；
- SQLite/WAL 大小；
- group-key 目录可读写状态。

公开 `/healthz` 必须保持最小响应，不得泄露上述诊断或 token 配置。

## 9. Capability 契约

`anp.get_capabilities` 必须与真实实现一致：

- `anp.group.base.v1` 在 supported profiles 中；
- `features.group_participant.enabled=true`；
- `features.group_participant.management=true`；
- join modes 仅为 `open-join` 和 `admin-add`；
- `features.cross_domain_group.enabled=true`；
- mode 为 `did_discovery_direct_call`；
- Direct/Group E2EE、large-group fanout、Group HA 和 federation relay 明确禁用。

不能将 relay、HA、E2EE 或大群能力包装成“完整 federation”或“完整群管理”。

## 10. 测试门禁

必须以聚焦 ASGI 测试覆盖：

- 本地域完整群生命周期与 permission matrix；
- open-join、admin-add 和 add/join 后立即 active；
- DID-only、Handle-backed 和 rebind；
- origin proof、HTTP Signature、Content-Digest、caller anchor 和 Receipt；
- operation/message 幂等、state version 和 event sequence；
- Notification 无 JSON-RPC id；
- projection、history、sync、read-state 和 realtime；
- outbox retry、duplicate、FIFO、离线、背压、dead 和重启恢复；
- SSRF、伪造 proof/peer/receipt 和越权访问；
- legacy join-code 方法 `not_supported`。

聚焦测试通过后必须运行完整 pytest suite。协议、User Service façade、路由、消息面、Group Host 和 sync/read-state 变更均需运行对应测试文件。

## 11. 真实发布 Gate

使用实际 Rust CLI 和完全隔离的 workspace，分别连接：

- Open Server：`https://rwiki.cn`，DID host `rwiki.cn`；
- 兼容服务：`https://awiki.info`，DID host `awiki.info`。

两个方向都必须覆盖：

- host 域创建群；
- 远端成员通过 `group.add` 立即加入；
- 另一远端成员通过 `group.join` 立即加入；
- get/list/members、profile/policy 更新；
- 两域双向发送并读取唯一消息；
- history、sync、realtime projection 和 receipt；
- leave/remove 后立即失去发送权限；
- outbox retry/restart recovery。

证据至少包含 run ID、组件版本、方向、公共域、service DID、Group DID、成员 DID、operation/message ID、event sequence、state version、receipt 验证结果、投递状态和关键时间戳。证据必须脱敏。

还必须验证两个隔离 Open Server 的协议级双域测试，以及三域 fanout 中离线目标不影响在线目标、恢复后保持 FIFO。

## 12. 发布完成条件

只有以下条件全部有当前、可复核证据时才可宣告完成：

1. Community Group v1 实现、schema、migration 和兼容 façade 完整；
2. 相关专项测试及完整 pytest suite 通过；
3. 两 Open Server 双域和三域恢复测试通过；
4. `rwiki.cn` 托管群与 `awiki.info` 成员互通通过；
5. `awiki.info` 托管群与 `rwiki.cn` 成员互通通过；
6. Rust CLI 完整群生命周期通过；
7. invitation/token/join-code 审计无非标准实现；
8. 安全 Gate 无未处理高危问题；
9. capability、README、AGENTS、设计、配置、部署和运维文档与实现一致；
10. 工作区没有生成或提交 token、私钥、SQLite、上传对象等敏感运行数据。

任何失败都必须定位、修复并重新验证，不能用窄测试替代完整要求。
