# Step 03：消息、群参与、附件

主 Plan：[../plan.md](../plan.md)  
Step index：03  
状态：done

## 1. 执行状态

| 字段 | 值 |
|---|---|
| Status | done |
| Branch | 当前 worktree |
| Started | 2026-07-02 |
| Completed | 2026-07-02 22:36 CST |
| Commit | 未提交 |
| Review evidence | `/anp-im/rpc` 白名单仅含公开方法；群管理方法返回 `not_supported`；direct/group/attachment/sync/read-state 已覆盖 |
| Verification evidence | `PYTHONPATH=src python3 -m pytest tests/test_messaging_objects.py -q` pass；最终全量 pytest 9 passed |
| Next action | 已完成，进入后续 Step |
| Assigned agent | main |
| Parallel group | 串行 |
| Parallel safe | no |
| Parallel with | 无 |
| Conflict resources | `messaging/`, `object_store/`, DB schema |
| Baseline commit | 8f334b7 |

## 2. 目标

实现 `/im/rpc` 与 `/anp-im/rpc` 的 direct、group participant、attachment、sync/read-state 子集。

## 3. 设计方法

- `/im/rpc` 暴露本域方法：history、inbox、sync、read-state、attachment upload control、group local。
- `/anp-im/rpc` 只暴露 capability、direct send、group get_info/join、download ticket，并接受 ANP envelope。
- `group.create/add/remove/update_profile/update_policy` 返回 `not_supported`。
- 附件使用本地文件对象存储；E2EE attachment 返回策略错误。

## 4. 实现方法

- 新增 `messaging/service.py`、`object_store/service.py`。
- 实现 `anp.get_capabilities`。
- 实现 direct send/history/inbox/read-state/sync。
- 实现 group seed、join、leave、send、list、members、messages。
- 实现 attachment create slot、upload REST、commit、ticket、download REST。

## 5. 路径

- `awiki-open-server/src/awiki_open_server/messaging/**`
- `awiki-open-server/src/awiki_open_server/object_store/**`
- `awiki-open-server/tests/test_messaging_objects.py`

## 6. 验证方式

```bash
cd awiki-open-server
python3 -m pytest tests/test_messaging_objects.py -q
```

## 7. Review 环节

- 检查公开入口没有暴露 local-only 方法。
- 检查群管理方法禁用。
- 检查附件 ticket 过期和访问控制最小可用。

## 8. Commit 要求

建议提交：`Implement messaging group participant and attachments`。
