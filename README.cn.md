# awiki-open-server

[English](README.md) | [简体中文](README.cn.md)

`awiki-open-server` 是一个自包含的 Awiki 社区服务器 MVP。它以一个
FastAPI 进程运行，实现社区部署所需的本地身份、消息、附件、站点和 ANP
互通能力。

它不是 `awiki.info` 的代理。运行它不需要 `awiki.info`、User Service、
Message Service 或其他 AWiki 兄弟服务。

## 这个服务器提供什么

| 领域 | 当前 MVP 包含的能力 |
| --- | --- |
| 身份 | DID 注册、公开 DID 文档、个人资料 API、本地 token、DID verification 兼容、DID revoke。 |
| 消息 | 明文私信、本地 inbox/history、sync/read-state、仅参与者能力的群组消息。 |
| 附件 | 本地上传 slot、已提交对象存储、下载 ticket、受保护对象下载。 |
| 站点内容 | Markdown 页面 API 和公开原始 Markdown 页面路由。 |
| 兼容性 | 当前客户端和 Rust CLI 使用的本地 User Service、Message Service 兼容路由。 |
| 互通 | 用于跨域 ANP 私信调用和部分群组/附件方法的公开 `/anp-im/rpc` 入口。 |
| 实时能力 | 面向本地私信和群组活动的单进程 WebSocket 通知。 |

## 当前边界

社区版有意保持运行时简单。以下能力不在这个 MVP 范围内：

| 不包含的能力 | 说明 |
| --- | --- |
| 群组管理 | `group.create`、`group.add`、`group.remove`、`group.update_profile` 和 `group.update_policy` 返回 `not_supported`。 |
| 私信或群组端到端加密 | 消息会保留 payload 形状，但服务器不实现 E2EE。 |
| 联邦基础设施 | 不包含 federation peer routes、中继、远程投影或远程对象中继。 |
| 生产级身份提供方 | 不包含生产短信、邮件、阿里云、手机号验证或邮箱验证流程。 |
| 托管平台能力 | 不包含计费、多租户托管、托管运行时编排、委托式密钥管理或生产 policy 引擎。 |
| 高可用实时能力 | WebSocket 通知只在进程内发布；不包含外部 pub/sub、离线 push、presence、typing indicators 或 HA fanout。 |
| 同步日志修复 | 不包含 snapshot repair、retention-floor pruning 或事件日志压缩；MVP 仍保持 `retention_floor_event_seq = "0"`。 |

## 快速开始

使用 Python 3.10 或更新版本。如果系统 `python3` 版本较旧，请使用显式解释器创建环境，例如 `python3.11`。

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e '.[dev]'
```

启动服务器：

```bash
PYTHONPATH=src \
AWIKI_DATA_DIR=.awiki-open-server \
AWIKI_PUBLIC_BASE_URL=http://127.0.0.1:8765 \
AWIKI_DID_DOMAIN=localhost \
.venv/bin/python -m uvicorn 'awiki_open_server.app.main:create_app' \
  --factory --host 127.0.0.1 --port 8765
