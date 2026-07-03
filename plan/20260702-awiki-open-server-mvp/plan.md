# Plan：awiki-open-server MVP 落地

状态：in_progress  
DOC：awiki-open-server/plan/20260702-awiki-open-server-mvp/  
Harness：awiki-harness  
创建时间：2026-07-02  
恢复指针：Step 27 本仓门禁已完成，后续执行入口迁移到 `awiki-open-server/plan/20260703-awiki-open-server-mvp-reset/plan.md`。真实 MVP 完成仍回到 Step 09：`rwiki.info` 按本仓 `deploy/` 模板切到 open server 后，先跑 `verify-public`，再跑真实线上 `awiki.info` 双向 peer Gate。

## 1. 目标

- 任务目标：根据 `awiki-open-server/require.md` 实现可运行的 Awiki Community Server MVP。
- 预期行为：提供 DID/Profile/Pages、明文 direct、群参与子集、附件、sync/read-state、公开 `/anp-im/rpc`、能力声明和 CLI 冒烟验证；本仓作为独立开源 server 自行实现 awiki.info 类服务端能力，测试阶段再与线上 `awiki.info` 用户做跨服务 direct 互通。
- 非目标：群创建/管理、Group Host 托管、Direct/Group E2EE、federation peer routes、服务间 relay、生产认证、多租户托管。
- 完成标准：本地测试通过；本仓 Python smoke 覆盖身份、私聊、群参与、附件、Pages、capability；现有 Rust CLI `awiki-cli-rs2` 连接本服务验证 identity/direct/page/group；本服务用户发送到 `awiki.info` 用户 DID 时能解析远端 DID document，保留 CLI 生成的 `auth.origin_proof`，用本服务 `serviceDid` 做 HTTP Signature / DID WBA hop auth，并调用远端 `/anp-im/rpc`；`awiki.info` 用户发送到本服务 DID 时，本服务公开 `/anp-im/rpc` 校验 hop auth 和业务 proof 后投递本地收件人；若线上 `awiki.info` 对等服务对该互通有协议或实现阻塞，先记录 blocker，不修改其他项目。

## 2. Harness 上下文

| 来源 | 作用 |
|---|---|
| `awiki-harness/AGENTS.md` | 多仓库任务必须识别影响面、规则和验证。 |
| `awiki-harness/context/00-context-map.md` | 路由到 Identity、Protocol、Message Flow、Client Architecture。 |
| `awiki-harness/context/02-repo-map.md` | 确认 `user-service`、`message-service`、`awiki-cli-rs2`、`awiki-system-test` 权威边界。 |
| `awiki-harness/context/03-cross-repo-architecture.md` | 确认本项目是单仓库实现，不改其他服务契约。 |
| `awiki-harness/context/20-rules-index.md` | 应用 Architecture、Documentation、Verification 规则。 |
| `awiki-harness/context/30-tools-env.md` | 验证以本仓库 pytest 和 CLI smoke 为主；真实 Gate 是本服务公开域名/DID 域与线上 `awiki.info` 对等服务互通。 |
| `awiki-harness/context/40-verification.md` | 本次实现至少 L1；本服务公开域名与线上 `awiki.info` 用户互通属于 L2/L3 证据。 |
| `awiki-harness/context/50-task-workflow.md` | 需要记录计划、验证、风险和完成证据。 |

## 3. 影响分析

| 领域 / 仓库 / 模块 | 影响 | 权威文档或代码 |
|---|---|---|
| `awiki-open-server` | 新增服务实现、测试、CLI smoke、文档。 | `awiki-open-server/require.md` |
| Identity | 本地 DID 注册、Profile、dev JWT。 | `user-service/docs/api/did-auth.md`, `user-service/docs/api/did-profile.md` |
| Message Flow | Direct、本地域内视图、群参与、sync/read-state、附件。 | `message-service/docs/api/`, `awiki-harness/context/nodes/message-flow.node.md` |
| Protocol / Cross-domain | `ANPMessageService`、`serviceDid`、`/anp-im/rpc` 暴露面。 | `anp/AgentNetworkProtocol/chinese/message/02-身份与发现.md` |
| CLI 验证 | 使用本仓 Python smoke 做可重复检查；使用独立 `awiki-cli-rs2` worktree 验证现有 Rust CLI 真实连接；真实 Gate 使用本服务公开域名/DID 域（例如 `rwiki.info`）与线上 `awiki.info` 用户互通。 | `awiki-open-server/scripts/awiki_open_cli.py`, `awiki-cli-rs2/crates/awiki-cli/tests/*_live_contract.rs` |

## 4. 假设与开放问题

### 假设

- 当前实现可用 dev token 简化认证；安全 proof/WBA 验证预留接口但不做生产级密码学。
- `awiki.info` 是线上 AWiki 服务的远端对等服务，只用于互通验证，不是 `awiki-open-server` 的后端依赖；本开源 server 必须自行实现身份、DID 文档、消息公开入口和本地存储，并由自己的 `AWIKI_PUBLIC_BASE_URL`、`AWIKI_DID_DOMAIN` 和 `AWIKI_SERVICE_DID` 发布服务 DID 与用户 DID。
- 线上互通测试应使用一个 CLI 连接本服务，另一个 CLI 或已有用户连接 `awiki.info`；之前“两端 CLI 都连接 awiki.info”的验证只证明线上服务内部多 DID 域用户互通，不证明本开源 server 互通。
- `User Service` 和 `Message Service` 是只读协议参考和互通目标；本目标内不能修改这些仓库，也不能把这些服务或 `awiki.info` 配成运行时依赖。
- 群参与只支持 open-join 或 invite-token，本服务可以种子化已有群；不允许用户创建/管理群。
- 2026-07-03 本轮边界复核结论：`require.md`、`README.md`、`app/settings.py`、`app/routes.py`、`services.py` 与 `deploy/` 模板均按自实现 open server 模型组织；`/user-service/...` 路由是本仓本地 dispatch，跨域 direct 只按 recipient DID document 发现远端 `ANPMessageService.serviceEndpoint` 后直连，不是固定调用 `awiki.info`。

### 开放问题

- 需要一个可被 `awiki.info` 访问的本服务公开域名，才能完成真实线上双向互通验证；若只能本地运行，可先用单元/集成测试证明 outbound discovery、origin proof 透传、service HTTP Signature 和 inbound `/anp-im/rpc`。
- 当前 Step 06 本仓本地门禁已通过；真实 awiki.info 双向互通仍需要一个可被线上服务访问的本服务公开域名和对应 service DID 私钥配置，不能用本地测试替代线上 Gate。
- 如线上 `awiki.info` 对等服务在本仓协议收敛后仍拒绝本服务 DID document、origin proof 或 service HTTP Signature，应先把目标设为待确认 blocker，而不是直接修改其他项目。

## 5. 总体设计方法

- 设计边界：单进程 FastAPI + stdlib SQLite；所有状态在 `AWIKI_DATA_DIR` 下。
- 关键决策：实现 JSON-RPC 2.0 binding；`/im/rpc` 暴露本域方法；`/anp-im/rpc` 只暴露 capability、direct send、group info/join、download ticket。
- 兼容性策略：保留方法名和 Rust CLI 期望的响应形态；新增 `/user-service/did-auth/rpc`、`/user-service/did/profile/rpc`、`/user-service/handle/rpc` 兼容入口是为了兼容现有客户端路由，不表示依赖外部 User Service；不支持能力返回 `not_supported`；远端对等服务 capability 使用 ANP 兼容的 `params.meta/body`，远端 direct 使用 `params.meta/auth/body`，本地 smoke 可以继续使用简化参数。
- 数据策略：sqlite3 轻量 schema，启动时自动迁移；对象文件写入本地目录。
- 风险控制：不持有 E2EE 明文以外的密钥状态；不实现 federation relay；远端跨域验证不写入真实生产数据之外的测试消息。

## 6. 任务拆分

