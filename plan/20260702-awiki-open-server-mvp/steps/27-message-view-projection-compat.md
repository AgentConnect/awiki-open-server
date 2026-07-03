# Step 27：Message local view 投影兼容收敛

主 Plan：[../plan.md](../plan.md)  
Step index：27  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-with-pending-online-gate |
| Branch | 当前 worktree |
| Started | 2026-07-03 |
| Completed | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 |
| Commit | 未提交 |
| Review evidence | 已复核：`direct.get_history`、`inbox.get`、`group.list_messages` 和 `sync.thread_after` direct/group 分支均使用 Message Service 兼容投影；JSON 返回 `type=json`，附件清单返回 `type=attachment_manifest`，二进制扩展返回 `type=binary`；`body` 与 `content_type` 保留；旧 flat text CLI 路径不回归；public `/anp-im/rpc` 白名单未扩大；未修改相邻仓库 |
| Verification evidence | `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_application_json_payload_shape_and_daemon_heartbeat_no_store tests/test_messaging_objects.py::test_message_local_views_project_payload_attachment_and_binary_content tests/test_messaging_objects.py::test_sync_delta_thread_after_and_read_state_standard_shapes -q` 3 passed；`PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q` 23 passed；`PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 43 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step27-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step27-cross --clean` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step27-rust-cli --clean` pass；`verify-public https://rwiki.info` 仍失败 404，归 Step 09 公网路由 |
| Next action | 回到 Step 09：待 `rwiki.info` 切到本仓后先跑 `verify-public`，再跑真实 `awiki.info` 双向 direct Gate |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki-open-server/src/awiki_open_server/services.py`, `awiki-open-server/tests/test_messaging_objects.py`, `awiki-open-server/README.md`, `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md` |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | focused pytest + messaging tests + compileall + 全量 pytest + ASGI smoke + 双实例本地跨域 Gate + Rust CLI local Gate |

## 2. 目标

补齐 Message Service direct/group local view 的消息投影兼容。Community server 已支持 `meta.content_type` 与 `body` 绑定校验，本步骤要求本地视图统一按 Message Service 规则返回 `type/content/content_type/body`：

- `text/plain` + `body.text` -> `type = "text"`，`content = body.text`。
- `application/json` + `body.payload` -> `type = "json"`，`content = body.payload`。
- `application/anp-attachment-manifest+json` + `body.payload` -> `type = "attachment_manifest"`，`content = body.payload`。
- 其他非文本 content type + `body.payload_b64u` -> `type = "binary"`，`content = body.payload_b64u`。
- `direct.get_history`、`inbox.get`、`group.list_messages` 和 `sync.thread_after` 的 direct/group 分支行为一致。
- 不引入 E2EE/system event 投影，不扩大 public `/anp-im/rpc`，不修改 `user-service`、`message-service` 或 `awiki-cli-rs2`。

## 3. 设计方法

`message-service/docs/api/ANP-client-server-api-direct.md` 和 `message-service/docs/api/ANP-client-server-api-group.md` 都把 local view 定义为本域便利接口，不属于 Federation / Relay 层。Rust 实现中 direct 的 `message_view_to_json` 与 group 的 `group_message_body_projection` 都按 `content_type` 和 `body` 计算 `type/content`。

本仓应复用同一个投影 helper，而不是在 `direct.get_history`、`inbox.get`、`group.list_messages` 和 `sync.thread_after` 分支里各自拼 raw body。这样现有 CLI/SDK 能用同一套 Message Service local view 语义读取 JSON 状态、附件清单和二进制扩展消息。

## 4. 实现方法

1. 在 `awiki-open-server/src/awiki_open_server/services.py`：
   - 保留或补齐 `_project_message_content(body, content_type)`。
   - 确认 `_direct_message_result()` 和 `_group_message_result()` 都返回 `type/content/content_type/body`。
   - 将 `sync.thread_after` direct 分支从 raw row + body 改为 `_direct_message_result(row, owner)`，保证 direct sync repair 与 `direct.get_history` 的投影一致。
   - 不改变 `direct.send` / `group.send` 的存储 schema，不扩展 public handler 白名单。
2. 在 `awiki-open-server/tests/test_messaging_objects.py`：
   - 扩展 JSON payload 测试，明确断言 direct/group local view 的 `type = "json"`。
   - 新增 focused 测试覆盖 direct/group 附件清单和二进制扩展投影。
   - 覆盖 `sync.thread_after` direct 分支返回投影字段，而不是 raw-only message。
3. 更新 `awiki-open-server/README.md` 与主 Plan 证据。

实现结果：

- `_direct_message_result()` 和 `_group_message_result()` 统一使用 `_project_message_content()` 返回 `type/content/content_type/body`。
- `sync.thread_after` direct 分支改为 `_direct_message_result(row, owner)`，与 `direct.get_history` / `inbox.get` 一致。
- focused 测试已覆盖 direct/group 的 JSON、附件清单、二进制扩展投影，以及 direct/group `sync.thread_after` 投影。
- README 已同步 local message view projection 说明。

## 5. 路径

可修改：

- `awiki-open-server/src/awiki_open_server/services.py`
- `awiki-open-server/tests/test_messaging_objects.py`
- `awiki-open-server/README.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/plan.md`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/steps/27-message-view-projection-compat.md`

