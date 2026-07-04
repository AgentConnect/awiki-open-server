# Step 02：路径配置与公开 endpoint 对齐

主 Plan：[../plan.md](../plan.md)  
Step index：02  
状态：done

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done |
| Branch | main |
| Started | 2026-07-04 10:49:36 +0800 |
| Completed | 2026-07-04 10:53:13 +0800 |
| Commit | db7f6e8 |
| Review evidence | 本地 review 通过：route 注册改为读取 `Settings` 路径；DID document `serviceEndpoint` 与 custom `AWIKI_ANP_PUBLIC_RPC_PATH` 一致；public ANP 方法仍限定为 `anp.get_capabilities`、`direct.send`、`group.get_info`、`group.join`、`attachment.get_download_ticket`；未新增公开 API。 |
| Verification evidence | `PYTHONPATH=../anp/anp:src python3 -m pytest tests/test_route_config.py -q` 4 passed；`PYTHONPATH=../anp/anp:src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step02-asgi` ok=true；`PYTHONPATH=../anp/anp:src python3 -m pytest tests -q` 60 passed, 2 skipped；cross-domain local smoke ok=true。 |
| Next action | 等待 Step 03 合并后执行 Wave B group gate |
| Assigned agent | agent-routing |
| Parallel group | B |
| Parallel safe | yes |
| Parallel with | Step 03 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/app/routes.py`, `awiki-open-server/src/awiki_open_server/app/settings.py`, `awiki-open-server/deploy/*` |
| Baseline commit | ec6b8d6 |
| Worktree / branch | main |
| Merge gate | Route config gate |
| Verification gate | focused route tests |
| Gate status | pass_with_explicit_sdk_path; committed as `db7f6e8` |

## 2. 目标

- 结果：`AWIKI_IM_RPC_PATH`、`AWIKI_ANP_PUBLIC_RPC_PATH`、`AWIKI_WS_PATH`、object path 配置与实际 FastAPI route 挂载一致，或删除不真正支持的配置项。
- 用户 / 系统可见行为：DID 文档里的 `serviceEndpoint` 必须真实可访问。
- 非目标：不新增新的公开 API，不扩大 `/anp-im/rpc` 白名单。
- 完成标准：自定义 ANP public path 下 `/.well-known/did.json` 和 FastAPI route 同步；默认 `/anp-im/rpc` 仍兼容。

## 3. 设计方法

- 设计边界：route 层只处理路径、请求读取、异常转换；业务逻辑不在本步骤扩展。
- 核心决策：若配置项保留，必须真实影响 route 注册；否则从 Settings/README 中移除。
- 契约 / API / 数据流：`settings.anp_service_endpoint` 和 `@app.post(settings.anp_public_rpc_path)` 必须一致。
- 兼容性：保留默认旧路径 `/im/rpc`、`/anp-im/rpc`、`/im/ws`、`/objects/*`。
- 风险控制：新增测试覆盖 default 和 custom path 两套应用实例。

## 4. 实现方法

1. 检查 `app/routes.py` 中所有硬编码路径。
2. 将可配置路径改为从 `request.app.state.settings` 或注册时 settings 读取。
3. 如果 FastAPI decorator 无法直接读取 runtime settings，则在 `mount_routes(app)` 内先取 `settings = app.state.settings`，再注册路径。
4. 对 object upload/download path 选择“保留固定路径”或“真正支持配置”，并同步 README/deploy。
5. 新增 `tests/test_route_config.py`，验证 custom `anp_public_rpc_path` 的 DID document endpoint 和 POST route 一致。

## 5. 路径

| 仓库 / 模块 / 文件 | 计划变更 | 备注 |
|---|---|---|
| `awiki-open-server/src/awiki_open_server/app/routes.py` | 使用 settings 注册可配置路径 | 保持 default route |
| `awiki-open-server/src/awiki_open_server/app/settings.py` | 清理或确认路径配置 | 避免假配置 |
| `awiki-open-server/tests/test_route_config.py` | 新增 focused tests | 覆盖 custom path |
| `awiki-open-server/deploy/nginx-rwiki.cn.conf.example` | 同步路径说明 | Step 06 可最终补齐 |

## 6. 依赖与并行约束

- 前置步骤：Step 01。
- 可并行步骤：Step 03。
- 不可并行步骤：Step 04 需等本步骤完成。
- 并行安全依据：只改 routing/settings/deploy，不改 User Service compat 业务模块。
- 互斥资源 / 冲突路径：`routes.py` 可能与 Step 03 有 import/handler touch，需提前划定 Step 03 不改 route 注册结构。
- 合并前置条件：Step 01 adapter 已提交。
- 合并后验证门禁：Route config gate + Wave B group pytest。

## 7. 验收标准

- [x] `AWIKI_ANP_PUBLIC_RPC_PATH` 修改后 DID 文档和实际 POST route 一致。
- [x] 默认 `/anp-im/rpc` 仍可用。
- [x] public handler 白名单不扩大。
- [x] README/deploy 不再描述未实际支持的配置。
- [x] 本步骤在进入依赖步骤前已创建聚焦 commit。

## 8. 验证方式

| 检查项 | 命令 / 方法 | 运行时机 | 预期证据 | 门禁类型 |
|---|---|---|---|---|
| Route config | `PYTHONPATH=src python3 -m pytest tests/test_route_config.py -q` | commit 前 | pass | Step gate |
| Public verify default | `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step02-asgi` | commit 前 | pass | Step gate |

## 9. Review 环节

- Review 重点：DID document endpoint、nginx 示例、`direct_send` 对 public path 的判断、旧路径兼容。

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | 无阻塞问题 | 默认路径和 custom path 测试均通过。 |
| 已修复问题 | 配置漂移 | `im_rpc_path`、`anp_public_rpc_path`、`ws_path`、object upload/download path 现在都会在启动时注册。 |
| 剩余风险 | 环境需安装 ANP SDK 0.8.8 | 当前本机仍需 `PYTHONPATH=../anp/anp:src` 运行验证。 |
| 新增或缺失测试 | 已新增 | `tests/test_route_config.py` 覆盖 custom ANP public path、IM path、WS path、object path。 |
| 并行安全是否仍成立 | 是 | 未改 User Service compat 业务拆分区域；与 Step 03 仅可能在 imports 合并时需要协调。 |

## 10. Commit 要求

- Commit 范围：routing/settings/deploy 直接相关测试和文档。
- 建议消息：`routing: align configurable public endpoints`

## 11. Blocked 处理

| Blocker | 证据 | 已尝试方案 | 影响范围 | 是否影响并行组 | 是否影响合并门禁 | 下一步决策 |
|---|---|---|---|---|---|---|
| FastAPI dynamic route 和测试冲突 | route test 失败 | 固定路径或启动时 settings route | Step 02 | 否 | 是 | 选择最小真实支持面 |

## 12. Plan 变更记录

| 日期 | 变更 | 原因 | 主 Plan 变更记录链接 |
|---|---|---|---|
| 2026-07-04 | 初始创建 | 修复配置漂移风险 | `../plan.md#16-plan-变更记录` |

## 13. 风险、回滚与后续文档

- 风险：部署 nginx 与 app path 不一致。
- 回滚 / 回退：回退本步骤 commit，保留默认路径。
- 后续文档：Step 06 最终同步 README/deploy。