| Step | 标题 | 依赖 | 并行组 | Parallel-safe | 建议 Agent | 可并行对象 | 互斥资源 / 冲突路径 | 产出 | 小 Plan 文档 | Commit gate | 合并 / 验证门禁 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 01 | 服务骨架与存储 | 无 | 串行 | 否 | main | 无 | `awiki_open_server/`, `pyproject.toml` | FastAPI app、settings、sqlite store、JSON-RPC | [steps/01-service-skeleton.md](steps/01-service-skeleton.md) | 建议 | pytest health/schema | done |
| 02 | 身份、Profile、Pages | Step 01 | 串行 | 否 | main | 无 | `awiki_open_server/identity`, `awiki_open_server/pages` | DID/Profile/Content API | [steps/02-identity-pages.md](steps/02-identity-pages.md) | 建议 | focused pytest | done |
| 03 | 消息、群参与、附件 | Step 02 | 串行 | 否 | main | 无 | `awiki_open_server/messaging`, `awiki_open_server/object_store` | Direct、group participant、attachment、sync/read-state | [steps/03-messaging-objects.md](steps/03-messaging-objects.md) | 建议 | focused pytest | done |
| 04 | CLI smoke 与测试 | Step 03 | 串行 | 否 | main | 无 | `scripts/`, `tests/`, `src/awiki_open_server/services.py` | CLI 脚本、本地 smoke、远端 DID discovery/outbound direct/inbound public direct 测试；awiki.info 只作为远端对端 | [steps/04-cli-tests.md](steps/04-cli-tests.md) | 建议 | CLI + pytest | done |
| 05 | 最终 Review 与文档同步 | Step 04 | 串行 | 否 | main | 无 | `README.md`, `plan/...` | 运行证据、文档更新、风险记录 | [steps/05-final-verification.md](steps/05-final-verification.md) | 如有修改则建议 | final gate | done |
| 06 | 真实跨域互通加固 | Step 05 | 串行 | 否 | main | 无 | `src/`, `tests/`, `README.md`, `plan/...` | 修复 origin proof 透传、service DID 可验证文档、HTTP Signature/DID WBA、身份 API 兼容和真实 awiki.info Gate | [steps/06-interop-hardening.md](steps/06-interop-hardening.md) | 建议 | pytest + Rust CLI + real interop gate | done-with-pending-online-gate |
| 07 | 架构边界复核与互通收敛 | Step 06 | 串行 | 否 | main | 无 | `plan/...`, `README.md`, `src/`, `tests/` | 按用户更正复核方案和实现：本仓自行实现 awiki.info 类服务端能力，`awiki.info` 只做线上互通测试对象；补充 User Service / Message Service 兼容差距和验证缺口 | [steps/07-architecture-boundary-review.md](steps/07-architecture-boundary-review.md) | 建议 | docs review + pytest + CLI gate | done-with-pending-online-gate |
| 08 | User Service / Message Service 互通收敛 | Step 07 | 串行 | 否 | main | 无 | `src/`, `tests/`, `scripts/`, `README.md`, `plan/...` | 使用现有 Rust CLI 隔离 workspace 验证本服务 User Service / Message Service 兼容面；按失败点只修本仓；真实线上 peer Gate 若卡在相邻服务则记录 blocker | [steps/08-service-interop-convergence.md](steps/08-service-interop-convergence.md) | 建议 | Rust CLI + pytest + ASGI smoke + real peer gate/blocker | done-with-pending-online-gate |
| 09 | 公网 rwiki.info 与 awiki.info 双向互通 Gate | Step 08/10 | 串行 | 否 | main | 无 | `plan/...`；如发现本仓缺陷则 `src/`, `tests/`, `scripts/`, `README.md` | 将 `rwiki.info` 切到本仓 open server 后，运行 `verify-public` 和真实双向 direct/inbox/history Gate；若公网已正确但对端拒绝则记录 blocker | [steps/09-public-rwiki-awiki-gate.md](steps/09-public-rwiki-awiki-gate.md) | 建议 | verify-public + Rust CLI 双向线上 Gate | pending-deployment |
| 10 | User / Message Service 兼容形态补齐 | Step 08 | 串行 | 否 | main | 无 | `src/awiki_open_server/services.py`, `src/awiki_open_server/app/routes.py`, `tests/`, `plan/...` | 补齐 WNS handle 解析、旧 auth/token/ws ticket、小型 `/im/ws`、标准 sync/read-state/attachment 响应字段；只修本仓，不改相邻服务 | [steps/10-service-shape-convergence.md](steps/10-service-shape-convergence.md) | 建议 | pytest + ASGI smoke + Rust CLI 本地 Gate | done-with-pending-online-gate |
| 11 | 协议边缘兼容收敛 | Step 10 | 串行 | 否 | main | 无 | `src/`, `scripts/`, `tests/`, `plan/...` | 收敛 read-state、attachment upload、动态默认群 DID、公开 `group.join` proof/signature 与 `{body}` envelope 展开；只修本仓，不改相邻服务 | [steps/11-protocol-edge-convergence.md](steps/11-protocol-edge-convergence.md) | 建议 | pytest + ASGI smoke + 双实例本地跨域 Gate | done-with-pending-online-gate |
| 12 | Message Service 实时通知兼容补齐 | Step 11 | 串行 | 否 | main | 无 | `src/awiki_open_server/app/`, `src/awiki_open_server/services.py`, `tests/`, `README.md`, `plan/...` | 将 `/im/ws` 从一次性 sync hint 补成进程内保持连接的 realtime fanout，覆盖 `direct.incoming`、`group.incoming` 和 `group.state_changed`；只修本仓，不引入外部队列或 federation | [steps/12-realtime-notification-convergence.md](steps/12-realtime-notification-convergence.md) | 建议 | pytest + WS focused tests + ASGI smoke | done-with-pending-online-gate |
| 13 | User Service auth_request 与 dev 登录兼容补齐 | Step 12 | 串行 | 否 | main | 无 | `src/awiki_open_server/app/routes.py`, `tests/test_identity_pages.py`, `README.md`, `plan/...` | 补齐 User Service/nginx 常见 `auth_request` 路由别名、`X-User-Id` header、WS ticket header 验证和 dev SMS OTP 登录/注册；只修本仓，不改线上 User Service | [steps/13-user-service-auth-compat.md](steps/13-user-service-auth-compat.md) | 建议 | focused pytest + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate | done-with-pending-online-gate |
| 14 | User Service Profile REST/RPC 与 Message Service health 兼容补齐 | Step 13 | 串行 | 否 | main | 无 | `src/awiki_open_server/services.py`, `src/awiki_open_server/app/routes.py`, `tests/`, `README.md`, `plan/...` | 补齐旧 `/me`、`/me/rpc`、公开 profile Markdown、`/users/{user_id}/profile` 以及 `/im/healthz` 兼容；只修本仓，不改相邻服务 | [steps/14-profile-health-compat.md](steps/14-profile-health-compat.md) | 建议 | focused pytest + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate | done-with-pending-online-gate |
| 15 | Directory / Site 兼容面补齐 | Step 14 | 串行 | 否 | main | 无 | `src/awiki_open_server/storage/db.py`, `src/awiki_open_server/services.py`, `src/awiki_open_server/app/routes.py`, `tests/`, `README.md`, `plan/...` | 补齐 DID relationship、phone bind dev 兼容和 `/site/rpc` Markdown site surface；只修本仓，不改相邻服务 | [steps/15-directory-site-compat.md](steps/15-directory-site-compat.md) | 建议 | focused pytest + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate | done-with-pending-online-gate |
| 16 | Rust CLI 本地互通 Gate 自动化 | Step 15 | 串行 | 否 | main | 无 | `scripts/awiki_open_cli.py`, `README.md`, `plan/...` | 将现有 Rust CLI 连接本仓的 User Service / Message Service / Directory / Site 兼容验证固化成可重复 smoke 命令；只修本仓，不改 `awiki-cli-rs2` | [steps/16-rust-cli-local-gate.md](steps/16-rust-cli-local-gate.md) | 建议 | smoke-rust-cli-local + 全量本仓门禁 | done-with-pending-online-gate |
| 17 | Users RPC 与 Agent Inventory 兼容补齐 | Step 16 | 串行 | 否 | main | 无 | `src/awiki_open_server/storage/db.py`, `src/awiki_open_server/services.py`, `src/awiki_open_server/app/routes.py`, `tests/test_identity_pages.py`, `README.md`, `plan/...` | 补齐 User Service `/users/rpc` 查询接口和 daemon 使用的 `/user-service/agent-inventory/rpc` 最小兼容；只修本仓，不实现商业托管 runtime | [steps/17-users-agent-inventory-compat.md](steps/17-users-agent-inventory-compat.md) | 建议 | focused pytest + compileall + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate | done-with-pending-online-gate |
| 18 | Message payload 与 daemon heartbeat 兼容收敛 | Step 17 | 串行 | 否 | main | 无 | `src/awiki_open_server/services.py`, `src/awiki_open_server/storage/db.py`, `tests/test_messaging_objects.py`, `README.md`, `plan/...` | 补齐 Message Service direct/group `meta.content_type` 与 `body` 绑定校验；识别 `awiki.agent.status.v1` daemon heartbeat 并返回 `delivery_state=ephemeral` 且不写历史/sync；只修本仓，不改相邻服务 | [steps/18-message-payload-heartbeat-compat.md](steps/18-message-payload-heartbeat-compat.md) | 建议 | focused pytest + compileall + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate + Rust CLI local Gate | done-with-pending-online-gate |
| 19 | ANP envelope meta 必填字段收敛 | Step 18 | 串行 | 否 | main | 无 | `src/awiki_open_server/services.py`, `tests/test_messaging_objects.py`, `README.md`, `plan/...` | 对 `direct.send` / `group.send` 的 ANP envelope 收紧 `meta.sender_did`、`meta.target`、`meta.operation_id`、`meta.message_id`、`meta.content_type` 必填和 target 一致性；旧 flat text CLI 路径保持兼容 | [steps/19-anp-envelope-meta-compat.md](steps/19-anp-envelope-meta-compat.md) | 建议 | focused pytest + compileall + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate + Rust CLI local Gate | done-with-pending-online-gate |
| 20 | DID Verify JSON-RPC 兼容补齐 | Step 19 | 串行 | 否 | main | 无 | `src/awiki_open_server/services.py`, `src/awiki_open_server/app/routes.py`, `src/awiki_open_server/app/settings.py`, `tests/test_identity_pages.py`, `README.md`, `plan/...` | 补齐 User Service `/did-verify/rpc` 与 `/user-service/did-verify/rpc` 的 `send_code`、`login`、`refresh` 最小兼容；只使用本仓本地 DID/user/token，不调用 `awiki.info` 或相邻服务 | [steps/20-did-verify-compat.md](steps/20-did-verify-compat.md) | 建议 | focused pytest + compileall + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate + Rust CLI local Gate | done-with-pending-online-gate |
| 21 | Attachment ticket ANP 兼容补齐 | Step 20 | 串行 | 否 | main | 无 | `src/awiki_open_server/storage/db.py`, `src/awiki_open_server/services.py`, `src/awiki_open_server/app/routes.py`, `tests/test_messaging_objects.py`, `README.md`, `plan/...` | 补齐 `attachment.get_download_ticket` 对 Message Service ANP `body.object_uri/requester_did/sender_did/message_id/message_security_profile/message_target_did|group_did` 请求形态和 `download_ticket_b64u/ticket_binding` 响应字段的最小兼容；数据面支持 Bearer download ticket；保留本地 owner ticket 路径；不实现跨域上传代理、完整 grant 表或 E2EE 授权 | [steps/21-attachment-ticket-compat.md](steps/21-attachment-ticket-compat.md) | 建议 | focused pytest + compileall + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate + Rust CLI local Gate | done-with-pending-online-gate |
| 22 | DID revoke 兼容补齐 | Step 21 | 串行 | 否 | main | 无 | `src/awiki_open_server/storage/db.py`, `src/awiki_open_server/services.py`, `src/awiki_open_server/app/routes.py`, `tests/test_identity_pages.py`, `README.md`, `plan/...` | 补齐 User Service `/did-auth/rpc revoke` 最小兼容：本地 DID 和 DID document 标记 revoked，撤销后 token/DID verify/update/get_me/ws ticket/auth verify 均不能再认证为 active DID；不实现 replace/recover 或生产恢复流程 | [steps/22-did-revoke-compat.md](steps/22-did-revoke-compat.md) | 建议 | focused pytest + compileall + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate + Rust CLI local Gate | done-with-pending-online-gate |
| 23 | Inbox mark-read 兼容补齐 | Step 22 | 串行 | 否 | main | 无 | `src/awiki_open_server/services.py`, `tests/test_messaging_objects.py`, `README.md`, `plan/...` | 补齐 Message Service `inbox.mark_read` 真实 direct view 已读语义：写入 `direct_message_views.read_at`，默认 `inbox.get` 只返回未读，`include_read` 和 `direct.get_history` 投影准确 `is_read/read_at`；public `/anp-im/rpc` 白名单不扩大 | [steps/23-inbox-mark-read-compat.md](steps/23-inbox-mark-read-compat.md) | 建议 | focused pytest + messaging tests + compileall + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate + Rust CLI local Gate | done-with-pending-online-gate |
| 24 | Local view 参数语义兼容补齐 | Step 23 | 串行 | 否 | main | 无 | `src/awiki_open_server/services.py`, `tests/test_messaging_objects.py`, `README.md`, `plan/...` | 补齐 Message Service `inbox.get` / `direct.get_history` local-only 参数契约：校验 `meta.sender_did` 和 `body.user_did` 与当前 DID 一致，支持 `since_seq`、`since`、`skip`、`limit`，废弃 `group_did` history 路径返回明确错误；不实现 delegated local view 和 public 暴露 | [steps/24-local-view-params-compat.md](steps/24-local-view-params-compat.md) | 建议 | focused pytest + messaging tests + compileall + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate + Rust CLI local Gate | done-with-pending-online-gate |
| 25 | Group participant 成员权限收敛 | Step 24 | 串行 | 否 | main | 无 | `src/awiki_open_server/services.py`, `tests/test_messaging_objects.py`, `README.md`, `plan/...` | 收紧 Community 群参与子集：`group.list_members` / `group.list_messages` 要求当前 DID 已加入群；`group.leave` 只允许 active member 离开，非成员不生成 sync/realtime 事件；继续不支持群创建/管理 | [steps/25-group-participant-membership-compat.md](steps/25-group-participant-membership-compat.md) | 建议 | focused pytest + messaging tests + compileall + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate + Rust CLI local Gate | done-with-pending-online-gate |
| 26 | Group local view 参数与 sync 权限收敛 | Step 25 | 串行 | 否 | main | 无 | `src/awiki_open_server/services.py`, `tests/test_messaging_objects.py`, `README.md`, `plan/...` | 补齐 Message Service / Rust CLI group local view 参数契约：`group.list/list_members/list_messages` 校验 `meta.sender_did` / `user_did`，`group.list_messages` 支持 `since_seq/since_event_seq/skip/limit` 与 page cursor，`sync.thread_after` 的 group thread 要求当前 DID 是群成员，防止绕过 Step 25 | [steps/26-group-local-view-sync-compat.md](steps/26-group-local-view-sync-compat.md) | 建议 | focused pytest + messaging tests + compileall + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate + Rust CLI local Gate | done-with-pending-online-gate |
| 27 | Message local view 投影兼容收敛 | Step 26 | 串行 | 否 | main | 无 | `src/awiki_open_server/services.py`, `tests/test_messaging_objects.py`, `README.md`, `plan/...` | 对齐 Message Service direct/group local view 的 `type/content/content_type/body` 投影：JSON 为 `type=json`，附件清单为 `type=attachment_manifest`，二进制扩展为 `type=binary`；`sync.thread_after` direct 分支复用 direct view 投影；只修本仓，不扩大 public `/anp-im/rpc` | [steps/27-message-view-projection-compat.md](steps/27-message-view-projection-compat.md) | 建议 | focused pytest + messaging tests + compileall + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate + Rust CLI local Gate | done-with-pending-online-gate |

## 7. 并行执行与多智能体分工

- 并行策略：本仓库从零实现，步骤共享 schema、RPC 契约和测试环境，实际执行采用串行。
- 最大并行度：1。
- Coordinator：当前 Codex。
- 串行原因：Step 02/03 依赖 Step 01 的 app/store/RPC；Step 04 依赖所有 API；并行会造成 schema 和测试证据冲突。

### Agent 分工

| Agent / Worker | 负责 Step | 责任边界 | 可修改路径 | 禁止修改路径 / 资源 | 交付物 | Review 责任 |
|---|---|---|---|---|---|---|
| main | 01-27 | 计划、实现、验证、最终 Review | `awiki-open-server/**` | 其他仓库 | 代码、测试、CLI、证据 | 自查 + 命令证据 |

### 并行组

| Wave / 并行组 | 可并行 Step | 可并行原因 | 共享依赖 | 写入范围 | 依赖屏障 | 合并顺序 | Group gate / 验证责任 |
|---|---|---|---|---|---|---|---|
| 串行 | 无 | 不适用 | schema/app/test env；Step 09 额外依赖公网域名 | 全仓库 | Step 01 -> 09 | 顺序提交 | 每步 pytest/CLI gate |

### 互斥资源

| 资源 / 路径 / 契约 | 互斥原因 | 受影响 Step | 规则 |
|---|---|---|---|
| SQLite schema | 所有 API 共享 | 01-04 | 只能串行变更。 |
| JSON-RPC error shape | 所有客户端测试依赖 | 01-04 | 变更前更新 Plan 和测试。 |

## 8. 执行台账

