# AWiki Open Server 数据、备份与运维

[English](operations.md) | [简体中文](operations.zh-CN.md)

## 1. 数据资产

`AWIKI_DATA_DIR` 是最重要的持久化边界，至少包含：

- SQLite 数据库；
- SQLite WAL、群 durable outbox 与本地 projection；
- 已提交的附件对象；
- `group-keys` 下的 Group Host 私钥；
- 未提交/临时对象或 slot 相关状态（按实现）；
- 运行所需的本地业务状态。

Service private key 通常位于独立安全目录，不应放在 Git checkout 或公开数据备份中无保护传播。

## 2. 一致性备份

数据库与对象文件共同构成消息/附件事实。只备份 SQLite 或只备份对象目录都可能造成不可恢复的不一致。

当前单节点 MVP 的保守流程：

1. 停止外部写入；
2. 停止应用服务，或使用经过验证的一致性 snapshot 方法；
3. 备份整个 `AWIKI_DATA_DIR`；
4. 单独备份 service DID private key 与配置，使用更严格的访问控制；
5. 记录代码 commit、Python/ANP 版本和环境变量摘要（不包含秘密）；
6. 重启服务并执行 health/smoke。

## 3. 恢复

在隔离环境先恢复：

1. 使用匹配的代码 commit 和依赖；
2. 恢复 `AWIKI_DATA_DIR`；
3. 恢复同一 service DID/private key；
4. 确认文件 owner/permission；
5. 启动在非生产端口；
6. 运行 `healthz`、`smoke-local` 和必要的 client smoke；
7. 检查 DID Document 与 endpoint；
8. 再切换正式流量。

不要在没有备份的情况下对生产数据尝试 schema 或 key 修复。

## 4. 升级

当前 README 基线没有声明完整的在线 migration、rollback 或跨版本兼容契约。因此升级前：

- 阅读 release notes 和 schema 变化；
- 记录当前 commit 与 ANP SDK version；
- 完整备份；
- 在副本数据上验证；
- 停止写入后升级；
- 运行 pytest、local smoke、CLI smoke 和 public verify；
- 如失败，恢复代码、数据和 key 的一致组合。

版本升级不能只替换 Python 代码而忽略数据/对象与 service identity。

## 5. Health 与监控

最低检查：

```bash
curl --noproxy '*' https://community.example.com/healthz
```

受保护的聚合诊断需要配置 `AWIKI_OPERATIONS_TOKEN_FILE`，并从本机或受限运维入口查询：

```bash
curl --fail-with-body \
  -H "Authorization: Bearer ${AWIKI_OPERATIONS_TOKEN}" \
  http://127.0.0.1:8766/operations/status
```

响应包含托管群/active 成员、outbox pending/retry/delivered/dead、最旧 pending age、worker heartbeat/last drain、DB/WAL 大小和 group-key 目录状态。未配置时返回 `404`，无有效 Bearer 时返回 `401`。真实运维不要把 secret 留在命令历史中；上例只展示请求形状，服务应从权限为 `0600` 的文件读取。公开 `/healthz` 不包含这些诊断。

还应监控：

- 进程 restart/failure；
- SQLite 锁、磁盘空间与文件权限；
- 对象目录容量；
- group-key 目录状态与 outbox backlog/dead delivery/worker age；
- HTTP 4xx/5xx 与 JSON-RPC error code；
- WebSocket connection 数；
- attachment upload/commit failure；
- DID resolution/signature/receipt failure；
- refresh/revoke 异常；
- `verify-public` 结果。

日志不能记录 access/refresh/operations token、private key、完整 proof/signature、非测试 message body 或敏感 attachment URL。

## 6. Attachment 清理

Upload slot 约 30 分钟过期，download ticket 约 15 分钟过期。实现提供过期附件状态清理 helper，但当前没有公共 cleanup endpoint 或后台 daemon。

生产采用前需要明确：

- 谁调用 cleanup；
- 调度频率；
- 是否只删除未提交 slot 和过期 ticket；
- committed object 的保留和删除策略；
- orphan object 检测；
- 磁盘告警和容量上限。

## 7. Realtime 运维

WebSocket 通知只在单进程内发布：

- 不能通过增加多个 Uvicorn worker 自动获得 HA；
- 无外部 pub/sub fanout；
- 客户端必须用 `sync.delta` / `sync.thread_after` 做 durable recovery；
- realtime hint 不是 read watermark 或可靠 checkpoint。

需要多进程/多节点前，应先设计共享 event bus、session、ordering、backfill 和 failure recovery。

## 8. 故障诊断顺序

1. `healthz`；
2. systemd/process status；
3. Nginx route 与 TLS；
4. `/.well-known/did.json`；
5. `anp.get_capabilities`；
6. local smoke；
7. CLI smoke；
8. public verify；
9. 受保护 operations status 与 outbox 健康状态；
10. 双向 Direct/Group interop，记录方向、DID、目标 URL 和脱敏错误。

不要先修改 sibling AWiki 服务；本仓库必须能够独立解释自己的请求路径。

## 9. 单节点风险

- 单进程故障会中断 realtime 和 API；
- 本地磁盘故障会同时影响 DB、对象和 Group key；
- 无内置 replica/failover；
- 无完整 event-log compaction/retention；
- 无生产离线推送；
- 无对象远程 relay。
- 群投递可通过 SQLite 重试并在重启后恢复，但这不等于 HA。

这些风险应在任何生产试点的 SLO、备份和容量计划中显式接受。
