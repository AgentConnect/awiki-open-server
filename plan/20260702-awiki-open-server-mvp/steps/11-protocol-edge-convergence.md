# Step 11：协议边缘兼容收敛

主 Plan：[../plan.md](../plan.md)  
Step index：11  
状态：done-with-pending-online-gate

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done-with-pending-online-gate |
| Branch | main |
| Started | 2026-07-03 |
| Completed | 2026-07-03 本仓门禁完成；公网 Gate 仍待 Step 09 |
| Commit | 未提交 |
| Review evidence | 已复核：`read_state.mark_read` 只写 thread watermark、不写未知 sync event；message-id watermark 只在调用方可见 thread 内解析并校验 seq；attachment header token 不破坏 query token；默认群 DID 跟随 domain；公开 `group.join` 要求 origin proof 与 service HTTP Signature；`/im/rpc group.join` 仍保持本地 Bearer 兼容 |
| Verification evidence | `PYTHONPATH=src python3 -m compileall -q src scripts tests` pass；`PYTHONPATH=src python3 -m pytest tests -q` 28 passed；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step11-asgi` pass；`PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step11-cross --clean` pass；隔离 Rust CLI 本地最小回归 pass：注册 Alice/Bob、Alice -> Bob direct、Bob inbox/history 均可见消息；`verify-public https://rwiki.info` 仍 404，属 Step 09 公网路由 blocker |
| Next action | 公网 `rwiki.info` 切到本仓后继续 Step 09；先跑 `verify-public`，再跑与线上 `awiki.info` 用户双向 direct Gate |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `src/awiki_open_server/services.py`、`src/awiki_open_server/app/routes.py`、`src/awiki_open_server/shared/jsonrpc.py`、`src/awiki_open_server/storage/db.py`、`scripts/awiki_open_cli.py`、`tests/` |
| Baseline commit | 8f334b7 |
| Worktree / branch | 当前 worktree |
| Merge gate | 本仓 pytest + ASGI smoke + 双实例本地跨域 Gate pass；公网 Gate 仍按 Step 09 |

## 2. 目标

补齐 Step 10 后继续发现的本仓可修协议边缘缺口，避免极简 open server 在现有 CLI/Message Service 文档形态下出现不必要的不兼容。

验收标准：

- `read_state.mark_read` 只持久化 thread-local watermark 并返回 ack，不写当前稳定客户端不支持的账号级 sync event。
- `read_state.mark_read` 支持仅用 `read_up_to_message_id` 推导 thread-local `server_seq`，并校验 message id 与显式 seq 匹配。
- `sync.delta` 能接受只有 `{body}`、没有 `{meta}` 的兼容 JSON-RPC envelope。
- 附件上传数据面同时接受 query `token` 和控制面返回的 `X-ANP-Upload-Token` header。
- 默认 open group DID 跟随 `AWIKI_DID_DOMAIN`，本地仍是 `did:wba:localhost:groups:open`，测试域是 `did:wba:testserver:groups:open`。
- 公开 `/anp-im/rpc group.join` 要求业务 origin proof 和服务 HTTP Signature；本地 `/im/rpc group.join` 保持 CLI 兼容。

## 3. 设计方法

- 不扩大 Community 能力，只收紧已有公开方法的安全和 wire 兼容形态。
- 继续保留 `/im/rpc` local-only 与 `/anp-im/rpc` public peer entry 分离。
- 对现有 CLI 兼容优先：旧扁平参数、query upload token 和默认本地域群 DID 仍可用。
- 对公开跨域写操作 fail closed：没有 origin proof 或 hop signature 时拒绝，不把 `group.join` 变成匿名跨域写入口。

## 4. 实现方法

已完成：

1. `awiki-open-server/src/awiki_open_server/shared/jsonrpc.py`：允许只有 `body` 的 envelope 展开到 flat params，保留 `{meta, auth, client}` 存在时的 ANP 参数。
2. `awiki-open-server/src/awiki_open_server/services.py`：`read_state.mark_read` 去掉 `read_state.updated` sync event；增加 message id 到 `server_seq` 的解析与 mismatch 校验；公开 `group.join` 增加 origin proof 与 peer HTTP Signature 校验；修正附件 URL 的 trailing slash 处理。
3. `awiki-open-server/src/awiki_open_server/app/routes.py`：`PUT /objects/upload/{slot_id}` 同时接受 query `token` 和 `X-ANP-Upload-Token`。
4. `awiki-open-server/src/awiki_open_server/storage/db.py` 与 `scripts/awiki_open_cli.py`：默认 open group DID 跟随配置的 DID domain。
5. `awiki-open-server/tests/test_messaging_objects.py`：新增/更新 read-state、公开 group.join 签名、header upload token、动态群 DID 覆盖。

