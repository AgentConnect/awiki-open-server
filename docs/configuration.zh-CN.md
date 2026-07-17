# AWiki Open Server 配置参考

[English](configuration.md) | [简体中文](configuration.zh-CN.md)

## 1. 核心配置

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `AWIKI_DATA_DIR` | `.awiki-open-server` | SQLite 数据库和对象文件根目录 |
| `AWIKI_PUBLIC_BASE_URL` | `http://127.0.0.1:8000` | DID Document、服务端点与对象 URL 的公开 base |
| `AWIKI_DID_DOMAIN` | `localhost` | 本地用户 DID 和 handle 域名 |
| `AWIKI_SERVICE_DID` | `did:wba:<domain>` | `ANPMessageService` 公布的 service DID |
| `AWIKI_SERVICE_PRIVATE_KEY_PEM` | unset | 内联 Ed25519 PKCS#8 PEM；不推荐生产使用 |
| `AWIKI_SERVICE_PRIVATE_KEY_PATH` | unset | Service private key 文件路径；生产优先 |
| `AWIKI_SERVICE_DID_DOCUMENT_JSON` | generated | 可选固定 service DID Document |

## 2. 路由

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `AWIKI_IM_RPC_PATH` | `/im/rpc` | 本地客户端 JSON-RPC |
| `AWIKI_ANP_PUBLIC_RPC_PATH` | `/anp-im/rpc` | 跨域 ANP public RPC |
| `AWIKI_WS_PATH` | `/im/ws` | 本地 WebSocket 通知 |
| `AWIKI_OBJECT_UPLOAD_PATH` | `/objects/upload` | 附件上传 data plane |
| `AWIKI_OBJECT_DOWNLOAD_PATH` | `/objects` | 附件下载 data plane |

反向代理与客户端配置必须跟随实际 route，不能只修改一端。

## 3. 附件

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `AWIKI_MAX_ATTACHMENT_BYTES` | `10485760` | 最大附件大小（10 MiB） |
| `AWIKI_ATTACHMENT_ALLOWED_MIME_TYPES` | 内置 allowlist | 允许的附件 MIME 列表 |

默认 MIME 包括：

```text
application/anp-attachment-manifest+json
application/json
application/octet-stream
application/pdf
image/gif
image/jpeg
image/png
text/plain
```

修改 allowlist 时应同时测试 upload、commit、download、客户端预览和安全扫描策略。

## 4. 开发与兼容开关

| 变量 | 默认值 | 用途与风险 |
| --- | --- | --- |
| `AWIKI_ALLOW_UNSIGNED_PEER_DEV` | `false` | 仅本地测试允许未签名 public peer；公网禁止 |
| `AWIKI_DID_RESOLVER_BASE_URLS` | unset | 本地跨域测试把虚构 DID 域映射到 loopback |
| `AWIKI_DID_VERIFY_DEV_CODE` | `666666` | 本地 DID verify 开发码；不是生产身份验证 |
| `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT` | `false` | 开启旧客户端 phone/email shim；公网应关闭 |
| `AWIKI_CONTACT_VERIFICATION_DEV_OTP` | `123456` | 仅兼容 shim 使用的本地 OTP |

公共部署不得依赖这些开发默认值。

## 5. 群组与运维

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `AWIKI_GROUP_MAX_MESSAGE_BYTES` | `65536` | 规范化群消息 payload 最大字节数 |
| `AWIKI_GROUP_OUTBOX_MAX_PENDING` | `10000` | durable Group delivery 的背压阈值 |
| `AWIKI_OPERATIONS_TOKEN` | unset | `/operations/status` 的内联 Bearer secret；只适合受控测试 |
| `AWIKI_OPERATIONS_TOKEN_FILE` | unset | 独立 operations Bearer secret 的文件路径，公网部署优先 |

未配置 operations token 时 `/operations/status` 返回 `404`；缺少或提供错误 Bearer 时返回 `401`。公网部署应在仓库外创建随机 secret 文件，权限设为 `0600`，只授予 service user 读取权限，并且只配置 `AWIKI_OPERATIONS_TOKEN_FILE`。不得复用 access token、refresh token、service key 或客户端凭据。

## 6. Public Deployment 最小示例

```bash
AWIKI_DATA_DIR=/var/lib/awiki-open-server
AWIKI_PUBLIC_BASE_URL=https://community.example.com
AWIKI_DID_DOMAIN=community.example.com
AWIKI_SERVICE_DID=did:wba:community.example.com
AWIKI_SERVICE_PRIVATE_KEY_PATH=/etc/awiki-open-server/keys/service-ed25519.pem
AWIKI_ALLOW_UNSIGNED_PEER_DEV=false
AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false
AWIKI_MAX_ATTACHMENT_BYTES=10485760
AWIKI_GROUP_MAX_MESSAGE_BYTES=65536
AWIKI_GROUP_OUTBOX_MAX_PENDING=10000
AWIKI_OPERATIONS_TOKEN_FILE=/etc/awiki-open-server/operations.token
```

## 7. Service DID Document

若未提供固定 JSON，服务会从 private key 生成文档。公开文档必须满足：

- DID 与 `AWIKI_SERVICE_DID` 一致；
- verification method 为受支持的 Ed25519 Multikey；
- authentication/assertion method 正确；
- proof 可验证；
- 恰好一个 `ANPMessageService`；
- endpoint 与公开域和 RPC path 一致。

已签名 service entry 不应被服务静默改写。

## 8. 本地用户 DID

自动生成形状：

```text
did:wba:<domain>:users:<handle>:e1_default
```

上传本地 DID Document：

- 必须属于 `AWIKI_DID_DOMAIN`；
- 必须使用当前 e1 方向；
- 默认需要 proof；
- proof verification method 必须属于 DID 并被 `assertionMethod` 授权；
- service entry 必须与本服务匹配。

## 9. Token

当前本地 token 语义：

- access token：1 小时；
- refresh token：30 天；
- refresh 时 rotation；
- stale/expired refresh token 被拒绝；
- revoke 后 token、DID verify、WebSocket ticket 和 profile access 失效。

Token 不得写入截图、Issue、普通日志或客户端示例。
