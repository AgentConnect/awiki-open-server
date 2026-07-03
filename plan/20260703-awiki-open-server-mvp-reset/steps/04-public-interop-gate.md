# Step 04：Public rwiki.cn / awiki.info interop gate

主 Plan：[../plan.md](../plan.md)  
Step index：04  
状态：done-public-interop

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-public-interop |
| Branch | 当前 worktree |
| Started | 2026-07-03 |
| Completed | 2026-07-03 |
| Commit | 未提交 |
| Review evidence | deploy explorer 已只读审计；用户确认当前测试域改为 `rwiki.cn`；nginx 已切到本仓服务；真实互通发现 signed CLI DID document 被重写会破坏 proof，已修复为 signed 文档不重写、unsigned legacy 文档继续补齐 `ANPMessageService`；只读 Review 发现 signed 文档错误 service 和自定义 service DID JSON 漂移风险，已补拒绝校验 |
| Verification evidence | 旧域历史证据：2026-07-03 21:09 CST `verify-public --base-url https://rwiki.info --did-domain rwiki.info` failed 404。当前证据：2026-07-03 22:36 CST `verify-public --base-url https://rwiki.cn --did-domain rwiki.cn` pass，包含 `anp_service_auth_schemes` 检查；新 `rwiki.cn` 用户 DID document proof 校验通过；真实 `rwiki.cn -> awiki.info` direct/inbox/history pass；真实 `awiki.info -> rwiki.cn` direct/inbox/history pass；服务形态防护后 2026-07-03 22:40 CST 复跑双向 direct/inbox/history pass；全量 pytest 47 passed |
| Next action | 最终全局 Review 与整体验证 |
| Assigned agent | main + deploy-explorer |
| Parallel group | A |
| Parallel safe | yes for read-only audit |
| Parallel with | Step 01 只读文档审计 |
| Conflict resources | 公网域名、nginx/systemd、service private key |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | verify-public + real bidirectional direct |

## 2. 目标

- 结果：证明 `rwiki.cn` 公网域名真实路由到本仓 open server，并与线上 `awiki.info` 用户双向 direct 互通。
- 用户 / 系统可见行为：`rwiki.cn` 服务 DID、用户 DID 文档和 `/anp-im/rpc` 可被 `awiki.info` 发现并调用。
- 非目标：不把 `awiki.info` 当后端，不在 public gate 未过时继续扩本地功能。
- 完成标准：`verify-public` 通过；真实 `rwiki.cn -> awiki.info` 和 `awiki.info -> rwiki.cn` direct/inbox/history 均通过。

## 3. 设计方法

- 设计边界：public gate 分两层，先 routing readiness，再真实双向 interop。
- 核心决策：404 是部署 blocker，不是本仓协议失败；不能用本地 cross-domain smoke 替代。
- 契约 / API / 数据流：要求 `AWIKI_PUBLIC_BASE_URL=https://rwiki.cn`、`AWIKI_DID_DOMAIN=rwiki.cn`、`AWIKI_SERVICE_DID=did:wba:rwiki.cn`、稳定 service private key、`AWIKI_ALLOW_UNSIGNED_PEER_DEV=false`。
- 兼容性：只验证 direct 主线，不扩 group/federation/site；signed CLI DID document 不重写 proof 覆盖字段，但必须只包含一个指向本服务的 `ANPMessageService`；unsigned legacy DID document 仍 rehome 到本服务 `ANPMessageService`。
- 风险控制：失败时记录 sender DID、recipient DID、target URL、RPC error body、服务日志。

## 4. 实现方法

1. 跑 `verify-public`。
2. 若仍 404，记录 `blocked-public-route`，不继续真实 interop。
3. 若 public gate 通过，用两个隔离 CLI workspace：
   - 一个连接 `https://rwiki.cn` 注册本服务用户。
   - 一个连接 `https://awiki.info` 准备线上用户。
   - 验证 `rwiki -> awiki.info` direct 和远端 inbox/history。
   - 验证 `awiki.info -> rwiki` direct 和本地 inbox/history。
4. 如发现本仓签名、DID document、origin proof 问题，只改本仓；如是远端服务限制，记录 blocker。
5. 本轮真实互通发现的 peer auth 拒绝已定位为 signed CLI DID document proof 被注册路径重写破坏；修复点为本仓 identity 文档处理和 service DID document `authSchemes`。
6. 只读 Review 发现 signed 文档错误 service 和自定义 service DID JSON 漂移风险；补充启动/注册时拒绝校验，不通过重写 signed 文档来修复。

## 5. 路径

