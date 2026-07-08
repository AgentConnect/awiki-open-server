# awiki-open-server

[English](README.md) | [简体中文](README.cn.md)

单进程 Awiki 社区服务器 MVP。它提供 DID 注册、公开 DID 文档、个人资料 API、Markdown 页面、明文私信、群组参与者 API、本地附件存储、同步/已读状态，以及用于跨域直连调用的公开 `/anp-im/rpc` 入口。

这个服务器自己实现上述能力。它不是 `awiki.info` 的代理，也不依赖 `awiki.info` 或其他 AWiki 兄弟服务运行。

社区版有意不实现群组创建或管理、私信/群组端到端加密、联邦 peer 路由、中继、远程投影、计费、生产级身份提供方、邮箱或手机号验证流程、阿里云集成、多租户托管。

## 代码结构

应用代码位于 `src/awiki_open_server/`。`protocol/anp_adapter.py` 是唯一的 ANP Python SDK 适配器，运行时要求 `anp==0.8.8`；`service_identity.py` 使用它处理 HTTP Signatures、Content-Digest 和 origin proof 校验。`app/` 负责 FastAPI 设置、路由挂载和实时能力接线。`messaging/` 负责私信、群组参与者方法、本地同步和已读状态处理。`attachments/` 负责本地上传 slot、已提交对象和下载 ticket。`user_compat/` 实现本地 User Service 兼容面。`shared/runtime.py` 包含跨领域 DID 发现、HTTP JSON、签名、对象 URL 和实时辅助函数。`services.py` 现在是兼容性 facade，以及剩余的内容、站点和 DID 关系处理器；新的领域逻辑应该进入对应领域包，而不是再放回 `services.py`。

## 本地运行

使用 Python 3.10 或更新版本。如果系统 `python3` 版本较旧，请使用显式解释器创建环境，例如 `python3.11`：

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e '.[dev]'
```

依赖集固定 ANP Python SDK 为 `anp==0.8.8`；如果加载了其他 SDK 版本，导入 `awiki_open_server.protocol.anp_adapter` 会快速失败。在当前工作区，如果活跃环境中仍安装了旧版 `anp` 包，本地验证可以通过 `PYTHONPATH=../anp/anp:src` 使用相邻 SDK checkout。

启动服务器：

```bash
PYTHONPATH=src \
AWIKI_DATA_DIR=.awiki-open-server \
AWIKI_PUBLIC_BASE_URL=http://127.0.0.1:8765 \
AWIKI_DID_DOMAIN=localhost \
.venv/bin/python -m uvicorn 'awiki_open_server.app.main:create_app' \
  --factory --host 127.0.0.1 --port 8765
