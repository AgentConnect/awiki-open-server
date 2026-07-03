# Step 09：公网 rwiki.info 与 awiki.info 双向互通 Gate

主 Plan：[../plan.md](../plan.md)  
Step index：09  
状态：pending-deployment

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | pending-deployment |
| Branch | main |
| Started | 未开始 |
| Completed | 未完成 |
| Commit | 未提交 |
| Review evidence | 待补：`rwiki.info` 已由本仓 open server 发布 service DID document 和 `/anp-im/rpc` |
| Verification evidence | 待补：`verify-public` pass；Rust CLI 本服务用户与 `awiki.info` 用户双向 direct/inbox/history pass |
| Next action | 先按 `awiki-open-server/deploy/` 模板完成域名路由切换，再运行本步骤 Gate |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `rwiki.info` nginx/systemd 运行配置、service DID 私钥、CLI 临时 workspace |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | `verify-public` pass + 双向 `awiki.info` direct Gate pass 或明确 blocker |

## 2. 目标

完成真实公网互通验证：本仓 open server 作为 `rwiki.info` 服务端运行，线上 `awiki.info` 只作为远端对等服务。

验收标准：

- `https://rwiki.info/.well-known/did.json` 由本仓服务返回，`id=did:wba:rwiki.info`。
- DID document 包含 exactly one `ANPMessageService`，`serviceEndpoint=https://rwiki.info/anp-im/rpc`，`serviceDid=did:wba:rwiki.info`。
- `https://rwiki.info/healthz` 返回 `status=ok`。
- `https://rwiki.info/anp-im/rpc` 可响应 `anp.get_capabilities`。
- 一个 Rust CLI workspace 指向 `https://rwiki.info`，注册本服务 DID 域用户。
- 另一个 Rust CLI workspace 或已有测试用户指向 `https://awiki.info`。
- 双向 direct send、inbox、history 均通过。
- 如果 `verify-public` 已通过但线上 `awiki.info` 仍拒绝本仓请求，记录 blocker；不要修改 `user-service`、`message-service`、`awiki-cli-rs2` 或线上服务。

## 3. 设计方法

- 本步骤只验证真实公网路径，不改变 Community 功能边界。
- `rwiki.info` 必须代理到本仓服务；不能继续代理到现有 `user-service`。
- `awiki.info` 是远端对等服务；不能把它作为本仓认证、消息或存储后端。
- 先运行公开部署检查，再运行双向业务互通，避免用错误域名环境制造无效证据。

## 4. 实现方法

1. 在部署机上按 `awiki-open-server/deploy/awiki-open-server.env.example` 配置环境变量。
2. 生成并保护 Ed25519 service private key，路径写入 `AWIKI_SERVICE_PRIVATE_KEY_PATH`。
3. 按 `awiki-open-server/deploy/awiki-open-server.service.example` 启动本仓服务。
4. 按 `awiki-open-server/deploy/nginx-rwiki.info.conf.example` 将 `rwiki.info` 的 DID、ANP、User Service 兼容路由和内容路由转到本仓服务。
5. 运行：

```bash
cd awiki-open-server
PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public \
  --base-url https://rwiki.info \
  --did-domain rwiki.info
```

6. `verify-public` 通过后，创建两个隔离 Rust CLI workspace：
   - workspace A：`service_base_url=https://rwiki.info`、`did_domain=rwiki.info`、`anp_service_endpoint=https://rwiki.info/anp-im/rpc`、`anp_service_did=did:wba:rwiki.info`。
   - workspace B：`service_base_url=https://awiki.info`，使用线上允许的测试用户或默认开发手机号/OTP。
7. A 注册本服务用户，B 注册或使用 `awiki.info` 用户。
8. A -> B direct send，B `msg inbox` / `msg history` 验证。
9. B -> A direct send，A `msg inbox` / `msg history` 验证。
10. 如果失败，记录方向、sender DID、recipient DID、DID document URL、ANP endpoint URL、RPC error、服务日志和 `verify-public` 输出。

## 5. 路径

可修改路径：

- `awiki-open-server/plan/20260702-awiki-open-server-mvp/`
- 如发现本仓 bug，可修改 `awiki-open-server/src/`、`awiki-open-server/tests/`、`awiki-open-server/scripts/`、`awiki-open-server/README.md`

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

本仓回归：

```bash
cd awiki-open-server
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
```

公网部署检查：

```bash
PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public \
  --base-url https://rwiki.info \
  --did-domain rwiki.info
```

Rust CLI 双向 Gate：

- `rwiki.info` 用户注册成功。
- `awiki.info` 用户注册或登录成功。
- `rwiki.info` 用户发送给 `awiki.info` 用户：发送命令成功，远端 inbox/history 可见。
- `awiki.info` 用户发送给 `rwiki.info` 用户：发送命令成功，本仓 inbox/history 可见。

当前已知状态：

- `verify-public --base-url https://rwiki.info --did-domain rwiki.info` 当前失败：service DID document 404、healthz 404、`anp.get_capabilities` 404。
- 这说明 `rwiki.info` 尚未路由到本仓 open server；在此状态下不能运行或宣称真实 `awiki.info` 双向互通通过。

## 7. Review 环节

Review 必须检查：

- `rwiki.info` 返回的 DID document 是否由本仓生成，且不是现有 `user-service` 返回。
- `AWIKI_ALLOW_UNSIGNED_PEER_DEV` 未在真实互通环境启用。
- service DID 私钥未写入仓库、Plan、日志或 CLI workspace。
- `/anp-im/rpc` 仍只暴露公开 peer 子集，不暴露 inbox/history/sync/read-state/group management。
- 失败时是否先排除本仓问题，再判断是否为 `awiki.info` 或相邻服务 blocker。

## 8. 并行安全

- parallel-safe：否。
- 原因：该步骤依赖单一公网域名、nginx/systemd 切换和真实线上测试账号；并行会造成环境证据混乱。
- 合并策略：串行执行，先部署检查，后双向业务 Gate。

## 9. Blocker 判定

可以记录 blocker 的条件：

- `verify-public` 已通过。
- 本仓本地测试和 Rust CLI 本地 Gate 仍通过。
- 真实双向 direct 失败，并且错误指向远端 `awiki.info` 接受策略、DID proof 兼容差异或相邻服务实现。
- 已记录最小复现和完整错误证据。

不能记录 blocker 的情况：

- `verify-public` 仍失败。
- `rwiki.info` 仍返回现有 `user-service` 或 nginx 404。
- 本仓服务无 service DID 私钥，或 DID document 不可验证。
- CLI workspace 配置仍指向 `127.0.0.1` 或 `awiki.info` 而不是 `rwiki.info`。

## 10. 文档影响

本步骤只更新 `awiki-open-server` 计划和本仓文档。若发现相邻服务需要调整，记录为后续事项，等待用户确认。
