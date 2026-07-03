# Step 02：身份、Profile、Pages

主 Plan：[../plan.md](../plan.md)  
Step index：02  
状态：done

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done |
| Branch | 当前 worktree |
| Started | 2026-07-02 |
| Completed | 2026-07-02 22:36 CST |
| Commit | 未提交 |
| Review evidence | DID document 含唯一 `ANPMessageService`；dev token 不写日志；Pages 使用 handle+slug；`rename` 和 DID resolve 已覆盖 |
| Verification evidence | `PYTHONPATH=src python3 -m pytest tests/test_identity_pages.py -q` pass；最终全量 pytest 9 passed |
| Next action | 已完成，进入后续 Step |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `identity/`, `pages/`, DB schema |
| Baseline commit | 8f334b7 |

## 2. 目标

实现 `/did-auth/rpc`、`/did/profile/rpc`、`/content/rpc` 和 `GET /content/{slug}.md`。

## 3. 设计方法

- dev DID 注册返回本地 DID、handle、token 和 DID document。
- token 使用轻量 dev token，不宣称生产 JWT 安全。
- Profile 字段遵循 `did`、`handle`、`display_name`、`avatar_uri`、`profile_uri`、`description`、`subject_type`。
- Pages 以 handle + slug 唯一。

## 4. 实现方法

- 新增 `identity/service.py` 和 `pages/service.py`。
- JSON-RPC 方法：`register`、`verify`、`get_me`、`update_me`、`get_public_profile`、`resolve`、`create/update/rename/delete/list/get`。
- `replace_did`、`recover_handle` 返回 `not_supported`。

## 5. 路径

- `awiki-open-server/src/awiki_open_server/identity/**`
- `awiki-open-server/src/awiki_open_server/pages/**`
- `awiki-open-server/tests/test_identity_pages.py`

## 6. 验证方式

```bash
cd awiki-open-server
python3 -m pytest tests/test_identity_pages.py -q
```

## 7. Review 环节

- 检查 token 不写入日志。
- 检查 DID document 包含唯一 `ANPMessageService`。
- 检查 Pages visibility 和 slug 唯一性。

## 8. Commit 要求

建议提交：`Implement identity profile and pages APIs`。