| Step | 状态 | Agent / Owner | 并行组 | 分支 / worktree | 基线 commit | 开始时间 | 完成时间 | Commit | Review 证据 | 验证证据 | 合并状态 | 门禁状态 | 下一步 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 01 | done | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-02 | 2026-07-02 22:36 CST | 未提交 | Review：app factory 无 import 写状态；SQLite init 幂等；JSON-RPC error shape 统一 | `PYTHONPATH=src python3 -m pytest tests/test_health.py -q`；全量 pytest 9 passed | merged | pass | Step 02 已完成 |
| 02 | done | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-02 | 2026-07-02 22:36 CST | 未提交 | Review：dev token 不写日志；DID document 唯一 `ANPMessageService`；Pages handle+slug 唯一；DID resolve 可用 | `PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py -q`；全量 pytest 9 passed | merged | pass | Step 03 已完成 |
| 03 | done | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-02 | 2026-07-02 22:36 CST | 未提交 | Review：`/anp-im/rpc` 白名单隔离；群管理方法 `not_supported`；sync/read-state 有事件；附件明文对象可上传下载 | `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q`；全量 pytest 9 passed | merged | pass | Step 04 已完成 |
| 04 | done | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-02 | 2026-07-03 09:15 CST | 未提交 | Review：已识别并撤销此前线上验证错误；补齐 remote DID discovery、outbound direct 与 public inbound target 校验；awiki.info 只作为远端对端 | `tests/test_messaging_objects.py` 6 passed；全量 pytest 12 passed；ASGI smoke pass；HTTP smoke pass；Rust CLI 本地 identity/direct/inbox/history pass | merged | pass | Step 05 同步文档和最终验证 |
| 05 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-02 | 2026-07-03 09:15 CST | 未提交 | Review：README/Plan 已改为自有开源 server + awiki.info 远端对等测试模型；未修改相邻仓库；awiki-cli-rs2 已有用户变更未触碰 | compileall pass；pytest 12 passed；ASGI smoke pass；HTTP smoke pass；Rust CLI 本地 smoke pass；真实 awiki.info 双向互通待公网域名 | merged | pass/online-pending | 有公网域名后执行 Real awiki.info Interop |
| 06 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 本地门禁完成 | 未提交 | Review：方案边界正确，未发现使用 awiki.info 作为后端、fallback、存储或内部依赖；`normalize_params` 已保留 `_anp_body`，`direct_send` 用原始 envelope body 做 origin proof 校验、远端转发和存储；公开 direct 入站会解析 sender DID document 并验证 origin proof Ed25519 签名；未修改相邻仓库 | focused messaging 10 passed；全量 pytest 16 passed；compileall pass；ASGI smoke pass；真实 awiki.info 双向 Gate 待本服务公开域名 | merged | pass/online-pending | 配置公开域名、service private key 和 Rust CLI 后执行双向 awiki.info interop Gate；若线上拒绝则记录 blocker |
| 07 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 本地复核完成 | 未提交 | Review：已按用户更正重新检查 `require.md`、`README.md`、Plan、`src/awiki_open_server/services.py`、`service_identity.py`、`routes.py` 和测试；未发现把 `awiki.info` 作为本服务后端、fallback、代理或存储依赖；`smoke-awiki-info` 仅是远端 capability 诊断，不能作为本仓互通完成证据 | grep 复核通过；compileall pass；全量 pytest 19 passed；ASGI smoke pass；Rust CLI 本地 Gate 本轮未重跑，需隔离 HOME 后继续；真实线上 awiki.info Gate 待公开域名 | merged | pass/online-pending | 配置本服务公开域名、service private key 和 Rust CLI 后执行双向 awiki.info interop Gate；若线上拒绝则记录 blocker |
| 08 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 本地 Gate 完成；公开部署材料完成 | 未提交 | Review：现有 Rust CLI 使用隔离 `HOME`/workspace 连接本仓服务通过；`/user-service/...` 路由由本仓本地 dispatch，未转发外部 User Service；`/im/rpc` local-only 与 `/anp-im/rpc` public peer entry 分离；`group.send` 响应已补齐 CLI/Message Service 期望字段；`group.create` 返回 `not_supported`；未修改相邻仓库；未发现 `awiki.info` 作为本仓后端、fallback、代理、认证源或消息存储；已新增 `deploy/` 模板和 `verify-public`，将公网路由缺口变成可验证项 | `PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 21 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step08-asgi-final-2` pass；Rust CLI 本地 Gate pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info` 预期失败并证明公网未切到本仓：service DID document 404、healthz 404、`anp.get_capabilities` 404 | merged | pass/online-pending | 将 `rwiki.info` nginx/systemd 按 `deploy/` 模板切到本仓服务后，先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct Gate |
| 09 | pending-deployment | main | 串行 | 当前 worktree | 8f334b7 | 未开始 | 未完成 | 未提交 | 待补：公网 `rwiki.info` 已切到本仓；`verify-public` 通过；双向 `awiki.info` direct Gate Review | 当前阻塞证据：2026-07-03 11:41 CST 复跑 `verify-public --base-url https://rwiki.info --did-domain rwiki.info` 仍失败，service DID document 404、healthz 404、`anp.get_capabilities` 404；说明公开域名尚未由本仓服务发布 DID document 和 `/anp-im/rpc` | pending | waiting-deployment | 完成部署切换后执行 Step 09 |
| 10 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 本仓门禁、Rust CLI 本地 Gate、双实例跨域 Gate 与 Agent 兼容完成 | 未提交 | Review：已补齐 WNS handle 解析、旧 auth/token/ws ticket、agent-registration/message-agent 最小兼容、基础 `/im/ws`、标准 sync/read-state/attachment 响应字段；所有路径仍由本仓本地实现；未引入外部 User Service / Message Service / `awiki.info` 运行依赖；`/anp-im/rpc` public 白名单未扩大；现有 Rust CLI 连接本仓验证注册、direct、inbox/history、Pages、群参与均通过，`group.create` 保持 `not_supported`；双实例 Gate 暴露并修复了同步 HTTP 外发阻塞源服务 DID 回查、以及出站 direct 改写已签名 `meta` 两个本仓问题；双实例 Gate 已纳入 pytest 自动回归 | `PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 26 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-agent-compat-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-agent-compat-cross --clean` pass；Agent 兼容 focused pytest pass；隔离 Rust CLI 最小回归 pass：`id register` Alice/Bob pass，Alice -> Bob direct pass，Bob inbox/history pass；`verify-public https://rwiki.info` 仍为预期 404 | merged | pass/online-pending | 继续 Step 09 公网 Gate：`rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| 11 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 | 未提交 | Review：`read_state.mark_read` 只写 thread watermark、不写未知 sync event；message-id watermark 只在调用方可见 thread 内解析并校验 seq；attachment header token 不破坏 query token；默认群 DID 跟随 domain；公开 `group.join` 要求 origin proof 与 service HTTP Signature；本地 `/im/rpc group.join` 仍保持 Bearer 兼容 | focused public group/read-state pass；`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py tests/test_cli_smoke.py -q` 20 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 28 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step11-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step11-cross --clean` pass；隔离 Rust CLI 本地最小回归 pass：注册 Alice/Bob、Alice -> Bob direct、Bob inbox/history 均可见消息；`verify-public https://rwiki.info` 仍为预期 404 | merged | pass/online-pending | 继续 Step 09 公网 Gate：`rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| 12 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 | 未提交 | Review：`/im/ws` 使用本仓 in-process `RealtimeHub` 保持连接并推送 direct/group participant 通知；direct/group RPC response 不变；public `/anp-im/rpc` 白名单不变；未引入外部 User Service / Message Service / `awiki.info` 运行依赖；`group.joined` / `group.left` 本地 sync event 兼容性已保留 | `PYTHONPATH=src python3 -m pytest tests/test_health.py::test_im_websocket_receives_direct_and_group_notifications -q` pass；focused direct/group + WS 2 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 29 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step12-asgi-rerun` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step12-cross --clean` pass；`verify-public https://rwiki.info` 仍为预期 404 | merged | pass/online-pending | 继续 Step 09 公网 Gate：`rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| 13 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 13:05 CST | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 | 未提交 | Review：新增 health/auth/session/ws-ticket 兼容别名均由本仓本地实现；`/auth/sms` dev OTP 只创建或复用本地 SQLite DID 用户；token/ticket verify 返回 `X-User-Id` / `X-DID` header；未引入外部 User Service / Message Service / `awiki.info` 运行依赖；README 已标注 dev auth 边界 | `PYTHONPATH=src python3 -m pytest tests/test_health.py::test_healthz tests/test_identity_pages.py::test_legacy_auth_and_ws_ticket_compat_routes -q` 2 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 29 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step13-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step13-cross --clean` pass；`verify-public https://rwiki.info` 仍为预期 404 | merged | pass/online-pending | 继续 Step 09 公网 Gate：`rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| 14 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 | 未提交 | Review：旧 `/me`/公开 profile REST/RPC 均由本仓本地 profile 表实现，`user_id` 在 Community 版中等同 DID；`/im/healthz` 复用本仓 health response，不代理外部 Message Service；`/anp-im/rpc` public 白名单未扩大；`delete_me` 保持 `not_supported`；REST 错误映射已补 401/404/400 | `PYTHONPATH=src python3 -m pytest tests/test_health.py::test_healthz tests/test_identity_pages.py::test_legacy_me_profile_and_message_health_compat_routes -q` 2 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 30 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step14-asgi-rerun` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step14-cross-rerun --clean` pass；`verify-public https://rwiki.info` 仍为预期 404 | merged | pass/online-pending | 继续 Step 09 公网 Gate：`rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| 15 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 | 未提交 | Review：DID relationship、phone bind、site RPC 均由本仓本地 SQLite / handler 实现，不代理外部 `awiki.info`、User Service 或 Message Service；DID relationship 只允许本域本地用户；`/site/rpc` 只管理 `AWIKI_DID_DOMAIN` 的 raw Markdown 页面，不扩展为生产 tenant hosting；README 已同步能力和非目标 | `PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py::test_did_relationship_phone_bind_and_site_rpc_compat -q` 1 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 31 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step15-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step15-cross --clean` pass；`verify-public https://rwiki.info` 仍为预期 404 | merged | pass/online-pending | 继续 Step 09 公网 Gate：`rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| 16 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 | 未提交 | Review：新增 `smoke-rust-cli-local` 只写 `/tmp` 隔离 server data、HOME 和 CLI workspace；调用现有 `awiki-cli-rs2` 二进制但不修改 CLI 仓库；验证范围覆盖 `/user-service/did-auth/rpc` dev phone OTP 注册、`/im/rpc` direct/inbox/history、群参与、`/user-service/did/relationships/rpc` people、`/site/rpc` site；未把本地 loopback Gate 当作真实 `awiki.info` 互通证据 | `CARGO_TARGET_DIR=/tmp/awiki-cli-rs2-open-server-target cargo build -p awiki-cli --bin awiki-cli --locked` pass；手工双 workspace Rust CLI Gate pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-rust-cli-script --clean` pass；全量本仓门禁见最终证据 | merged | pass/online-pending | 继续 Step 09 公网 Gate：`rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| 17 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 | 未提交 | Review：`/users/rpc`、`/user-service/users/rpc`、`/user-service/agent-inventory/rpc` 均由本仓本地 SQLite/profile/binding/status 表实现；未引入外部 User Service / Message Service / `awiki.info` 运行依赖；agent inventory 只做 daemon 兼容最小状态、controller scope、sender check、authorization、archive/policy 字段，不实现商业托管 runtime；public `/anp-im/rpc` 白名单未扩大 | `PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py::test_users_rpc_compat_routes tests/test_identity_pages.py::test_agent_inventory_minimal_compat_routes -q` 2 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 33 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step17-asgi-final` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step17-cross-final --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step17-rust-cli --clean` pass；`verify-public https://rwiki.info` 仍为预期 404 | merged | pass/online-pending | 继续 Step 09 公网 Gate：`rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| 18 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 | 未提交 | Review：direct/group 在 ANP envelope 或显式非文本 content type 下严格绑定 `meta.content_type` 与 `body`；旧 flat text CLI 调用保持兼容；新增 `content_type` 持久列用于正确投影 JSON payload；daemon heartbeat no-store 只匹配精确 liveness payload，非 heartbeat agent status 仍持久化；未修改相邻仓库，public `/anp-im/rpc` 白名单未扩大 | `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_application_json_payload_shape_and_daemon_heartbeat_no_store -q` 1 passed；`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q` 16 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 34 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step18-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step18-cross --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step18-rust-cli --clean` pass | merged | pass/online-pending | 继续 Step 09 公网 Gate：`rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| 19 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 | 未提交 | Review：ANP envelope meta 校验只对 `_anp_body` / `_anp_meta` 生效；direct/group 缺少 `sender_did`、`target`、`operation_id`、`message_id`、`content_type` 或 target kind/did 不一致会被拒绝；旧 flat text CLI 路径保持兼容；public `/anp-im/rpc` 白名单未扩大；未修改相邻仓库 | `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_anp_envelope_meta_required_fields_and_target_validation -q` 1 passed；`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q` 17 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 35 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step19-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step19-cross --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step19-rust-cli --clean` pass | merged | pass/online-pending | 继续 Step 09 公网 Gate：`rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| 20 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 | 未提交 | Review：`/did-verify/rpc` 与 `/user-service/did-verify/rpc` 均由本仓本地 handler 实现；`send_code` 不调用外部消息服务；`login` 只接受本仓已注册 DID 和 DID verify dev code；`refresh` 只接受本仓本地 token；DID verify 默认 `666666` 与 SMS/Handle dev OTP `123456` 边界已在 README 说明；public `/anp-im/rpc` 白名单未扩大；未修改相邻仓库 | `PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py::test_did_verify_rpc_compat_routes -q` 1 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 36 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step20-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step20-cross --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step20-rust-cli --clean` pass；Step 20 后复跑 `PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info` failed，service DID document 404、healthz 404、`anp.get_capabilities` 404，继续归 Step 09 公网路由 | merged | pass/online-pending | 继续 Step 09 公网 Gate：`rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| 21 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 15:43 CST 本仓门禁完成；公网 Gate 仍待 Step 09 | 未提交 | Review：`attachment.get_download_ticket` 同时保留本地 owner `object_id/object_uri` 路径并支持 ANP `body.object_uri/requester_did/sender_did/message_id/message_security_profile/message_target_did|group_did`；响应补齐 `download_ticket_b64u/ticket_binding`；`GET /objects/{object_id}` 支持 Bearer download ticket；public `/anp-im/rpc` 白名单未扩大，upload/commit/abort 仍不公开；不调用外部 Message Service / `awiki.info`；未实现跨域上传代理、完整 `attachment_access_grants`、E2EE 授权或远端 object relay；未修改相邻仓库 | `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_attachment_roundtrip tests/test_messaging_objects.py::test_attachment_download_ticket_accepts_anp_body_shape -q` 2 passed；`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q` 18 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 37 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step21-asgi-rerun` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step21-cross-rerun --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step21-rust-cli-rerun --clean` pass | merged | pass/online-pending | 继续 Step 09 公网 Gate：`rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| 22 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 | 未提交 | Review：DID revoke 由本仓 SQLite `users.revoked_at` 与 `did_documents.status/revoked_at` 实现；`did_for_token()` 不再允许 DID 字符串绕过 active 状态；token verify、DID verify、WS ticket、`get_me`、`update_document`、DID path 和公开 Handle discovery 均拒绝 revoked DID；public `/anp-im/rpc` 白名单未扩大；`replace_did` / `recover_handle` 仍 `not_supported`；未调用外部 User Service、Message Service 或 `awiki.info`；未修改相邻仓库 | `PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py::test_did_auth_revoke_marks_did_inactive_and_blocks_auth_paths -q` 1 passed；`PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py -q` 12 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 38 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step22-asgi-final` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step22-cross-final --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step22-rust-cli-final --clean` pass；`verify-public https://rwiki.info` 仍为预期 404 | merged | pass/online-pending | 继续 Step 09 公网 Gate：`rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| 23 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 | 未提交 | Review：`inbox.mark_read` 已由本仓更新当前 owner 的 `direct_message_views.read_at`，不可见 message id 不更新；默认 `inbox.get` 只返回未读，`include_read` 和 `direct.get_history` 投影准确 `is_read/read_at`；`read_state.mark_read` thread watermark 语义未改变；public `/anp-im/rpc` 白名单未扩大；未调用外部 User Service、Message Service 或 `awiki.info`；未修改相邻仓库 | `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_inbox_mark_read_updates_owner_view_and_filters_default_inbox -q` 1 passed；`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q` 19 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 39 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step23-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step23-cross --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step23-rust-cli --clean` pass；`verify-public https://rwiki.info` 仍为预期 404 | merged | pass/online-pending | 继续 Step 09 公网 Gate：`rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| 24 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 | 未提交 | Review：`inbox.get`、`inbox.mark_read`、`direct.get_history` 均校验可选 `meta.sender_did` / `user_did` 与当前 token DID 一致；旧 flat 参数仍兼容；`inbox.get` 支持 `skip/limit`，`direct.get_history` 支持 `since_seq/since/skip/limit` 且 `since_seq` 优先；废弃 `group_did` history 路径返回明确错误；delegated local view 明确 `not_supported`；public `/anp-im/rpc` 白名单未扩大；未修改相邻仓库 | `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_local_view_params_validate_owner_and_support_pagination -q` 1 passed；`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q` 20 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 40 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step24-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step24-cross --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step24-rust-cli --clean` pass；`verify-public https://rwiki.info` 仍为预期 404 | merged | pass/online-pending | 继续 Step 09 公网 Gate：`rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| 25 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 | 未提交 | Review：`group.list_members` / `group.list_messages` 现在要求当前 DID 是群成员，非成员返回 `group.not_member`；`group.leave` 删除前先校验成员身份，非成员不写 sync event、不推 realtime；`group.get_info` 保留公开最小信息以支持 open-join discovery；`group.send` 既有成员校验不回归；群创建/管理仍 `not_supported`；public `/anp-im/rpc` 白名单未扩大 | `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_group_participant_local_views_require_membership -q` 1 passed；`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q` 21 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 41 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step25-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step25-cross --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step25-rust-cli --clean` pass；`verify-public https://rwiki.info` 仍为预期 404 | merged | pass/online-pending | 继续 Step 09 公网 Gate：`rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| 26 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 | 未提交 | Review：`group.list/list_members/list_messages` 现在校验可选 `meta.sender_did` / `user_did` 与当前 token DID 一致；`group.list_members` 和 `group.list_messages` 校验 `meta.target.kind=group` 与 target DID；`group.list_messages` 支持 `since_seq/since_event_seq/skip/limit` 并返回 `next_since_seq/next_server_seq/total/has_more`；`sync.thread_after` group 分支先校验成员身份，非成员返回 `group.not_member`，不能绕过 Step 25；旧 flat 调用保持兼容；public `/anp-im/rpc` 白名单未扩大；未修改相邻仓库 | `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_group_participant_local_views_require_membership tests/test_messaging_objects.py::test_group_local_views_support_anp_params_and_pagination -q` 2 passed；`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q` 22 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 42 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step26-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step26-cross --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step26-rust-cli --clean` pass；`verify-public https://rwiki.info` 仍为预期 404 | merged | pass/online-pending | 继续 Step 09 公网 Gate：`rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| 27 | done-with-pending-online-gate | main | 串行 | 当前 worktree | 8f334b7 | 2026-07-03 | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 | 未提交 | Review：`direct.get_history`、`inbox.get`、`group.list_messages` 和 `sync.thread_after` direct/group 分支均使用 Message Service 兼容投影；JSON 返回 `type=json`，附件清单返回 `type=attachment_manifest`，二进制扩展返回 `type=binary`；`body` 与 `content_type` 保留；旧 flat text CLI 路径不回归；public `/anp-im/rpc` 白名单未扩大；未修改相邻仓库 | `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_application_json_payload_shape_and_daemon_heartbeat_no_store tests/test_messaging_objects.py::test_message_local_views_project_payload_attachment_and_binary_content tests/test_messaging_objects.py::test_sync_delta_thread_after_and_read_state_standard_shapes -q` 3 passed；`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q` 23 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 43 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step27-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step27-cross --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step27-rust-cli --clean` pass；`verify-public https://rwiki.info` 仍失败 404，归 Step 09 公网路由 | merged | pass/online-pending | 后续入口迁移到 `plan/20260703-awiki-open-server-mvp-reset/plan.md`；真实公网 Gate 仍归 Step 09 |

## 9. Codex Goal 执行协议

