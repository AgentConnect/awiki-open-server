# Step 01：ANP SDK 0.8.8 接入与协议 adapter

主 Plan：[../plan.md](../plan.md)  
Step index：01  
状态：reviewed

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | reviewed |
| Branch | main |
| Started | 2026-07-04 10:26:58 +0800 |
| Completed | 2026-07-04 10:42:05 +0800 |
| Commit | pending |
| Review evidence | 本地 review + 并行 reviewer 通过：ANP SDK import 只在 `awiki-open-server/src/awiki_open_server/protocol/anp_adapter.py`；未扩大 public `/anp-im/rpc` 白名单；未引入手机/邮箱/Aliyun/E2EE/federation/group management；`service_identity.py` 删除旧手写 HTTP Signature / origin proof helper 并保留 DID document 本地生成；已补 `_sdk_verify_http_message_signature` 异常映射和 malformed/label mismatch/unauthorized key 负例。 |
| Verification evidence | `PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_protocol_anp_sdk.py -q` pass；`PYTHONPATH=../anp/anp:src python3 -m pytest tests -q` 56 passed, 2 skipped；`PYTHONPATH=../anp/anp:src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step01-cross --clean` ok=true。标准 `PYTHONPATH=src` gate 当前被本机已安装 `anp 0.6.8` 版本断言阻断；PyPI 与本地 build install 受 SSL / hatchling 环境限制。 |
| Next action | 创建 Step 01 聚焦 commit，然后进入 Step 02/03 并行 Wave B |
| Assigned agent | agent-protocol |
| Parallel group | A |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/pyproject.toml`, `awiki-open-server/src/awiki_open_server/service_identity.py`, `awiki-open-server/src/awiki_open_server/services.py` |
| Baseline commit | 2b7c467 |
| Worktree / branch | main |
| Merge gate | SDK parity gate |
| Verification gate | focused protocol tests + compileall |
| Gate status | pass with explicit `../anp/anp` SDK 0.8.8 path; standard env blocked by installed `anp 0.6.8` |

## 2. 目标

- 结果：`awiki-open-server` 依赖 ANP Python SDK `anp==0.8.8`，并通过本仓 `protocol/anp_adapter.py` 统一封装 DID WBA、HTTP Signature、Content-Digest、origin proof。
- 用户 / 系统可见行为：现有 CLI、local smoke、rwiki.cn public gate 的 wire 行为保持兼容。
- 非目标：不引入 ANP SDK 的 E2EE、federation、FastANP runtime、OpenAI 或 miniapp 能力。
- 完成标准：协议核心调用集中到 adapter；手写重复逻辑被删除或标记为兼容 shim；parity tests 覆盖旧实现的重要输入/输出。

## 3. 设计方法

- 设计边界：ANP SDK 是协议权威；业务模块只调用 adapter，不直接依赖 SDK 私有函数。
- 核心决策：目标版本固定 `anp==0.8.8`。
- 契约 / API / 数据流：adapter 需要提供 `build_content_digest`、`generate_service_http_signature_headers`、`verify_service_http_signature`、`verify_origin_proof`、`resolve_did_document` 等本仓稳定函数。
- 兼容性：保留现有 Ed25519 service DID 形态；如果 SDK 默认偏向 secp256k1，adapter 只在边界做必要适配。
- 迁移策略：先添加 adapter 和测试，再逐步替换 `service_identity.py` / `services.py` 里对应手写函数。
- 风险控制：不在业务代码散落 import `anp.*`，避免未来升级难以定位。

## 4. 实现方法

1. 在 `awiki-open-server/pyproject.toml` 添加 `anp==0.8.8`。
2. 新增 `awiki-open-server/src/awiki_open_server/protocol/anp_adapter.py` 与 `__init__.py`。
3. 复用 `anp.authentication.build_content_digest`、`generate_http_signature_headers`、`verify_http_message_signature`、`DidWbaVerifier` 或底层 verify 函数。
4. 复用 `anp.proof.rfc9421_origin.verify_rfc9421_origin_proof` 验证 `auth.origin_proof`。
5. 将 `service_identity.py` 的 HTTP Signature / content digest / origin proof 验证路径切到 adapter；保留本仓错误类型映射。
6. 新增 `tests/test_protocol_anp_sdk.py`，覆盖旧 CLI 生成 proof、服务签名、缺失字段、签名错误、DID document relationship 校验。

## 5. 路径

| 仓库 / 模块 / 文件 | 计划变更 | 备注 |
|---|---|---|
| `awiki-open-server/pyproject.toml` | 添加 `anp==0.8.8` | 不添加 Aliyun/SMS/email 依赖 |
| `awiki-open-server/src/awiki_open_server/protocol/anp_adapter.py` | 新增 SDK 封装 | 唯一 ANP SDK 接入层 |
| `awiki-open-server/src/awiki_open_server/service_identity.py` | 替换重复协议函数 | 保持对外函数名可兼容 |
| `awiki-open-server/src/awiki_open_server/services.py` | 将 DID resolve/proof verify 调用切 adapter | 避免大范围行为重写 |
| `awiki-open-server/tests/test_protocol_anp_sdk.py` | 新增 focused parity tests | Step gate |

## 6. 依赖与并行约束

- 前置步骤：无。
- 可并行步骤：无。
- 不可并行步骤：Step 02/03/04 都依赖 adapter 契约。
- 并行安全依据：无，必须串行。
- 互斥资源 / 冲突路径：协议函数和 `services.py` 调用点。
- 外部文档或决策：`anp/anp/pyproject.toml` 确认 0.8.8；User Service 仅参考 0.8.7 形态。
- 环境前提：能安装 `anp==0.8.8` 或使用 workspace sibling editable 进行本地验证。
- 合并前置条件：focused protocol tests 通过。
- 合并后验证门禁：compileall + focused identity/messaging tests。

## 7. 验收标准

- [x] `pyproject.toml` 明确依赖 `anp==0.8.8`。
- [x] 业务模块不直接散落导入 `anp.*`，除 adapter 测试外只通过 `protocol/anp_adapter.py` 使用。
- [x] service HTTP Signature 和 origin proof 验证使用 SDK 0.8.8。
- [x] 现有跨域 direct 本地 smoke 仍通过。
- [x] Review 发现已经修复或记录。
- [ ] 本步骤在进入下一步前已创建聚焦 commit。

## 8. 验证方式

| 检查项 | 命令 / 方法 | 运行时机 | 预期证据 | 门禁类型 |
|---|---|---|---|---|
| SDK parity | `PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_protocol_anp_sdk.py -q` | commit 前 | pass；标准 `PYTHONPATH=src` 需环境安装 `anp==0.8.8` | Step gate |
| Compile | `PYTHONPATH=../anp/anp:src python3 -m compileall -q src scripts tests` | commit 前 | pass | Step gate |
| Focused messaging | `PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step01-cross --clean` | commit 前 | pass | Step gate |

## 9. Review 环节

- Review 时机：adapter 切换完成、测试通过后、commit 前。
- Review 重点：SDK 版本、错误映射、relationship 校验、签名输入是否无损、origin proof 是否不被改写。

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | 已记录环境问题 | 当前机器 site-packages 中 `anp==0.6.8` 会让标准 `PYTHONPATH=src` 失败；PyPI 安装 `anp==0.8.8` 受 SSL 错误阻塞，本地 sibling 安装受缺少 `hatchling` 阻塞。 |
| 已修复问题 | 子进程 PYTHONPATH 传递 | `scripts/awiki_open_cli.py` 启动本仓服务时保留父进程 `PYTHONPATH`，避免 smoke 子进程误用旧 SDK。 |
| 剩余风险 | 环境需安装 ANP SDK 0.8.8 | 部署/CI 必须按 `pyproject.toml` 安装依赖；当前本机只能通过 `PYTHONPATH=../anp/anp:src` 使用只读 sibling 0.8.8 源码验证。 |
| 新增或缺失测试 | 已新增 | `awiki-open-server/tests/test_protocol_anp_sdk.py` 覆盖 SDK 版本、HTTP Signature、origin proof、digest mismatch、Signature label mismatch、malformed Signature-Input、unauthorized authentication method、tampered signature。 |
| 已更新或缺失文档 | 已更新计划台账 | README 最终同步留给 Step 06。 |
| 并行安全是否仍成立 | 不适用 | 串行步骤 |

## 10. Commit 要求

- Commit 时机：实现、验证、Review 完成后。
- Commit 范围：SDK dependency、adapter、替换调用、focused tests。
- 建议消息：`protocol: adopt anp sdk adapter`

## 11. Blocked 处理

| Blocker | 证据 | 已尝试方案 | 影响范围 | 是否影响并行组 | 是否影响合并门禁 | 下一步决策 |
|---|---|---|---|---|---|---|
| `anp==0.8.8` 无法安装 | pip/uv 错误 | sibling editable 验证 | 当前步骤 | 是 | 是 | 记录并询问是否允许 editable/path 依赖 |
| SDK 不支持当前 Ed25519 service DID shape | parity test 失败 | adapter 兼容 shim | 协议 gate | 是 | 是 | 保持 SDK 核心，shim 限定在 adapter |

## 12. Plan 变更记录

| 日期 | 变更 | 原因 | 主 Plan 变更记录链接 |
|---|---|---|---|
| 2026-07-04 | 初始创建 | 用户要求修复结构并使用 ANP SDK 0.8.8 | `../plan.md#16-plan-变更记录` |

## 13. 风险、回滚与后续文档

- 风险：SDK 0.8.8 与线上服务细节不一致。
- 回滚 / 回退：回退本步骤 commit；或将兼容逻辑收敛在 adapter 内，不恢复散落实现。
- 后续文档：Step 06 同步 README 的 SDK 版本和协议边界。
