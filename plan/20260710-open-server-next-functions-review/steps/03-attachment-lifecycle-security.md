# Step 03：附件生命周期与安全补齐

主 Plan：[../plan.md](../plan.md)  
Step index：03  
状态：done

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done |
| Branch | `main` |
| Started | 2026-07-10T11:09:52Z |
| Completed | 2026-07-10T11:15:57Z |
| Commit | 待提交：`attachments: enforce object lifecycle checks` |
| Review evidence | slot expected metadata、upload/commit expiry、size/digest/MIME/max bytes、download ticket expiry、cleanup helper、HTTP 错误映射和 Community 非目标边界已复核；新增配置文档同步留给 Step 06。 |
| Verification evidence | `tests/test_attachments.py` 6 passed；`tests/test_direct_messages.py tests/test_group_participant.py` 19 passed；`smoke-asgi --data-dir .awiki-open-server/attachment-asgi` pass；`tests -q` 68 passed, 2 skipped；`git diff --check` pass。 |
| Next action | 启动 Step 04 DID/Auth 注册 proof 与 token 生命周期硬化 |
| Assigned agent | agent-attachments |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/attachments/core.py`, `app/routes.py`, `storage/db.py` |
| Baseline commit | `459f17e` |
| Worktree / branch | `main` |
| Merge gate | Attachment lifecycle gate |
| Verification gate | `tests/test_attachments.py` + full local tests |
| Gate status | pass |

## 2. 目标

- 结果：补齐 attachment upload/commit/download ticket 的基础生命周期和安全校验。
- 用户 / 系统可见行为：上传对象能按 expected size/digest 验证；过期 ticket 不可下载；过期 slot 可清理；超过配置限制或不允许 MIME 能稳定失败。
- 非目标：不引入 object E2EE、CDN、病毒扫描、商业配额系统、跨域 object relay。
- 完成标准：新增 negative tests 覆盖 digest mismatch、size mismatch、expired ticket、expired slot、unauthorized ticket、quota/MIME；现有 direct/group attachment grant 仍通过。

## 3. 设计方法

- 设计边界：Community 版只支持明文 attachment manifest 和本地对象存储。
- 核心决策：在 `create_slot` 记录 expected metadata，在 `commit_object` 做最终校验，在 download route 强制 ticket expiry。
- 契约 / API / 数据流：`attachment.create_slot` 返回 slot/upload/commit token；`upload_slot` 写临时文件；`commit_object` 计算 sha256/size/content_type 并写 `attachment_objects`；`get_download_ticket` 写 `download_tickets`；`GET /objects/{object_id}` 验 ticket。
- 兼容性：旧客户端未传 expected metadata 时仍允许 commit，但返回实际 digest/size；新 metadata 不破坏旧 tests。
- 迁移策略：如需给 `attachment_slots` 增加 expected 字段，必须允许旧行为空值。
- 风险控制：download route 不读取未授权对象；错误信息不泄露本地文件路径；不在 sync payload 中放 object secret。

## 4. 实现方法

1. 扩展 slot metadata：
   - `expected_size` 或 `size`。
   - `expected_digest` / `digest`，至少支持 `sha-256 value_hex`。
   - `content_type` / MIME。
   - `expires_at`。
2. 在 `attachment_create_slot` 记录 slot 过期时间和 expected metadata；返回仍兼容旧字段。
3. 在 `upload_slot` 检查 slot 状态和过期时间；超过限制时拒绝或清理临时文件。
4. 在 `attachment_commit` 校验：
   - slot status 必须是 uploaded/open 的合法状态。
   - 文件存在且未过期。
   - 实际 size 等于 expected size。
   - 实际 sha256 等于 expected digest。
   - MIME/content_type 符合保守 allowlist 或配置。
   - 超过 `max_attachment_bytes` 时稳定报错。
5. 在 `download_object` route 的 SQL 中加入 `t.expires_at > now` 判断，或读取后用 UTC 时间比较；过期票据返回 401/404 的兼容策略需测试锁定。
6. 增加 cleanup helper 或 CLI/internal function，至少能清理 expired slots/tickets；如不暴露公开 endpoint，保留启动/测试调用或 future ops hook。
7. 增加 tests 覆盖 direct/group attachment grant 不被破坏，public ticket 仍要求有效 peer signature/binding。

## 5. 路径

| 仓库 / 模块 / 文件 | 计划变更 | 备注 |
|---|---|---|
| `awiki-open-server/src/awiki_open_server/attachments/core.py` | expected metadata、commit 校验、cleanup helper | 主要路径 |
| `awiki-open-server/src/awiki_open_server/app/routes.py` | download ticket expiry enforcement | 主要路径 |
| `awiki-open-server/src/awiki_open_server/storage/db.py` | 可选 slot metadata / expiry schema | 兼容旧数据 |
| `awiki-open-server/src/awiki_open_server/app/settings.py` | 可选 max bytes / MIME config | 默认保守 |
| `awiki-open-server/tests/test_attachments.py` | lifecycle/security tests | 必需 |
| `awiki-open-server/README.md` | 如新增配置则同步 | Step 06 可统一 |

## 6. 依赖与并行约束

- 前置步骤：Step 02 完成，避免 storage/JSON-RPC error 改动冲突。
- 可并行步骤：无。
- 不可并行步骤：Step 04 可能也碰 `storage/db.py`，不能同时写。
- 并行安全依据：attachment route、storage schema 和 access grant 高风险。
- 互斥资源 / 冲突路径：`attachments/core.py`, `app/routes.py`, `storage/db.py`。
- 外部文档或决策：参考 `message-service/docs/api/ANP-client-server-api-attachment.md`。
- 环境前提：无公网依赖。
- 合并前置条件：attachment focused tests、full local tests 或明确说明。
- 合并后验证门禁：object download negative tests 全部通过。

## 7. 验收标准

- [x] `commit_object` 对 expected size mismatch 稳定失败。
- [x] `commit_object` 对 expected digest mismatch 稳定失败。
- [x] expired slot 不能 upload/commit。
- [x] expired download ticket 不能下载对象。
- [x] unauthorized requester 仍不能拿 ticket 或下载对象。
- [x] direct/group attachment manifest grant 仍通过现有 tests。
- [x] E2EE object encryption 仍返回 `not_supported` 或 policy violation。
- [x] 配置项如新增已同步 docs 或记录到 Step 06。
- [x] 本步骤在进入下一步之前已经创建聚焦 commit。

## 8. 验证方式

| 检查项 | 命令 / 方法 | 运行时机 | 预期证据 | 门禁类型 |
|---|---|---|---|---|
| Attachment focused | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_attachments.py -q` | commit 前 | pass | Step gate |
| Messaging interaction | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_direct_messages.py tests/test_group_participant.py -q` | commit 前 | pass | Step gate |
| Full local | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 -m pytest tests -q` | commit 前或 final | pass | Repo gate |
| ASGI smoke | `cd awiki-open-server && PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir .awiki-open-server/attachment-asgi` | 如 route/config 变更 | pass | Step gate |

