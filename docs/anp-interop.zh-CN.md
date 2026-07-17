# AWiki Open Server ANP 互通

[English](anp-interop.md) | [简体中文](anp-interop.zh-CN.md)

## 1. 目标

当前互通目标是：

- 发布可解析的 service/user/Group DID Document；
- 公开 Community ANP `/anp-im/rpc`；
- 验证业务 `auth.origin_proof`；
- 验证服务间 HTTP Signature 与 Content-Digest；
- 验证 Group Receipt；
- 让本地域和远端域进行双向 Direct；
- 支持小规模跨域 Group Host、成员域 projection 和选定 Attachment public method。

这是 DID discovery 后的服务直连，不是 federation relay 或 peer-route mesh。

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
| `group.create`、`group.get_info` | 创建 Group Host 或按权限读取群状态 | create 需要 origin proof；读取遵循 P4 可见性；跨域需要 service signature |
| `group.join`、`group.add`、`group.remove`、`group.rebind_member`、`group.leave` | 立即生效的成员生命周期 | origin proof + service signature |
| `group.update_profile`、`group.update_policy`、`group.send` | 群管理与消息 | origin proof、角色/成员校验和 service signature |
| `group.incoming`、`group.state_changed` | 成员域投递 Notification | 无 JSON-RPC `id`；signed peer request + Group Receipt |
| `attachment.get_download_ticket` | 获取本地对象下载 ticket | 本地对象与消息上下文验证 |

Public peer 调用仅在本地开发显式开启 unsigned peer 模式时可放宽。公网不能开启。Inbox、History、sync、read-state、本地群 list/history 和附件 upload/commit 仍是本地客户端方法。

## 4. 两层认证

### 业务 origin proof

证明用户/Agent 对业务调用的授权。Open Server 对 outbound 请求保留并转发客户端 envelope 中的 `auth.origin_proof`。

### 服务间 HTTP Signature

证明当前 HTTP hop 来自目标域信任的 service DID。服务使用 `AWIKI_SERVICE_PRIVATE_KEY_PATH` 对请求签名，并验证远端签名与 DID Document。

两者不能相互替代。

普通群请求的 P8 caller anchor 是 `meta.sender_did`。`group.incoming` 与 `group.state_changed` 的 caller anchor 是 `body.group_did`，且二者必须是没有 JSON-RPC `id` 的 Notification。

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

## 7. 跨域 Group

```text
Local member -> local Open Server verifies origin proof
-> resolves Group DID and calls remote Group Host
-> remote host commits one ordered event and signs Group Receipt
-> durable outbox sends group.incoming/group.state_changed to member homes
-> member home verifies peer signature, Content-Digest, caller anchor,
   Group Receipt, payload digest and event sequence before projection
```

`group.add` 和 `group.join` 成功后成员立即 active，不存在 invitation、token、join code、pending membership 或 accept 步骤。跨域投递按目标 FIFO durable retry，并支持重启恢复；这不等于 relay、HA 或大群 fanout。

## 8. 本地跨域 Gate

```bash
PYTHONPATH=src \
.venv/bin/python scripts/awiki_open_cli.py smoke-cross-domain-local \
  --data-root /tmp/awiki-open-server-cross-domain-local \
  --clean
```

它启动两个独立 Uvicorn 进程，使用独立 SQLite、service DID 和 Ed25519 key，并通过 resolver map 把测试域映射到 loopback。

该 Gate 证明协议方向，但不证明公网 DNS、TLS、Nginx 和真实远端服务。

## 9. 公开验证

```bash
PYTHONPATH=src \
.venv/bin/python scripts/awiki_open_cli.py verify-public \
  --base-url https://community.example.com \
  --did-domain community.example.com
```

然后使用两个完全隔离的 Rust CLI workspace，通过两个公网域验证双向 Direct 和两个 Group Host 方向。必须覆盖 create/get/list/add/join/members/update、双向 send/read、projection/sync/realtime、receipt、leave/remove 和 retry/restart。

### 不足以通过的情况

- 只有 `anp.get_capabilities` 成功；
- `live_direct_gate = skipped_missing_credentials`；
- 两个 CLI workspace 都连接到 `awiki.info`；
- 只验证本地 loopback；
- 远端返回 `missing params.meta` 等请求形状错误；
- 公网域实际代理到其他 AWiki 服务。

## 10. Attachment 边界

当前 Community Server 只为本地 committed object 和本地 Direct/Group message context 签发 ticket。

不包含：

- 跨域 upload delegation；
- 完整 attachment access grant；
- object E2EE authorization；
- remote object relay。

## 11. 故障记录

互通失败至少记录：

```text
方向：local -> remote / remote -> local
source service DID：
target service DID：
Agent / Group DID：
operation / message ID：
group_event_seq / group_state_version：
target URL：
HTTP status：
receipt / delivery / retry 验证结果：
JSON-RPC error code/body（脱敏）：
DID Document digest/version：
service log correlation：
```

不要记录 private key、完整 token/proof/signature 或非测试消息正文。
