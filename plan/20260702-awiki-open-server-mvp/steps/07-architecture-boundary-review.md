# Step 07：架构边界复核与互通收敛

主 Plan：[../plan.md](../plan.md)  
Step index：07  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-with-pending-online-gate |
| Branch | main |
| Started | 2026-07-03 |
| Completed | 2026-07-03 本地复核完成，真实线上 Gate 待公开域名 |
| Commit | 未提交 |
| Review evidence | 已按用户更正复核：本仓是开源 server 服务端，必须自行实现 AWiki 服务能力；`awiki.info` 只作为线上远端对等测试对象，不是后端、fallback、代理、认证服务、消息存储或内部服务依赖 |
| Verification evidence | grep 复核通过：`awiki.info` 仅用于 README/Plan/测试 fixture/远端 diagnostic，核心服务代码未固定依赖；compileall pass；全量 pytest 19 passed；ASGI smoke pass；真实 `awiki.info` Gate 待本服务公开域名 |
| Next action | 配置本服务公开域名和 service DID 私钥后跑真实双向 `awiki.info` Gate；如线上拒绝，记录 blocker，不修改相邻仓库 |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/plan/...`, `awiki-open-server/README.md`, `awiki-open-server/src/`, `awiki-open-server/tests/` |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | 文档 Review + 本仓测试 + CLI 验证或明确 blocker |

## 2. 目标

按用户最新更正复核当前方案和实现是否仍错误地使用 `awiki.info` 域服务。

验收标准：

- `awiki-open-server` 自己实现 DID 注册、DID document 发布、Profile、消息入口、本地存储、`/anp-im/rpc` 和 User Service / Message Service 兼容路由。
- `awiki.info` 只出现在远端互通测试、diagnostic、fixture 或说明中，不能作为本仓运行时后端、fallback、代理或数据真相源。
- `/user-service/...` 兼容路径由本仓本地处理，不能转发到外部 User Service。
- `User Service`、`Message Service` 和 `awiki-cli-rs2` 只能作为只读参考或测试客户端；本步骤不修改相邻仓库。
- 真实互通 Gate 必须是一端连接本服务公开域名，另一端连接 `awiki.info` 用户；两个 CLI 都连 `https://awiki.info` 仍是无效证据。

## 3. 设计方法

复核分三层：

1. 文档层：检查 `require.md`、`README.md` 和主 Plan 是否明确本仓自行实现服务端能力，`awiki.info` 只作为线上 peer。
2. 代码层：检查 settings、routes、services、service identity 和 CLI smoke，确认没有固定调用 `awiki.info` 做本地认证、消息存储、fallback、proxy 或代理转发。
3. 验证层：用单元测试和 CLI 证明本仓本地服务可独立运行；真实线上 Gate 单独标为待公开域名验证，不能用本地或 `awiki.info` 内部互发替代。

## 4. 实现方法

- 更新主 Plan 的恢复指针、任务拆分、执行台账、验证策略、风险和变更记录。
- 新增本 Step 文档，固化用户最新更正和后续执行规则。
- 对 `awiki-open-server/src/awiki_open_server/services.py`、`service_identity.py`、`app/routes.py`、`app/settings.py` 做边界复核。
- 对 `scripts/awiki_open_cli.py smoke-awiki-info` 做说明性复核：它只能作为远端 capability 诊断；若后续继续误用，应在本仓重命名为 diagnostic 或加更强输出提示。
- 继续保留 `awiki.info` 作为测试 fixture 里的远端 DID 域，因为这正是线上互通目标。
- 如果发现实现仍把 `awiki.info` 当后端，必须在本仓修复，不修改 `user-service`、`message-service`、`awiki-cli-rs2` 或线上服务。

## 5. 路径

可修改路径：

- `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/steps/07-architecture-boundary-review.md`
- `awiki-open-server/README.md`
- `awiki-open-server/src/`
- `awiki-open-server/tests/`
- `awiki-open-server/scripts/`

只读参考路径：

- `user-service/**`
- `message-service/**`
- `awiki-cli-rs2/**`
- `anp/**`
- `awiki-harness/**`

禁止修改路径：

- `user-service/**`
- `message-service/**`
- `awiki-cli-rs2/**`
- `awiki-harness/**`
- 其他相邻仓库

## 6. 验证方式

边界复核：

```bash
rg -n "awiki\\.info|AWIKI_INFO|rwiki\\.info|proxy|fallback|/user-service" awiki-open-server
```

本轮结果：

