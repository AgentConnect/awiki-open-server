# Step 03：附件生命周期与安全补齐

主 Plan：[../plan.md](../plan.md)  
Step index：03  
状态：draft

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | pending |
| Branch | 执行时填写 |
| Started |  |
| Completed |  |
| Commit |  |
| Review evidence |  |
| Verification evidence |  |
| Next action | 等 Step 02 完成后，补 attachment digest/expiry/quota tests |
| Assigned agent | agent-attachments |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/attachments/core.py`, `app/routes.py`, `storage/db.py` |
| Baseline commit | 执行时填写 |
| Worktree / branch | 执行时填写 |
| Merge gate | Attachment lifecycle gate |
| Verification gate | `tests/test_attachments.py` + full local tests |
| Gate status | pending |

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

- [ ] `commit_object` 对 expected size mismatch 稳定失败。
- [ ] `commit_object` 对 expected digest mismatch 稳定失败。
- [ ] expired slot 不能 upload/commit。
- [ ] expired download ticket 不能下载对象。
- [ ] unauthorized requester 仍不能拿 ticket 或下载对象。
- [ ] direct/group attachment manifest grant 仍通过现有 tests。
- [ ] E2EE object encryption 仍返回 `not_supported` 或 policy violation。
- [ ] 配置项如新增已同步 docs 或记录到 Step 06。
- [ ] 本步骤在进入下一步之前已经创建聚焦 commit。

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
| 发现问题 | 执行时填写 |  |
| 已修复问题 | 执行时填写 |  |
| 剩余风险 | 执行时填写 |  |
| 新增或缺失测试 | 执行时填写 |  |
| 已更新或缺失文档 | 执行时填写 |  |
| 并行安全是否仍成立 | 执行时填写 |  |
| Agent 是否越界修改 | 执行时填写 |  |
| 互斥资源是否被修改 | 执行时填写 |  |
| 合并风险 | 执行时填写 |  |
| Group gate 影响 | 无 | 串行 |

## 10. Commit 要求

- Commit 时机：实现、验证、Review 完成后。
- Commit 范围：attachment lifecycle/security 相关代码、tests、必要 docs。
- Commit 前状态：记录 `git status --short --branch`。
- Commit 后证据：记录 commit hash 和 commit 后状态。
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
