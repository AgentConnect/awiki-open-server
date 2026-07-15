# 参与贡献 AWiki Open Server

[English](CONTRIBUTING.md) | [简体中文](CONTRIBUTING.zh-CN.md)

感谢你帮助改进 AWiki Open Server。项目目标是保持一个可读、自包含、边界清晰的 Community Server MVP；贡献不应把它悄悄变成 AWiki 托管服务代理或无边界的 compatibility layer。

## 开始之前

- 搜索现有 Issue/PR；
- API、身份、签名、数据库 schema、同步、附件或公网部署变化先开 Issue；
- 明确变更属于 MVP 核心、compatibility、ANP interop 还是开发工具；
- 不把 `awiki.info`、User Service 或 Message Service 变成本服务的隐藏依赖；
- 不在同一 PR 混入无关 route、格式化和部署环境修改。

## 环境

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e '.[dev]'
```

## 测试

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests -q
```

按变化补充：

```bash
PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-asgi \
  --data-dir /tmp/awiki-open-server-asgi

PYTHONPATH=src .venv/bin/python scripts/awiki_open_cli.py smoke-cross-domain-local \
  --data-root /tmp/awiki-open-server-cross-domain --clean
```

公网变化需要 `verify-public` 和受保护 system tests。客户端 compatibility 变化需要对应 CLI/App smoke。

## 架构规则

- `protocol/anp_adapter.py` 是 ANP Python SDK adapter 的集中边界；
- service identity/signature 逻辑保持集中；
- 新 domain logic 应进入明确 domain package，不继续堆入单体 facade；
- local compatibility route 必须本地实现，不静默代理托管服务；
- public `/anp-im/rpc` 只暴露明确方法；
- realtime hint 不是 durable checkpoint；
- SQLite 与对象存储语义必须保持一致。

## 安全规则

禁止提交：

- `.awiki-open-server/`；
- SQLite 与对象文件；
- `.env`；
- access/refresh token；
- service private key；
- real origin proof、HTTP Signature 或用户消息；
- 公网服务器私有路径和凭据。

公网默认必须保持：

```text
AWIKI_ALLOW_UNSIGNED_PEER_DEV=false
AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false
```

无 E2EE 是当前明确边界，不能用文案或兼容 shim 掩盖。

安全问题请按 [SECURITY.md](SECURITY.zh-CN.md) 私下报告。

## PR 描述

请说明：

```text
User/deployer problem
Affected API or data model
Local vs public surface
Security/interop impact
Backward compatibility
Tests and smoke run
Deployment/backup implications
Known limitations
```