- 将本 Plan 作为执行进度的唯一事实来源。
- 启动或恢复前，读取本 Plan、当前小 Plan、执行台账和当前 `git status`。
- 本计划全部串行执行；不得跳过依赖步骤。
- 每个步骤依次标记状态、实现、验证、Review、修复或记录风险。
- 本目标只允许修改 `awiki-open-server`；相邻仓库只作为阅读依据，任何需要同步到 `awiki-harness`、`user-service`、`message-service`、`awiki-cli-rs2` 或其他工程的事项只记录为后续风险，不在本次目标中修改。
- 改变范围、公开契约、数据模型或验证策略前，先更新 Plan 变更记录。

## 9.1 Codex Goal 提示词

```text
请以 `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md` 为唯一规划入口，按文档执行完整实现。

开始前先读取主 Plan、当前第一个未 done / 未完成线上 Gate 的 Step 文档、执行台账、验证策略和当前 `git status --short --branch`。本计划默认串行执行；每步都要按对应小 Plan 实现、运行列出的 pytest/CLI 验证、做 Review、修复或记录发现，并回填执行台账。

核心注意点：
- Community 版支持群参与，不支持群创建/管理和 Group E2EE。
- `/im/rpc` 与 `/anp-im/rpc` 暴露面必须分离。
- 跨域 direct 是 DID discovery direct call，不是 federation peer routes 或 relay。
- `awiki.info` 只能作为远端对端服务；本开源 server 要发布自己的 DID document 和 `/anp-im/rpc`。
- 本仓必须自行实现 AWiki 服务端能力，不能使用 `awiki.info` 作为后端、fallback、代理、认证服务、消息存储或内部服务依赖。
- 真实 awiki.info 互通必须保留 CLI 业务 `auth.origin_proof`，并使用本服务 `serviceDid` 做 HTTP Signature / DID WBA；dev proof 只能作为本地模拟证据。
- 本地 CLI smoke 必须通过；线上互通验证必须至少包含“本服务用户 -> awiki.info 用户”和“awiki.info 用户 -> 本服务用户”两个方向，不能用“两端都连接 awiki.info”代替。
- 不要写入其他仓库；如果实现中发现其他仓库需要配合修改，只在本 Plan 中记录后续事项并向用户说明。
```

## 10. 小 Plan 摘要

### Step 01：服务骨架与存储

- 小 Plan：[steps/01-service-skeleton.md](steps/01-service-skeleton.md)
- 目标：FastAPI app、settings、JSON-RPC、sqlite store、health。
- 验证方式：`python3 -m pytest tests/test_health.py -q`。

### Step 02：身份、Profile、Pages

- 小 Plan：[steps/02-identity-pages.md](steps/02-identity-pages.md)
- 目标：`/did-auth/rpc`、`/did/profile/rpc`、`/content/rpc`、公开 `.md`。
- 验证方式：focused pytest。

### Step 03：消息、群参与、附件

- 小 Plan：[steps/03-messaging-objects.md](steps/03-messaging-objects.md)
- 目标：`/im/rpc`、`/anp-im/rpc`、direct、group participant、attachment、sync/read-state。
- 验证方式：focused pytest。

### Step 04：CLI smoke 与测试

- 小 Plan：[steps/04-cli-tests.md](steps/04-cli-tests.md)
- 目标：本仓库 CLI 覆盖本地 smoke；支持线上 `awiki.info` 远端诊断与本服务 DID 域配置。
- 验证方式：`python3 scripts/awiki_open_cli.py smoke-local --base-url ...`；可选 `smoke-awiki-info`。

### Step 05：最终 Review 与文档同步

- 小 Plan：[steps/05-final-verification.md](steps/05-final-verification.md)
- 目标：全量 pytest、CLI、本地/远端证据、README 更新。

### Step 06：真实跨域互通加固

- 小 Plan：[steps/06-interop-hardening.md](steps/06-interop-hardening.md)
- 目标：把“本地模拟跨域”收敛为可与线上 `awiki.info` 互通的协议实现。
- 验证方式：focused pytest、全量 pytest、Rust CLI 连接本服务、公开域名下与 `awiki.info` 用户双向 direct。

### Step 07：架构边界复核与互通收敛

- 小 Plan：[steps/07-architecture-boundary-review.md](steps/07-architecture-boundary-review.md)
- 目标：按用户更正复核方案和实现，确认本仓是独立开源 server，`awiki.info` 只作为线上互通测试对象；补齐文档中的执行边界、验证缺口和后续修复点。
- 验证方式：文档/代码 grep、compileall、全量 pytest、ASGI smoke、Rust CLI 本地连接验证；真实 `awiki.info` Gate 仍需要本服务公开域名。

### Step 08：User Service / Message Service 互通收敛

- 小 Plan：[steps/08-service-interop-convergence.md](steps/08-service-interop-convergence.md)
- 目标：用现有 Rust CLI 连接本服务，验证本仓实现的 User Service 兼容路由和 Message Service direct/group/page 行为；按失败点只修本仓，无法在本仓修复的相邻服务问题记录 blocker。
- 验证方式：隔离 `HOME`/CLI workspace 的 Rust CLI 本地 Gate、全量 pytest、ASGI smoke；真实线上 `awiki.info` peer Gate 或明确 blocker。

### Step 09：公网 rwiki.info 与 awiki.info 双向互通 Gate

- 小 Plan：[steps/09-public-rwiki-awiki-gate.md](steps/09-public-rwiki-awiki-gate.md)
- 目标：完成真实公网部署检查和线上 `awiki.info` 双向 direct/inbox/history Gate。
- 验证方式：`verify-public --base-url https://rwiki.info --did-domain rwiki.info` 先通过；随后用两个隔离 Rust CLI workspace 分别连接 `rwiki.info` 和 `awiki.info`，验证双向 direct。

### Step 10：User / Message Service 兼容形态补齐

- 小 Plan：[steps/10-service-shape-convergence.md](steps/10-service-shape-convergence.md)
- 目标：继续补齐本仓可自行修复的 User Service / Message Service 兼容形态，包括公开 Handle 解析、旧 auth/token/ws ticket、基础 `/im/ws`、标准 sync/read-state/attachment 响应字段。
- 验证方式：全量 pytest、ASGI smoke、隔离 Rust CLI 本地 Gate；真实公网互通仍由 Step 09 证明。

### Step 11：协议边缘兼容收敛

- 小 Plan：[steps/11-protocol-edge-convergence.md](steps/11-protocol-edge-convergence.md)
- 目标：补齐 Step 10 后继续发现的协议边缘兼容：read-state 不写未知 sync event、message id watermark 校验、只有 `body` 的 envelope 展开、上传 header token、默认群 DID 跟随 domain、公开 `group.join` proof/signature。
- 验证方式：全量 pytest、ASGI smoke、双实例本地跨域 Gate；真实公网互通仍由 Step 09 证明。

### Step 12：Message Service 实时通知兼容补齐

- 小 Plan：[steps/12-realtime-notification-convergence.md](steps/12-realtime-notification-convergence.md)
- 目标：把 `/im/ws` 从一次性 sync hint 补成保持连接的本进程 realtime fanout，覆盖 `direct.incoming`、`group.incoming` 和 `group.state_changed`。
- 验证方式：focused WebSocket tests、全量 pytest、ASGI smoke；真实公网互通仍由 Step 09 证明。

### Step 13：User Service auth_request 与 dev 登录兼容补齐

- 小 Plan：[steps/13-user-service-auth-compat.md](steps/13-user-service-auth-compat.md)
- 目标：补齐 User Service/nginx 常见 `auth_request` 兼容路径、`X-User-Id` header、WS ticket header 验证和 dev SMS OTP 登录/注册，避免 `rwiki.info` 切到本仓后卡在认证验证面。
- 验证方式：focused auth compat pytest、全量 pytest、ASGI smoke、双实例本地跨域 Gate；真实公网互通仍由 Step 09 证明。

### Step 14：User Service Profile REST/RPC 与 Message Service health 兼容补齐

- 小 Plan：[steps/14-profile-health-compat.md](steps/14-profile-health-compat.md)
- 目标：补齐 User Service 旧 profile 入口 `/me`、`/me/rpc`、`/profiles/{user_id}`、`/user-service/profiles/{user_id}`、`/users/{user_id}/profile`，并补齐 Message Service 常见 `/im/healthz` 健康检查别名。
- 验证方式：focused profile/health pytest、全量 pytest、ASGI smoke、双实例本地跨域 Gate；真实公网互通仍由 Step 09 证明。

### Step 15：Directory / Site 兼容面补齐

- 小 Plan：[steps/15-directory-site-compat.md](steps/15-directory-site-compat.md)
- 目标：补齐现有 Rust CLI / User Service 暴露出的 DID relationship、phone bind dev、`/site/rpc` 与公开 Markdown site 路由。
- 验证方式：focused directory/site pytest、全量 pytest、ASGI smoke、双实例本地跨域 Gate；真实公网互通仍由 Step 09 证明。

### Step 16：Rust CLI 本地互通 Gate 自动化

- 小 Plan：[steps/16-rust-cli-local-gate.md](steps/16-rust-cli-local-gate.md)
- 目标：把现有 Rust CLI 连接本仓的 User Service / Message Service / Directory / Site 兼容验证固化为 `smoke-rust-cli-local`。
- 验证方式：构建隔离 `awiki-cli-rs2` 二进制，运行 `smoke-rust-cli-local`、全量 pytest、ASGI smoke、双实例本地跨域 Gate；真实公网互通仍由 Step 09 证明。

### Step 17：Users RPC 与 Agent Inventory 兼容补齐

- 小 Plan：[steps/17-users-agent-inventory-compat.md](steps/17-users-agent-inventory-compat.md)
- 目标：补齐 User Service `/users/rpc` 查询面，以及 `awiki-cli-rs2` daemon 使用的 `/user-service/agent-inventory/rpc` 最小响应面。
- 验证方式：focused users/agent-inventory pytest、compileall、全量 pytest、ASGI smoke、双实例本地跨域 Gate；真实公网互通仍由 Step 09 证明。

### Step 18：Message payload 与 daemon heartbeat 兼容收敛

- 小 Plan：[steps/18-message-payload-heartbeat-compat.md](steps/18-message-payload-heartbeat-compat.md)
- 目标：对齐 Message Service direct/group 普通结构化消息规则，严格绑定 `meta.content_type` 与 `body` 字段；对 daemon liveness heartbeat 返回 `delivery_state=ephemeral` 且不写入历史、inbox 或 sync。
- 验证方式：focused messaging pytest、compileall、全量 pytest、ASGI smoke、双实例本地跨域 Gate；真实公网互通仍由 Step 09 证明。

### Step 19：ANP envelope meta 必填字段收敛

- 小 Plan：[steps/19-anp-envelope-meta-compat.md](steps/19-anp-envelope-meta-compat.md)
- 目标：只对 ANP envelope 形态的 `direct.send` / `group.send` 收紧 `meta.sender_did`、`meta.target.kind`、`meta.target.did`、`meta.operation_id`、`meta.message_id`、`meta.content_type` 必填，并校验 target DID 与业务目标一致。
- 验证方式：focused messaging pytest、compileall、全量 pytest、ASGI smoke、双实例本地跨域 Gate、Rust CLI local Gate；真实公网互通仍由 Step 09 证明。

### Step 20：DID Verify JSON-RPC 兼容补齐

- 小 Plan：[steps/20-did-verify-compat.md](steps/20-did-verify-compat.md)
- 目标：补齐 User Service `/did-verify/rpc` 与 `/user-service/did-verify/rpc` 的 `send_code`、`login`、`refresh` 最小兼容。
- 验证方式：focused DID verify pytest、compileall、全量 pytest、ASGI smoke、双实例本地跨域 Gate、Rust CLI local Gate；真实公网互通仍由 Step 09 证明。

### Step 21：Attachment ticket ANP 兼容补齐

- 小 Plan：[steps/21-attachment-ticket-compat.md](steps/21-attachment-ticket-compat.md)
- 目标：让 `attachment.get_download_ticket` 同时兼容现有本地 `object_id` 调用和 Message Service ANP `body.object_uri/requester_did/sender_did/message_id/message_security_profile/message_target_did|group_did` 调用，响应补齐 `download_ticket_b64u` 与 `ticket_binding`，数据面下载同时支持 `?ticket=` 和 `Authorization: Bearer <download_ticket>`。
- 验证方式：focused attachment pytest、compileall、全量 pytest、ASGI smoke、双实例本地跨域 Gate、Rust CLI local Gate；真实公网互通仍由 Step 09 证明。

### Step 22：DID revoke 兼容补齐

- 小 Plan：[steps/22-did-revoke-compat.md](steps/22-did-revoke-compat.md)
- 目标：补齐 User Service `/did-auth/rpc revoke` 的 Community 最小语义：当前 DID 被标记 revoked，撤销后不能再通过 token、DID verify、WS ticket、auth verify、`get_me` 或 `update_document` 作为 active DID 使用。
- 验证方式：focused identity pytest、compileall、全量 pytest、ASGI smoke、双实例本地跨域 Gate、Rust CLI local Gate；真实公网互通仍由 Step 09 证明。

## 11. Review 策略

- 每步骤 Review：检查方法暴露面、not_supported、数据持久化、测试覆盖。
- 契约 Review：确认 `group.create` 等管理方法禁用；`group.join` 等参与方法可用。
- 安全 Review：dev token 仅用于 Community 本地；远端 awiki.info/rwiki.info 验证不得提交真实 token。
- 文档 Review：README 和 Plan 证据同步。

## 12. 验证策略

