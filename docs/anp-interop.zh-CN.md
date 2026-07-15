# AWiki Open Server ANP 互通

[English](anp-interop.md) | [简体中文](anp-interop.zh-CN.md)

## 1. 目标

当前互通目标是：

- 发布可解析的 service/user DID Document；
- 公开有限的 `/anp-im/rpc`；
- 验证业务 `auth.origin_proof`；
- 验证服务间 HTTP Signature 与 Content-Digest；
- 让本地域和远端域进行双向 Direct；
- 支持选定 Group/Attachment public method。

这不是完整 federation。

## 2. Public Service DID

公开域必须提供：

```text
GET https://community.example.com/.well-known/did.json
```

文档应包含：

- `did:wba:community.example.com`；
- 可验证 Ed25519 method；
- authentication/assertionMethod；
- proof；
- 恰好一个 `ANPMessageService`；
- endpoint `https://community.example.com/anp-im/rpc`。

## 3. Public RPC

当前公开方法：

| Method | 用途 | 认证要求 |
| --- | --- | --- |
| `anp.get_capabilities` | 能力发现 | 按公开 capability contract |
| `direct.send` | 跨域 Direct | origin proof + service HTTP Signature |
| `group.get_info` | 发现 open group | 按当前 public contract |
| `group.join` | 加入 open group | origin proof + service signature |
| `attachment.get_download_ticket` | 获取本地对象下载 ticket | 本地对象与消息上下文验证 |

Public `direct.send` / `group.join` 仅在本地开发显式开启 unsigned peer 模式时可放宽。公网不能开启。

## 4. 两层认证

### 业务 origin proof

证明用户/Agent 对业务调用的授权。Open Server 对 outbound 请求保留并转发客户端 envelope 中的 `auth.origin_proof`。

### 服务间 HTTP Signature

证明当前 HTTP hop 来自目标域信任的 service DID。服务使用 `AWIKI_SERVICE_PRIVATE_KEY_PATH` 对请求签名，并验证远端签名与 DID Document。

两者不能相互替代。

## 5. Outbound Direct

```text
Local client
→ Open Server validates local identity and origin proof
→ resolves remote recipient DID
→ reads remote ANPMessageService endpoint
→ signs HTTP hop as local service DID
→ POST remote /anp-im/rpc direct.send
```

## 6. Inbound Direct

```text
Remote user/service
→ resolves local service/user DID Documents
→ sends origin proof + signed HTTP request
→ Open Server verifies signature and proof
→ writes local Direct view/event
→ local client reads Inbox/History or receives realtime hint
```

## 7. 本地跨域 Gate

```bash
PYTHONPATH=src \
.venv/bin/python scripts/awiki_open_cli.py smoke-cross-domain-local \
  --data-root /tmp/awiki-open-server-cross-domain-local \
  --clean
```

它启动两个独立 Uvicorn 进程，使用独立 SQLite、service DID 和 Ed25519 key，并通过 resolver map 把测试域映射到 loopback。

该 Gate 证明协议方向，但不证明公网 DNS、TLS、Nginx 和真实远端服务。

## 8. 公开验证

```bash
PYTHONPATH=src \
.venv/bin/python scripts/awiki_open_cli.py verify-public \
  --base-url https://community.example.com \
  --did-domain community.example.com
```

然后使用真实远端 peer 做双向 Direct。

### 不足以通过的情况

- 只有 `anp.get_capabilities` 成功；
- `live_direct_gate = skipped_missing_credentials`；
- 两个 CLI workspace 都连接到 `awiki.info`；
- 只验证本地 loopback；
- 远端返回 `missing params.meta` 等请求形状错误；
- 公网域实际代理到其他 AWiki 服务。

## 9. Attachment 边界

当前 Community Server 只为本地 committed object 和本地 Direct/Group message context 签发 ticket。

不包含：

- 跨域 upload delegation；
- 完整 attachment access grant；
- object E2EE authorization；
- remote object relay。

## 10. 故障记录

互通失败至少记录：

```text
方向：local -> remote / remote -> local
source service DID：
target service DID：
sender DID：
recipient DID：
target URL：
HTTP status：
JSON-RPC error code/body（脱敏）：
DID Document digest/version：
service log correlation：
```

不要记录 private key、完整 token 或 origin proof 中的敏感材料。