```

检查健康接口：

```bash
curl --noproxy '*' http://127.0.0.1:8765/healthz
```

预期响应：

```json
{"status":"ok","edition":"community"}
```

`--noproxy '*'` 用于避免本地检查被开发机器上的 HTTP 代理转发。

## 依赖说明

依赖集固定 ANP Python SDK 为 `anp==0.8.8`。

如果加载了其他 SDK 版本，`awiki_open_server.protocol.anp_adapter` 会快速失败。在当前工作区，如果活跃环境中仍安装了旧版 `anp` 包，本地验证可以通过 `PYTHONPATH=../anp/anp:src` 使用相邻 SDK checkout。

## 安全注意事项

不要提交本地运行数据或密钥：

- `.awiki-open-server/`
- SQLite 数据库
- 对象文件
- `.env`
- 真实 token
- 服务私钥

公开部署时，请保持 `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false`，并且不要启用 `AWIKI_ALLOW_UNSIGNED_PEER_DEV`。使用真实服务私钥部署时，优先使用 `AWIKI_SERVICE_PRIVATE_KEY_PATH`，不要把私钥直接写进环境变量。

## 身份和 Token

本地用户受限于本服务器配置的 DID 域名。自动生成的用户 DID 使用
`did:wba:<domain>:users:<handle>:e1_default` 形状；上传的本地 DID 文档必须
使用 `did:wba:<AWIKI_DID_DOMAIN>:...`，并且包含 `e1_` 段。域名不匹配或非
e1/K1-like DID 会 fail closed。

上传的 DID 文档默认必须带 proof；只有为本地开发显式启用
`AWIKI_ALLOW_UNSIGNED_PEER_DEV=true` 时才允许未签名文档。带签名的上传 DID
文档会执行 `DataIntegrityProof` / `eddsa-jcs-2022` 密码学验证：proof
verification method 必须属于该 DID、被 `assertionMethod` 授权、暴露
Ed25519 Multikey，并且能通过 proof options 和去掉 `proof` 的 DID Document
的 JCS hash 验签。带签名文档必须只包含一个 `ANPMessageService`，且 endpoint
和 service DID 必须匹配本服务；已签名的 service entry 不会被静默改写。

注册会返回 access token 和 refresh token。Access token 1 小时过期；
refresh token 30 天过期，并在刷新时轮换。旧 refresh token 或过期 refresh
token 会被拒绝。为兼容迁移，只有历史行的 `refresh_token` 仍为 null 时，才
允许使用旧 access token 作为刷新凭据。

## 配置

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
| `AWIKI_MAX_ATTACHMENT_BYTES` | `10485760` | 允许接收的附件对象最大字节数。 |
| `AWIKI_ATTACHMENT_ALLOWED_MIME_TYPES` | `application/anp-attachment-manifest+json,application/json,application/octet-stream,application/pdf,image/gif,image/jpeg,image/png,text/plain` | 逗号分隔的附件 MIME allowlist。 |
| `AWIKI_ALLOW_UNSIGNED_PEER_DEV` | `false` | 仅为本地开发测试允许未签名的 `/anp-im/rpc direct.send`。不要在真实互通中启用。 |
| `AWIKI_DID_RESOLVER_BASE_URLS` | 未设置 | 可选的开发解析器映射，例如 `source.test=http://127.0.0.1:9001,target.test=http://127.0.0.1:9002` 或 JSON 对象。正常公开部署保持未设置。 |
| `AWIKI_DID_VERIFY_DEV_CODE` | `666666` | 本地 `/did-verify/rpc login` 开发验证码。如果设置了 `DEV_BYPASS_CODE`，则回退使用它。 |
| `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT` | `false` | 为旧客户端测试启用遗留本地手机号/邮箱验证 shim。MVP 和公开部署应保持关闭。 |
| `AWIKI_CONTACT_VERIFICATION_DEV_OTP` | `123456` | 仅在显式启用 contact verification 兼容时使用的本地兼容 OTP。 |

## 公开部署和互通

真实跨域私信互通需要配置稳定的服务 DID 和私钥：

```bash
AWIKI_PUBLIC_BASE_URL=https://rwiki.cn
AWIKI_DID_DOMAIN=rwiki.cn
AWIKI_SERVICE_DID=did:wba:rwiki.cn
AWIKI_SERVICE_PRIVATE_KEY_PATH=/secure/path/rwiki-service-ed25519.pem
AWIKI_ALLOW_UNSIGNED_PEER_DEV=false
AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false
AWIKI_MAX_ATTACHMENT_BYTES=10485760
AWIKI_ATTACHMENT_ALLOWED_MIME_TYPES=application/anp-attachment-manifest+json,application/json,application/octet-stream,application/pdf,image/gif,image/jpeg,image/png,text/plain
```

部署要求：

- `https://rwiki.cn/.well-known/did.json` 必须由这个进程提供。
- DID 文档必须包含匹配的 `verificationMethod`、`authentication`、proof，以及唯一一个公开 `ANPMessageService`。
- 出站远程私信请求需要客户端或 CLI ANP envelope 中的 `auth.origin_proof`。
- 服务器会原样转发 `auth.origin_proof`，并使用 `AWIKI_SERVICE_DID` 签署 HTTP hop。
- `rwiki.cn` 必须代理到这个进程，而不是代理到 `awiki.info`、`user-service` 或 `message-service`。

