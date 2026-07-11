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
- 采用当前机器可验证的运行方式：systemd 显式设置 workspace-relative `PYTHONPATH=anp/anp:awiki-open-server/src`，并保留 host Python user site-packages，确保 ANP SDK 加载 `0.8.8`。
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
PYTHONPATH=anp/anp:awiki-open-server/src \
python3 awiki-open-server/scripts/awiki_open_cli.py verify-public \
  --base-url https://rwiki.cn \
  --did-domain rwiki.cn
```

结果：`ok=true`。

```bash
AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 \
PYTHONPATH=anp/anp:awiki-open-server/src \
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

> 2026-07-12 CST / 2026-07-11 UTC 复测更新：本节记录的是历史阻塞。`awiki.info` 公开 DID 文档与 message-service 实际签名密钥已同步，且第 10 节的 Rust CLI live gate 已完成 `rwiki.cn <-> awiki.info` 双向 direct、inbox、history 验证。

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

## 9. 2026-07-10 复核记录

本节是后续复核记录，不覆盖上方历史部署证据。

只读公网复核结果：

- `curl https://rwiki.cn/healthz` 返回 `{"status":"ok","edition":"community"}`。
- `https://rwiki.cn/.well-known/did.json` 仍由本仓服务提供，`ANPMessageService.serviceEndpoint=https://rwiki.cn/anp-im/rpc`，`serviceDid=did:wba:rwiki.cn`，`did:wba:rwiki.cn#key-1` 为 `z6Mkr5R7gCTV7YptJmq3MYW4GKeBMnQZV8thgPadDdd9uScU`。
- `https://awiki.info/.well-known/did.json` 当前 `did:wba:awiki.info#key-1` 为 `z6MkiwA2psGssYjWkUBdDkRpNWoaKJxDqQvvSx8dufNhxgry`，已经与本计划第 6 节记录的 message-service 实际签名公钥一致；历史的公开 DID 文档旧 key mismatch 看起来已修复。
- `verify-public --base-url https://rwiki.cn --did-domain rwiki.cn` 返回 `ok=true`。
- `AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_rwiki_cn_system.py -q` 返回 `2 passed`。
- `smoke-awiki-info --base-url https://awiki.info --did-domain rwiki.cn` capability 诊断返回 `ok=true`，`service_did=did:wba:awiki.info`。
- 隔离 Rust CLI workspace 连接 `https://rwiki.cn` 注册两个 `did:wba:rwiki.cn` 测试用户并完成 direct send、Bob inbox、Bob history，消息 `msg-18d948334d22f63` 可见。

写入型 live 双向互通状态：

- 当前环境没有可用的 `awiki.info` 测试 token、sender DID、recipient DID、origin proof，且没有有效的 `awiki.info` 注册 OTP。
- 使用隔离 Rust CLI workspace 尝试通过 `https://awiki.info` 注册临时测试用户时，服务返回 `验证码验证失败：验证码无效或已过期`。
- 因此本次没有复跑完整 `rwiki.cn <-> awiki.info` 双向 direct/inbox/history live gate。当前结论只能证明历史 key mismatch 已经从公开 DID 文档层面修复，不能替代需要真实 `awiki.info` 测试身份的双向写入 gate。

后续如需关闭该 live gate 风险，需要提供或配置有效的 `awiki.info` 测试身份/OTP/token，并用隔离 Rust CLI workspace 重跑两方向 direct、inbox、history。

## 10. 2026-07-12 CST / 2026-07-11 UTC live 双向 Gate 关闭记录

本节是第 9 节之后的写入型复测记录。`awiki.info` 与 `rwiki.cn` 均部署在本机环境；本次通过当前源码重新构建的 Rust CLI 执行真实公网 direct 互通验证。仓库内旧 `target/debug/awiki-cli` 曾返回 `tenant is not implemented`，因此先执行：

```bash
cd ../awiki-cli-rs2
CARGO_TARGET_DIR=/tmp/awiki-cli-rs2-live-gate-target cargo build -p awiki-cli --bin awiki-cli --locked
```

验证二进制：`/tmp/awiki-cli-rs2-live-gate-target/debug/awiki-cli`，`version=dev`，`schema tenant.create`、`schema id.register`、`schema msg.send` 均显示 `implemented=true`。

隔离 workspace：