```

验证正在运行的服务器：

```bash
curl --noproxy '*' http://127.0.0.1:8765/healthz
```

预期响应是 `{"status":"ok","edition":"community"}`。`--noproxy '*'` 标志用于避免本地检查被开发机器上的 HTTP 代理转发。

常用配置：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `AWIKI_DATA_DIR` | `.awiki-open-server` | SQLite 数据库和对象文件。 |
| `AWIKI_PUBLIC_BASE_URL` | `http://127.0.0.1:8000` | DID 文档和对象 URL 使用的公开 base。 |
| `AWIKI_DID_DOMAIN` | `localhost` | 默认 DID 和 handle 域名。 |
| `AWIKI_SERVICE_DID` | `did:wba:<domain>` | 在 `ANPMessageService` 中公布的服务 DID。 |
| `AWIKI_SERVICE_PRIVATE_KEY_PEM` | 未设置 | 用于签署服务间 HTTP 请求的 Ed25519 PKCS#8 PEM。通过 env 文件传入时使用 `\n` 转义。 |
| `AWIKI_SERVICE_PRIVATE_KEY_PATH` | 未设置 | 同一个 Ed25519 私钥的文件路径。本地部署优先使用这个选项。 |
| `AWIKI_SERVICE_DID_DOCUMENT_JSON` | 自动生成 | 可选的固定服务 DID 文档。如果省略，服务器会从服务私钥生成。 |
| `AWIKI_IM_RPC_PATH` | `/im/rpc` | 本地客户端 JSON-RPC 路径。 |
| `AWIKI_ANP_PUBLIC_RPC_PATH` | `/anp-im/rpc` | 公开 ANP RPC 路径。 |
| `AWIKI_WS_PATH` | `/im/ws` | 本地 WebSocket 通知路径。 |
| `AWIKI_OBJECT_UPLOAD_PATH` | `/objects/upload` | 本地对象上传路径前缀。 |
| `AWIKI_OBJECT_DOWNLOAD_PATH` | `/objects` | 本地对象下载路径前缀。 |
| `AWIKI_ALLOW_UNSIGNED_PEER_DEV` | `false` | 仅为本地开发测试允许未签名的 `/anp-im/rpc direct.send`。不要在真实互通中启用。 |
| `AWIKI_DID_RESOLVER_BASE_URLS` | 未设置 | 可选的开发解析器映射，例如 `source.test=http://127.0.0.1:9001,target.test=http://127.0.0.1:9002` 或 JSON 对象。正常公开部署保持未设置。 |
| `AWIKI_DID_VERIFY_DEV_CODE` | `666666` | 本地 `/did-verify/rpc login` 开发验证码。如果设置了 `DEV_BYPASS_CODE`，则回退使用它。 |
| `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT` | `false` | 为旧客户端测试启用遗留本地手机号/邮箱验证 shim。MVP 和公开部署应保持关闭。 |
| `AWIKI_CONTACT_VERIFICATION_DEV_OTP` | `123456` | 仅在显式启用 contact verification 兼容时使用的本地兼容 OTP。 |

不要提交 `.awiki-open-server/`、SQLite 数据库、对象文件、`.env` 或真实 token。

真实跨域私信互通需要配置稳定的服务 DID 和私钥：

```bash
AWIKI_PUBLIC_BASE_URL=https://rwiki.cn
AWIKI_DID_DOMAIN=rwiki.cn
AWIKI_SERVICE_DID=did:wba:rwiki.cn
AWIKI_SERVICE_PRIVATE_KEY_PATH=/secure/path/rwiki-service-ed25519.pem
AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false
```

发布的 `https://rwiki.cn/.well-known/did.json` 必须由这个进程提供，并且包含匹配的 `verificationMethod`、`authentication`、proof，以及唯一一个公开 `ANPMessageService`。出站远程私信请求需要客户端/CLI ANP envelope 中的 `auth.origin_proof`；服务器会原样转发该 proof，并用 `AWIKI_SERVICE_DID` 签署 HTTP hop。

部署模板位于 `deploy/`。它们展示如何在 localhost 上运行 Uvicorn，并通过 nginx 发布 `https://rwiki.cn`。关键边界是 `rwiki.cn` 必须代理到这个进程，而不是代理到 `awiki.info`、`user-service` 或 `message-service`。

## 测试和 Smoke

运行测试套件：

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests -q
```

重点测试套件：

- ANP SDK/签名适配器：`tests/test_protocol_anp_sdk.py`
- 路由和环境路径配置：`tests/test_route_config.py`
- User Service 兼容性：`tests/test_user_service_compat.py`、`tests/test_identity_documents.py`、`tests/test_contact_auth_compat.py`、`tests/test_profile_compat.py`、`tests/test_agent_compat.py`、`tests/test_site_relationships.py`
- 消息能力面：`tests/test_messaging_surface.py`、`tests/test_direct_messages.py`、`tests/test_group_participant.py`、`tests/test_attachments.py`、`tests/test_sync_read_state.py`
- 公开部署门禁：`tests/test_rwiki_cn_system.py`，除非设置 `AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1`，否则跳过

不启动 Uvicorn，运行进程内 CLI smoke：

```bash
PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-asgi \
  --data-dir /tmp/awiki-open-server-cli-asgi
```

对运行中的服务器执行本地 HTTP smoke：

```bash
PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-local \
  --base-url http://127.0.0.1:8765 \
  --did-domain localhost
```

运行本地双服务器跨域 smoke：

```bash
PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-cross-domain-local \
  --data-root /tmp/awiki-open-server-cross-domain-local --clean