部署模板位于 `deploy/`。它们展示如何在 localhost 上运行 Uvicorn，并通过 nginx 发布 `https://rwiki.cn`。

## 测试和 Smoke 检查

运行完整测试套件：

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests -q
```

重点测试范围：

| 范围 | 文件 |
| --- | --- |
| ANP SDK 和签名 | `tests/test_protocol_anp_sdk.py` |
| 路由和路径配置 | `tests/test_route_config.py` |
| User Service 兼容性 | `tests/test_user_service_compat.py`、`tests/test_identity_documents.py`、`tests/test_contact_auth_compat.py`、`tests/test_profile_compat.py`、`tests/test_agent_compat.py`、`tests/test_site_relationships.py` |
| 消息能力面 | `tests/test_messaging_surface.py`、`tests/test_direct_messages.py`、`tests/test_group_participant.py`、`tests/test_attachments.py`、`tests/test_sync_read_state.py` |
| 公开部署门禁 | `tests/test_rwiki_cn_system.py`，除非设置 `AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1`，否则跳过 |

Smoke 命令：

| 检查 | 命令 | 验证内容 |
| --- | --- | --- |
| 进程内 ASGI smoke | `PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-cli-asgi` | 不启动 Uvicorn 的核心本地流程。 |
| 本地 HTTP smoke | `PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-local --base-url http://127.0.0.1:8765 --did-domain localhost` | 通过 HTTP 访问运行中的本地服务器。 |
| 本地跨域 smoke | `PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-cross-domain-local --clean` | 两个本地服务器、DID 发现、客户端 origin proof、服务 HTTP Signature、签名的 `/anp-im/rpc direct.send` 和双向 inbox 投递。 |
| 公开部署验证 | `PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py verify-public --base-url https://rwiki.cn --did-domain rwiki.cn` | 确认公开域名正在由这个仓库提供服务。 |
| 受保护的公开系统测试 | `AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 PYTHONPATH=src .venv/bin/python -m pytest tests/test_rwiki_cn_system.py -q` | `https://rwiki.cn` 上的公开服务 DID 文档、能力、关闭的 contact verification、DID 注册、inbox/history 和开放群组边界。 |

说明：

- `smoke-cross-domain-local` 会启动两个独立的 Uvicorn 进程，使用独立的 SQLite 存储、服务 DID 和 Ed25519 服务密钥。
- 它只使用 `AWIKI_DID_RESOLVER_BASE_URLS` 将测试 DID 域名映射到 loopback 端口。
- 它是本地协议门禁，不能替代公开的 `rwiki.cn` 到 `awiki.info` 互通门禁。
- 在使用 `rwiki.cn` 进行真实 `awiki.info` 互通测试之前，`verify-public` 必须通过。
- `/.well-known/did.json`、`/healthz` 或 `/anp-im/rpc` 返回 404 表示公开域名尚未路由到这个服务器。

## Rust CLI 兼容性

现有 Rust CLI 可以连接这个服务器。请使用隔离的 `awiki-cli-rs2` worktree
和临时 CLI workspace，避免验证写入开发者正在使用的 CLI checkout。

构建 CLI：

```bash
CARGO_TARGET_DIR=/tmp/awiki-cli-rs2-open-server-target \
  cargo build -p awiki-cli --bin awiki-cli --locked
```

注册本地测试身份：

```bash
AWIKI_CLI_WORKSPACE_HOME_DIR=/tmp/awiki-cli-open-server-workspace \
  /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli \
  id register --handle cli-alice --phone 13800138000 --otp 123456
```

当前 Rust CLI 在执行 `id register` 时仍要求传入 `--phone` 或 `--email`。在这个 MVP 中，这些参数只是为了保持现有 CLI 命令形态。服务器端 `did-auth.register` 路径不会发送短信、发送邮件、调用阿里云，或持久化手机号/邮箱验证状态。

运行可重复的本地 Rust CLI 门禁：

```bash
PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-rust-cli-local \
  --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli \
  --data-root /tmp/awiki-open-server-rust-cli-local --clean
```

该命令验证：

