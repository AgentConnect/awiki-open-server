# Step 16：Rust CLI 本地互通 Gate 自动化

主 Plan：[../plan.md](../plan.md)  
Step index：16  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-with-pending-online-gate |
| Branch | main |
| Started | 2026-07-03 |
| Completed | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 |
| Commit | 未提交 |
| Review evidence | 已检查：新增 smoke 只写 `/tmp` 下 server data、HOME 和 CLI workspace；调用现有 `awiki-cli-rs2` 二进制但不修改 CLI 仓库；覆盖 User Service / Message Service / Directory / Site 兼容面；不把 loopback Gate 当作真实 `awiki.info` 互通证据 |
| Verification evidence | `CARGO_TARGET_DIR=/tmp/awiki-cli-rs2-open-server-target cargo build -p awiki-cli --bin awiki-cli --locked` pass；手工双 workspace Rust CLI Gate pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step16-rust-cli --clean` pass；compileall、全量 pytest、ASGI smoke、双实例本地跨域 Gate 均 pass |
| Next action | 继续 Step 09：`rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `scripts/awiki_open_cli.py`、临时端口、`/tmp` CLI workspace、Rust CLI 二进制 |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | `smoke-rust-cli-local` pass + 本仓全量门禁 |

## 2. 目标

把现有 Rust CLI 连接本仓的本地互通验证从手工步骤固化为可重复命令，证明本仓可以作为极简开源 User Service / Message Service 兼容服务被当前 CLI 使用。

验收标准：

- 自动启动一个本仓临时 server。
- 自动创建两个隔离 Rust CLI workspace，不写开发者默认 `~/.awiki-cli`。
- 使用默认 dev 手机号/OTP 注册 Alice/Bob。
- 验证 Alice -> Bob direct send，Bob inbox/history 可见。
- 验证群参与：join open group、group send、group messages。
- 验证 people：follow、status、following、followers。
- 验证 site：root get/set、page create/get。
- 不修改 `awiki-cli-rs2`、`user-service`、`message-service` 或 `awiki-harness`。

## 3. 设计方法

- 复用本仓现有 `scripts/awiki_open_cli.py`，新增 `smoke-rust-cli-local` 子命令。
- 通过 `--awiki-cli-bin` 指向已构建的现有 Rust CLI 二进制。
- 通过 `AWIKI_CLI_WORKSPACE_HOME_DIR` 和 `HOME` 指向 `/tmp` 下隔离目录。
- 由脚本生成 CLI `config.yaml`，配置 `service_base_url`、`did_domain`、`anp_service_endpoint` 和 `anp_service_did` 指向本仓临时 server。
- 该 Gate 只证明本地兼容互通；真实公网互通仍由 Step 09 证明。

## 4. 实现方法

1. 在 `awiki-open-server/scripts/awiki_open_cli.py` 增加 helper：
   - `write_rust_cli_config`
   - `rust_cli_json`
   - `smoke_rust_cli_local`
2. 新增 CLI 子命令：

```bash
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local \
  --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli \
  --data-root /tmp/awiki-open-server-rust-cli-local --clean
```

3. 更新 `awiki-open-server/README.md`，说明该命令是本地兼容 Gate，不替代公网 `rwiki.info` ↔ `awiki.info` Gate。
4. 更新主 Plan 的恢复指针、任务表、执行台账、验证矩阵和变更记录。

## 5. 路径

可修改路径：

- `awiki-open-server/scripts/awiki_open_cli.py`
- `awiki-open-server/README.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/`

只读参考路径：

- `awiki-cli-rs2/**`
- `user-service/**`
- `message-service/**`

禁止修改路径：

- `awiki-cli-rs2/**`
- `user-service/**`
- `message-service/**`
- `awiki-harness/**`
- 其他相邻仓库

## 6. 验证方式

本步骤 focused 验证：

```bash
cd awiki-cli-rs2
CARGO_TARGET_DIR=/tmp/awiki-cli-rs2-open-server-target \
  cargo build -p awiki-cli --bin awiki-cli --locked

cd awiki-open-server
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local \
  --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli \
  --data-root /tmp/awiki-open-server-rust-cli-script --clean
```

本仓回归：

```bash
cd awiki-open-server
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step16-asgi
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step16-cross --clean
```

公网预检仍归 Step 09：

```bash
PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public \
  --base-url https://rwiki.info \
  --did-domain rwiki.info
```

## 7. Review 环节

Review 必须检查：

- `smoke-rust-cli-local` 不依赖开发者本地默认 CLI workspace。
- 生成的 CLI config 指向本仓临时 server，不指向 `awiki.info`。
- 新增验证只调用现有 Rust CLI 二进制，不修改 CLI 源码或配置仓库。
- 验证覆盖 User Service、Message Service、Directory 和 Site 主要兼容面。
- 文档没有把本地 loopback Gate 表述为真实公网互通完成。

## 8. 并行安全

- parallel-safe：否。
- 原因：该步骤修改主 smoke 脚本和主 Plan，同时会启动临时 server、占用随机端口并调用 Rust CLI 二进制；并行执行会让证据和日志难以归属。
- 合并策略：串行执行，脚本、README、Plan 一起 Review。

## 9. 风险与回滚

| 风险 | 缓解措施 | 回滚 |
|---|---|---|
| Rust CLI 输出字段变化导致 smoke 误报 | 只校验 `ok`、DID、message id、messages、people 状态和 site body 等稳定字段 | 回滚 `scripts/awiki_open_cli.py` 的新增子命令 |
| 临时目录污染 | 默认 `--clean` 清理 `--data-root`；所有写入均在 `/tmp` 或用户显式指定目录 | 删除 `--data-root` |
| 误把本地 Gate 当线上互通 | README 和 Plan 明确该 Gate 不替代 Step 09 | 保留 Step 09 为最终 Gate |