| 层级 | 适用 Step / 并行组 | 命令 / 检查 | 运行时机 | 预期证据 | 门禁结果 |
|---|---|---|---|---|---|
| Step Unit | Step 01 | `python3 -m pytest tests/test_health.py -q` | Step 01 后 | health/schema pass | pass |
| API Unit | Step 02/03 | `python3 -m pytest tests -q` | Step 03 后 | 全部本地测试 pass | pass |
| CLI Local | Step 04 | `python3 scripts/awiki_open_cli.py smoke-local --base-url http://127.0.0.1:<port>` | 服务启动后 | 身份、私聊、群参与、附件、Pages pass | pass |
| Existing Rust CLI | Step 04 | 独立 `awiki-cli-rs2` worktree + 临时 workspace，运行 `awiki-cli id/msg/page/group` | 服务启动后 | identity、handle lookup、direct、inbox/history/mark-read、Pages CRUD、group join/send/messages pass；`group.create` 返回 `not_supported` | pass |
| Remote DID Discovery Unit | Step 04/05 | monkeypatch DID document fetch 与远端 `/anp-im/rpc` POST，调用本服务 `/im/rpc direct.send` 到远端 DID | Step 04 后 | 本服务解析远端 DID document，POST `direct.send` 到远端 `serviceEndpoint`，本地 sender history 可见 | pass |
| Public Inbound Direct Unit | Step 04/05 | 调用本服务 `/anp-im/rpc direct.send`，sender 为远端 DID，target 为本地/非本地 DID | Step 04 后 | 本地 target 被投递；非本地 target 返回 `recipient_not_local`，不成为 relay | pass |
| Interop Hardening Unit | Step 06 | monkeypatch 远端 POST 和请求 headers，验证 `auth.origin_proof` 原样透传、`x-anp-source-service-did`、`Signature-Input`、`Signature`、`Content-Digest` 存在，并验证 inbound proof/signature 缺失会拒绝 | Step 06 后 | 不再生成 fake remote proof；公开入口不接受无 proof/hop auth 的真实 direct | pass |
| Boundary Review | Step 07 | grep 检查 `awiki.info` 仅用于远端测试/fixture，`/user-service/...` 兼容路由由本仓实现；复核 `require.md`、README、Plan、核心服务代码 | Step 07 | 不存在把 `awiki.info` 当本服务依赖的设计或实现；如有偏差，只改本仓 | pass |
| Corrected Boundary Re-review | Step 07/09/16 | 复核 `require.md`、`README.md`、`src/awiki_open_server/app/settings.py`、`src/awiki_open_server/app/routes.py`、`src/awiki_open_server/services.py`、`deploy/` 和 Plan，确认 `awiki.info` 只作为远端 peer；`rwiki.info` 必须由本仓发布 DID document 和 `/anp-im/rpc` | 2026-07-03 用户再次更正后 | 当前方案和代码符合自实现 open server 模型；剩余真实 Gate 是公网 `rwiki.info` 路由和线上 `awiki.info` 双向 direct 验证 | pass/online-pending |
| Rust CLI Interop | Step 08 | 隔离 `HOME` 和 `AWIKI_CLI_WORKSPACE_HOME_DIR`，现有 `awiki-cli-rs2` 二进制连接本服务；注册两个用户，验证 direct、inbox/history、Pages、group participant，管理方法返回 `not_supported` | Step 08 | CLI 能把本仓当作 User Service / Message Service 兼容服务使用；`doctor` 对 loopback ANP endpoint 的 error 只说明本地地址不能用于公开 DID 发现 | pass |
| Public Deployment Check | Step 08 | `python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info` | Step 08 后、真实线上 Gate 前 | 验证 `rwiki.info` 是否由本仓服务发布 service DID document、healthz 和 `/anp-im/rpc` capability | fail-current-domain-not-routed |
| Service Shape Convergence | Step 10 | `python3 -m pytest tests -q` + `python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step10-asgi` + 隔离 Rust CLI 本地 Gate + `python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-cross-domain-local-final --clean` | Step 10 后 | WNS handle、旧 auth/token/ws ticket、基础 `/im/ws`、sync/read-state/attachment 标准字段可用，且不破坏现有 CLI Gate；两个独立本仓实例可用真实 service DID HTTP Signature 和 origin proof 完成双向跨域 direct | pass |
| Protocol Edge Convergence | Step 11 | `python3 -m pytest tests -q` + `python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step11-asgi` + `python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step11-cross --clean` | Step 11 后 | read-state 不产生未知 sync event；message id watermark 校验；attachment header token；动态默认群 DID；公开 `group.join` proof/signature；双实例跨域 direct 不回归 | pass |
| Realtime Notification Convergence | Step 12 | `python3 -m pytest tests/test_health.py::test_im_websocket_receives_direct_and_group_notifications -q` + `python3 -m pytest tests -q` + `python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step12-asgi` | Step 12 后 | `/im/ws` 保持连接；本地 direct 可推送 `direct.incoming`；群成员加入可推送 `group.state_changed`；群消息可推送 `group.incoming`；不破坏现有 ASGI smoke | pass/online-pending |
| User Service Auth Compat | Step 13 | `python3 -m pytest tests/test_identity_pages.py::test_legacy_auth_and_ws_ticket_compat_routes -q` + `python3 -m pytest tests -q` + `python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step13-asgi` + `python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step13-cross --clean` | Step 13 后 | dev SMS OTP 登录/注册；token/session/auth verify 返回 `X-User-Id`；WS ticket 可通过 query/header 验证；不破坏现有本地和跨域 Gate | pass/online-pending |
| Profile/Health Compat | Step 14 | `python3 -m pytest tests/test_health.py::test_healthz tests/test_identity_pages.py::test_legacy_me_profile_and_message_health_compat_routes -q` + `python3 -m pytest tests -q` + `python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step14-asgi-rerun` + `python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step14-cross-rerun --clean` | Step 14 后 | `/im/healthz` 返回健康；`/me`、`/me/rpc`、公开 profile REST/Markdown 由本仓本地 profile 数据返回；REST 错误映射为 401/404；不破坏现有本地和跨域 Gate | pass/online-pending |
| Directory/Site Compat | Step 15 | `python3 -m pytest tests/test_identity_pages.py::test_did_relationship_phone_bind_and_site_rpc_compat -q` + `python3 -m pytest tests -q` + `python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step15-asgi` + `python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step15-cross --clean` | Step 15 后 | DID relationship、phone bind dev、`/site/rpc` 和公开 Markdown site 路由由本仓本地实现；不破坏现有本地和跨域 Gate | pass/online-pending |
| Rust CLI Local Gate Automation | Step 16 | `CARGO_TARGET_DIR=/tmp/awiki-cli-rs2-open-server-target cargo build -p awiki-cli --bin awiki-cli --locked`；`python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-rust-cli-script --clean` | Step 16 后 | 自动启动本仓临时 server，创建两个隔离 Rust CLI workspace，验证 dev phone OTP 注册、direct/inbox/history、group、people、site；不修改 `awiki-cli-rs2`，不替代公网 Gate | pass/online-pending |
| Users/Agent Inventory Compat | Step 17 | `python3 -m pytest tests/test_identity_pages.py::test_users_rpc_compat_routes tests/test_identity_pages.py::test_agent_inventory_minimal_compat_routes -q` + `python3 -m compileall -q src scripts tests` + `python3 -m pytest tests -q` + ASGI smoke + 双实例本地跨域 Gate | Step 17 后 | `/users/rpc` 和 `/user-service/users/rpc` 支持 get_me/get_by_did/get_by_dids/get_by_handle；`/user-service/agent-inventory/rpc` 支持 daemon latest status、controller scope、sender verification、invocation authorization、archive/list/update policy 的 Community 最小形态 | pass/online-pending |
| Message Payload/Heartbeat Compat | Step 18 | `python3 -m pytest tests/test_messaging_objects.py::test_application_json_payload_shape_and_daemon_heartbeat_no_store -q` + `python3 -m compileall -q src scripts tests` + `python3 -m pytest tests -q` + ASGI smoke + 双实例本地跨域 Gate + Rust CLI local Gate | Step 18 后 | direct/group `application/json` 保留 `body.payload` 对象；错误 body shape 被拒绝；daemon heartbeat 返回 `ephemeral` 且不进入 inbox/history/sync；非 heartbeat agent status 仍持久化；旧 Rust CLI flat text 路径不回归 | pass/online-pending |
| ANP Envelope Meta Compat | Step 19 | `python3 -m pytest tests/test_messaging_objects.py::test_anp_envelope_meta_required_fields_and_target_validation -q` + `python3 -m compileall -q src scripts tests` + `python3 -m pytest tests -q` + ASGI smoke + 双实例本地跨域 Gate + Rust CLI local Gate | Step 19 后 | direct/group ANP envelope 缺少必填 meta 或 target 不一致会被拒绝；旧 flat text CLI 路径不回归 | pass/online-pending |
| DID Verify Compat | Step 20 | `python3 -m pytest tests/test_identity_pages.py::test_did_verify_rpc_compat_routes -q` + `python3 -m compileall -q src scripts tests` + `python3 -m pytest tests -q` + ASGI smoke + 双实例本地跨域 Gate + Rust CLI local Gate | Step 20 后 | `/did-verify/rpc` 与 `/user-service/did-verify/rpc` 支持 `send_code`、`login`、`refresh`；只使用本仓本地 DID/user/token；未知 DID、错误 code、无效 refresh token 返回 JSON-RPC error；不破坏现有 Rust CLI 注册流 | pass/online-pending |
| Attachment Ticket Compat | Step 21 | `python3 -m pytest tests/test_messaging_objects.py::test_attachment_download_ticket_accepts_anp_body_shape -q` + `python3 -m compileall -q src scripts tests` + `python3 -m pytest tests -q` + ASGI smoke + 双实例本地跨域 Gate + Rust CLI local Gate | Step 21 后 | `attachment.get_download_ticket` 支持 `object_uri`、`requester_did`、`sender_did`、`message_id`、`message_security_profile`、`message_target_did/group_did` 请求形态；返回 `download_ticket_b64u` 和 `ticket_binding`；`GET /objects/{object_id}` 支持 Bearer download ticket；本地 owner 路径与 Rust CLI 不回归；不实现跨域上传代理或 E2EE 授权 | pass/online-pending |
| DID Revoke Compat | Step 22 | `python3 -m pytest tests/test_identity_pages.py::test_did_auth_revoke_marks_did_inactive_and_blocks_auth_paths -q` + `python3 -m compileall -q src scripts tests` + `python3 -m pytest tests -q` + ASGI smoke + 双实例本地跨域 Gate + Rust CLI local Gate | Step 22 后 | `/did-auth/rpc revoke` 返回成功并写入本仓 revoked 状态；后续 token/auth/session/ws-ticket/DID verify login/refresh/get_me/update_document 都拒绝 revoked DID；DID document 不再作为 active 文档发布；replace/recover 仍不支持；不调用外部 User Service 或 `awiki.info` | pass/online-pending |
| Real awiki.info Interop | Step 09 | 一个 CLI 连接本服务公开域名；一个 CLI/已有用户连接 `awiki.info`；双向 direct + inbox/history | 需要本服务公网域名、本服务 service DID 可解析、HTTP Signature/DID WBA 可验证、线上 proof 可接受 | 待运行；若 awiki.info 侧在本仓收敛后仍拒绝本服务 DID/proof/signature，记录 blocker 由用户确认后再决定是否调整线上服务或协议参考 | pending |
| Final | Step 09 | `python3 -m pytest tests -q` + Rust CLI + real interop gate 或 blocker 证据 | 完成前 | 本仓本地协议收敛完成；真实 awiki.info Gate 仍待公网部署条件，不能用本地 loopback 证明 | pass/online-pending |

## 13. 文档更新

- Harness 文档：本目标不修改其他仓库；最终只记录是否需要后续同步。
- 子仓库文档：更新 `awiki-open-server/README.md` 和本 Plan。
- 本次生成文档：`awiki-open-server/plan/20260702-awiki-open-server-mvp/`。

## 14. Commit 计划

- 目标是一 Step 一个聚焦 commit；当前工作区有未跟踪 `AGENTS.md`、`require.md`，提交前需只纳入当前步骤相关文件。
- 如果用户未要求实际 commit，可记录建议 commit gate，但不强制执行 `git commit`。

## 15. Blocked 处理

| Blocker | Step | Agent | 并行组 | 证据 | 已尝试方案 | 影响范围 | 是否暂停同组 | 下一步决策 |
|---|---|---|---|---|---|---|---|---|
| `rwiki.info` 当前未路由到本仓 open server | 08/09 | main | 串行 | 2026-07-03 13:00 CST 复查：`getent hosts rwiki.info awiki.info` 均解析到同一公网 IP；`https://rwiki.info/healthz` 由 nginx 返回 404；只读查看当前 nginx `rwiki.info.conf`，其 `/.well-known/did.json`、handle、pages 等路径代理到 `127.0.0.1:9891` user-service，缺少 `/healthz`、`/anp-im/rpc`、`/im/rpc` 等本仓路由；Step 19 后复跑 `PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info` 仍失败：service DID document 404、healthz 404、`anp.get_capabilities` 404 | 新增 `deploy/` systemd/nginx/env 模板；新增 `verify-public`；本仓测试、ASGI smoke、Rust CLI 本地 Gate 和双实例跨域 Gate 均通过；Step 19 继续补齐本仓 ANP envelope meta 兼容 | 真实线上 Gate | 否 | 按 `awiki-open-server/deploy/` 模板将 `rwiki.info` 切到本仓服务；切换后先跑 `verify-public`，再与 `awiki.info` 用户做双向 direct |
| 真实公网互通尚未证明 | 09 | main | 串行 | Step 10 已证明本仓可修兼容形态、本地门禁、Rust CLI 本地 Gate 和双实例本地跨域 Gate；`rwiki.info` 仍需切到本仓后运行 `verify-public` 和双向 CLI Gate | 本仓已补齐服务形态并新增测试；ASGI smoke 通过；隔离 Rust CLI 本地 Gate 通过；双实例跨域 Gate 通过 | 最终互通完成标准 | 否 | 继续 Step 09；不能把本地 pytest/CLI Gate 或双实例本地 Gate 当作真实 `awiki.info` 互通完成 |
| 本轮复核未发现 `awiki.info` 运行时依赖 | 07/09/16 | main | 串行 | `require.md` 明确本仓必须自行实现 `awiki.info` 类服务；`README.md` 明确不是 `awiki.info` proxy；`settings.py` 只从本仓环境变量生成 DID/service endpoint；`routes.py` 的 `/user-service/...` 均本地 dispatch；`services.py` 出站 direct 只按 recipient DID document discovery 调用远端 `ANPMessageService.serviceEndpoint` | 已用 `rg` 和代码阅读复核；无需修改代码 | 设计边界 | 否 | 保持 Step 09：完成公网路由后再做真实 `awiki.info` 用户互通；若对端拒绝且本仓证据完整，再记录 blocker |

## 16. Plan 变更记录