```

该命令会启动两个独立的 Uvicorn 进程，使用独立的 SQLite 存储、服务 DID 和 Ed25519 服务密钥。它只使用 `AWIKI_DID_RESOLVER_BASE_URLS` 将测试 DID 域名映射到 loopback 端口，然后验证 DID 发现、客户端 `auth.origin_proof`、服务间 HTTP Signature、签名的 `/anp-im/rpc direct.send` 和双向 inbox 投递。这是本地协议门禁，不能替代公开的 `rwiki.cn` 到 `awiki.info` 互通门禁。

检查公开部署是否确实由这个仓库提供服务：

```bash
PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py verify-public \
  --base-url https://rwiki.cn \
  --did-domain rwiki.cn
```

在使用 `rwiki.cn` 进行真实 `awiki.info` 互通测试之前，`verify-public` 必须通过。`/.well-known/did.json`、`/healthz` 或 `/anp-im/rpc` 返回 404 表示公开域名尚未路由到这个服务器。

对 `rwiki.cn` 运行受保护的公开系统测试：

```bash
AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 \
PYTHONPATH=src .venv/bin/python -m pytest tests/test_rwiki_cn_system.py -q
```

这些测试在本地和 CI 运行中默认跳过。启用后，它们会验证 `https://rwiki.cn` 上的公开服务 DID 文档、能力、关闭的 contact verification、DID 注册、私信 inbox/history，以及开放群组参与者边界。

现有 Rust CLI 也可以连接这个服务器。请使用隔离的 `awiki-cli-rs2` worktree 和临时 CLI workspace，避免验证写入开发者正在使用的 CLI checkout：

```bash
CARGO_TARGET_DIR=/tmp/awiki-cli-rs2-open-server-target \
  cargo build -p awiki-cli --bin awiki-cli --locked

AWIKI_CLI_WORKSPACE_HOME_DIR=/tmp/awiki-cli-open-server-workspace \
  /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli \
  id register --handle cli-alice --phone 13800138000 --otp 123456
```

当前 Rust CLI 在执行 `id register` 时仍要求传入 `--phone` 或 `--email`。在这个 MVP 中，这些 CLI 参数只是为了匹配现有 CLI 命令形态：服务器端 `did-auth.register` 路径不会发送短信、发送邮件、调用阿里云，或持久化手机号/邮箱验证状态。

为了获得可重复的本地 Rust CLI 兼容性门禁，可以让这个仓库启动自己的临时服务器，并创建两个隔离的 CLI workspace：

```bash
PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-rust-cli-local \
  --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli \
  --data-root /tmp/awiki-open-server-rust-cli-local --clean
```

这会验证当前 Rust CLI 通过本地 DID 注册路径注册、私信发送/inbox/history、群组 join/send/messages、people follow/status/following/followers，以及 site root/page 命令。它是本地 User Service / Message Service 兼容性门禁，不能替代公开的 `rwiki.cn` 到 `awiki.info` 互通门禁。

服务器暴露 Rust CLI 使用的兼容路由，包括 `/user-service/did-auth/rpc`、`/user-service/did/profile/rpc` 和 `/user-service/handle/rpc`。这些路由由本仓库本地实现，不会转发到外部 User Service。

它还暴露最小的 `/user-service/agent-registration/rpc`、`/user-service/message-agent/rpc` 和 `/user-service/agent-inventory/rpc` 兼容路由，覆盖当前 daemon 状态、controller scope、sender 检查、调用授权、archive 和本地 policy 字段。这些能力只覆盖本地一次性 agent 注册 token、message-agent 绑定状态和 daemon 兼容性；不实现托管运行时编排、委托式密钥管理或生产 policy 引擎。

MVP 不使用手机号或邮箱验证。遗留 contact-verification 路由，例如 `/auth/sms`、`/auth/sms-codes`、`/auth/email-send`、`/auth/email-status` 和 phone-bind 路由，默认返回 `contact_verification_not_enabled`。它们只能通过 `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=true` 为本地兼容测试启用；即使启用，它们仍然只是进程内开发 shim，不会调用短信、邮箱、阿里云、`awiki.info`、User Service 或 Message Service。Token 和 WebSocket ticket 验证路由仍然是本地兼容辅助能力，并返回 `X-User-Id` / `X-DID` header，用于 nginx `auth_request` 集成。

