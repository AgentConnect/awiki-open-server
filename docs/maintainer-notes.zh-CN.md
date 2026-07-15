# AWiki Open Server README 上线前维护说明

[English](maintainer-notes.md) | [简体中文](maintainer-notes.zh-CN.md)

本文不面向最终用户。

## 1. 建议 GitHub About

**Description**

```text
Self-hosted single-node AWiki Community Server with DID identity, messaging, attachments, realtime, and ANP interoperability.
```

**Topics**

```text
self-hosted, fastapi, anp, did, messaging, community-server, federation, python
```

当前 `awiki lite server` 描述信息量不足，应与 README 首段同步更新。

## 2. 状态

`pyproject.toml` 当前为 `0.1.0`，描述为 Single-process Community Server MVP。README 使用 `v0.1 MVP`，并把以下边界放在首屏：

- 无 E2EE；
- 单节点；
- 无生产 SMS/Email；
- 无完整 Group Admin；
- 无 HA/Offline Push；
- 无完整 Federation。

除非这些边界发生实质变化，不应改成 Stable。

## 3. 中文文件名

中文 README 已统一为：

```text
README.zh-CN.md
```

英文 README 语言入口也已同步。

## 4. 公网案例与通用文档

仓库现有部署文档以 `rwiki.cn` 为真实案例。主 README 和通用部署文档使用 `community.example.com`；`rwiki.cn` 的当前服务器临时故障、PyPI SSL EOF 与本地 path workaround 应保留在案例/运维记录，不应进入项目首屏。

## 5. 容器化

当前基线没有可验证的 Dockerfile/Compose 主路径，因此提案不写 Docker 命令。若增加容器化，必须先有：

- non-root image；
- persistent data/object volume；
- key secret mount；
- healthcheck；
- compose smoke；
- upgrade/backup contract。

## 6. 客户端兼容性

发布前至少跑：

- pytest；
- `smoke-asgi`；
- `smoke-local`；
- `smoke-cross-domain-local`；
- Rust CLI local smoke；
- 公网 `verify-public`（如发布公网）；
- AWiki Me custom tenant smoke（如对外宣称 App 兼容）。

特别确认 AWiki Me 的 Agent realm allowlist，不要写成“完整支持当前 App”。

## 7. Security 与 License

README 需要稳定链接：

- `SECURITY.md`；
- `CONTRIBUTING.md`；
- `LICENSE`；
- private vulnerability reporting/contact。

当前提案中的安全联系渠道仍需组织负责人填写。

## 8. 下沉内容

旧 README 的以下内容转入专项文档：

- 全部环境变量；
- 完整 route/API table；
- JSON-RPC payload semantics；
- Read/Sync、Heartbeat、Group、Realtime、Attachment 细则；
- `rwiki.cn` 专属诊断；
- 测试文件清单；
- 临时服务器安装问题。

首页保留采用所需摘要与入口。
