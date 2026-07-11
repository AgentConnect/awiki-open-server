# Step 01：实现 uploaded DID Document DataIntegrity/JCS 验签

主 Plan：[../plan.md](../plan.md)  
Step index：01  
状态：done

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done |
| Branch | `main` |
| Started | 2026-07-11 |
| Completed | 2026-07-11 |
| Commit | `b2cc11e` (`identity: verify uploaded did document proofs`) |
| Review evidence | L3 Review 完成：验签输入与本仓服务 DID 文档签名逻辑一致；`proofPurpose=assertionMethod` 必须有 `assertionMethod` 授权；Ed25519 Multikey、base64url proofValue、64 字节签名、controller 和 DID 绑定均 fail closed；signed service entry 不自动重写；dev unsigned 路径未放宽。 |
| Verification evidence | identity focused 22 passed；protocol/direct/group/sync regression 30 passed；`smoke-cross-domain-local` pass，双向 inbox delivery；ASGI smoke pass；full local tests 73 passed, 2 skipped；`git diff --check` pass。 |
| Next action | Step 02 继续 public live gate 证据 |
| Assigned agent | agent-identity |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/service_identity.py`, `awiki-open-server/src/awiki_open_server/user_compat/core.py`, `awiki-open-server/tests/helpers.py`, `awiki-open-server/scripts/awiki_open_cli.py` |
| Baseline commit | `f202c3b` |
| Worktree / branch | `main` |
| Merge gate | Identity security gate |
| Verification gate | focused identity tests + local cross-domain smoke + full tests |
| Gate status | pass |

## 2. 目标

- 结果：signed uploaded DID Document 的 proof 从结构检查升级为真实 Ed25519 DataIntegrity/JCS 验签。
- 用户 / 系统可见行为：有效签名被接受；篡改文档、坏 `proofValue`、缺失 verification method、不支持 public key 或 DID mismatch 被拒绝。
- 非目标：不支持 K1 DID、不支持非 Ed25519 cryptosuite、不实现完整 Linked Data Proof 规范扩展、不引入外部网络解析。
- 完成标准：register 和 update signed doc 路径都调用 verifier；测试覆盖有效签名和常见失败；README 去掉“尚未做密码学验证”的风险描述；cross-domain local smoke 使用真实 DID document proof。

## 3. 设计方法

- 设计边界：密码学 helper 放在 `service_identity.py`；`user_compat/core.py` 只负责调用和 service binding 约束。
- 核心决策：只接受 `type=DataIntegrityProof`、`cryptosuite=eddsa-jcs-2022`、`proofPurpose=assertionMethod`、`proofValue` base64url、Ed25519 Multikey。
- 契约 / API / 数据流：签名输入为 `sha256(JCS(proof_without_proofValue)) || sha256(JCS(document_without_proof))`，与本仓服务 DID 文档签名逻辑一致。
- 兼容性：unsigned uploaded DID Document 继续只在 `AWIKI_ALLOW_UNSIGNED_PEER_DEV=true` 的 dev 路径被 service rehome；signed 路径验证后保持原 service，不自动改写。
- 迁移策略：不改存储 schema；已有数据库中的旧假 proof 文档不会在读取时批量重验，本步骤只约束 register/update 新写入。
- 风险控制：fail closed；错误码尽量稳定并可测试；不记录 private key 或 token。

## 4. 实现方法

1. 在 `service_identity.py` 增加 `verify_did_document_data_integrity_proof(document, expected_did=None)`：
   - 校验 document/proof 类型；
   - 校验 `id` 与 expected DID；
   - 查找 `verificationMethod`；
   - 解析 `publicKeyMultibase` 的 Ed25519 public key；
   - 重建 proof options 和 unsigned document 的 JCS hash；
   - 用 `ed25519.Ed25519PublicKey.verify` 校验 `proofValue`。
2. 在 `user_compat/core.py` 的 signed uploaded doc 路径调用 verifier，再执行现有单个 `ANPMessageService`、endpoint 和 service DID 绑定校验。
3. 在 `tests/helpers.py` 增加真实 `sign_did_document` helper，并让 `register_with_key` 使用真实签名。
4. 更新 `tests/test_identity_documents.py`：
   - signed CLI doc 使用真实 key/doc；
   - wrong endpoint / wrong service DID / multiple services 用各自有效签名，确保错误来自 service binding；
   - 新增 tampered proof、bad proofValue、missing verification method、update tamper 的负测试。
5. 更新 `scripts/awiki_open_cli.py::user_did_document`，让 local cross-domain smoke 注册真实 signed DID Document。
6. 更新 README / README.cn 的身份 proof 说明。

## 5. 路径

| 仓库 / 模块 / 文件 | 计划变更 | 备注 |
|---|---|---|
| `awiki-open-server/src/awiki_open_server/service_identity.py` | 新增 DataIntegrity/JCS proof verifier | 主要实现 |
| `awiki-open-server/src/awiki_open_server/user_compat/core.py` | signed uploaded doc 路径调用 verifier | 主要接入 |
| `awiki-open-server/tests/helpers.py` | 增加真实 DID document 签名 helper | 测试和 fixture |
| `awiki-open-server/tests/test_identity_documents.py` | 更新假 proof tests，新增验签负测试 | 必需 |
| `awiki-open-server/scripts/awiki_open_cli.py` | local smoke 生成真实 signed DID Document | 防止 smoke 失败 |
| `awiki-open-server/README.md` | 英文 proof 行为更新 | docs sync |
| `awiki-open-server/README.cn.md` | 中文 proof 行为更新 | docs sync |
| `awiki-open-server/plan/20260711-proof-live-gate/` | 回填执行证据 | 本轮计划 |

## 6. 依赖与并行约束

- 前置步骤：无。
- 可并行步骤：无。
- 不可并行步骤：Step 02 依赖本步骤 smoke helper 真实签名。
- 并行安全依据：identity/security-sensitive，且共享 `scripts/awiki_open_cli.py` 与 README。
- 互斥资源 / 冲突路径：见执行状态表。
- 外部文档或决策：参考 `awiki-open-server/README.md`、`awiki-harness/context/nodes/identity.node.md`、`awiki-harness/rules/verification-policy.md`。
- 环境前提：`PYTHONPATH=../anp/anp:src` 可加载 ANP SDK 0.8.8；`base58`、`jcs`、`cryptography` 可用。
- 合并前置条件：focused tests、smoke、Review、`git diff --check`。
- 合并后验证门禁：full local tests 通过或记录失败原因。

## 7. 验收标准

- [x] 有效 Ed25519 DataIntegrity/JCS signed uploaded DID Document 可注册。
- [x] signed uploaded DID Document 的 service 不被自动重写，但必须匹配本 open-server endpoint 和 service DID。
- [x] 篡改签名覆盖的文档内容会被拒绝。
- [x] 错误 `proofValue`、缺失 verification method、不支持 public key 被拒绝。
- [x] `update_document` 对 signed document 同样执行密码学验签。
- [x] local cross-domain smoke 不再依赖假 `proofValue`。
- [x] README / README.cn 与实际 proof 行为一致。
- [x] Review 发现已经修复或明确记录。
- [x] 本步骤在进入下一步之前已经创建聚焦 commit。

## 8. 验证方式

| 检查项 | 命令 / 方法 | 运行时机 | 预期证据 | 门禁类型 |
|---|---|---|---|---|
| Identity focused | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_identity_documents.py tests/test_user_service_compat.py tests/test_contact_auth_compat.py tests/test_profile_compat.py tests/test_agent_compat.py -q` | commit 前 | pass | Step gate |
| Protocol / messaging regression | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_protocol_anp_sdk.py tests/test_direct_messages.py tests/test_group_participant.py tests/test_sync_read_state.py -q` | commit 前 | pass | Step gate |
| Local cross-domain smoke | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root .awiki-open-server/proof-cross --clean` | commit 前 | pass | Integration gate |
| ASGI smoke | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir .awiki-open-server/proof-asgi` | commit 前 | pass | Regression |
| Full local | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests -q` | commit 前或 final | pass | Repo gate |
| Hygiene | `cd awiki-open-server && git diff --check` | commit 前 | pass | Hygiene |