| 日期 | 变更 | 原因 | 影响步骤 | 是否需要 Review |
|---|---|---|---|---|
| 2026-07-02 | 新增本服务 DID 域（例如 `rwiki.info`）与线上 `awiki.info` 对等服务的跨域验证 Gate | 用户要求使用本服务域用户 DID 与 `awiki.info` 用户验证跨域互通 | 04/05 | 是 |
| 2026-07-02 | 明确远端验证请求必须使用 ANP `params.meta/auth/body` 包装，并收紧“只修改当前工程”的硬约束 | 线上 `awiki.info` 服务按 ANP 参数 envelope 校验；用户要求开发过程中不要修改其他项目 | 04/05 | 是 |
| 2026-07-02 | 将远端请求形态细化为 capability `params.meta/body`、direct `params.meta/auth/body` | `awiki.info` capability 不接受空 `auth` 对象；direct 需要真实 `auth.origin_proof` | 04/05 | 是 |
| 2026-07-03 | 补充现有 Rust CLI `awiki-cli-rs2` 真实连接验证，并同步服务端兼容路由/响应形态 | 用户指出仅用本仓 smoke 不够，要求用现有 CLI 连接本服务验证 | 02/03/04/05 | 是 |
| 2026-07-03 | 按旧理解尝试用现有 Rust CLI 注册线上真实 DID 并准备跨域互通验证 | 当时理解为可用线上 `awiki.info` 同时承载 `awiki.info` 与 `rwiki.info` DID 域；该验证后来已撤销为无效证据 | 04/05 | 是 |
| 2026-07-03 | 按旧理解使用默认开发手机号/OTP 完成线上 Rust CLI 跨 DID 域互通验证 | 该结果只证明线上 `awiki.info` 自身支持多 DID 域用户，不证明本仓 server；已在验证证据中标为无效 | 04/05 | 是 |
| 2026-07-03 | 撤销“两端 CLI 都连接 awiki.info”作为本项目互通证据，并改为“本开源 server 与 awiki.info 用户互通”的目标 | 用户澄清 awiki.info 是远端线上服务，不是本开源 server 后端；本项目要实现 awiki.info 类服务能力 | 04/05 | 是 |
| 2026-07-03 | 进一步明确本仓必须自行实现 awiki.info 类服务端能力，不能使用 awiki.info 作为服务依赖 | 用户更正：这是开源 server 服务端，测试时才与 awiki.info 用户互通 | 04/05 | 是 |
| 2026-07-03 | 新增 Step 06 真实跨域互通加固 | 复核发现文档边界正确，但代码仍缺 origin proof 透传、service HTTP Signature/DID WBA、service DID 可验证文档和身份兼容细节，不能宣称真实 awiki.info 互通已完成 | 06 | 是 |
| 2026-07-03 | Step 06 状态从完成回滚为进行中 | 复核发现 focused tests 失败，origin proof 校验使用 normalized body 而非 ANP envelope 原始 body；此前 `pytest tests -q 15 passed` 证据已过期 | 06 | 是 |
| 2026-07-03 | 修复 Step 06 origin proof 原始 body 一致性并恢复本地门禁 | `normalize_params` 保留 `_anp_body`，`direct_send` 用原始 envelope body 校验、转发和存储；focused/full/smoke 本地验证通过 | 06 | 是 |
| 2026-07-03 | 补齐业务 origin proof Ed25519 验签 | `direct_send` 解析 sender DID document，校验 proof keyid 属于 `meta.sender_did` 且位于 `authentication`，并验证 RFC9421 origin proof 签名；新增无效签名拒绝测试 | 06 | 是 |
| 2026-07-03 | 按用户更正收敛架构表述 | 本仓必须自行实现 awiki.info 类服务端能力；`awiki.info` 只作为线上对等测试对象，User Service/Message Service 只作为只读协议参考 | 04/05/06 | 是 |
| 2026-07-03 | 新增 Step 07 架构边界复核与互通收敛 | 用户进一步更正：本仓是开源 server 服务端，不能使用 `awiki.info` 域服务；测试时才与 `awiki.info` 用户互通，需要再次检查方案是否按该模型设计实现 | 07 | 是 |
| 2026-07-03 | 新增 Step 08 User Service / Message Service 互通收敛 | 用户要求继续完成缺口：极简开源服务器必须能与 User Service、Message Service 行为互通；如果相邻服务确有问题，先修本仓再记录 blocker | 08 | 是 |
| 2026-07-03 | Step 08 本地 Rust CLI 兼容 Gate 完成并保留线上 Gate | 使用现有 Rust CLI 隔离 workspace 验证本仓 User Service 兼容路由、Message Service direct/page/group participant；同时确认本仓未把 `awiki.info` 作为后端，真实线上 `awiki.info` 双向互通仍需要本服务公网 HTTPS 域名和 service DID 私钥 | 08 | 是 |
| 2026-07-03 | 补齐公开部署交付物和公网验证脚本 | 实测 `rwiki.info` DNS 已存在但当前没有路由到本仓服务；为继续推进真实线上 Gate，在本仓新增 `deploy/` 模板、`verify-public` 和测试，明确切换前置条件 | 08 | 是 |
| 2026-07-03 | 新增 Step 09 公网 rwiki.info 与 awiki.info 双向互通 Gate | Step 08 已完成本地兼容和部署材料，但真实线上 Gate 仍依赖域名切换；新增独立步骤避免把部署切换和业务互通混在已完成 Step 08 内 | 09 | 是 |
| 2026-07-03 | 新增 Step 10 User / Message Service 兼容形态补齐 | 用户要求继续完成“极简开源服务器能与 User Service、Message Service 互通”的缺口；本仓先补可自行修复的公开 Handle、旧 auth/token/ws ticket、基础 `/im/ws`、sync/read-state/attachment 响应形态 | 10 | 是 |
| 2026-07-03 | Step 10 Rust CLI 本地 Gate 复跑完成 | 使用隔离 `HOME` 和 CLI workspace 验证 Step 10 补齐后仍兼容现有 Rust CLI：注册、direct、inbox/history、Pages、群参与通过，群创建仍为 `not_supported` | 10 | 是 |
| 2026-07-03 | 复跑最终本地门禁和公网预检 | 本仓 `compileall`、pytest、ASGI smoke 继续通过；`verify-public https://rwiki.info` 仍为 404，真实线上 Gate 继续等待公网路由切换 | 09/10 | 是 |
| 2026-07-03 | 新增双实例本地跨域 Gate 并修复本仓跨域链路问题 | 本地两个独立 open-server 实例运行真实 DID discovery、service HTTP Signature、origin proof 和双向 direct；该 Gate 暴露同步 RPC 外发阻塞事件循环和出站转发改写已签名 `meta` 两个问题，已在本仓修复 | 06/10 | 是 |
| 2026-07-03 | 双实例本地跨域 Gate 纳入 pytest | 新增 `tests/test_cli_smoke.py::test_smoke_cross_domain_local_subprocess`，常规 pytest 会启动两个本仓 Uvicorn 子进程并验证双向跨域 direct，避免后续回归破坏互通链路 | 10 | 是 |
| 2026-07-03 | 补齐 agent-registration/message-agent 最小兼容 | `require.md` 将 agent-registration 与 message-agent binding 标为最小建议子集；本仓新增 SQLite 表、RPC handlers 和 `/user-service/...` 路由，覆盖 token issue/verify/exchange/revoke 与 binding ensure/get/list/mark_seen/disable/revoke | 10 | 是 |
| 2026-07-03 | 新增 Step 11 协议边缘兼容收敛 | 继续复核 Message Service 文档和当前实现后发现本仓可修边缘缺口：`read_state.mark_read` 不应写未知 sync event、附件上传应接受返回的 header token、默认群 DID 应跟随 DID domain、公开 `group.join` 应要求 proof/signature、只有 `body` 的兼容 envelope 也应展开 | 11 | 是 |
| 2026-07-03 | Step 11 本仓门禁完成 | compileall、全量 pytest、ASGI smoke、双实例本地跨域 Gate 均通过；`verify-public https://rwiki.info` 仍为 404，继续归属 Step 09 公网路由 blocker | 11/09 | 是 |
| 2026-07-03 | 再次按用户更正复核开源 server 边界 | 用户澄清本仓不能使用 `awiki.info` 域服务承载运行时，必须自行实现 `awiki.info` 类 server；复核结论为当前方案和代码符合该模型，并补强 `require.md` 硬边界说明 | 07/09/11 | 是 |
| 2026-07-03 | 新增 Step 12 Message Service 实时通知兼容补齐 | 继续按最终目标复核后发现 `/im/ws` 仍只是一次性 sync hint，和极简开源 server 需要兼容 Message Service realtime 通知的目标不一致；该缺口可在本仓通过进程内 fanout 修复，不需要修改相邻服务 | 12 | 是 |
| 2026-07-03 | 新增 Step 13 User Service auth_request 与 dev 登录兼容补齐 | 继续对照 User Service 文档和当前 nginx 形态后，发现本仓可自行补齐 `auth_request` header/别名、WS ticket header 验证和 dev SMS 登录/注册；同时确认公网 `rwiki.info` 仍是 nginx 路由未切到本仓 | 13/09 | 是 |
| 2026-07-03 | 新增 Step 14 User Service Profile REST/RPC 与 Message Service health 兼容补齐 | 继续对照 `user-service/docs/user-id-api/profile.md`、`user-service/docs/api/README.md` 和 `message-service/docs/installation.md` 后，发现本仓仍可自行补齐旧 `/me`/公开 profile 路由和 `/im/healthz`，这些能力不需要修改相邻服务 | 14/09 | 是 |
| 2026-07-03 | 新增 Step 15 Directory / Site 兼容面补齐 | 继续对照 `awiki-cli-rs2` wire contract、`user-service/docs/api/did-relationship.md` 和 `user-service/docs/api/site.md` 后，发现本仓仍缺 `/user-service/did/relationships/rpc`、phone bind dev 路由和 `/site/rpc`；这些缺口可在本仓最小实现，不需要修改相邻服务 | 15/09 | 是 |
| 2026-07-03 | 新增 Step 16 Rust CLI 本地互通 Gate 自动化 | 手工 Rust CLI Gate 已证明本仓可被现有 CLI 当作 User Service / Message Service / Directory / Site 兼容服务使用；为避免后续只保留不可重复手工证据，将该 Gate 固化到本仓 `scripts/awiki_open_cli.py smoke-rust-cli-local` | 16/09 | 是 |
| 2026-07-03 | 按用户最新更正再次复核 open server 边界 | 用户澄清本仓不能使用 `awiki.info` 域服务承载运行时，必须自行实现 `awiki.info` 类 server；本轮复核 `require.md`、README、settings、routes、services、deploy 和 Plan，结论为当前方案和代码符合该模型，剩余 blocker 是公网 `rwiki.info` 尚未切到本仓以及真实 `awiki.info` 双向 Gate 未跑 | 07/09/16 | 是 |
| 2026-07-03 | 新增 Step 17 Users RPC 与 Agent Inventory 兼容补齐 | 继续对照 `user-service/docs/api/users.md`、`user-service/src/user_service/app/users/rpc_handlers.py`、`user-service/src/user_service/app/agent_inventory/rpc_handlers.py` 和 `awiki-cli-rs2/crates/awiki-deamon/src/registration/mod.rs` 后，发现本仓仍缺 `/users/rpc` 与 `/user-service/agent-inventory/rpc`；这些缺口可在本仓最小实现，不修改相邻服务 | 17/09 | 是 |
| 2026-07-03 | Step 17 本仓门禁完成 | `/users/rpc`、`/user-service/users/rpc`、`/user-service/agent-inventory/rpc` 已由本仓本地实现；focused pytest、compileall、全量 pytest、ASGI smoke、双实例本地跨域 Gate 均通过；`verify-public https://rwiki.info` 仍 404，继续归 Step 09 | 17/09 | 是 |
| 2026-07-03 | 新增 Step 18 Message payload 与 daemon heartbeat 兼容收敛 | 继续对照 `message-service/docs/api/ANP-client-server-api-direct.md`、`message-service/docs/api/ANP-client-server-api-group.md` 和 `awiki-cli-rs2` daemon/IM 代码后，发现本仓仍缺 `meta.content_type` 与 `body` 绑定校验，以及 daemon heartbeat no-store 语义；这些缺口可在本仓实现，不修改相邻服务 | 18/09 | 是 |
| 2026-07-03 | Step 18 本仓门禁完成 | direct/group payload shape 绑定、message `content_type` 持久化投影和 daemon heartbeat no-store 已在本仓实现；focused pytest、messaging tests、compileall、全量 pytest、ASGI smoke、双实例本地跨域 Gate、Rust CLI local Gate 均通过；真实公网 Gate 仍归 Step 09 | 18/09 | 是 |
| 2026-07-03 | 新增 Step 19 ANP envelope meta 必填字段收敛 | 继续对照 Message Service direct/group 文档后，发现本仓对 ANP envelope 仍会自动生成 `message_id` / `operation_id` 或默认 `content_type`，且未显式校验 target kind/did；这些缺口可在本仓收紧，不影响旧 flat text 兼容路径 | 19/09 | 是 |
| 2026-07-03 | Step 19 本仓门禁完成 | direct/group ANP envelope meta 必填字段和 target 一致性已在本仓实现；focused pytest、messaging tests、compileall、全量 pytest、ASGI smoke、双实例本地跨域 Gate、Rust CLI local Gate 均通过；真实公网 Gate 仍归 Step 09 | 19/09 | 是 |
| 2026-07-03 | Step 19 后复跑公网预检 | `verify-public --base-url https://rwiki.info --did-domain rwiki.info` 仍返回 service DID document 404、healthz 404、`anp.get_capabilities` 404；说明 `rwiki.info` 尚未由本仓服务发布公开 DID document 和 `/anp-im/rpc` | 09 | 是 |
| 2026-07-03 | 新增 Step 20 DID Verify JSON-RPC 兼容补齐 | 继续对照 `user-service/docs/api/did-verify.md` 与 `user-service/src/user_service/app/did_verify/rpc_handlers.py` 后，发现本仓缺 `/did-verify/rpc` 的 `send_code`、`login`、`refresh`；该缺口可在本仓最小实现，不修改相邻服务 | 20/09 | 是 |
| 2026-07-03 | Step 20 本仓门禁完成 | `/did-verify/rpc` 与 `/user-service/did-verify/rpc` 已由本仓本地实现；DID verify 使用 Community dev provider 和 `666666` 默认 code，不调用外部消息服务；focused pytest、compileall、全量 pytest、ASGI smoke、双实例本地跨域 Gate、Rust CLI local Gate 均通过；真实公网 Gate 仍归 Step 09 | 20/09 | 是 |
| 2026-07-03 | Step 20 后复跑公网预检 | `verify-public --base-url https://rwiki.info --did-domain rwiki.info` 仍返回 service DID document 404、healthz 404、`anp.get_capabilities` 404；说明 `rwiki.info` 尚未由本仓服务发布公开 DID document 和 `/anp-im/rpc` | 09 | 是 |
| 2026-07-03 | 新增 Step 21 Attachment ticket ANP 兼容补齐 | 继续对照 `message-service/docs/api/ANP-client-server-api-attachment.md` 与 `message-service/crates/im-attachment/src/handlers.rs` 后，发现本仓 `attachment.get_download_ticket` 仍偏本地 `object_id`/owner 形态，缺少 ANP `body.object_uri/requester_did/sender_did/message_id/message_security_profile/message_target_did|group_did` 请求校验和 `download_ticket_b64u/ticket_binding` 响应字段，数据面也缺 Bearer download ticket；该缺口可在本仓最小实现，不修改相邻服务 | 21/09 | 是 |
| 2026-07-03 | Step 21 本仓门禁完成 | `attachment.get_download_ticket` 已兼容 Message Service ANP ticket 请求/响应形态，数据面支持 Bearer download ticket；本仓只对本地 committed object 和本地 direct/group message context 签票据，不实现跨域上传代理、完整 grant collector、E2EE 授权或远端 object relay；focused pytest、messaging tests、compileall、全量 pytest、ASGI smoke、双实例本地跨域 Gate、Rust CLI local Gate 均通过；真实公网 Gate 仍归 Step 09 | 21/09 | 是 |
| 2026-07-03 | 新增 Step 22 DID revoke 兼容补齐 | 继续对照 `user-service/docs/api/did-auth.md` 后，发现本仓 `/did-auth/rpc revoke` 仍是占位返回，且 `did_for_token()` 允许 DID 字符串直通，会让 revoked DID 绕过 active 状态；该缺口属于本仓可自行修复的 User Service 兼容面，不需要修改相邻服务 | 22/09 | 是 |
| 2026-07-03 | Step 22 本仓门禁完成 | DID revoke 已由本仓 SQLite 状态字段和统一 active DID 校验实现；撤销后 token、DID 字符串、DID verify、WS ticket、auth verify、`get_me`、`update_document`、DID path 和公开 Handle discovery 均不能把 revoked DID 当 active 身份；focused pytest、identity tests、compileall、全量 pytest、ASGI smoke、双实例本地跨域 Gate、Rust CLI local Gate 均通过；真实公网 Gate 仍归 Step 09 | 22/09 | 是 |
| 2026-07-03 | 新增 Step 23 Inbox mark-read 兼容补齐 | 继续对照 Message Service direct/read-state 文档后，发现本仓 `inbox.mark_read` 仍为占位 lambda，且 `direct_message_views.read_at` 未用于 inbox/history 投影；该缺口属于本仓可自行修复的 Message Service 兼容面，不需要修改相邻服务 | 23/09 | 是 |
| 2026-07-03 | Step 23 本仓门禁完成 | `inbox.mark_read` 已真实写入当前 owner direct view 的 `read_at`；默认 `inbox.get` 只返回未读，`include_read` 和 `direct.get_history` 投影 `is_read/read_at`；focused pytest、messaging tests、compileall、全量 pytest、ASGI smoke、双实例本地跨域 Gate、Rust CLI local Gate 均通过；真实公网 Gate 仍归 Step 09 | 23/09 | 是 |
| 2026-07-03 | 新增 Step 24 Local view 参数语义兼容补齐 | 继续对照 `message-service/docs/api/ANP-client-server-api-direct.md` 和 `awiki-cli-rs2` wire 参数后，发现本仓 `inbox.get` / `direct.get_history` 仍未完整校验 `meta.sender_did` / `body.user_did`，也缺 `since_seq`、`skip`、limit 上限和 deprecated `group_did` 明确错误；该缺口可在本仓实现，不修改相邻服务 | 24/09 | 是 |
| 2026-07-03 | Step 24 本仓门禁完成 | `inbox.get` / `inbox.mark_read` / `direct.get_history` 已支持 Message Service local view 参数语义和分页；旧 flat 参数继续兼容；focused pytest、messaging tests、compileall、全量 pytest、ASGI smoke、双实例本地跨域 Gate、Rust CLI local Gate 均通过；真实公网 Gate 仍归 Step 09 | 24/09 | 是 |
| 2026-07-03 | 新增 Step 25 Group participant 成员权限收敛 | 继续对照群参与边界后发现本仓 `group.list_members` / `group.list_messages` 只要求登录不要求成员，`group.leave` 对非成员也会生成离群事件；该缺口可在本仓修复，不修改相邻服务，且不扩展为群创建/管理 | 25/09 | 是 |
| 2026-07-03 | Step 25 本仓门禁完成 | 群参与 local view 已按成员身份收敛：非成员不能读成员列表/消息历史或产生离群事件，成员 join 后可读写，leave 后不能再读写；focused pytest、messaging tests、compileall、全量 pytest、ASGI smoke、双实例本地跨域 Gate、Rust CLI local Gate 均通过；真实公网 Gate 仍归 Step 09 | 25/09 | 是 |
| 2026-07-03 | 新增 Step 26 Group local view 参数与 sync 权限收敛 | 继续对照 Message Service group/sync 文档和 Rust CLI group wire 后发现：本仓 `group.list_messages` 缺 `since_seq/skip` 页面语义，`group.list/list_members/list_messages` 未校验 ANP local meta owner，且 `sync.thread_after` 的 group 分支可绕过 Step 25 成员读限制；这些缺口可在本仓修复，不修改相邻服务 | 26/09 | 是 |
| 2026-07-03 | Step 26 本仓门禁完成 | Group local view 已支持 Message Service / Rust CLI `params.meta/body` owner/target 校验和消息分页；`sync.thread_after` group 分支不再绕过成员权限；focused pytest、messaging tests、compileall、全量 pytest、ASGI smoke、双实例本地跨域 Gate、Rust CLI local Gate 均通过；真实公网 Gate 仍归 Step 09 | 26/09 | 是 |
| 2026-07-03 | 新增 Step 27 Message local view 投影兼容收敛 | 对照 Message Service direct/group local view 文档和实现后发现：本仓已有 `body.payload`/`payload_b64u` 校验，但 local view 对 `type/content` 的测试不足，`sync.thread_after` direct 分支仍返回 raw row + body，未复用 direct view projection；这些缺口可在本仓修复，不修改相邻服务 | 27/09 | 是 |
| 2026-07-03 | Step 27 本仓门禁完成并迁移到 reset plan | Message local view 投影已按小 Plan 完成，focused pytest、messaging tests、compileall、全量 pytest、ASGI smoke、双实例本地跨域 Gate、Rust CLI local Gate 均通过；真实公网 Gate 仍归 Step 09；后续按 `plan/20260703-awiki-open-server-mvp-reset/plan.md` 收敛 v0.1 范围 | 27/09/reset | 是 |
| 2026-07-03 | 新增 v0.1 MVP reset plan | 用户要求新增“不使用邮件或手机号码验证过程、不引入阿里云依赖”，并按 MVP 原则停止继续扩边缘兼容 | reset/09 | 是 |