- 通过本地 DID 注册路径注册。
- 私信发送、inbox 和 history。
- 群组 join、send 和 messages。
- People `follow`、`status`、`following` 和 `followers`。
- Site root 和 page 命令。

这是本地 User Service / Message Service 兼容性门禁，不能替代公开的
`rwiki.cn` 到 `awiki.info` 互通门禁。

## 兼容模型

| 兼容范围 | 行为 |
| --- | --- |
| Rust CLI 路由 | `/user-service/did-auth/rpc`、`/user-service/did/profile/rpc` 和 `/user-service/handle/rpc` 由本仓库本地实现，不会转发到外部 User Service。 |
| Agent 路由 | `/user-service/agent-registration/rpc`、`/user-service/message-agent/rpc` 和 `/user-service/agent-inventory/rpc` 覆盖 daemon 状态、controller scope、sender 检查、调用授权、archive 和本地 policy 字段。 |
| Agent 限制 | Agent 兼容只覆盖本地一次性注册 token、message-agent 绑定状态和 daemon 兼容性；不实现托管运行时编排、委托式密钥管理或生产 policy 引擎。 |
| Contact verification | `/auth/sms`、`/auth/sms-codes`、`/auth/email-send`、`/auth/email-status` 和 phone-bind 路由默认返回 `contact_verification_not_enabled`。 |
| Contact verification shim | 只有本地兼容测试才应设置 `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=true`。即使启用，这些路由也只是进程内开发 shim，不会调用短信、邮箱、阿里云、`awiki.info`、User Service 或 Message Service。 |
| Token 和 WebSocket 验证 | 兼容辅助路由会返回 `X-User-Id` 和 `X-DID` header，用于 nginx `auth_request` 集成。 |
| DID verification | `/did-verify/rpc` 和 `/user-service/did-verify/rpc` 暴露 `send_code`、`login` 和 `refresh`。`send_code` 不调用外部 message service。`login` 接受 `AWIKI_DID_VERIFY_DEV_CODE`，默认 `666666`；如果设置了 `DEV_BYPASS_CODE`，则使用它。 |
| DID verification 范围 | DID verification 使用已注册 DID 的本地 Community token，不会启用手机号或邮箱验证。 |
| DID revoke | `revoke` 会将本地用户和 DID 文档标记为 inactive。同一个 token 或 DID 之后不能再通过 token verification、DID verify login/refresh、WebSocket ticket verification、`get_me` 或 `update_document`。 |
| Revoke 后的数据保留 | 个人资料和历史消息数据仍会保留，但 active DID 文档路由返回 404。 |
| 不支持的 DID auth 方法 | `replace_did` 和 `recover_handle` 在社区服务器中仍不支持。 |
| 旧版 profile 客户端 | `/me`、`/me/rpc`、`/profiles/{user_id}`、`/user-service/profiles/{user_id}`、`/users/{user_id}/profile` 和 `/users/rpc` 会把 `user_id` 映射为本地 DID，不会调用外部 User Service。 |

## 远程 awiki.info 诊断

远程能力诊断可以调用在线 `awiki.info` 服务，但 `awiki.info` 是用于互通测试的远程 peer，不是这个服务器的后端。

```bash
PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-awiki-info \
  --base-url https://awiki.info \
  --did-domain rwiki.cn
```

要发送私信测试消息，还需要提供：

- `--token` 或 `AWIKI_INFO_TOKEN`
- `--sender-did` 或 `AWIKI_INFO_SENDER_DID`
- `--recipient-did` 或 `AWIKI_INFO_RECIPIENT_DID`
- `--origin-proof-json` 或 `AWIKI_INFO_ORIGIN_PROOF_JSON`

请求形状要求：

| 检查 | 形状 |
| --- | --- |
| 远程能力 | ANP JSON-RPC `params.meta/body` |
| 远程私信 | ANP JSON-RPC `params.meta/auth/body` |

如果响应为 `missing params.meta`，说明请求形状错误，不能视为通过远程检查。

没有这些 direct 凭据时，`smoke-awiki-info` 只能证明远端 capability 调用。它的
JSON 输出会包含 `direct_ready`、`credential_status`、`missing_credentials`
和 `live_direct_gate`；当 `live_direct_gate = "skipped_missing_credentials"`
时，这表示 live direct 验证被凭据阻塞，不能当作通过。

