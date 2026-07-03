# Step 08：User Service / Message Service 互通收敛

主 Plan：[../plan.md](../plan.md)  
Step index：08  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-with-pending-online-gate |
| Branch | main |
| Started | 2026-07-03 |
| Completed | 2026-07-03 本地 Gate 完成；公开部署材料完成；真实线上 Gate 待域名切换 |
| Commit | 未提交 |
| Review evidence | 已复核：现有 Rust CLI 通过本仓 `/user-service/...` 兼容路由注册两个本地 DID；direct、inbox/history、Pages 和群参与均走本仓 `/im/rpc`；`group.create` 返回 `not_supported`；未引入外部 User Service / Message Service / `awiki.info` 运行依赖；`/anp-im/rpc` 仍只暴露公开 peer 子集；新增 `deploy/` 模板和 `verify-public` 只服务本仓部署验证；未修改相邻仓库 |
| Verification evidence | `compileall` pass；全量 pytest 21 passed；ASGI smoke pass；Rust CLI 本地 Gate pass：register Alice/Bob、Alice->Bob direct、Bob inbox/history、Pages create/get/update/list、group join/send/messages；`group.create` 退出码 1 且包含 `service rpc error -32010: not_supported`；`doctor` 唯一 error 是 loopback ANP endpoint 不能用于公开 DID discovery；`verify-public https://rwiki.info` 当前失败，证明公网域名尚未路由到本仓 |
| Next action | 按 `deploy/` 模板将 `rwiki.info` 切到本仓服务；`verify-public` 通过后执行真实线上 `awiki.info` 双向 direct Gate；若对端拒绝且本仓证据完整，再记录 blocker 给用户确认 |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/`, `awiki-open-server/tests/`, `awiki-open-server/scripts/`, `awiki-open-server/plan/...`, CLI 临时 workspace |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | Rust CLI 本地 Gate + 本仓测试 + Review + 公开部署材料已通过；真实线上 Gate 仍为 online-pending |

## 2. 目标

把当前“本仓本地单元测试通过”推进到“现有客户端可把本仓作为极简 User Service / Message Service 兼容服务使用”。

验收标准：

- 现有 Rust CLI `awiki-cli-rs2` 通过本仓兼容 `/user-service/...` 路由完成注册、DID document 上传、Profile/handle lookup。
- Rust CLI 通过本仓 `/im/rpc` 完成明文 direct send、inbox、history、mark-read。
- Rust CLI 完成 Pages CRUD 和 group participant 子集：join、send、messages；`group.create` 等管理方法返回 `not_supported`。
- 跨域 direct 的本仓实现继续满足 Message Service 参考行为：保留 CLI `auth.origin_proof`、外发使用本服务 `serviceDid` HTTP Signature、入站校验业务 proof 和 hop signature、非本地 target 不 relay。
- 如果 CLI 或真实 peer Gate 暴露问题，先修本仓；只有在本仓兼容面已符合参考实现而相邻 `User Service` / `Message Service` 或线上 `awiki.info` 仍拒绝时，才记录 blocker 给用户确认。

## 3. 设计方法

本步骤不再扩大产品范围，只收敛互通面：

- User Service 兼容面：保持本仓本地实现，不转发到外部 `user-service`。
- Message Service 兼容面：保持 `/im/rpc` local-only 与 `/anp-im/rpc` public peer entry 分离。
- CLI 验证面：使用现有 Rust CLI 作为黑盒客户端，比本仓 Python smoke 更接近真实互通。
- 线上 peer 面：`awiki.info` 只作为远端对等服务；没有公开域名时不能把线上 Gate 标为通过。

## 4. 实现方法

1. 使用现有或已构建的 Rust CLI 二进制，优先 `/tmp/awiki-cli-rs2-release-open-server-target/debug/awiki-cli`；如果不存在，再在只读参考 worktree 中构建到 `/tmp` target。
2. 启动本仓 Uvicorn，使用独立数据目录，例如 `/tmp/awiki-open-server-step08-rust-cli`。
3. 创建全新 CLI workspace 和全新 `HOME`，避免从开发者 `~/.openclaw` 迁移旧数据。
4. 写入 CLI config：

```yaml
schema_version: 1
services:
  service_base_url: http://127.0.0.1:8765
  did_domain: localhost
  anp_service_endpoint: http://127.0.0.1:8765/anp-im/rpc
  anp_service_did: did:wba:localhost