## 17. 风险与回滚

| 风险 | 缓解措施 | 回滚 / 回退方案 |
|---|---|---|
| dev auth 与生产 DID WBA 不等价 | 标注为 MVP，保留验证接口和远端 Gate | 不宣称生产安全 |
| 真实线上互通需要本服务公开域名 | 先完成 Step 06 的 DID discovery、origin proof、service signature、inbound 校验测试 | 有公开域名后重跑 awiki.info 双向 CLI 验证 |
| origin proof 校验和 ANP envelope 原始 body 不一致 | 已在 `normalize_params` 中保留 `_anp_body`，并在 `direct_send` 中用原始 `meta/body` 校验、转发和存储 | 已用 focused/full/smoke 验证；真实线上 Gate 仍需公网域名 |
| origin proof 仅做结构和 content digest 校验 | 已补最小 Ed25519 DID key 验证：keyid 必须属于 `meta.sender_did`、位于 DID document `authentication`，并验证 RFC9421 origin proof 签名 | 已用无效签名拒绝测试覆盖；真实线上 Gate 若被 awiki.info 拒绝，记录响应并请用户确认后续独立处理方式 |
| awiki.info 侧在本仓协议收敛后仍拒绝本服务 proof/signature 或 DID document | 本仓只实现开源 server，不把 awiki.info 当后端兜底；如线上协议要求不同，记录 blocker 由用户确认 | 用户确认后再决定是否调整线上服务或协议参考；默认不修改相邻仓库 |
| `smoke-awiki-info` 名称被误解为本项目互通通过 | 在 Step 07 明确它只是远端 capability 诊断；真实 Gate 必须一端连接本服务公开域名，另一端连接 `awiki.info` | 必要时后续重命名脚本子命令或在输出中继续标注 `diagnostic-only` |
| 群参与边界误扩展成管理 | 测试 `group.create` 返回 `not_supported` | 回滚管理方法 |
| 本仓 Python `smoke-awiki-info` raw direct 仍需显式 token/origin proof | 线上真实 direct 以现有 Rust CLI 高层命令验证；raw ANP direct 只作为诊断工具 | 需要 raw direct 时提供 `--token --sender-did --recipient-did --origin-proof-json` |
| WebSocket 只实现基础 sync hint | Step 12 补齐本进程 realtime fanout，覆盖 direct/group participant；不承诺多进程、多节点或外部队列 fanout | 如 Step 12 回归失败，可回退到 Step 10 的基础 sync hint，同时保留 sync.delta/thread_after 作为补偿路径 |
| 旧 auth/token/ws ticket 是 dev 兼容实现 | 明确 provider 为 `dev`，默认 OTP 为 `123456`，不接生产短信/邮件 | 生产身份提供方仍属非目标，不能作为线上安全承诺 |
| agent-registration/message-agent 只是最小兼容 | token 只做本地一次性注册，binding 只维护状态和 last_seen，不实现托管 runtime orchestration、delegated secret 管理或生产级准入 | 若客户端需要完整 runtime agent 管理，后续单独规划；当前不宣称商业托管能力 |
| 同步 RPC handler 中执行外部 HTTP 可能阻塞单 worker 服务 | 已将同步 JSON-RPC handler 放入线程池，双实例本地跨域 Gate 验证源服务外发时对端仍能回查源服务 DID document | 保持测试覆盖；如后续改为 async HTTP client，需要保留同等双实例 Gate |
| 跨域出站改写已签名 `meta` 会破坏对端 origin proof 验签 | 已修复为原样转发客户端签名覆盖的 `meta/body`；service DID 通过 HTTP Signature header 表达 | 双实例 Gate 已覆盖；禁止在转发前追加已签名业务字段 |
| `read_state.mark_read` 写入未知 sync event 破坏旧客户端 reliable sync | Step 11 去掉 `read_state.updated` sync event；只通过 mark-read response 返回 ack；新增 sync.delta after-read 空事件断言 | 后续若要启用 read-state sync event，必须先和客户端兼容策略同步并另开步骤 |
| 公开 `group.join` 成为无签名跨域写入口 | Step 11 要求 public `/anp-im/rpc group.join` 同时验证业务 origin proof 与服务 HTTP Signature；本地 `/im/rpc group.join` 保持 Bearer token | 如线上 peer 对 group.join 语义不同，按 Step 09 blocker 记录，不扩大匿名写入 |
| 默认群 DID 固定 `localhost` 导致公网 DID domain 部署不自然 | Step 11 将 seed group 改为跟随 `AWIKI_DID_DOMAIN`；本地默认仍为 `did:wba:localhost:groups:open` | 如已有 SQLite 中保留旧群，新 domain 会追加新默认群，不迁移删除旧数据 |
| 旧 User Service Profile REST/RPC 字段与本仓 DID Profile 字段不完全一致 | Step 14 将 `user_id` 映射为 DID，将 `nick_name`、`avatar_url`、`bio`、`profile_url` 映射到本仓 profile 字段；`delete_me` 保持 `not_supported` | 若未来需要完整 User Service 账号删除、算法邀请码或搜索资料，需要另开步骤，不在 Community MVP 中隐式承诺 |
| DID relationship 或 `/site/rpc` 被误解为生产社交图 / tenant hosting | Step 15 只允许本域本地 DID relationship；`/site/rpc` 只管理 `AWIKI_DID_DOMAIN` 的 raw Markdown 页面，不实现生产 tenant admin、模板、SEO、跨域管理 | 若客户端需要完整 Directory 或 tenant hosting，另开步骤；当前不修改 User Service / Message Service |
| Agent Inventory 被误解为完整商业托管 runtime | Step 17 只实现 daemon/CLI 所需最小查询、状态、controller scope 和授权响应；不实现 delegated secret、hosted orchestration、生产级策略引擎或多 controller 治理 | 若客户端需要完整 agent inventory 管理，另开步骤；当前不修改 User Service / Message Service / awiki-cli-rs2 |
| daemon heartbeat no-store 被误用为通用客户端 no-store | Step 18 只识别精确 `schema=awiki.agent.status.v1`、`status_scope=daemon`、`message=daemon heartbeat`、`content_type=application/json` 的 liveness payload；其他 agent status 仍持久化 | 如未来需要通用 ephemeral/no-store 能力，必须另开协议步骤，不在 Community MVP 中隐式支持 |
| DID revoke 被误解为账号数据删除或 handle recovery | Step 22 只撤销 active DID 认证和 DID/Handle discovery，保留 profile、消息、附件等历史数据；`replace_did` / `recover_handle` 仍 `not_supported` | 如需要资料隐藏、账号删除、handle 恢复或 DID 换绑，另开 User Service 兼容步骤，不在 Community MVP 中隐式支持 |
| `inbox.mark_read` 被误解为跨域 read-state ack 或消息删除 | Step 23 只更新本仓当前 owner 的 `direct_message_views.read_at`；默认 `inbox.get` 过滤已读但 `include_read` 和 history 仍可查看；public `/anp-im/rpc` 不暴露该方法 | 如未来需要跨域 read receipt 或多端 read sync event，另开 Message Service 协议步骤，不在 Community MVP 中隐式支持 |
| local view 参数校验过严影响旧 flat CLI 调用 | Step 24 只在调用方提供 `meta.sender_did` 或 `user_did` 时校验一致性；旧 flat `peer_did/limit` 路径仍兼容 | 如现有 CLI 发送标准 ANP envelope 失败，优先修本仓参数展开；不修改 CLI |
| 群参与读接口泄露非成员可见信息 | Step 25 要求 `group.list_members` / `group.list_messages` 当前 DID 必须是成员；`group.get_info` 仍保留公开最小信息 | 如后续需要公开 listed 群成员预览，另开策略字段，不在 Community MVP 中默认开放 |
| `sync.thread_after` group 分支绕过群成员读权限 | Step 26 要求 group thread 增量读取先校验当前 DID 是群成员，并使用 group message projection；非成员返回 `group.not_member` | 如客户端需要群预览或离群后历史保留，应另开产品策略，不复用 durable sync repair 接口 |
| group local view 参数与 Message Service / Rust CLI wire 不一致 | Step 26 补齐 `group.list/list_members/list_messages` 对 `meta.sender_did`、`user_did`、`meta.target`、`since_seq/since_event_seq`、`skip`、`limit` 的本仓兼容 | 如完整 Message Service page schema 继续扩展，优先在本仓补只读投影字段，不修改 CLI 或 Message Service |
| local view 投影把 JSON/附件/二进制消息降级成文本或 raw body | Step 27 对齐 Message Service direct/group 投影规则，并让 `sync.thread_after` direct 分支复用 direct view projection；focused tests 锁定 `type=json/attachment_manifest/binary` 与 `content` | 如未来支持 E2EE/system event，应新增独立投影类型，不把 Community 明文 local view 改成解释业务 payload |

## 18. 最终全局 Review 与整体验证