真实互通验证需要：

1. 在可访问的独立 base URL 上运行这个服务器。
2. 配置服务私钥。
3. 让 Rust CLI 指向该 URL。
4. 使用 `awiki.info` 上的现有用户或测试用户作为远端。

有效测试需要证明两个方向：

| 方向 | 预期行为 |
| --- | --- |
| 本地 open-server 用户到 `awiki.info` 用户 | 这个服务器解析远端 DID 文档，保留 CLI 的 `auth.origin_proof`，以 `AWIKI_SERVICE_DID` 签署 HTTP hop，并将 `direct.send` POST 到远端 `ANPMessageService.serviceEndpoint`。 |
| `awiki.info` 用户到本地 open-server 用户 | `awiki.info` 解析本服务器的 DID 文档，并将签名的 `direct.send` POST 到本服务器的 `/anp-im/rpc`。 |

不要把两个都指向 `https://awiki.info` 的 CLI workspace 当作这个仓库的验证；那只是在验证在线服务自身。

## API 参考

核心路由和兼容路由会一起挂载。Contact-verification 兼容路由为旧客户端保留，但除非为本地测试显式设置 `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=true`，否则返回 `contact_verification_not_enabled`。

| 路由 | 用途 | 说明 |
| --- | --- | --- |
| `GET /healthz`<br>`GET /health`<br>`GET /user-service/health`<br>`GET /im/healthz` | 健康检查。 | `/healthz` 返回服务器状态和版本类型。 |
| `POST /did-auth/rpc`<br>`POST /user-service/did-auth/rpc` | DID auth 和注册兼容。 | 本地实现。支持本地 revoke。不发送短信/邮件，也不调用阿里云。 |
| `POST /did-verify/rpc`<br>`POST /user-service/did-verify/rpc` | DID verification 兼容。 | 暴露 `send_code`、`login` 和 `refresh`，使用本地开发验证码。 |
| `POST /did/profile/rpc`<br>`POST /user-service/did/profile/rpc` | DID profile RPC 兼容。 | 将 profile 字段映射到本地 DID profile 记录。 |
| `GET /me`<br>`PATCH /me`<br>`POST /me/rpc`<br>`GET /user-service/me`<br>`PATCH /user-service/me`<br>`POST /user-service/me/rpc` | 当前用户 profile 兼容。 | 使用本地 Community token 和本地 DID 身份。 |
| `GET /profiles/{user_id}`<br>`GET /user-service/profiles/{user_id}`<br>`GET /users/{user_id}/profile`<br>`GET /user-service/users/{user_id}/profile` | Profile 查询兼容。 | 在这个服务器中，`user_id` 是本地 DID。 |
| `POST /users/rpc`<br>`POST /user-service/users/rpc` | 旧版用户查询 RPC 兼容。 | 仅本地实现，不调用外部 User Service。 |
| `POST /handle/rpc`<br>`POST /user-service/handle/rpc` | Handle 兼容 RPC。 | 使用本服务器配置的 DID 域名。 |
| `POST /did/relationships/rpc`<br>`POST /user-service/did/relationships/rpc` | 本地 DID 关系。 | 支持 `follow`、`unfollow`、`get_following`、`get_followers` 和 `get_status`，只作用于配置 DID 域名中已注册的用户。 |
| `POST /user-service/agent-registration/rpc` | Agent 注册兼容。 | 支持本地一次性 agent 注册 token。 |
| `POST /user-service/agent-inventory/rpc` | Agent inventory 兼容。 | 覆盖当前客户端使用的本地 daemon 和 inventory 字段。 |
| `POST /user-service/message-agent/rpc` | Message-agent 兼容。 | 覆盖绑定状态、sender 检查、controller scope、调用授权、archive 和本地 policy 字段。 |
| `POST /auth/sms-codes`<br>`POST /user-service/auth/sms-codes`<br>`POST /auth/sms`<br>`POST /user-service/auth/sms` | 遗留 SMS 验证兼容。 | 默认关闭。只有启用 contact verification 兼容时才作为开发 shim。 |
| `POST /auth/email-send`<br>`POST /user-service/auth/email-send`<br>`GET /auth/email-status`<br>`GET /user-service/auth/email-status` | 遗留邮箱验证兼容。 | 默认关闭。仅开发 shim；不会发送真实邮件。 |
| `POST /auth/phone-bind-send`<br>`POST /user-service/auth/phone-bind-send`<br>`POST /auth/phone-bind-verify`<br>`POST /user-service/auth/phone-bind-verify` | 遗留 phone-bind 兼容。 | 默认关闭。仅开发 shim；不会调用短信或阿里云。 |
| `POST /auth/token-refresh`<br>`POST /user-service/auth/token-refresh` | Token refresh 兼容。 | 本地 Community token 流程，并轮换 refresh token。 |
| `GET /auth/token-verify`<br>`GET /user-service/auth/token-verify`<br>`GET /auth/verify`<br>`GET /user-service/auth/verify`<br>`GET /sessions/verify`<br>`GET /user-service/sessions/verify` | Token 和 session 验证兼容。 | 返回本地验证 header，可用于 nginx `auth_request` 集成。 |
| `POST /ws/tickets`<br>`POST /user-service/ws/tickets` | 本地 WebSocket ticket 创建。 | Ticket 可用于 `/im/ws`。 |
| `GET /ws/tickets/verify`<br>`GET /user-service/ws/tickets/verify`<br>`GET /auth/ws-ticket/verify`<br>`GET /user-service/auth/ws-ticket/verify` | WebSocket ticket 验证。 | 面向代理和旧客户端的本地兼容辅助能力。 |
| `POST /content/rpc`<br>`POST /user-service/content/rpc` | Markdown content 兼容 RPC。 | 本地内容 API。 |
| `GET /content/{slug}.md` | 原始 Markdown 内容路由。 | 返回配置本地域名下的 Markdown。 |
| `POST /site/rpc` | Markdown site RPC。 | 支持下文列出的 root 和 page 管理方法。 |
| `GET /`<br>`GET /pages/{slug}.md` | 公开 Markdown 站点路由。 | 返回原始 Markdown。不是生产级租户托管。 |
| `POST /im/rpc` 或 `AWIKI_IM_RPC_PATH` | 本地客户端 JSON-RPC 入口。 | Inbox、history、sync、read-state、群组参与者和附件控制方法。 |
| `POST /anp-im/rpc` 或 `AWIKI_ANP_PUBLIC_RPC_PATH` | 公开 ANP JSON-RPC 入口。 | 受限公开跨域方法。公开 `direct.send` 和 `group.join` 需要 origin proof 和服务 HTTP Signature，除非启用了 unsigned peer dev 模式。 |
| `PUT /objects/upload/{slot_id}` 或 `AWIKI_OBJECT_UPLOAD_PATH/{slot_id}` | 附件上传数据平面。 | 接受 `?token=...` 或返回的 `X-ANP-Upload-Token`。 |
| `GET /objects/{object_id}` 或 `AWIKI_OBJECT_DOWNLOAD_PATH/{object_id}` | 附件下载数据平面。 | 接受 `?ticket=...` 和 `Authorization: Bearer <download_ticket>`。 |
| `GET /.well-known/did.json` | 公开服务 DID 文档。 | 真实公开互通时必须由这个进程提供。 |
| `GET /dids/resolve/{sub_path}/did.json`<br>`GET /{sub_path}/did.json` | 公开 DID 文档解析。 | 发布配置域名下的本地 DID 文档。 |