如果某个命令不能运行，必须记录原因、影响和替代证据。

## 9. Review 环节

- Review 时机：实现和 tests 完成后、commit 前。
- Review 重点：签名输入是否与生成逻辑一致；proof bypass；verification method DID 绑定；public key 解析；JCS canonicalization；service binding；dev unsigned 边界；测试覆盖；README 是否准确。
- Review 结论必须在 commit 前记录；必须修复必要问题，或明确记录剩余风险。

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | 1 项 | Review 中补强了 Ed25519 proofValue 解码后的 64 字节长度检查，并新增 `assertionMethod` 未授权负例。 |
| 已修复问题 | 已修复 | `did_document_proof_value_invalid` 明确覆盖非 64 字节签名；`did_document_proof_verification_method_unauthorized` 覆盖方法存在但未被 `assertionMethod` 授权。 |
| 剩余风险 | 低 | 旧外部客户端若继续上传假 `proofValue` 会被拒绝；这是本步骤目标行为。历史已存储旧文档不会批量重验，后续更新时会受新规则约束。 |
| 新增或缺失测试 | 已新增 | 有效 signed doc、service 不重写、service mismatch、tamper、坏 proofValue、缺 verification method、缺 assertionMethod 授权、update tamper 均有覆盖。 |
| 已更新或缺失文档 | 已更新 | `README.md` / `README.cn.md` 已同步 proof 密码学验签行为。 |
| 并行安全是否仍成立 | 成立 | 未启动并行写入。 |
| Agent 是否越界修改 | 未越界 | 修改限于 Step 01 授权路径和计划台账。 |
| 互斥资源是否被修改 | 已修改 | `service_identity.py`、`user_compat/core.py`、tests、smoke 脚本和 README 均属于本步骤范围。 |
| 合并风险 | 低到中 | 行为更严格，主要兼容风险是拒绝旧假 proof。 |
| Group gate 影响 | 无 | 串行 |