| 仓库 / 模块 / 文件 | 计划变更 | 备注 |
|---|---|---|
| `awiki-open-server/src/awiki_open_server/services.py` | signed DID document 保持不变，并拒绝多 service、错 endpoint、错 serviceDid；unsigned legacy 文档继续补齐 `ANPMessageService` | 本仓 |
| `awiki-open-server/src/awiki_open_server/service_identity.py` | service DID document `authSchemes` 对齐 `bearer` / `didwba`，并校验自定义 JSON 的 service shape | 本仓 |
| `awiki-open-server/src/awiki_open_server/app/routes.py` | fallback service DID document `authSchemes` 对齐 `bearer` / `didwba` | 本仓 |
| `awiki-open-server/scripts/awiki_open_cli.py` | `verify-public` 增加 `authSchemes` 检查 | 本仓 |
| `awiki-open-server/tests/test_identity_pages.py` | 增加 signed CLI DID document 不被重写和 service 必须匹配本服务的回归测试 | 本仓 |
| `awiki-open-server/tests/test_messaging_objects.py` | 增加自定义 service DID JSON shape 校验测试 | 本仓 |
| `awiki-open-server/tests/test_cli_smoke.py` | 更新 `verify-public` fake DID 文档 fixture | 本仓 |
| `awiki-open-server/deploy/README.md` | 只在需要补充 gate 说明时修改 | 本仓 |
| `awiki-open-server/deploy/nginx-rwiki.cn.conf.example` | 只在 route surface 缺失时修改 | 本仓 |
| `awiki-open-server/scripts/awiki_open_cli.py` | 可后续补自动 interop gate | 本仓 |
| 公网 `rwiki.cn` 配置 | 本轮由主机 nginx/systemd 配置完成 | 本机运行配置 |

## 6. 依赖与并行约束

- 前置步骤：Step 03 本地 gate。
- 可并行步骤：Step 01 只读审计。
- 不可并行步骤：真实 interop 必须等 public gate 通过。
- 并行安全依据：只读 `verify-public` 可并行；部署变更不可由本计划自动执行。
- 互斥资源 / 冲突路径：公网域名、service key。
- 外部文档或决策：用户已确认 `rwiki.cn` 证书配置到 nginx 且解析到本机；需要把 nginx upstream 指向本仓服务。
- 环境前提：公网 HTTPS、DNS/nginx/systemd 正常。
- 合并前置条件：public gate pass。
- 合并后验证门禁：双向 interop。

## 7. 验收标准

- [x] `https://rwiki.cn/.well-known/did.json` 200，id 为 `did:wba:rwiki.cn`。
- [x] DID document 含 verification method、authentication、proof 和唯一 `ANPMessageService`。
- [x] `ANPMessageService.serviceEndpoint` 为 `https://rwiki.cn/anp-im/rpc`。
- [x] `https://rwiki.cn/healthz` 200。
- [x] `https://rwiki.cn/anp-im/rpc` capability 返回 Community，`cross_domain_direct.enabled=true`，`federation.enabled=false` 或 disabled。
- [x] `verify-public` 校验 service DID document `authSchemes=["bearer","didwba"]`。
- [x] 本地用户 DID 文档公网可解析，新 `rwiki.cn` 用户 DID document proof 校验通过。
- [x] `rwiki.cn` 用户与 `awiki.info` 用户双向 direct/inbox/history 通过。

## 8. 验证方式

| 检查项 | 命令 / 方法 | 运行时机 | 预期证据 | 门禁类型 |
|---|---|---|---|---|
| Public readiness | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.cn --did-domain rwiki.cn` | Step 04 | 2026-07-03 22:36 CST pass：DID document 200，endpoint `https://rwiki.cn/anp-im/rpc`，authSchemes pass，healthz 200，capability pass，cross-domain direct enabled，federation disabled | Public gate |
| Focused regression | `PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py::test_user_service_identity_compat_path_accepts_cli_did_document tests/test_identity_pages.py::test_signed_cli_did_document_service_is_not_rewritten tests/test_identity_pages.py::test_signed_cli_did_document_service_must_match_open_server tests/test_messaging_objects.py::test_service_identity_custom_document_must_match_public_service_shape tests/test_messaging_objects.py::test_public_anp_direct_accepts_signed_peer_request tests/test_messaging_objects.py::test_public_anp_direct_verifies_signature_against_public_base_url tests/test_cli_smoke.py::test_verify_public_accepts_open_server_surface -q` | 修复后 | 7 passed | Code gate |
| Full regression | `PYTHONPATH=src python3 -m compileall -q src scripts tests && PYTHONPATH=src python3 -m pytest tests -q` | 最终 Review | compileall pass；47 passed | Repo gate |
| Real interop | 两个隔离 CLI workspace 连接 `rwiki.cn` / `awiki.info` 双向 direct | Public gate 后 | 初次通过：`rwiki.cn -> awiki.info` message `msg-1886f11dae554754`，`awiki.info -> rwiki.cn` message `msg-1886f0a64010ebc5`。服务形态防护后复跑通过：`rwiki.cn -> awiki.info` message `msg-1886aba5c219cefe`，`awiki.info -> rwiki.cn` message `msg-1886abacc4c1a11e`；两侧 inbox/history 均可见 | Final gate |