## JSON-RPC 能力面

| 能力面 | 方法 | 行为 |
| --- | --- | --- |
| 本地 `/im/rpc` | Inbox、history、sync、read-state、群组参与者和附件控制方法。 | 面向已认证 Community 用户的本地客户端入口。按文档接受 Message Service `params.meta/body` 形状和较旧的扁平 params。 |
| 公开 `/anp-im/rpc` | `anp.get_capabilities`、`direct.send`、`group.get_info`、`group.join`、`attachment.get_download_ticket`。 | 跨域入口。公开 `direct.send` 和 `group.join` 要求业务层 `auth.origin_proof` 和服务间 HTTP Signature，除非启用了 unsigned peer dev 模式。 |
| DID 关系 | `follow`、`unfollow`、`get_following`、`get_followers`、`get_status`。 | 只作用于本服务器配置 DID 域名中已注册的用户。 |
| Site RPC | `get_root`、`set_root`、`list_pages`、`get_page`、`create_page`、`update_page`、`rename_page`、`delete_page`。 | 面向配置本地域名的小型 Markdown 站点兼容面。 |

## 消息语义

| 主题 | 行为 |
| --- | --- |
| Payload 存储 | 私信和群组消息会保留 Message Service payload 形状。 |
| 文本 payload | `text/plain` 使用 `body.text`。 |
| JSON payload | `application/json` 和 `application/anp-attachment-manifest+json` 使用 `body.payload` 作为 JSON 对象。 |
| 其他 payload | 其他非文本内容类型使用 `body.payload_b64u`。 |
| 校验 | 当 body 字段与 `meta.content_type` 不匹配时，ANP-envelope 消息会被拒绝。较旧的扁平 text CLI 调用仍保持兼容。 |
| 本地投影 | `inbox.get`、`direct.get_history`、`group.list_messages` 和 `sync.thread_after` 返回 Message Service 风格投影：`type=text`、`type=json`、`type=attachment_manifest` 或 `type=binary`。 |
| 原始数据 | 原始 `body` 和 `content_type` 仍包含在响应中，供需要原始 ANP 形状的客户端使用。 |
| 本地 owner 校验 | 当存在时，`meta.sender_did` 和 `body.user_did` 必须与已认证的本地 DID 匹配。 |
| 分页 | `inbox.get` 支持 `skip` 和 `limit`。`direct.get_history` 支持 `peer_did`、`since_seq` 或 `since`、`skip` 和 `limit`。 |
| 已废弃群组历史路径 | direct-history 的 `group_did` 路径会被拒绝。群组历史请使用 `group.list_messages`。 |