- `README.md` 明确本服务不是 `awiki.info` proxy，兼容 `/user-service/...` 路由由本仓实现。
- `plan/...` 明确 `awiki.info` 只作为远端对等测试对象，并撤销“两端都连接 awiki.info”的证据。
- `scripts/awiki_open_cli.py smoke-awiki-info` 仍使用 `https://awiki.info` 作为默认远端 diagnostic base URL；该命令只用于 capability/远端诊断，不是本仓互通通过证据。
- `tests/` 中的 `awiki.info` 是远端 DID、远端 service DID 和公开 URL fixture。
- `src/awiki_open_server/**` 没有固定 `awiki.info` 后端、fallback、代理、认证源或消息存储依赖；`/user-service/...` 兼容路径在 `app/routes.py` 内本地 dispatch。

本仓门禁：

```bash
cd awiki-open-server
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step07-asgi
```

本轮结果：

- `PYTHONPATH=src python3 -m compileall -q src scripts tests`：pass。
- `PYTHONPATH=src python3 -m pytest tests -q`：19 passed。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step07-asgi-final`：pass。

Rust CLI 本地 Gate：

- 使用独立 `awiki-cli-rs2` worktree 和临时 workspace。
- 额外设置独立 `HOME`，避免 CLI 从开发者 `~/.openclaw` 迁移旧数据。
- CLI config 指向本服务，例如 `service_base_url=http://127.0.0.1:8765`、`did_domain=localhost`、`anp_service_endpoint=http://127.0.0.1:8765/anp-im/rpc`、`anp_service_did=did:wba:localhost`。
- 覆盖注册两个本服务用户、direct send、inbox、history；群参与和 Pages 可沿用 Step 05 证据或重新跑。

当前状态：Step 05/06 已有 Rust CLI 本地连接证据；本轮 Step 07 未重新跑完整 Rust CLI Gate。若继续执行实现目标，下一步应使用独立 `HOME` 与临时 workspace 重跑，避免旧 `~/.openclaw` 迁移污染。

真实线上 Gate：

- 前置条件：本服务通过公开域名提供 HTTPS、`/.well-known/did.json`、用户 DID document 和 `/anp-im/rpc`，并配置真实 `AWIKI_SERVICE_PRIVATE_KEY_PATH`。
- 一个 CLI 连接本服务公开域名并注册本服务 DID 域用户。
- 另一个 CLI 或已有用户连接 `https://awiki.info`。
- 双向执行 direct send、inbox、history。
- 如果失败，记录方向、DID、公开 URL、错误响应和已排除项；默认不修改相邻仓库。

## 7. Review 环节

Review 必须检查：

- `awiki.info` 未作为本仓后端、fallback、代理、认证源、存储源或内部服务依赖。
- `rwiki.info` 或其他域名只是本服务 DID 域和公开 base URL 配置，不代表服务仍由 `awiki.info` 承载。
- User Service / Message Service 兼容由本仓本地实现；相邻服务只是协议参考。
- `smoke-awiki-info` 的证据不被记录为本仓互通完成证据。
- `/anp-im/rpc` 只做公开跨域 direct/capability 子集，不提供 federation relay。
- 当前步骤没有修改相邻仓库。

## 8. 并行安全

- parallel-safe：否。
- 原因：本步骤更新全局计划状态和验证口径，且可能触发服务边界修复；必须由一个 coordinator 串行处理。
- 合并策略：先完成文档复核，再运行本仓验证；如果需要代码修复，先更新本 Step 的实现记录和验证证据。

## 9. 文档影响

本步骤只更新 `awiki-open-server` 内的 Plan/README。Harness 或相邻仓库文档若与本目标边界不一致，只记录后续事项，不在本目标中修改。

## 10. 本轮复核补充

2026-07-03 再次按用户更正复核：

- 方案方向符合更正后的模型：本仓实现开源 server 服务端能力，不依赖 `awiki.info` 承载运行时。
- `require.md` 已补充硬边界：`awiki.info` 只能作为远端对等测试服务，不能作为认证、消息、存储、代理、fallback 或后端。
- 代码层复核 `src/awiki_open_server/app/settings.py`、`src/awiki_open_server/app/routes.py`、`src/awiki_open_server/services.py`：默认配置为本地开发域；`/user-service/...` 兼容路由本地 dispatch；跨域外发只按 recipient DID 文档发现远端 `ANPMessageService.serviceEndpoint`，不是固定调用 `awiki.info`。
- `scripts/awiki_open_cli.py smoke-awiki-info` 仍只是远端 capability/direct 诊断命令；真实完成证据必须由 Step 09 的 `rwiki.info` 本仓部署 + `awiki.info` 双向 direct Gate 给出。
- 当前剩余 blocker 不在方案设计本身，而是公网 `rwiki.info` 尚未路由到本仓 open server；`verify-public` 未通过前不能宣称线上互通完成。