## 9. Review 环节

- Review 时机：public gate 或 blocker 记录后。
- Review 重点：是否误把 `awiki.info` 当后端；是否把本地 gate 当公网完成；失败证据是否足够定位。

| Review 项 | 结果 | 备注 |
|---|---|---|
| 发现问题 | 旧域 `rwiki.info` 404；`rwiki.cn` 原先 nginx upstream 指向 `user-service:9891`；真实互通首次失败时远端返回 `service DID requests must use peer auth on /anp-im/rpc` | 根因是 signed CLI DID document 被注册路径重写，proof 失效 |
| 已修复问题 | `rwiki.cn` 已切到本仓并通过 public gate；signed CLI DID document 不再重写且错误 service 会被拒绝；unsigned legacy DID document 仍补齐 `ANPMessageService`；service DID document `authSchemes` 对齐 `bearer` / `didwba` 并纳入启动校验和 public gate；真实双向 interop 已通过 |  |
| 剩余风险 | 真实互通依赖公网配置和外部 `awiki.info` 可用性；公共部署必须保持 contact verification compat 关闭 | 环境变化后复跑 public gate 和 real interop gate |
| 新增或缺失测试 | 已新增 signed CLI DID document 不被重写、signed service shape、自定义 service DID JSON shape、verify-public authSchemes 测试；缺自动真实 awiki.info interop gate | 自动真实 interop gate 可后续补 |
| 已更新或缺失文档 | 已更新 reset Plan 和 Step 04；`deploy/awiki-open-server.env.example` 标明 contact verification compat disabled |  |
| 并行安全是否仍成立 | 是 | 只读审计 |

## 10. Commit 要求

- Commit 时机：代码、测试、计划文档完成 Review 和整体验证后。
- Commit 范围：只包含本仓 source/test/docs/plan/deploy/script 变更；不包含 sibling repo 或 `AGENTS.md`。
- 建议消息：`fix: preserve signed did documents for interop`

## 11. Blocked 处理

| Blocker | 证据 | 已尝试方案 | 影响范围 | 是否影响并行组 | 是否影响合并门禁 | 下一步决策 |
|---|---|---|---|---|---|---|
| 旧域 `rwiki.info` 未路由到本仓 | `verify-public` 三个关键入口 404 | 只读运行 public gate | 历史证据，不影响当前 `rwiki.cn` 配置 | 否 | 否 | 当前改用 `rwiki.cn` |

## 12. Plan 变更记录

| 日期 | 变更 | 原因 | 主 Plan 变更记录链接 |
|---|---|---|---|
| 2026-07-03 | 新增 Step 04 | 真实 MVP 完成依赖公网互通 | `../plan.md#16-plan-变更记录` |
| 2026-07-03 | Step 04 当前公网域切换为 `rwiki.cn` | 用户确认使用 `rwiki.cn` 测试且要求自行配置域名 | `../plan.md#16-plan-变更记录` |
| 2026-07-03 | 增加 signed DID document proof 修复 | 真实互通发现远端 peer auth 拒绝；需要保护 CLI 已签名 DID document | `../plan.md#16-plan-变更记录` |
| 2026-07-03 | 增加 DID service shape 防护 | 只读 Review 发现 signed 用户 DID 文档可保留错误 service、自定义 service DID JSON 可漂移；补拒绝校验和 public gate `authSchemes` 检查 | `../plan.md#16-plan-变更记录` |

## 13. 风险、回滚与后续文档

- 风险：公网路由不在本仓代码内完成，且真实互通依赖外部 `awiki.info` 可用性。
- 配置风险：如果公共部署误设 `AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=true`，会启用本地 dev contact shim；当前 systemd env 已确认保持 `false`。
- 并行执行风险：无。
- 合并冲突风险：低。
- Group gate 失败回退：记录 blocker，不扩本地功能。
- Agent 交接说明：Step 04 已通过；后续从最终全局 Review 与整体验证继续。
- 回滚 / 回退：如 signed DID document 处理回退，会再次破坏 CLI DID document proof，不建议回退；若必须回退，需要同步替代 proof 重签方案。
- 后续文档：可新增自动 `interop-awiki-info` 脚本设计。