对于 User Service DID verification 兼容性，`/did-verify/rpc` 和 `/user-service/did-verify/rpc` 暴露 `send_code`、`login` 和 `refresh`。这是本地开发 provider：`send_code` 不调用外部 message service，`login` 默认接受 DID verify 开发验证码 `666666`，token 是已经为已注册 DID 存储的本地 Community token。可以用 `AWIKI_DID_VERIFY_DEV_CODE` 或 `DEV_BYPASS_CODE` 覆盖 DID verify code。这只是 DID verify 兼容，不会启用手机号或邮箱验证。

DID Auth 支持对已注册 DID 执行本地 `revoke`。撤销会将本地用户和 DID 文档标记为 inactive；同一个 token 或 DID 字符串之后无法再通过 token verification、DID verify login/refresh、WebSocket ticket verification、`get_me` 或 `update_document`。个人资料和历史消息数据仍会保留，但 active DID 文档路由返回 404。`replace_did` 和 `recover_handle` 在社区服务器中仍不支持。

对于较旧的 User Service profile 客户端，服务器还暴露本地 profile 兼容路由：`/me`、`/me/rpc`、`/profiles/{user_id}`、`/user-service/profiles/{user_id}`、`/users/{user_id}/profile` 和 `/users/rpc`。在这个社区服务器中，`user_id` 是本地 DID，profile 字段映射到本地 DID profile 记录。这些路由不会调用外部 User Service。

远程能力诊断可以调用在线 `awiki.info` 服务，但 `awiki.info` 是用于互通测试的远程 peer，不是这个服务器的后端：

```bash
PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-awiki-info \
  --base-url https://awiki.info \
  --did-domain rwiki.cn
```

要发送私信测试消息，还需要提供 `--token`、`--sender-did`、`--recipient-did` 和 `--origin-proof-json`。远程能力使用 ANP JSON-RPC `params.meta/body`；远程私信使用 `params.meta/auth/body`。如果响应为 `missing params.meta`，说明请求形状错误，不能视为通过远程检查。

真实互通验证需要在可访问的独立 base URL 上运行这个服务器，并配置服务私钥，同时让 Rust CLI 指向该 URL。远端应是 `awiki.info` 上的现有用户或测试用户。有效测试需要证明两个方向：

- 本地 open-server 用户 -> `awiki.info` 用户：这个服务器解析远端 DID 文档，保留 CLI 的 `auth.origin_proof`，以 `AWIKI_SERVICE_DID` 签署 HTTP hop，并将 `direct.send` POST 到远端 `ANPMessageService.serviceEndpoint`。
- `awiki.info` 用户 -> 本地 open-server 用户：`awiki.info` 解析本服务器的 DID 文档，并将签名的 `direct.send` POST 到本服务器的 `/anp-im/rpc`。

不要把两个都指向 `https://awiki.info` 的 CLI workspace 当作这个仓库的验证；那只是在验证在线服务自身。

## API Surface

核心路由和兼容路由。Contact-verification 兼容路由会为旧客户端挂载，但除非为本地测试显式设置 `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=true`，否则返回 `contact_verification_not_enabled`：

