# AWiki Open Server 公开部署

[English](deployment.md) | [简体中文](deployment.zh-CN.md)

本文描述单节点 Uvicorn + systemd + Nginx 的当前推荐路径。仓库现有示例位于 `deploy/`，默认案例域名为 `rwiki.cn`；部署自己的服务时应替换为真实域名。

## 1. 部署边界

公开域名必须直接指向本仓库运行的进程。它不能把业务 route 代理到：

- `awiki.info`；
- 外部 User Service；
- 外部 Message Service。

`awiki.info` 只能作为远端互通 peer 或诊断目标。

## 2. 目录建议

```text
/opt/awiki-open-server/        release checkout
/etc/awiki-open-server/        private env/config
/var/lib/awiki-open-server/    SQLite and objects
/var/log/awiki-open-server/    service logs if not using journal only
/etc/awiki-open-server/keys/   service private key
/etc/awiki-open-server/operations.token  独立 operations Bearer secret
```

具体路径由运维环境决定，但私钥、数据与 Git checkout 应分离。

## 3. 安装

```bash
cd /opt/awiki-open-server
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e .
```

生产安装不需要 `.[dev]`，除非服务器本身承担测试任务。

## 4. Service DID 与私钥

至少配置：

```bash
AWIKI_PUBLIC_BASE_URL=https://community.example.com
AWIKI_DID_DOMAIN=community.example.com
AWIKI_SERVICE_DID=did:wba:community.example.com
AWIKI_SERVICE_PRIVATE_KEY_PATH=/etc/awiki-open-server/keys/service-ed25519.pem
AWIKI_ALLOW_UNSIGNED_PEER_DEV=false
AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false
AWIKI_GROUP_MAX_MESSAGE_BYTES=65536
AWIKI_GROUP_OUTBOX_MAX_PENDING=10000
AWIKI_OPERATIONS_TOKEN_FILE=/etc/awiki-open-server/operations.token
```

要求：

- 私钥为 Ed25519 PKCS#8 PEM；
- 文件权限最小化；
- 不把 PEM 放进 Git、普通 env dump、日志或 Issue；
- service DID 与 `/.well-known/did.json`、endpoint 和域名一致。
- 在 checkout 外创建独立随机 operations token 文件，权限 `0600`；不得复用或内联 service key 或用户 token。

## 5. Uvicorn 与 systemd

仓库提供：

```text
deploy/awiki-open-server.service.example
```

建议：

- Uvicorn 只监听 loopback；
- 由 systemd 管理 restart、environment file 和权限；
- service user 只拥有数据目录和私钥的必要读写权限；
- 不以 root 运行应用进程；
- 使用 journal 或受控日志目录，不记录 token 或 payload。

## 6. Nginx

仓库提供：

```text
deploy/nginx-rwiki.cn.conf.example
```

对外必须正确暴露：

- `/.well-known/did.json`；
- DID document resolve route；
- `/healthz`（是否公开可按策略限制，但 verify-public 需要访问）；
- `/anp-im/rpc`；
- 客户端需要的 local compatibility route；
- WebSocket upgrade；
- attachment upload/download data plane。

所有 `proxy_pass` 必须指向本机 Open Server 监听端口，而不是 AWiki 托管服务。

变更后：

```bash
nginx -t
systemctl reload nginx
```

## 7. TLS 与 Public Base

- 使用稳定 HTTPS 证书；
- `AWIKI_PUBLIC_BASE_URL` 必须与外部访问 origin 一致；
- DID Document 中的 `ANPMessageService.serviceEndpoint` 应为：

```text
https://community.example.com/anp-im/rpc
```

反向代理 path、Host、WebSocket 和对象 URL 必须保持一致。

## 8. 部署验证

```bash
PYTHONPATH=src \
.venv/bin/python scripts/awiki_open_cli.py verify-public \
  --base-url https://community.example.com \
  --did-domain community.example.com
```

验证内容包括：

- `/.well-known/did.json`；
- service DID；
- 唯一 `ANPMessageService`；
- endpoint；
- health；
- `anp.get_capabilities`；
- Community 跨域 Direct/Group 模式与 relay/E2EE 禁用边界；
- contact verification compatibility disabled。

还应验证 `/operations/status` 无 Bearer 时返回未授权、带正确 Bearer 时成功，并且 `/healthz` 没有增加内部诊断。随后再做双向真实互通。

## 9. 双向互通

需要两个独立域和完全隔离的 CLI workspace：

```text
Open Server local user -> awiki.info or another ANP user
Remote ANP user -> Open Server local user
```

必须验证两个 Group Host 方向：Open Server 托管群接收远端 add/join 成员，以及远端托管群接收 Open Server add/join 成员；覆盖 create/get/list/members、profile/policy、双向 send/read、projection/sync/realtime、Group Receipt、leave/remove 和 outbox retry/restart。只验证 capability 不等于互通通过。必须记录 DID、operation/message ID、event/state version、receipt/delivery、目标 URL、错误 body 和服务日志（脱敏）。

## 10. 开发开关禁用

公网必须：

```text
AWIKI_ALLOW_UNSIGNED_PEER_DEV=false
AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false
```

不要使用默认开发 OTP 作为生产认证。

## 11. 容器化状态

当前仓库公开基线以 venv/systemd/Nginx 为主。README 不应展示不存在或未持续验证的 Docker/Compose 命令。

如后续增加容器化，应同时提供：

- pinned base image；
- non-root user；
- persistent DB/object volume；
- healthcheck；
- service key secret mount；
- migration/upgrade policy；
- compose smoke；
- 与 systemd 路径一致的安全默认值。