## 已读状态和同步

| 方法 | 行为 |
| --- | --- |
| `inbox.mark_read` | 将当前用户可见的私信 message id 标记到 `direct_message_views.read_at`。 |
| `inbox.get` | 默认只返回未读消息。使用 `{"include_read": true}` 可包含已读消息。 |
| `direct.get_history` | 可以显示带 `is_read` 和 `read_at` 的已读消息。 |
| `sync.delta` | 返回账号级 metadata event。`direct.message.created` 和 `group.message.created` payload 只标识 thread 和 message，不包含 `body`、`content` 或消息正文。分页使用多取一条判断稳定的 `has_more`；`retention_floor_event_seq` 仍为 `"0"`。 |
| `sync.thread_after` | 通过 `after_server_seq` 返回线程内持久内容，并使用与群组读取相同的成员检查。离开群组后不能再用它读取该群组。分页也使用多取一条判断稳定的 `has_more`。 |
| `read_state.mark_read` | 只是线程水位 API。私信线程会把 `read_up_to_server_seq` 前的未读视图标记为已读；群组线程按 thread-local `server_seq` 水位计算。返回实际 `updated_count` 和剩余 `unread_count`。 |
| 不支持的 read-state checkpoint | `event_seq`、`since_event_seq`、`next_event_seq`、`checkpoint` 和 `read_up_to_group_event_seq` 会被拒绝。MVP 不发出 `message.read_state_updated` sync event。 |

## Heartbeat 消息

只有已记录的 daemon liveness heartbeat 会被视为 no-store：

| 必需字段 | 值 |
| --- | --- |
| Content type | `application/json` |
| `body.payload.schema` | `awiki.agent.status.v1` |
| `status_scope` | `daemon` |
| `message` | `daemon heartbeat` |

对于该 heartbeat，服务器返回 `delivery_state = ephemeral`，并可能通知在线收件人。它不会把 heartbeat 写入 inbox、history、sync events 或发送方历史。

其他 daemon/App status payload，包括 run 和 snapshot 状态，仍然是持久消息。

## 群组参与者能力