- `rwiki.cn` workspace：`/tmp/awiki-live-rwiki.tZvWWX`，tenant `rwiki`，`backend_base_url=https://rwiki.cn`，`did_host=rwiki.cn`。
- `awiki.info` workspace：`/tmp/awiki-live-awikiinfo.RFMXtA`，tenant `awikiinfo`，`backend_base_url=https://awiki.info`，`did_host=awiki.info`。
- 两个 workspace 的 `config show` 均确认 `secret_storage.mode=vault_required`；root key 由 CLI live path 在各自临时 workspace 下生成，不写入仓库。
- `awiki.info` 注册使用本机 `user-service` 运行配置中的 `DEV_OTP_PHONE` / `DEV_OTP_CODE`，具体值未记录到文档。

测试身份：

- `rwiki.cn`：`gate-rwiki-160928.rwiki.cn`，DID `did:wba:rwiki.cn:gate-rwiki-160928:e1__EfAPIO1f6ax0jPTgqI4rh-acuiNtGKpM_AlH14-Px0`，`ready_for_messaging=true`。
- `awiki.info`：`gate-awiki-160928.awiki.info`，DID `did:wba:awiki.info:gate-awiki-160928:e1_u-I8nZ4YJkIlZxvtJrIR3Y84Mbtt9M_Dz5svQUazlA0`。

正向 `rwiki.cn -> awiki.info`：

```bash
AWIKI_CLI_WORKSPACE_HOME_DIR=/tmp/awiki-live-rwiki.tZvWWX \
/tmp/awiki-cli-rs2-live-gate-target/debug/awiki-cli msg send \
  --to did:wba:awiki.info:gate-awiki-160928:e1_u-I8nZ4YJkIlZxvtJrIR3Y84Mbtt9M_Dz5svQUazlA0 \
  --text 'live-gate rwiki-to-awiki evidence 20260711160928'
```

结果：

- `ok=true`，`delivery.accepted=true`，消息 `msg-18dd252bc8958117`，`accepted_at=2026-07-11T16:12:11.993639+00:00`。
- `awiki.info` workspace 执行 `msg inbox --scope direct --limit 10` 返回 `Loaded 2 inbox messages`，包含 `msg-18dd252bc8958117`，正文 `live-gate rwiki-to-awiki evidence 20260711160928`，`sender_did` 为上述 `rwiki.cn` DID，`receiver_did` 为上述 `awiki.info` DID。
- `awiki.info` workspace 执行 `msg history --with <rwiki DID> --limit 10` 返回 `Loaded 2 direct history messages`，同样包含 `msg-18dd252bc8958117`。

反向 `awiki.info -> rwiki.cn`：

```bash
AWIKI_CLI_WORKSPACE_HOME_DIR=/tmp/awiki-live-awikiinfo.RFMXtA \
/tmp/awiki-cli-rs2-live-gate-target/debug/awiki-cli msg send \
  --to did:wba:rwiki.cn:gate-rwiki-160928:e1__EfAPIO1f6ax0jPTgqI4rh-acuiNtGKpM_AlH14-Px0 \
  --text 'live-gate awiki-to-rwiki evidence 20260711160928'
```

结果：

- `ok=true`，`delivery.accepted=true`，消息 `msg-18dd256033e0f512`，`accepted_at=2026-07-11T16:12:30.967861+00:00`。
- `rwiki.cn` workspace 执行 `msg inbox --scope direct --limit 10` 返回 `Loaded 3 inbox messages`，包含 `msg-18dd256033e0f512`，正文 `live-gate awiki-to-rwiki evidence 20260711160928`，`sender_did` 为上述 `awiki.info` DID，`receiver_did` 为上述 `rwiki.cn` DID，`received_at=2026-07-11T16:12:30.964360+00:00`。
- `rwiki.cn` workspace 执行 `msg history --with <awiki.info DID> --limit 10` 返回 `Loaded 3 direct history messages`，同样包含 `msg-18dd256033e0f512`。

结论：

- `rwiki.cn <-> awiki.info` live direct 双向 gate 通过：两边均通过当前 Rust CLI 完成注册、发送、收件箱读取、会话历史读取。
- 历史 `awiki.info` 服务 DID 文档 key mismatch / `invalid_peer_http_signature` 阻塞已关闭。
- 本 gate 覆盖明文 direct 互通；不覆盖 E2EE、群、WebSocket realtime 长连接或非 direct 能力。
