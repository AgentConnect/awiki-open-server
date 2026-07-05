# Plan：rwiki.cn 公开部署与互通验证

状态：done
Resume From Here：部署已完成；如需继续处理互通问题，应从“阻塞与风险”中的 `awiki.info` 服务 DID 文档不同步问题开始。

## 1. 目标

将 `awiki-open-server` 通过 `https://rwiki.cn` 对外发布，使用 nginx 代理到本机 Uvicorn，并配置 systemd 开机自启动。完成后用 Rust CLI 验证 `rwiki.cn` 注册、私聊、inbox/history，并验证与 `awiki.info` 的跨域互通。

## 2. 边界

- 只部署和修改 `awiki-open-server` 相关运行配置。
- 不修改 `anp`、`user-service`、`message-service`、`awiki-cli-rs2` 源码。
- `awiki.info` 仅作为远端互通 peer，不作为本服务后端。
- `rwiki.cn` 的 public `/anp-im/rpc` 仍只接受 MVP 白名单能力。
- 本服务不启用手机/邮箱验证，不引入 Aliyun、E2EE、federation 或群管理。

## 3. 实施摘要

- 发现现有 `awiki-open-server.service` 已存在并 enabled，但运行环境会优先加载用户 site-packages 中的旧 `anp`。
- 安装系统包 `python3.10-venv`，尝试创建 `.venv`；由于 PyPI SSL EOF，无法从公网安装 `hatchling/wheel` 依赖。
- 采用当前机器可验证的运行方式：systemd 显式设置 `PYTHONPATH=<workspace>/anp/anp:<workspace>/awiki-open-server/src:<python-user-site-packages>`，确保 ANP SDK 加载 `0.8.8`。
- 备份并更新 host systemd service。
- 备份并用 `awiki-open-server/deploy/nginx-rwiki.cn.conf.example` 对齐 host nginx `rwiki.cn` server block，保留实际证书路径。
- 运行 `systemctl daemon-reload`、`nginx -t`、重启 `awiki-open-server.service`、reload nginx。

## 4. 实际配置

- systemd service：host `awiki-open-server.service`
- env file：host `awiki-open-server.env`
- nginx server block：host `rwiki.cn` server block
- 本地监听：`127.0.0.1:8766`
- 公网 base URL：`https://rwiki.cn`
- service DID：`did:wba:rwiki.cn`
- service private key：host protected Ed25519 key file，未写入仓库

## 5. 验证证据

### 部署状态

- `systemctl is-enabled awiki-open-server.service`：`enabled`
- `systemctl is-active awiki-open-server.service`：`active`
- 进程环境确认加载 ANP SDK 0.8.8 路径。
- `curl https://rwiki.cn/healthz` 返回 `{"status":"ok","edition":"community"}`。
- `curl https://rwiki.cn/.well-known/did.json` 返回 `did:wba:rwiki.cn`，`ANPMessageService.serviceEndpoint=https://rwiki.cn/anp-im/rpc`。

### 公网 gate

```bash
PYTHONPATH=<workspace>/anp/anp:<workspace>/awiki-open-server/src:<python-user-site-packages> \
python3 awiki-open-server/scripts/awiki_open_cli.py verify-public \
  --base-url https://rwiki.cn \
  --did-domain rwiki.cn
```

结果：`ok=true`。

```bash
AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 \
PYTHONPATH=<workspace>/anp/anp:<workspace>/awiki-open-server/src:<python-user-site-packages> \
python3 -m pytest awiki-open-server/tests/test_rwiki_cn_system.py -q
```

结果：`2 passed`。

### Rust CLI 对 rwiki.cn 端到端

使用 `awiki-cli-rs2/target/debug/awiki-cli` 注册两个 `did:wba:rwiki.cn` 用户，验证 direct send、Bob inbox、Bob direct history。

结果：`ok=true`，消息 `msg-18ae2ec2acbc3b63` 成功可见。

### rwiki.cn 与 awiki.info 互通

使用 Rust CLI：

- `rwiki.cn` 用户：通过 `https://rwiki.cn` 注册。
- `awiki.info` 用户：通过 `https://awiki.info` 注册，使用线上 User Service 运行配置中的 dev OTP（具体值未写入仓库文档）。

结果：

- `rwiki.cn -> awiki.info`：通过，awiki.info inbox/history 可见消息 `msg-18aec54c2e673039`。
- `awiki.info -> rwiki.cn`：失败，远端 CLI 返回 `service rpc error -32001: invalid_peer_http_signature`。

## 6. 阻塞与风险

反向互通失败经抓包和离线验签定位为 `awiki.info` 侧服务 DID 文档不同步：

- `message-service` PostgreSQL `service_identities` 表中 `did:wba:awiki.info#key-1` 公钥为 `z6MkiwA2psGssYjWkUBdDkRpNWoaKJxDqQvvSx8dufNhxgry`。
- 公网 `https://awiki.info/.well-known/did.json` 中 `did:wba:awiki.info#key-1` 公钥为 `z6MkiZQiC8mTEbnE4XjEKcYuMbw3Wn17ztrsP9SKpWeXhnZR`。
- 抓包显示 `awiki.info` 发往 `rwiki.cn/anp-im/rpc` 的请求包含 `x-anp-source-service-did: did:wba:awiki.info`、`Signature`、`Signature-Input`、`Content-Digest`，digest 正确，但无法用公网 DID 文档验过。

根据用户要求，本次未修改 `user-service` 或 `message-service` 源码/数据。修复反向互通需要同步 `awiki.info` 公开 DID 文档与 message-service 实际服务身份，或调整 awiki.info 服务身份生成/发布流程。

## 7. Review

- nginx `rwiki.cn` block 只代理到 `127.0.0.1:8766`，未代理到 `awiki.info`、User Service 或 Message Service。
- systemd service 已 enabled，重启后使用当前仓库代码与 ANP SDK 0.8.8。
- `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false`，公网测试确认手机/邮箱验证接口禁用。
- 本次失败点是远端 peer 的公开 DID 文档与签名私钥不一致，不是 `rwiki.cn` 部署链路不可用。

## 8. 最终复测记录

提交部署脚本与初始记录后，重新执行以下复测：

- `git status --short --branch`：`main...origin/main`，无未提交变更。
- `systemctl is-enabled awiki-open-server.service`：`enabled`。
- `systemctl is-active awiki-open-server.service`：`active`。
- `curl https://rwiki.cn/healthz`：`{"status":"ok","edition":"community"}`。
- `verify-public --base-url https://rwiki.cn --did-domain rwiki.cn`：`ok=true`。
- `AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 ... tests/test_rwiki_cn_system.py -q`：`2 passed`。
- Rust CLI `version`：`ok=true`，版本为 `dev`。
- Rust CLI 连接 `https://rwiki.cn` 注册两个 `did:wba:rwiki.cn` 用户，direct send、Bob inbox、Bob history 通过；消息 `msg-18ae9a382f6bf558`。
- Rust CLI 双域互通复测：`rwiki.cn -> awiki.info` 通过，消息 `msg-18ae8beb68a96b47`；`awiki.info -> rwiki.cn` 失败，错误仍为 `service rpc error -32001: invalid_peer_http_signature`。

复测结论：`rwiki.cn` 部署、自启动、nginx 代理、本域 CLI E2E 和正向跨域发送均正常；完整双向互通仍阻塞在 `awiki.info` 侧服务 DID 文档与实际签名密钥不同步。