- `GET /healthz`
- `GET /health`
- `GET /user-service/health`
- `GET /im/healthz`
- `POST /did-auth/rpc`
- `POST /user-service/did-auth/rpc`
- `POST /did-verify/rpc`
- `POST /user-service/did-verify/rpc`
- `POST /did/profile/rpc`
- `POST /user-service/did/profile/rpc`
- `GET /me`
- `PATCH /me`
- `POST /me/rpc`
- `GET /user-service/me`
- `PATCH /user-service/me`
- `POST /user-service/me/rpc`
- `GET /profiles/{user_id}`
- `GET /user-service/profiles/{user_id}`
- `GET /users/{user_id}/profile`
- `GET /user-service/users/{user_id}/profile`
- `POST /users/rpc`
- `POST /user-service/users/rpc`
- `POST /handle/rpc`
- `POST /user-service/handle/rpc`
- `POST /did/relationships/rpc`
- `POST /user-service/did/relationships/rpc`
- `POST /user-service/agent-registration/rpc`
- `POST /user-service/agent-inventory/rpc`
- `POST /user-service/message-agent/rpc`
- `POST /auth/sms-codes`
- `POST /user-service/auth/sms-codes`
- `POST /auth/sms`
- `POST /user-service/auth/sms`
- `POST /auth/email-send`
- `POST /user-service/auth/email-send`
- `GET /auth/email-status`
- `GET /user-service/auth/email-status`
- `POST /auth/phone-bind-send`
- `POST /user-service/auth/phone-bind-send`
- `POST /auth/phone-bind-verify`
- `POST /user-service/auth/phone-bind-verify`
- `POST /auth/token-refresh`
- `POST /user-service/auth/token-refresh`
- `GET /auth/token-verify`
- `GET /user-service/auth/token-verify`
- `GET /auth/verify`
- `GET /user-service/auth/verify`
- `GET /sessions/verify`
- `GET /user-service/sessions/verify`
- `POST /ws/tickets`
- `POST /user-service/ws/tickets`
- `GET /ws/tickets/verify`
- `GET /user-service/ws/tickets/verify`
- `GET /auth/ws-ticket/verify`
- `GET /user-service/auth/ws-ticket/verify`
- `POST /content/rpc`
- `POST /user-service/content/rpc`
- `GET /content/{slug}.md`
- `POST /site/rpc`
- `GET /`
- `GET /pages/{slug}.md`
- `POST /im/rpc` 默认路径，或 `AWIKI_IM_RPC_PATH`
- `POST /anp-im/rpc` 默认路径，或 `AWIKI_ANP_PUBLIC_RPC_PATH`
- `PUT /objects/upload/{slot_id}` 默认路径，或 `AWIKI_OBJECT_UPLOAD_PATH/{slot_id}`
- `GET /objects/{object_id}` 默认路径，或 `AWIKI_OBJECT_DOWNLOAD_PATH/{object_id}`
- `GET /.well-known/did.json`
- `GET /dids/resolve/{sub_path}/did.json`
- `GET /{sub_path}/did.json`

`/im/rpc` 是本地客户端入口，暴露 inbox、history、sync、read-state、群组参与者和附件控制方法。`/anp-im/rpc` 是公开跨域入口，只暴露 `anp.get_capabilities`、`direct.send`、`group.get_info`、`group.join` 和 `attachment.get_download_ticket`。公开 `direct.send` 和 `group.join` 要求业务层 `auth.origin_proof` 和服务间 HTTP Signature，除非为本地测试启用了 `AWIKI_ALLOW_UNSIGNED_PEER_DEV`。

私信和群组消息会保留 Message Service payload 形状。`text/plain` 使用 `body.text`；`application/json` 和 `application/anp-attachment-manifest+json` 使用 `body.payload` 作为 JSON 对象；其他非文本内容类型使用 `body.payload_b64u`。服务器会拒绝 body 字段与 `meta.content_type` 不匹配的 ANP-envelope 消息，同时保持对较旧扁平 text CLI 调用的兼容。

本地消息视图（`inbox.get`、`direct.get_history`、`group.list_messages` 和 `sync.thread_after`）会以 Message Service 语义投影这些已存储 body：文本消息返回 `type=text`，JSON payload 返回 `type=json`，附件 manifest 返回 `type=attachment_manifest`，其他非文本 payload 返回 `type=binary`。原始 `body` 和 `content_type` 仍然包含在响应中，供需要原始 ANP 形状的客户端使用。

私信 inbox 已读状态遵循 Message Service 兼容性拆分：`inbox.mark_read` 会把当前用户可见的私信 message id 标记到 `direct_message_views.read_at`，默认 `inbox.get` 只返回未读消息，`inbox.get {"include_read": true}` 或 `direct.get_history` 可以显示带 `is_read` 和 `read_at` 的已读消息。`read_state.mark_read` 仍然是线程水位 API，不会发出账号级 sync event。