## 10. Commit 要求

- Commit 时机：实现、验证、L3 Review 完成后。
- Commit 范围：proof verifier、User Service compat 接入、tests、smoke helper、README 和本步骤计划证据。
- Commit 前状态：`main...origin/main [ahead 11]`；Step 01 文件已修改，另有本轮新计划文档。
- 纳入文件：`README.md`, `README.cn.md`, `scripts/awiki_open_cli.py`, `src/awiki_open_server/service_identity.py`, `src/awiki_open_server/user_compat/core.py`, `tests/helpers.py`, `tests/test_identity_documents.py`, `plan/20260711-proof-live-gate/`。
- Commit 后证据：`b2cc11e`；提交后状态 `main...origin/main [ahead 12]`，工作区只剩 Step 02 修改。
- 遗留未提交变更：必须记录原因以及为什么安全。
- 建议消息：`identity: verify uploaded did document proofs`

## 11. Blocked 处理

| Blocker | 证据 | 已尝试方案 | 影响范围 | 是否影响并行组 | 是否影响合并门禁 | 下一步决策 |
|---|---|---|---|---|---|---|
| 无当前 blocker | 待回填 | 待回填 | 当前步骤 | 否 | 否 | 继续实现 |

## 12. Plan 变更记录

| 日期 | 变更 | 原因 | 主 Plan 变更记录链接 |
|---|---|---|---|
| 2026-07-11 | 创建 Step 01 | 初始计划 | `../plan.md#16-plan-变更记录` |

## 13. 风险、回滚与后续文档

- 风险：外部旧客户端假 proof 会被拒绝。
- 并行执行风险：无并行写入。
- 合并冲突风险：中等，测试和 smoke helper 依赖同一签名算法。
- Group gate 失败回退：回退 Step 01 commit 可恢复旧结构校验，但不满足用户目标。
- Agent 交接说明：Step 02 需要基于本步骤真实签名 smoke 成功结果继续。
- 回滚 / 回退：回退本步骤 commit；不需要数据迁移回滚。
- 后续文档：Step 02 / final 检查 README 与 public live gate 说明一致。
