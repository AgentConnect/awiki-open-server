# Step 05：最终 Review 与文档同步

主 Plan：[../plan.md](../plan.md)  
Step index：05  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done |
| Branch | 当前 worktree |
| Started | 2026-07-02 |
| Completed | 2026-07-03 09:15 CST |
| Commit | 未提交 |
| Review evidence | README/Plan 已同步新边界：本项目是独立开源 server，awiki.info 是线上对等服务测试对象；此前线上双 CLI awiki.info 证据已撤销；未修改 User Service / Message Service |
| Verification evidence | compileall pass；focused messaging tests 6 passed；全量 pytest 12 passed；ASGI smoke pass；HTTP smoke pass；Rust CLI 本地 identity/direct/inbox/history pass；真实 awiki.info 双向互通待公网域名 |
| Next action | 有公网域名后跑真实 awiki.info 双向互通；若线上 awiki.info 对等服务拒绝本服务协议，再记录 blocker |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `README.md`, `plan/...` |
| Baseline commit | 8f334b7 |

## 2. 目标

完成全局 Review、全量测试、本地 CLI 验证、开源 server 与线上 `awiki.info` 对等服务互通边界记录和 README 更新。

## 3. 设计方法

- 全量 `pytest` 是本地门禁。
- 本仓 Python smoke 和现有 Rust CLI 真实连接都是用户指定的验证门禁。
- `awiki.info` 是线上 AWiki 对等服务测试对象；真实跨域互通 Gate 必须使用一个 CLI 连接本服务，另一个 CLI 或已有用户连接 awiki.info。
- 远端验证必须记录实际请求形态：capability 使用 ANP JSON-RPC `params.meta/body`，direct 使用 `params.meta/auth/body`；如果失败原因是 `missing params.meta`，不能把该远端检查记为通过。

## 4. 实现方法

- 更新 `README.md` 的运行和测试命令。
- 回填主 Plan 执行台账和最终证据。
- 记录所有未运行远端检查的原因。
- 只修改 `awiki-open-server` 内的文件；如发现 `user-service`、`message-service`、`awiki-cli-rs2` 或 `awiki-harness` 需要后续适配，只记录为风险或后续事项。

## 5. 路径

- `awiki-open-server/README.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md`

## 6. 验证方式

```bash
cd awiki-open-server
python3 -m pytest tests -q
python3 scripts/awiki_open_cli.py smoke-local --base-url http://127.0.0.1:<port>
python3 scripts/awiki_open_cli.py smoke-awiki-info --base-url https://awiki.info --did-domain rwiki.info
```

现有 Rust CLI 验证使用独立 `awiki-cli-rs2` worktree 和临时 workspace，覆盖 identity、handle lookup、direct、inbox/history/mark-read、Pages CRUD、群加入/发言/读消息；`group.create` 预期失败并返回 `not_supported`。

已撤销的错误线上 Rust CLI 验证：

- `service_base_url=https://awiki.info`、`did_domain=awiki.info` 与 `service_base_url=https://awiki.info`、`did_domain=rwiki.info` 两个 workspace 互发，只证明 awiki.info 自身支持多 DID 域用户，不证明本开源 server 与 awiki.info 互通。

当前有效互通验证：

- 本地模拟 outbound：本服务用户发给远端 DID 时，解析远端 DID document，读取唯一 `ANPMessageService`，POST `direct.send` 到远端 `serviceEndpoint`，并在本地 sender history 记录发送视图。
- 本地模拟 inbound：远端 sender 调用本服务 `/anp-im/rpc direct.send` 时，target 为本服务用户会投递；target 非本服务用户返回 `recipient_not_local`，不做 relay。
- 真实线上 awiki.info 双向互通仍待本服务公开域名；如 awiki.info 侧拒绝本服务 DID/proof，则记录 blocker 给用户确认后再决定是否调整线上服务或协议参考。

远端诊断命令访问 `https://awiki.info/anp-im/rpc`；capability 使用 `params.meta/body`，direct 使用 `params.meta/auth/body`。本项目自身服务入口必须来自 `AWIKI_PUBLIC_BASE_URL`，不能用 `https://awiki.info` 替代。

## 7. Review 环节

- 检查 `require.md` 与实现是否一致。
- 检查 `/anp-im/rpc` 暴露面。
- 检查远端验证没有混淆 `awiki.info` 服务域与 `rwiki.info` 用户 DID 域。
- 检查最终工作区状态，避免提交本地 DB、对象和 token。
- 检查相邻仓库只读参考，未修改 `awiki-cli-rs2`、`user-service`、`message-service` 或 `awiki-harness`。

## 8. Commit 要求

如本步骤修改 README 或 Plan，建议提交：`Document verification evidence`。