## 9. Review 环节

- Review 时机：实现和 tests 完成后、commit 前。
- Review 重点：ticket expiry 是否真正 enforce、digest/size 是否在 commit 时校验、错误是否泄露路径、cleanup 是否会误删 committed objects、public attachment ticket 是否仍有 binding/signature。

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | 已处理 | 初版 upload 先按大小拒绝再查 slot，Review 后调整为先验证 slot/token/status/expiry，再执行 max bytes 判断；测试旧导入和长 SQL 行已清理。 |
| 已修复问题 | 已修复 | 增加 slot expected metadata 和 expires_at nullable schema；commit 校验 expected size/digest/content_type、MIME allowlist、max bytes；upload 和 commit 均校验过期；download route 校验 ticket expiry；upload route 将 AwikiError 映射为 HTTP 4xx；新增 cleanup helper。 |
| 剩余风险 | 已记录 | 新增 `AWIKI_MAX_ATTACHMENT_BYTES`、`AWIKI_ATTACHMENT_ALLOWED_MIME_TYPES` 配置尚未同步 README/deploy，按本 Plan 交给 Step 06；cleanup helper 暂未暴露公开 endpoint。 |
| 新增或缺失测试 | 已覆盖 | 新增 expected metadata/MIME/quota/expiry/cleanup tests；保留 direct/group attachment manifest grant 交互覆盖。 |
| 已更新或缺失文档 | 已记录 | 本 Plan 和 Step 台账已更新；用户文档由 Step 06 汇总同步。 |
| 并行安全是否仍成立 | 是 | 本 Step 串行执行，未启动写入型并行 worker。 |
| Agent 是否越界修改 | 否 | 修改范围限于 Step 03 允许的 attachments、routes、settings、storage、tests 和本 Plan/Step 文档。 |
| 互斥资源是否被修改 | 是，按计划修改 | 修改 `attachments/core.py`、`app/routes.py`、`app/settings.py`、`storage/db.py`。 |
| 合并风险 | 低 | 兼容列为 nullable；focused、交互、ASGI smoke 和 full local tests 均通过。 |
| Group gate 影响 | 无 | 串行 |

## 10. Commit 要求

- Commit 时机：实现、验证、Review 完成后。
- Commit 范围：attachment lifecycle/security 相关代码、tests、必要 docs。
- Commit 前状态：`## main...origin/main [ahead 3]`，修改 `plan/20260710-open-server-next-functions-review/plan.md`、`plan/20260710-open-server-next-functions-review/steps/03-attachment-lifecycle-security.md`、`src/awiki_open_server/app/routes.py`、`src/awiki_open_server/app/settings.py`、`src/awiki_open_server/attachments/core.py`、`src/awiki_open_server/storage/db.py`、`tests/test_attachments.py`。
- Commit 后证据：提交后回填 commit hash 和 commit 后状态。
- 建议消息：`attachments: enforce object lifecycle checks`。

## 11. Blocked 处理

| Blocker | 证据 | 已尝试方案 | 影响范围 | 是否影响并行组 | 是否影响合并门禁 | 下一步决策 |
|---|---|---|---|---|---|---|
| 旧 slot schema 无法安全扩展 | 执行时填写 | nullable columns、runtime fallback、无 schema 版本也兼容 | 当前步骤 | 是 | 是 | 先更新数据策略 |
| ticket 过期 HTTP status 与客户端不兼容 | 执行时填写 | 404 vs 401 兼容测试 | 当前步骤 | 是 | 是 | 锁定旧客户端可接受行为 |

## 12. Plan 变更记录

| 日期 | 变更 | 原因 | 主 Plan 变更记录链接 |
|---|---|---|---|
| 2026-07-10 | 创建 Step 03 | 初始计划 | `../plan.md#20-plan-变更记录` |

## 13. 风险、回滚与后续文档

- 风险：过严 MIME/size policy 可能破坏现有客户端上传。
- 并行执行风险：与 Step 04 共享 storage schema。
- 合并冲突风险：中等。
- Group gate 失败回退：回退本 Step commit；保留旧 attachment behavior。
- Agent 交接说明：Step 04 启动前确认 `storage/db.py` 当前状态和新增配置。
- 回滚 / 回退：回退代码和 schema 兼容扩展；不要删除已 committed object 文件。
- 后续文档：Step 06 同步配置、限制和 cleanup runbook。