| 支持的参与者方法 | 说明 |
| --- | --- |
| `group.get_info` | 暴露最小的现有群组信息，用于发现和开放加入。 |
| `group.join` | 允许加入预置开放群组。公开使用需要 origin proof 和服务签名。 |
| `group.leave` | 要求当前 DID 是群组成员。 |
| `group.send` | 要求当前 DID 是群组成员。 |
| `group.get` | 要求当前 DID 是群组成员。 |
| `group.list` | 列出本地群组参与状态。 |
| `group.list_members` | 要求当前 DID 是群组成员。 |
| `group.list_messages` | 要求当前 DID 是群组成员。支持 `limit`、`skip` 和 `since_seq`。 |

不支持的管理方法返回 `not_supported`：

- `group.create`
- `group.add`
- `group.remove`
- `group.update_profile`
- `group.update_policy`

预置开放加入群组 DID 遵循 `AWIKI_DID_DOMAIN`，例如：

- 本地：`did:wba:localhost:groups:open`
- 公开部署：`did:wba:rwiki.cn:groups:open`

## 实时能力

`/im/ws` 接受来自 `/ws/tickets` 或 `/user-service/ws/tickets` 的本地 ticket。

该连接会：

- 保持打开。
- 发送不包含 checkpoint 或 `event_seq` 的初始同步提示。
- 为本地私信和群组参与者活动发布进程内通知。

通知类型：

- `direct.incoming`
- `group.incoming`
- `group.state_changed`

客户端仍应使用 `sync.delta` 和 `sync.thread_after` 作为持久恢复路径。私信和群组
通知附带的 `sync` 对象只是调度/缺口提示，不是已读水位、checkpoint 或线程
`server_seq`。

## 附件

| 步骤 | 行为 |
| --- | --- |
| 创建上传 slot | 同时返回遗留 `upload_token` 和 `upload_headers`。 |
| 上传对象 | `PUT /objects/upload/{slot_id}?token=...`，或发送返回的 `X-ANP-Upload-Token` header。 |
| 请求下载 ticket | `attachment.get_download_ticket` 接受本地 `object_id` owner 流程和 Message Service ANP body 形状。 |
| 下载对象 | `GET /objects/{object_id}` 接受 `?ticket=...` 和 `Authorization: Bearer <download_ticket>`。 |

上传 slot 30 分钟后过期。下载 ticket 15 分钟后过期。
`attachment.create_slot` 接受 `expected_size`、`expected_digest` /
`expected_sha256`、`content_type` / `expected_content_type` 等期望元数据。
上传和 commit 会在对象变为 committed 前校验 token、slot 状态、过期时间、最大
大小、SHA-256 digest 和 MIME allowlist。`cleanup_expired_attachments` helper
可以清理过期未提交 slot 和过期 ticket，但 MVP 不提供公开清理接口或后台
daemon。

`attachment.get_download_ticket` 接受：

- `object_uri`
- `attachment_id`
- `requester_did`
- `sender_did`
- `message_id`
- `message_security_profile`
- `message_target_did` 或 `group_did`

响应同时包含遗留的 `ticket/download_uri` 字段和
`download_ticket_b64u/ticket_binding`。

这个 Community server 只会为本地已提交对象和本地私信/群组消息上下文签发
ticket。它不实现跨域附件上传委托、完整的 `attachment_access_grants`、对象
E2EE 授权或远程对象中继。

## 代码结构

| 路径 | 职责 |
| --- | --- |
| `src/awiki_open_server/protocol/anp_adapter.py` | 唯一的 ANP Python SDK 适配器。要求 `anp==0.8.8`。 |
| `src/awiki_open_server/service_identity.py` | HTTP Signatures、Content-Digest、服务 DID 和 origin proof 校验。 |
| `src/awiki_open_server/app/` | FastAPI 设置、路由挂载和实时能力接线。 |
| `src/awiki_open_server/messaging/` | 私信、群组参与者方法、本地同步和已读状态处理。 |
| `src/awiki_open_server/attachments/` | 本地上传 slot、已提交对象和下载 ticket。 |
| `src/awiki_open_server/user_compat/` | 本地 User Service 兼容面。 |
| `src/awiki_open_server/shared/runtime.py` | DID 发现、HTTP JSON、签名、对象 URL 和实时辅助函数。 |
| `src/awiki_open_server/services.py` | 兼容性 facade，以及剩余的内容、站点和 DID 关系处理器。新的领域逻辑应该进入对应领域包，而不是再放回 `services.py`。 |
