# Step 04：CLI smoke 与测试

主 Plan：[../plan.md](../plan.md)  
Step index：04  
状态：done

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done |
| Branch | 当前 worktree |
| Started | 2026-07-02 |
| Completed | 2026-07-03 09:15 CST |
| Commit | 未提交 |
| Review evidence | 已识别并撤销“两端 CLI 都连接 awiki.info”的错误互通证据；awiki.info 现在只作为线上对等服务测试对象；outbound discovery 与 public inbound target 校验已补 |
| Verification evidence | focused `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q`：6 passed；`PYTHONPATH=src python3 -m pytest tests -q`：12 passed；ASGI smoke pass；HTTP smoke pass；Rust CLI 本地 identity/direct/inbox/history pass |
| Next action | 有公网域名后跑真实 awiki.info 双向互通；如 awiki.info 侧拒绝本服务协议，记录 blocker |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `scripts/`, `tests/` |
| Baseline commit | 8f334b7 |

## 2. 目标

提供本仓 Python smoke，使用 HTTP 调用服务验证身份、私聊、群参与、附件、Pages；同时用现有 Rust CLI `awiki-cli-rs2` 连接本服务做真实 CLI 验证。`awiki.info` 只用于作为线上对等服务测试对象，不能作为本开源 server 的后端、fallback、代理或替代验证环境。

## 3. 设计方法

- `smoke-local` 自动创建两个本地 DID，发送 direct，加入 seeded group，上传附件，创建 page。
- 现有 Rust CLI 验证使用独立 `awiki-cli-rs2` worktree、`CARGO_TARGET_DIR=/tmp/...` 和 `AWIKI_CLI_WORKSPACE_HOME_DIR=/tmp/...`，避免写入正在开发的 CLI checkout。
- `smoke-awiki-info` 读取命令参数或环境变量，不把 token 写入仓库。
- 远端验证至少分两层：本地模拟远端 DID discovery/outbound direct；真实线上环境下，本服务公开域名与 awiki.info 用户双向 direct。
- 远端 capability 按线上 ANP JSON-RPC `params.meta/body` 发送；远端 direct 按 `params.meta/auth/body` 发送。`--base-url https://awiki.info` 只能用于探测远端对端，不代表本服务运行在 awiki.info。

## 4. 实现方法

- 新增 `scripts/awiki_open_cli.py`。
- CLI 需要区分本地简化 RPC 和远端 ANP envelope：本地 `smoke-local` 可继续发送简化参数；`smoke-awiki-info` capability 把参数放入 `body` 并补齐 `meta`；direct 必须额外提供真实 `auth.origin_proof`。
- 新增 `tests/test_cli_smoke.py`，通过 subprocess 或直接函数调用验证 smoke。
- 新增或更新测试，覆盖远端 capability 请求体包含 `params.meta/body`，direct 请求体包含 `params.meta/auth/body`，避免线上返回 `missing params.meta` 或无效空 `auth`。
- 服务端补齐 Rust CLI 使用的 `/user-service/did-auth/rpc`、`/user-service/did/profile/rpc`、`/user-service/handle/rpc` 兼容入口，以及 CLI 期望的 message/page 分页响应形态。

## 5. 路径

- `awiki-open-server/scripts/awiki_open_cli.py`
- `awiki-open-server/tests/test_cli_smoke.py`

## 6. 验证方式

```bash
cd awiki-open-server
python3 scripts/awiki_open_cli.py smoke-local --base-url http://127.0.0.1:8000
python3 scripts/awiki_open_cli.py smoke-awiki-info --base-url https://awiki.info --did-domain rwiki.info
```

现有 Rust CLI 验证覆盖：`id register`、`msg send`（DID 与 handle lookup）、`msg inbox`、`msg history`、`msg mark-read`、`page create/get/update/rename/list/delete`、`group join`、`msg send --group`、`group messages`；`group create` 预期失败且服务端返回 `not_supported`。

第二条只是远端 capability/diagnostic，不是本服务互通完成证据。若线上返回 `missing params.meta`，说明 CLI 仍在使用本地简化参数，必须修正为 ANP envelope 后再验。

已撤销的错误验证：

- 两个临时 workspace 都连接 `https://awiki.info` 并互发消息，只能证明 awiki.info 内部多 DID 域用户互通，不能证明 `awiki-open-server` 与 awiki.info 互通。

当前有效验证：

- `test_local_direct_to_remote_did_discovers_anp_service_and_posts`：本服务用户发给远端 DID，解析远端 DID document，POST 到远端 `ANPMessageService.serviceEndpoint`。
- `test_public_anp_direct_requires_local_recipient`：远端 sender 调用本服务 `/anp-im/rpc direct.send` 时，只允许 target 为本服务已注册用户；非本地 target 返回 `recipient_not_local`。

## 7. Review 环节

- 检查 CLI 不打印敏感 token。
- 检查远端 awiki.info 验证失败时输出可诊断错误，并明确失败在本服务出站、本服务入站、DID 文档发现、origin proof、HTTP Signature，还是线上对等服务拒绝。
- 检查远端 RPC 请求形态：capability 是 `params.meta/body`，direct 是 `params.meta/auth/body`，并确认 `awiki.info` 只是远端对端服务，不是本项目后端。
- 检查 smoke 覆盖群参与但不调用群管理。
- 检查现有 Rust CLI 能加入/使用已有群，但不能创建/管理群。

## 8. Commit 要求

建议提交：`Add CLI smoke coverage`。
