# Step 01：服务骨架与存储

主 Plan：[../plan.md](../plan.md)  
Step index：01  
状态：done

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done |
| Branch | 当前 worktree |
| Started | 2026-07-02 |
| Completed | 2026-07-02 22:36 CST |
| Commit | 未提交 |
| Review evidence | app factory 无 import 写状态；SQLite init 幂等；JSON-RPC error shape 统一 |
| Verification evidence | `PYTHONPATH=src python3 -m pytest tests/test_health.py -q` pass；最终全量 pytest 9 passed |
| Next action | 已完成，进入后续 Step |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `awiki_open_server/`, `tests/`, `pyproject.toml` |
| Baseline commit | 8f334b7 |

## 2. 目标

建立可运行服务骨架：FastAPI app factory、settings、route mount、JSON-RPC request/response/error、SQLite schema 初始化、`GET /healthz`。

## 3. 设计方法

- 使用 `src/awiki_open_server/` src-layout。
- 使用 stdlib `sqlite3`，避免网络依赖。
- app 启动时按 `AWIKI_DATA_DIR` 初始化 DB 和对象目录。
- JSON-RPC 层统一返回 `jsonrpc/result/error/id`。

## 4. 实现方法

- 新增 `pyproject.toml`。
- 新增 `awiki-open-server/src/awiki_open_server/app/main.py`、`settings.py`、`routes.py`。
- 新增 `shared/jsonrpc.py`、`shared/errors.py`、`storage/db.py`。
- 新增 `tests/test_health.py`。

## 5. 路径

- `awiki-open-server/pyproject.toml`
- `awiki-open-server/src/awiki_open_server/**`
- `awiki-open-server/tests/test_health.py`

## 6. 验证方式

```bash
cd awiki-open-server
python3 -m pytest tests/test_health.py -q
```

预期：health 返回 `ok`，DB schema 可初始化。

## 7. Review 环节

- 检查 app factory 不在 import 时写全局状态。
- 检查 DB 初始化可重复。
- 检查 JSON-RPC error shape 后续可复用。

## 8. Commit 要求

Step 完成后建议聚焦提交：`Implement awiki open server skeleton`。