禁止修改：

- `user-service/**`
- `message-service/**`
- `awiki-cli-rs2/**`
- `awiki-harness/**`
- `awiki-open-server/AGENTS.md`

只读参考：

- `message-service/docs/api/ANP-client-server-api-direct.md`
- `message-service/docs/api/ANP-client-server-api-group.md`
- `message-service/crates/im-direct/src/service.rs`
- `message-service/crates/im-group/src/handlers.rs`

## 6. 验证方式

先运行 focused：

```bash
PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_application_json_payload_shape_and_daemon_heartbeat_no_store tests/test_messaging_objects.py::test_message_local_views_project_payload_attachment_and_binary_content tests/test_messaging_objects.py::test_sync_delta_thread_after_and_read_state_standard_shapes -q
```

再运行本仓门禁：

```bash
PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step27-asgi
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step27-cross --clean
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step27-rust-cli --clean
PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info
```

`verify-public` 仍归 Step 09 公网部署 Gate；如果继续 404，应记录为公网路由未切到本仓，而不是 Step 27 协议失败。

本次证据：

- `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py::test_application_json_payload_shape_and_daemon_heartbeat_no_store tests/test_messaging_objects.py::test_message_local_views_project_payload_attachment_and_binary_content tests/test_messaging_objects.py::test_sync_delta_thread_after_and_read_state_standard_shapes -q`：3 passed。
- `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q`：23 passed。
- `PYTHONPATH=src python3 -m compileall -q src scripts tests`：pass。
- `PYTHONPATH=src python3 -m pytest tests -q`：43 passed。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step27-asgi`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step27-cross --clean`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-rust-cli-local --awiki-cli-bin /tmp/awiki-cli-rs2-open-server-target/debug/awiki-cli --data-root /tmp/awiki-open-server-step27-rust-cli --clean`：pass。
- `PYTHONPATH=src python3 scripts/awiki_open_cli.py verify-public --base-url https://rwiki.info --did-domain rwiki.info`：failed，`/.well-known/did.json`、`/healthz`、`/anp-im/rpc` 均 404；继续归 Step 09 公网路由。

## 7. Review 环节

Review 必须检查：

- `direct.get_history`、`inbox.get`、`group.list_messages`、`sync.thread_after` 的 direct/group message projection 一致。
- JSON、附件清单、二进制扩展的 `type/content` 与 Message Service 文档和 Rust 实现一致。
- 文本 flat CLI 路径不回归。
- public `/anp-im/rpc` 白名单未扩大。
- 未修改相邻仓库，未把 `awiki.info` 作为后端或 fallback。

Review 结论：

- 通过。`direct.get_history`、`inbox.get`、`group.list_messages` 和 `sync.thread_after` 的 direct/group 分支现在使用同一套 projection 规则，保留 raw `body` 与 `content_type`。
- 通过。JSON、附件清单、二进制扩展的 `type/content` 与 Message Service 文档和 Rust 实现一致。
- 通过。旧 flat text CLI 路径不回归，Rust CLI local Gate 通过。
- 通过。public `/anp-im/rpc` 白名单未扩大，未修改相邻仓库，未把 `awiki.info` 作为后端或 fallback。
- 剩余风险：公网 `rwiki.info` 尚未路由到本仓，真实 `awiki.info` 双向 Gate 仍待 Step 09。

## 8. 风险与回滚

| 风险 | 缓解措施 | 回滚 / 回退方案 |
|---|---|---|
| 客户端依赖 `sync.thread_after` direct raw body 但缺少 `type/content` | 本步骤只追加/对齐 local view 字段，保留 `body` 字段；旧客户端仍可读 raw body | 如发现客户端强依赖 raw-only 结构，应保留 `body` 并在 SDK 忽略新增字段，不回退投影兼容 |
| 附件 manifest payload shape 与 object ticket 校验不一致 | 复用已有 attachment ticket 测试里的 manifest body，并额外断言 local view projection | 如完整 manifest schema 后续扩展，只验证 `body.payload` 投影，不解释业务字段 |
| 二进制扩展未被 Rust CLI 当前路径使用 | 用 focused pytest 锁定协议兼容面，Rust CLI Gate 保证旧文本路径不回归 | 如 CLI 后续支持二进制，优先在本仓 local view 中保持当前 `type=binary` |