## 5. 路径

已修改路径：

- `awiki-open-server/src/awiki_open_server/app/main.py`
- `awiki-open-server/src/awiki_open_server/app/routes.py`
- `awiki-open-server/src/awiki_open_server/services.py`
- `awiki-open-server/src/awiki_open_server/shared/jsonrpc.py`
- `awiki-open-server/src/awiki_open_server/storage/db.py`
- `awiki-open-server/scripts/awiki_open_cli.py`
- `awiki-open-server/tests/test_messaging_objects.py`
- `awiki-open-server/plan/20260702-awiki-open-server-mvp/`

只读参考路径：

- `message-service/docs/api/ANP-client-server-api-sync.md`
- `message-service/docs/api/ANP-client-server-api-read-state.md`
- `message-service/docs/api/ANP-client-server-api-attachment.md`
- `awiki-harness/features/message-sync-reliability.md`

禁止修改路径：

- `user-service/**`
- `message-service/**`
- `awiki-cli-rs2/**`
- `awiki-harness/**`
- 其他相邻仓库

## 6. 验证方式

本仓回归：

```bash
cd awiki-open-server
PYTHONPATH=src python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m pytest tests -q
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-asgi --data-dir /tmp/awiki-open-server-step11-asgi
PYTHONPATH=src python3 scripts/awiki_open_cli.py smoke-cross-domain-local --data-root /tmp/awiki-open-server-step11-cross --clean
```

已运行：

- focused public group/read-state：pass。
- `tests/test_messaging_objects.py tests/test_cli_smoke.py`：20 passed。
- compileall：pass。
- 全量 pytest：28 passed。
- ASGI smoke：`{"ok": true, "mode": "asgi", ...}`。
- 双实例本地跨域 Gate：pass，继续验证两个独立服务实例、service DID HTTP Signature、DID discovery、origin proof 和双向 inbox delivery。
- 隔离 Rust CLI 本地最小回归：pass；服务运行在 `http://127.0.0.1:8765`，CLI workspace 为 `/tmp/awiki-cli-step11-workspace`，`id register` Alice/Bob、Alice -> Bob `msg send`、Bob `msg inbox` 和 `msg history --with <alice>.localhost` 均通过并可见 `hello bob from step11`。
- `verify-public --base-url https://rwiki.info --did-domain rwiki.info`：仍失败，`/.well-known/did.json`、`/healthz`、`/anp-im/rpc` 均 404；这只证明公网域名尚未路由到本仓，不是 Step 11 本地协议失败。

## 7. Review 环节

Review 必须检查：

- `read_state.mark_read` 是否符合 v0.1 不发送 `message.read_state_updated` / 未知 sync event 的边界。
- `read_up_to_message_id` fallback 是否只在调用方可见 thread 内解析，不泄露其他用户或群消息。
- 公开 `group.join` 是否和 direct 入站一样要求 origin proof 与 service HTTP Signature。
- 附件 header token 支持是否不破坏 query token 兼容。
- 默认群 DID 跟随 domain 后，README/CLI smoke/Rust CLI 本地 Gate 仍能使用 `localhost` 默认群。

## 8. 并行安全

- parallel-safe：否。
- 原因：修改共享 JSON-RPC normalizer、消息 handler、存储 seed 和 smoke 测试，必须串行验证。
- 合并策略：完成 focused 测试后跑全量门禁，再回填主 Plan。

## 9. Blocker 判定

本步骤不引入新的外部 blocker。若本地门禁失败，先修本仓。公网 `rwiki.info` 未路由仍属于 Step 09 blocker，不影响本步骤完成。

## 10. 文档影响

本步骤只更新 `awiki-open-server` Plan 和 README。相邻服务文档只作为只读参考，不修改。