runtime:
  mode: http
```

5. 顺序运行 CLI 命令，不并发触发 workspace migration。
6. 如果失败，先定位请求方法、路径、响应 shape 或 DID document 差异；只修改 `awiki-open-server`。
7. 修复后运行 focused pytest、全量 pytest、ASGI smoke，并重跑失败 CLI 命令。

执行结果：

- 本步骤使用 `/tmp/awiki-cli-rs2-release-open-server-target/debug/awiki-cli`、`/tmp/awiki-cli-open-server-step08-review` 和 `/tmp/awiki-cli-home-step08-review` 完成本地 Gate。
- `doctor` 只报告 `anp_service_endpoint must not use a loopback address`，该诊断说明本地 `127.0.0.1` 不能作为公开 DID discovery 端点；它不是本地 User Service / Message Service 兼容失败。
- CLI 注册使用 User Service 默认开发手机号和 OTP：`13800138000` / `123456`。
- Alice/Bob 注册、Alice 发 Bob、Bob `inbox`/`history`、Pages create/get/update/list、group join/send/messages 均通过。
- `group.send` 返回 `accepted: true`、`delivery_state: accepted`、`accepted_at`、`group_event_seq`、`group_state_version`，现有 CLI 可正常展示和读取消息。
- `group.create` 按预期失败，返回 `service rpc error -32010: not_supported`。
- CLI 输出中的 direct/group `final_acceptance: false` 来自 CLI 对 `DeliveryState::Accepted` 的展示映射；消息已被服务接受并可在 inbox/history/group messages 读到，不能解读为服务拒收。
- 本步骤新增 `deploy/awiki-open-server.env.example`、`deploy/awiki-open-server.service.example`、`deploy/nginx-rwiki.info.conf.example` 和 `deploy/README.md`，把 `rwiki.info` 切到本仓 open server 的部署要求固化为本仓交付物。
- 本步骤新增 `scripts/awiki_open_cli.py verify-public`，用于在真实线上 Gate 前检查公网域名是否真的由本仓发布 service DID document、`/healthz` 和 `/anp-im/rpc`。

## 5. 路径

可修改路径：

- `awiki-open-server/src/`
- `awiki-open-server/tests/`
- `awiki-open-server/scripts/`
- `awiki-open-server/deploy/`
- `awiki-open-server/README.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/`

只读参考路径：

- `user-service/**`
- `message-service/**`
- `awiki-cli-rs2/**`
- `awiki-cli-rs2-release-0.1.61/**`
- `anp/**`

禁止修改路径：

- `user-service/**`
- `message-service/**`
- `awiki-cli-rs2/**`
- `awiki-cli-rs2-release-0.1.61/**`
- `awiki-harness/**`
- 其他相邻仓库

## 6. 验证方式

本仓基础门禁：

```bash
cd awiki-open-server
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step08-asgi
```

Rust CLI 本地 Gate：

```bash
cd awiki-open-server
PYTHONPATH=src \
AWIKI_DATA_DIR=/tmp/awiki-open-server-step08-rust-cli \
AWIKI_PUBLIC_BASE_URL=http://127.0.0.1:8765 \
AWIKI_DID_DOMAIN=localhost \
AWIKI_SERVICE_DID=did:wba:localhost \
AWIKI_ALLOW_UNSIGNED_PEER_DEV=1 \
python3 -m uvicorn 'awiki_open_server.app.main:create_app' \
  --factory --host 127.0.0.1 --port 8765
```

另一个终端或同一执行流中：

```bash
WORK=/tmp/awiki-cli-open-server-step08
HOME_DIR=/tmp/awiki-cli-home-step08
CLI=/tmp/awiki-cli-rs2-release-open-server-target/debug/awiki-cli

HOME="$HOME_DIR" AWIKI_CLI_WORKSPACE_HOME_DIR="$WORK" "$CLI" doctor
HOME="$HOME_DIR" AWIKI_CLI_WORKSPACE_HOME_DIR="$WORK" "$CLI" id register --handle step08alice --phone 13800138000 --otp 123456
HOME="$HOME_DIR" AWIKI_CLI_WORKSPACE_HOME_DIR="$WORK" "$CLI" id register --handle step08bob --phone 13800138000 --otp 123456
HOME="$HOME_DIR" AWIKI_CLI_WORKSPACE_HOME_DIR="$WORK" "$CLI" msg send --to step08bob.localhost --text "hello from step08"
HOME="$HOME_DIR" AWIKI_CLI_WORKSPACE_HOME_DIR="$WORK" "$CLI" msg inbox
HOME="$HOME_DIR" AWIKI_CLI_WORKSPACE_HOME_DIR="$WORK" "$CLI" msg history --with step08alice.localhost
```

可选扩展 Gate：

- Pages：`page create/get/update/rename/list/delete`。
- Group participant：`group join`、`msg send --group`、`group messages`。
- 不支持能力：`group create` 预期失败并包含 `not_supported`。

真实线上 peer Gate：

- 前置：本服务必须有可被 `awiki.info` 访问的 HTTPS base URL、service DID 私钥和公开 DID document。
- 一个 CLI 指向本服务公开域名，注册本服务 DID 域用户。
- 另一个 CLI 或已有用户指向 `https://awiki.info`。
- 双向 direct send、inbox、history。
- 如果线上拒绝，记录请求方向、DID、URL、远端错误和本仓已验证证据；不要修改相邻服务，等待用户确认。

本地验证证据：

```bash
cd awiki-open-server
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step08-asgi-final-2
PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info
```

结果：

- `compileall`：pass。
- `pytest`：21 passed。
- `smoke-asgi`：返回 `{"ok": true, "mode": "asgi", ...}`。
- `verify-public`：当前对 `https://rwiki.info` 返回失败，具体为 service DID document 404、`/healthz` 404、`/anp-im/rpc anp.get_capabilities` 404；该失败是部署路由证据，不是本仓协议测试失败。

Rust CLI 本地 Gate 证据：

```bash
HOME=/tmp/awiki-cli-home-step08-review \
AWIKI_CLI_WORKSPACE_HOME_DIR=/tmp/awiki-cli-open-server-step08-review \
/tmp/awiki-cli-rs2-release-open-server-target/debug/awiki-cli id register \
  --handle step08reviewalice --phone 13800138000 --otp 123456

HOME=/tmp/awiki-cli-home-step08-review \
AWIKI_CLI_WORKSPACE_HOME_DIR=/tmp/awiki-cli-open-server-step08-review \
/tmp/awiki-cli-rs2-release-open-server-target/debug/awiki-cli id register \
  --handle step08reviewbob --phone 13800138000 --otp 123456
```

通过命令：

- `id register --handle step08reviewalice --phone 13800138000 --otp 123456`
- `id register --handle step08reviewbob --phone 13800138000 --otp 123456`
- `id use step08reviewalice`
- `msg send --to step08reviewbob.localhost --text "hello bob from step08 review"`
- `id use step08reviewbob`
- `msg inbox`：读取到 Alice 发出的 1 条消息。
- `msg history --with step08reviewalice.localhost`：读取到同一条 direct history。
- `page create --slug step08-review-page ...`
- `page get --slug step08-review-page`
- `page update --slug step08-review-page ...`
- `page list`：读取到更新后的页面。
- `group join --group did:wba:localhost:groups:open`
- `msg send --group did:wba:localhost:groups:open --text "hello group from step08 review"`
- `group messages --group did:wba:localhost:groups:open`：读取到 1 条群消息。
- `group create --name "Should Not Create"`：退出码 1，返回 `service rpc error -32010: not_supported`，符合 Community 边界。

真实线上 Gate 未运行：

- 原因：本地验证服务运行在 `http://127.0.0.1:8765`，线上 `awiki.info` 无法通过 DID discovery 访问；同时当前 `https://rwiki.info` 实测未路由到本仓服务，`verify-public` 已证明公开 DID document、healthz 和 ANP endpoint 都未通过。
- 需要：`AWIKI_PUBLIC_BASE_URL=https://rwiki.info` 或其他本服务可公网访问 HTTPS base URL、`AWIKI_DID_DOMAIN=rwiki.info`、`AWIKI_SERVICE_DID=did:wba:rwiki.info`、可验证 Ed25519 service private key、由本进程发布的 service DID document。
- 结论：本仓本地 User Service / Message Service 兼容面已验证；线上 `awiki.info` 双向互通仍为部署条件 pending，不能用 loopback 结果替代。

## 7. Review 环节

Review 必须检查：

- CLI 失败是否由本仓响应 shape、method 名、路由、DID document、origin proof 或 HTTP Signature 差异导致。
- 本仓修复是否仍保持极简开源 server 边界，没有引入外部 User Service / Message Service 运行依赖。
- `/anp-im/rpc` 没有暴露 local-only inbox/history/sync/read-state，也没有 relay 非本地 target。
- 群管理仍返回 `not_supported`，只支持群参与子集。
- 没有提交 CLI workspace、SQLite DB、上传对象、token、私钥或线上测试数据。

本次 Review 结论：

- 方案和实现符合用户更正后的模型：本仓是自实现开源 server，`awiki.info` 只作为线上远端对等测试对象。
- `src/awiki_open_server/app/settings.py` 默认本地开发配置，不固定 `awiki.info`；生产/真实 Gate 通过 `AWIKI_PUBLIC_BASE_URL`、`AWIKI_DID_DOMAIN`、`AWIKI_SERVICE_DID` 配置本服务域。
- `/user-service/did-auth/rpc`、`/user-service/did/profile/rpc`、`/user-service/handle/rpc` 在 `src/awiki_open_server/app/routes.py` 中本地 dispatch，不 proxy 到外部 User Service。
- `src/awiki_open_server/services.py` 的远端调用只在 recipient DID 不属于本域时通过 DID document discovery 调用对端 `ANPMessageService.serviceEndpoint`；这属于跨域 direct，不是 backend/fallback/proxy。
- `/anp-im/rpc` 公开 handler 只允许 `anp.get_capabilities`、`direct.send`、`group.get_info`、`group.join`、`attachment.get_download_ticket`，不暴露 inbox/history/sync/read-state/group management。
- `deploy/nginx-rwiki.info.conf.example` 明确把 `rwiki.info` 代理到本仓 Uvicorn，而不是当前线上 `user-service` 或 `message-service`。
- `verify-public` 会在真实线上 Gate 前拒绝当前这类“域名存在但没有路由到本仓”的状态，避免再次把错误环境当互通证据。
- 真实线上 Gate 仍缺公网部署条件；这不是本仓代码已知缺陷，但在完成目标时必须单独验证或记录 blocker。

## 8. 并行安全

- parallel-safe：否。
- 原因：CLI Gate、服务进程和本仓 API/响应 shape 修改强依赖同一个运行环境；并行会造成 workspace、端口和证据冲突。
- 合并策略：串行执行；每次修复后先跑 focused 验证，再跑全量本仓门禁。

## 9. Blocker 判定

可以记录 blocker 的条件：

- 本仓已通过 Rust CLI 本地 Gate 和协议单元测试。
- 本仓服务 DID document、用户 DID document、origin proof 透传、HTTP Signature、本地 recipient 限制均有测试证据。
- 真实线上 `awiki.info` 或相邻 User Service / Message Service 仍拒绝，且错误指向对端协议/实现差异而不是本仓缺口。
- 已记录最小复现、请求方向、DID、URL、错误响应和已运行验证。

不应记录 blocker 的情况：

- CLI workspace 污染、旧数据 migration、端口占用或本地配置错误。
- 本仓缺少兼容路由、字段 alias、响应 shape 或公开 DID document 字段。
- 本仓测试覆盖不足，无法证明问题在对端。

## 10. 文档影响

本步骤只更新 `awiki-open-server` 计划、README 或测试文档。若发现 `user-service`、`message-service` 或 Harness 文档与真实互通协议不一致，只在本步骤和主 Plan 中记录后续事项，不修改相邻仓库。