本地视图方法接受 Message Service 的 `params.meta/body` 形状，也接受较旧的扁平 params。当存在时，`meta.sender_did` 和 `body.user_did` 必须与已认证的本地 DID 匹配。`inbox.get` 支持 `skip` 和 `limit`；`direct.get_history` 支持 `peer_did`、`since_seq`/`since`、`skip` 和 `limit`。已废弃的 direct-history `group_did` 路径会被拒绝；群组历史请使用 `group.list_messages`。

服务器只把已记录的 daemon liveness heartbeat payload（`application/json`，`body.payload.schema = awiki.agent.status.v1`，`status_scope = daemon`，`message = daemon heartbeat`）识别为 no-store。它返回 `delivery_state = ephemeral`，并可能通知在线收件人，但不会把该 heartbeat 写入 inbox、history、sync events 或发送方历史。其他 daemon/App status payload，包括 run 和 snapshot 状态，仍然是持久消息。

支持的群组方法仅限参与者能力：`group.get_info`、`group.join`、`group.leave`、`group.send`、`group.get`、`group.list`、`group.list_members` 和 `group.list_messages`。`group.get_info` 暴露最小的现有群组信息，用于发现和开放加入。成员列表、群组消息、leave 和 send 要求当前 DID 是群组成员。`group.create`、`group.add`、`group.remove`、`group.update_profile` 和 `group.update_policy` 等管理方法返回 `not_supported`。预置的开放加入群组 DID 遵循 `AWIKI_DID_DOMAIN`，例如本地为 `did:wba:localhost:groups:open`，公开部署中为 `did:wba:rwiki.cn:groups:open`。

群组本地视图接受 Message Service 的 `params.meta/body` 形状，校验可选的本地 owner 字段，并为 `group.list_messages` 支持 `limit`、`skip` 和 `since_seq` 分页。`sync.thread_after` 对群组线程应用同样的成员检查，因此离开群组后不能再用它读取该群组。

`/im/ws` 接受来自 `/ws/tickets` 或 `/user-service/ws/tickets` 的本地 ticket。它会保持连接打开，发送初始同步提示，然后为本地私信和群组参与者活动发布进程内实时通知：`direct.incoming`、`group.incoming` 和 `group.state_changed`。这是单进程 Community runtime 功能；未实现多进程 fanout、外部 pub/sub、离线 push、presence、typing indicators 和 HA 实时投递。客户端仍应使用 `sync.delta` 和 `sync.thread_after` 作为持久恢复路径。

附件上传 slot 同时返回遗留 `upload_token` 和 `upload_headers`。数据平面接受 `PUT /objects/upload/{slot_id}?token=...`，也接受返回的 `X-ANP-Upload-Token` header。`attachment.get_download_ticket` 接受本地 `object_id` owner 流程，以及包含 `object_uri`、`attachment_id`、`requester_did`、`sender_did`、`message_id`、`message_security_profile` 和 `message_target_did` 或 `group_did` 的 Message Service ANP body 形状。响应包含遗留的 `ticket/download_uri` 字段，也包含 `download_ticket_b64u/ticket_binding`。`GET /objects/{object_id}` 接受 `?ticket=...` 和 `Authorization: Bearer <download_ticket>`。这个 Community server 只会为本地已提交对象和本地私信/群组消息上下文签发 ticket；不实现跨域附件上传委托、完整的 `attachment_access_grants`、对象端到端加密授权或远程对象中继。

`/did/relationships/rpc` 和 `/user-service/did/relationships/rpc` 提供当前 CLI 目录流程使用的最小本地 DID 关系方法：`follow`、`unfollow`、`get_following`、`get_followers` 和 `get_status`。它们只对注册在本服务器配置 DID 域名中的用户生效。

`/site/rpc` 为配置的本地域名提供一个小型 Markdown 站点兼容面：`get_root`、`set_root`、`list_pages`、`get_page`、`create_page`、`update_page`、`rename_page` 和 `delete_page`。公开 `GET /` 和 `GET /pages/{slug}.md` 返回原始 Markdown。这不是生产级租户托管；跨域站点管理、模板、SEO 渲染和租户管理策略不在 Community MVP 范围内。