- 触发条件：Step 01-09 实现、验证、Review 完成，或 Step 09 记录明确线上 blocker。
- Review 范围：代码、测试、CLI、README、Plan、`require.md` 一致性。
- 整体验证命令：`python3 -m pytest tests -q`；本地 CLI smoke；Rust CLI 连接本服务；本服务公开域名 + `awiki.info` 用户双向 direct Gate。
- Review 发现：原 CLI 远端 capability 曾因本地简化参数触发 `missing params.meta`，修复为 ANP envelope；随后发现 capability 不接受空 `auth` 对象，修复为 capability `meta/body`、direct `meta/auth/body`；direct 无真实 origin proof 时不发送。
- 已修复问题：补齐 JSON-RPC ANP envelope normalizer、CLI 远端请求构造、DID resolve 路由、Pages rename、sync/read-state 事件、附件 abort、README 与 `.gitignore`。
- 已修复问题：ANP envelope normalizer 保留原始 `body` 为 `_anp_body`，`direct_send` 以原始 body 校验 origin proof、外发远端请求和本地存储，避免 digest mismatch。
- 已修复问题：业务 `auth.origin_proof` 不再只做结构/digest 检查；现在会解析 sender DID document，检查 keyid 与 `meta.sender_did`、`authentication` 授权，并验证 Ed25519 签名。
- 已修复问题：补齐 User Service / Message Service 兼容形态：WNS Handle 解析、旧 auth/token/ws ticket、基础 `/im/ws`、标准 sync/read-state/attachment 响应字段。
- 已修复问题：补齐 direct inbox 已读兼容：`inbox.mark_read` 更新 owner view，默认 `inbox.get` 返回未读，`include_read` 和 `direct.get_history` 投影 `is_read/read_at`。
- 已修复问题：补齐 local view 参数兼容：`inbox.get`、`inbox.mark_read`、`direct.get_history` 校验可选 owner 字段，支持 `skip/limit/since_seq`，废弃 direct-history `group_did` 路径返回明确错误。
- 已修复问题：补齐群参与成员权限：非成员不能读 `group.list_members` / `group.list_messages` 或产生 `group.leave` 事件；`group.get_info` 仍保留 open-join discovery。
- 已修复问题：补齐 group local view 参数与 sync 权限：`group.list/list_members/list_messages` 接受 Rust CLI `params.meta/body` 的 owner、target、limit 和分页字段；`sync.thread_after` group 分支不得绕过成员权限。
- 整体验证证据：
  - `PYTHONPATH=src python3 -m compileall -q src scripts tests`：pass。
  - `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q`：10 passed。
  - `PYTHONPATH=src python3 -m pytest tests -q`：16 passed。
  - `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-interop-hardening-asgi-proof`：pass。
  - 失败回归证据已解决：此前 `origin_proof_content_digest_mismatch` 由 normalized body 校验引起，已通过 `_anp_body` 修复。
  - `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-local --base-url http://127.0.0.1:8765`：pass。
  - 现有 Rust CLI 本地连接验证：`id register` 两个本服务用户 pass；`msg send --to cliremotepeer.localhost` pass；接收方 `msg inbox` 返回 1 条消息；`msg history --with cliremotecheck.localhost` 返回 1 条 direct history。
  - 现有 Rust CLI `awiki-cli-rs2` 独立 worktree 验证：`id register`、`msg send`（DID 与 handle lookup）、`msg inbox`、`msg history`、`msg mark-read`、`page create/get/update/rename/list/delete`、`group join`、`msg send --group`、`group messages` 均 pass；`group create` exit 1 且服务端返回 `not_supported`。
  - `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-awiki-info --base-url https://awiki.info --did-domain rwiki.info`：仅证明 awiki.info capability 可访问，不证明本开源 server 与 awiki.info 互通。
  - 无效验证记录：此前两个隔离 CLI workspace 都连接 `https://awiki.info`，分别注册 `codexawiki0703083759.awiki.info` 与 `codexrwiki0703083759.rwiki.info` 并互发消息。这只能证明线上 awiki.info 服务内部支持两个 DID 域用户，不能作为本项目跨服务互通证据。
  - 新增有效本地证据：`tests/test_messaging_objects.py::test_local_direct_to_remote_did_discovers_anp_service_and_posts` 通过 monkeypatch 证明本服务用户发给远端 DID 会解析远端 DID document 并 POST 到远端 `ANPMessageService.serviceEndpoint`。
  - 新增有效本地证据：`tests/test_messaging_objects.py::test_public_anp_direct_requires_local_recipient` 证明远端 `/anp-im/rpc direct.send` 只投递本服务本地用户，非本地 target 返回 `recipient_not_local`，避免成为 relay。
  - Step 10 新增证据：`PYTHONPATH=src python3 -m pytest tests -q`：26 passed。
  - Step 10 新增证据：`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step10-asgi`：pass。
  - Step 10 新增证据：隔离 Rust CLI 本地 Gate pass；`doctor` 仅保留预期 loopback ANP endpoint error；`id register` Alice/Bob pass；Alice -> Bob `msg send` pass；Bob `msg inbox` 和 `msg history` pass；`page create/get/update/list` pass；`group join`、`msg send --group`、`group messages` pass；`group create` exit 1 且返回 `service rpc error -32010: not_supported`。
  - 2026-07-03 11:41 CST 复跑证据：`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q`：24 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step10-asgi-final-rerun`：pass。
  - 2026-07-03 11:41 CST 公网预检证据：`PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info` failed，`/.well-known/did.json`、`/healthz`、`/anp-im/rpc anp.get_capabilities` 均 404；该失败证明公网域名尚未路由到本仓，不能作为本仓协议失败或 `awiki.info` 对端失败处理。
  - 2026-07-03 双实例本地跨域 Gate 证据：`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-cross-domain-local-final --clean` pass；输出 `mode=cross-domain-local`，source=`did:wba:source.test`，target=`did:wba:target.test`，验证 `two independent uvicorn processes`、`service DID documents with Ed25519 HTTP signatures`、`DID discovery through AWIKI_DID_RESOLVER_BASE_URLS`、`origin_proof verification`、`signed /anp-im/rpc inbound direct`、`bidirectional inbox delivery`。
  - 2026-07-03 修复证据：双实例 Gate 初次失败为同步外发阻塞导致 timeout，修复 `shared/jsonrpc.py` 使用线程池执行同步 handler 后进入真实对端校验；随后失败为 `origin_proof_content_digest_mismatch`，修复 `services.py` 不再改写已签名 `meta` 后 Gate 通过。
  - 2026-07-03 Rust CLI 最小回归证据：修复 JSON-RPC 线程池和跨域 meta 后，隔离 `HOME=/tmp/awiki-cli-final-home`、`AWIKI_CLI_WORKSPACE_HOME_DIR=/tmp/awiki-cli-final-workspace` 连接 `http://127.0.0.1:8765`；`id register finalalice1783051032` pass，`id register finalbob1783051047` pass，Alice -> Bob `msg send` pass，Bob `msg inbox` 和 `msg history --with finalalice1783051032.localhost` 均返回该 direct 消息；`doctor` 仅保留预期 loopback ANP endpoint error。
  - 2026-07-03 pytest 自动化证据：`PYTHONPATH=src python3 -m pytest tests/test_cli_smoke.py::test_smoke_cross_domain_local_subprocess -q` pass；随后全量 `PYTHONPATH=src python3 -m pytest tests -q` 25 passed，证明双实例本地跨域 Gate 已纳入常规测试。
  - 2026-07-03 agent-registration/message-agent 证据：`PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py::test_agent_registration_and_message_agent_minimal_compat -q` pass；全量 `PYTHONPATH=src python3 -m pytest tests -q` 26 passed；覆盖 agent registration token issue/verify/exchange/revoke、message-agent binding ensure/get/list/mark_seen/disable/revoke。
  - 2026-07-03 Agent 兼容后 Rust CLI 最小回归证据：隔离 `HOME=/tmp/awiki-cli-agent-home`、`AWIKI_CLI_WORKSPACE_HOME_DIR=/tmp/awiki-cli-agent-workspace` 连接 `http://127.0.0.1:8765`；`id register agentalice1783051541` pass，`id register agentbob1783051542` pass，Alice -> Bob `msg send` pass，Bob `msg inbox` 和 `msg history --with agentalice1783051541.localhost` 均返回该 direct 消息。
  - 2026-07-03 Step 11 focused 证据：`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_public_anp_group_join_requires_origin_and_peer_signature tests/test_messaging_objects.py::test_public_anp_direct_verifies_signature_against_public_base_url tests/test_messaging_objects.py::test_public_anp_direct_accepts_signed_peer_request tests/test_messaging_objects.py::test_sync_delta_thread_after_and_read_state_standard_shapes -q` pass；覆盖公开 `group.join` proof/signature、public URL HTTP Signature、direct inbound 和 read-state 标准形态。
  - 2026-07-03 Step 11 全量证据：`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 28 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step11-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step11-cross --clean` pass。
  - 2026-07-03 Step 11 Rust CLI 本地回归证据：隔离 `HOME=/tmp/awiki-cli-step11-home`、`AWIKI_CLI_WORKSPACE_HOME_DIR=/tmp/awiki-cli-step11-workspace` 连接 `http://127.0.0.1:8765`；`id register step11alice...` pass，`id register step11bob...` pass，Alice -> Bob `msg send` pass，Bob `msg inbox` 和 `msg history --with step11alice....localhost` 均返回 `hello bob from step11`。
  - 2026-07-03 Step 11 公网预检证据：`PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info` 仍 failed，`/.well-known/did.json`、`/healthz`、`/anp-im/rpc anp.get_capabilities` 均 404；该失败继续证明公网域名尚未路由到本仓，不能作为本仓协议失败或 `awiki.info` 对端失败处理。
  - 2026-07-03 Step 12 realtime 证据：`PYTHONPATH=src python3 -m pytest tests/test_health.py::test_im_websocket_receives_direct_and_group_notifications -q` pass；focused direct/group + WS 2 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 29 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step12-asgi-rerun` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step12-cross --clean` pass。
  - 2026-07-03 Step 12 公网预检证据：`PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info` 仍 failed，`/.well-known/did.json`、`/healthz`、`/anp-im/rpc anp.get_capabilities` 均 404；该失败继续证明公网域名尚未路由到本仓，不能作为本仓协议失败或 `awiki.info` 对端失败处理。
  - 2026-07-03 Step 13 auth_request 兼容证据：`PYTHONPATH=src python3 -m pytest tests/test_health.py::test_healthz tests/test_identity_pages.py::test_legacy_auth_and_ws_ticket_compat_routes -q` 2 passed；覆盖 `/health`、`/user-service/health`、`/user-service/auth/sms` 默认 OTP 登录/注册、重复登录复用 token、`/user-service/auth/token-verify`、`/user-service/auth/verify`、`/sessions/verify` 的 `X-User-Id` header，以及 `/user-service/auth/ws-ticket/verify` 的 `X-WS-Ticket` header 验证。
  - 2026-07-03 Step 13 全量证据：`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 29 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step13-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step13-cross --clean` pass。
  - 2026-07-03 Step 13 公网/路由证据：`getent hosts rwiki.info awiki.info` 均解析到同一公网 IP；`curl https://rwiki.info/healthz` 返回 nginx 404；只读查看当前 nginx `rwiki.info.conf`，其 `/.well-known/did.json`、handle、pages 等路径代理到 `127.0.0.1:9891` user-service，缺少 `/healthz`、`/anp-im/rpc`、`/im/rpc` 等本仓路由；`PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info` 仍 failed，`/.well-known/did.json`、`/healthz`、`/anp-im/rpc` 均 404。
  - 2026-07-03 Step 14 profile/health 兼容证据：`PYTHONPATH=src python3 -m pytest tests/test_health.py::test_healthz tests/test_identity_pages.py::test_legacy_me_profile_and_message_health_compat_routes -q` 2 passed；覆盖 `/im/healthz`、`/me`、`PATCH /user-service/me`、`/me/rpc get_me/get_public_profile/delete_me`、`/users/{user_id}/profile`、`/user-service/users/{user_id}/profile`、`/profiles/{user_id}`、`/user-service/profiles/{user_id}`，以及未认证 `/me` 401、未知 profile Markdown 404。
  - 2026-07-03 Step 14 全量证据：`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 30 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step14-asgi-rerun` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step14-cross-rerun --clean` pass。
  - 2026-07-03 Step 14 公网/路由证据：`PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info` 仍 failed，`/.well-known/did.json`、`/healthz`、`/anp-im/rpc` 均 404；该失败继续证明公网域名尚未路由到本仓，不能作为本仓协议失败或 `awiki.info` 对端失败处理。
  - 2026-07-03 Step 15 Directory/Site 兼容证据：`PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py::test_did_relationship_phone_bind_and_site_rpc_compat -q` 1 passed；覆盖 `/user-service/auth/phone-bind-send`、`/user-service/auth/phone-bind-verify`、`/did/relationships/rpc`、`/user-service/did/relationships/rpc`、自关注拒绝、外域 DID follow 拒绝、`/site/rpc` root/page CRUD、公开 `GET /` 和 `GET /pages/{slug}.md`。
  - 2026-07-03 Step 15 全量证据：`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 31 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step15-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step15-cross --clean` pass。
  - 2026-07-03 Step 15 公网/路由证据：`PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info` 仍 failed，`/.well-known/did.json`、`/healthz`、`/anp-im/rpc` 均 404；该失败继续证明公网域名尚未路由到本仓，不能作为本仓协议失败或 `awiki.info` 对端失败处理。
  - 2026-07-03 Step 16 Rust CLI 本地互通 Gate 自动化证据：`CARGO_TARGET_DIR=/tmp/awiki-cli-rs2-open-server-target cargo build -p awiki-cli --bin awiki-cli --locked` pass；手工双 workspace Rust CLI Gate pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step16-rust-cli --clean` pass，覆盖 dev phone OTP 注册、direct/inbox/history、group join/send/messages、people follow/status/following/followers、site root/page。
  - 2026-07-03 Step 16 全量证据：`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 31 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step16-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step16-cross --clean` pass。
  - 2026-07-03 Step 16 公网/路由证据：`PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info` 仍 failed，`/.well-known/did.json`、`/healthz`、`/anp-im/rpc` 均 404；该失败继续证明公网域名尚未路由到本仓，不能作为本仓协议失败或 `awiki.info` 对端失败处理。
  - 2026-07-03 Step 17 Users/Agent Inventory focused 证据：`PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py::test_users_rpc_compat_routes tests/test_identity_pages.py::test_agent_inventory_minimal_compat_routes -q` 2 passed；覆盖 `/users/rpc`、`/user-service/users/rpc` 的 get_me/get_by_did/get_by_dids/get_by_handle，以及 `/user-service/agent-inventory/rpc` 的 update_latest_status、sync_controller_scope、verify_controller_sender、authorize_agent_invocation、list_agents、update_display_name、get/update policy、archive。
  - 2026-07-03 Step 17 全量证据：`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 33 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step17-asgi-final` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step17-cross-final --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step17-rust-cli --clean` pass。
  - 2026-07-03 Step 17 公网/路由证据：`PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info` 仍 failed，`/.well-known/did.json`、`/healthz`、`/anp-im/rpc` 均 404；该失败继续证明公网域名尚未路由到本仓，不能作为本仓协议失败或 `awiki.info` 对端失败处理。
  - 2026-07-03 Step 18 payload/heartbeat focused 证据：`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_application_json_payload_shape_and_daemon_heartbeat_no_store -q` 1 passed；覆盖 direct/group `application/json + body.payload` 保留、错误 body shape 拒绝、daemon heartbeat no-store、非 heartbeat agent status durable。
  - 2026-07-03 Step 18 全量证据：`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q` 16 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 34 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step18-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step18-cross --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step18-rust-cli --clean` pass。
  - 2026-07-03 Step 26 group local view/sync focused 证据：`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_group_participant_local_views_require_membership tests/test_messaging_objects.py::test_group_local_views_support_anp_params_and_pagination -q` 2 passed；覆盖非成员无法通过 `sync.thread_after` 读群消息、成员可读、ANP local owner/target 校验、`since_seq/skip/limit` 分页、invalid since 和 limit 上限。
  - 2026-07-03 Step 26 全量证据：`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q` 22 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 42 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step26-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step26-cross --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step26-rust-cli --clean` pass。
  - 2026-07-03 Step 26 公网预检证据：`PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info` 仍 failed，`/.well-known/did.json`、`/healthz`、`/anp-im/rpc` 均 404；该失败继续证明公网域名尚未路由到本仓，不能作为本仓协议失败或 `awiki.info` 对端失败处理。
  - 2026-07-03 Step 27 message local view projection focused 证据：`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_application_json_payload_shape_and_daemon_heartbeat_no_store tests/test_messaging_objects.py::test_message_local_views_project_payload_attachment_and_binary_content tests/test_messaging_objects.py::test_sync_delta_thread_after_and_read_state_standard_shapes -q` 3 passed；覆盖 JSON、附件清单、二进制扩展和 `sync.thread_after` 投影。
  - 2026-07-03 Step 27 全量证据：`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q` 23 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 43 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step27-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step27-cross --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step27-rust-cli --clean` pass。
- 剩余风险：真实 awiki.info 双向互通仍未跑，因为当前环境还没有确认 `rwiki.info` 或其他公开域名指向本服务并由本服务发布 `/.well-known/did.json` 和 `/anp-im/rpc`。如果公开域名 Gate 运行后线上 `awiki.info` 对等服务仍拒绝本服务 proof/signature/DID document，按 blocker 记录并由用户确认是否需要调整线上服务或协议参考；默认不修改相邻仓库。`/im/ws` 当前是单进程 in-process realtime fanout，不覆盖多进程、多节点、外部 pub/sub、离线推送、presence 或 typing；生产短信/邮件/agent registration 托管仍属后续范围。
- 最终工作区状态：存在未提交的当前工程文件变更；未修改相邻仓库。
