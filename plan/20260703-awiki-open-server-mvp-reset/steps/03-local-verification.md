# Step 03：本仓回归与 Rust CLI gate

主 Plan：[../plan.md](../plan.md)  
Step index：03  
状态：done

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done |
| Branch | 当前 worktree |
| Started | 2026-07-03 |
| Completed | 2026-07-03 |
| Commit | 未提交 |
| Review evidence | compileall、pytest、ASGI smoke、本地双域、Rust CLI local gate 均通过；Rust CLI gate 明确 phone/otp 为 placeholder；未修改 sibling repo |
| Verification evidence | compileall pass；`PYTHONPATH=src python3 -m pytest tests -q` 44 passed；ASGI smoke pass；cross-domain local pass；Rust CLI local pass |
| Next action | Step 04 blocked by public route |
| Assigned agent | main 或 verification-worker |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | 本地端口、`/tmp` 验证目录、Rust CLI 二进制 |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | full repo gate |

## 2. 目标

- 结果：证明默认禁用 contact verification 后，本仓核心 DID/direct/group/attachment/Pages 和 Rust CLI local gate 仍可用。
- 用户 / 系统可见行为：CLI 仍能注册两个用户并互发 direct；服务端不跑手机/邮箱验证。
- 非目标：不执行真实公网互通，不修改 sibling repo。
- 完成标准：compileall、全量 pytest、ASGI smoke、cross-domain local、Rust CLI local gate 通过，或记录明确失败和修复。

## 3. 设计方法

- 设计边界：本地 gate 只能证明本仓和本地协议，不代替 public interop。
- 核心决策：Rust CLI 的 phone/otp 是 placeholder；验证报告必须说明。
- 契约 / API / 数据流：不扩大 public `/anp-im/rpc`。
- 兼容性：如 Rust CLI 失败，优先修本仓，仍不修改 `awiki-cli-rs2`。
- 风险控制：所有临时数据写 `/tmp`。

## 4. 实现方法

1. 运行 focused tests 和 dependency grep，确认 Step 02 行为。
2. 运行 compileall 和全量 pytest。
3. 运行 `smoke-asgi`。
4. 运行 `smoke-cross-domain-local`。
5. 运行 `smoke-rust-cli-local`，使用已有隔离 Rust CLI worktree/binary。
6. 如果失败，只修改本仓，并回到 Step 02/03 重新验证。

## 5. 路径

| 仓库 / 模块 / 文件 | 计划变更 | 备注 |
|---|---|---|
| `awiki-open-server/src/**` | 只在验证失败时修复 | 本仓 |
| `awiki-open-server/tests/**` | 只在验证失败时修复 | 本仓 |
| `awiki-open-server/scripts/awiki_open_cli.py` | 只在验证失败时修复 | 本仓 |
| `awiki-cli-rs2/**` | 只读 / 执行二进制 | 不修改 |

## 6. 依赖与并行约束

- 前置步骤：Step 02。
- 可并行步骤：无。
- 不可并行步骤：Step 04 依赖本步骤结果。
- 并行安全依据：验证命令共享临时端口和二进制，串行更清晰。
- 互斥资源 / 冲突路径：`/tmp/awiki-open-server-mvp-reset-*`。
- 外部文档或决策：无。
- 环境前提：pytest 可运行；Rust CLI 二进制存在或可构建。
- 合并前置条件：所有必要 gate 通过或记录 blocker。
- 合并后验证门禁：public gate。

## 7. 验收标准

- [x] `python3 -m compileall` 通过。
- [x] `pytest tests -q` 通过。
- [x] ASGI smoke 通过。
- [x] 本地双域 smoke 通过。
- [x] Rust CLI local gate 通过。
- [x] 验证报告明确本地 gate 不等于真实 `awiki.info` 互通。

## 8. 验证方式

| 检查项 | 命令 / 方法 | 运行时机 | 预期证据 | 门禁类型 |
|---|---|---|---|---|
| Compile | `PYTHONPATH=src python3 -m compileall -q src scripts tests` | Step 03 | pass | Step gate |
| Tests | `PYTHONPATH=src python3 -m pytest tests -q` | Step 03 | 44 passed | Step gate |
| ASGI smoke | `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-mvp-reset-asgi` | Step 03 | pass | Step gate |
| Cross-domain local | `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-mvp-reset-cross --clean` | Step 03 | pass | Step gate |
| Rust CLI local | `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-mvp-reset-rust-cli --clean` | Step 03 | pass；输出说明 phone/otp 仅为 CLI placeholder | Step gate |

## 9. Review 环节

- Review 时机：验证完成后。
- Review 重点：失败是否被正确修复，Rust CLI 输出是否没有误导成手机验证，是否有未提交生成物。

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | Public gate 仍 404 | 归 Step 04 |
| 已修复问题 | 无本地回归失败 |  |
| 剩余风险 | 本地 gate 不证明线上 `awiki.info` 双向互通 | Step 04 继续 |
| 新增或缺失测试 | 已有默认禁用和 compat 测试 |  |
| 已更新或缺失文档 | reset Plan 已回填 |  |
| 并行安全是否仍成立 | 是 | 串行 |

## 10. Commit 要求

- Commit 时机：所有本地 gate 通过且 Review 完成后。
- Commit 范围：如 Step 03 只运行验证不改文件，不需要 commit。
- 建议消息：`test: verify open server mvp reset`

## 11. Blocked 处理

| Blocker | 证据 | 已尝试方案 | 影响范围 | 是否影响并行组 | 是否影响合并门禁 | 下一步决策 |
|---|---|---|---|---|---|---|
| Rust CLI binary 不存在 | shell 输出 | 尝试在隔离 target 构建 | Rust CLI gate | 否 | 是 | 记录未运行或构建后继续 |

## 12. Plan 变更记录

| 日期 | 变更 | 原因 | 主 Plan 变更记录链接 |
|---|---|---|---|
| 2026-07-03 | 新增 Step 03 | 需要本仓回归证据 | `../plan.md#16-plan-变更记录` |

## 13. 风险、回滚与后续文档

- 风险：本地 gate 通过但公网仍 404。
- 并行执行风险：端口冲突。
- 合并冲突风险：低。
- Group gate 失败回退：清理 `/tmp` 后重跑。
- Agent 交接说明：Step 04 负责公网。
- 回滚 / 回退：只读验证无需回滚。
- 后续文档：将实际命令结果回填主 Plan。
