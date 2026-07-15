# 开始使用 AWiki Open Server

[English](getting-started.md) | [简体中文](getting-started.zh-CN.md)

## 1. 目标

完成本文后，你应该能够：

- 启动一个完全本地的 Community Server；
- 访问 health endpoint；
- 运行 ASGI 或 HTTP smoke；
- 理解数据目录和开发开关；
- 决定下一步是连接 CLI、连接 App，还是部署到公开域名。

## 2. 环境

- Python 3.10+；
- venv/pip；
- 本地端口；
- 开发测试需要 `httpx`、`pytest` 和 `pytest-asyncio`（包含在 `.[dev]`）。

```bash
python3 --version
```

如果系统 Python 较旧，使用显式解释器，例如 `python3.11`。

## 3. 安装

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e '.[dev]'
```

当前依赖固定 ANP Python SDK `anp==0.8.8`。Adapter 会在加载到其他版本时 fail fast。

如本地环境暂时无法正确安装 ANP package，仓库开发验证可以显式使用 sibling SDK checkout：

```bash
PYTHONPATH=../anp/anp:src \
.venv/bin/python -m pytest tests -q
```

这只适用于受控开发环境，不应成为公共部署默认方案。

## 4. 启动

```bash
PYTHONPATH=src \
AWIKI_DATA_DIR=.awiki-open-server \
AWIKI_PUBLIC_BASE_URL=http://127.0.0.1:8765 \
AWIKI_DID_DOMAIN=localhost \
.venv/bin/python -m uvicorn 'awiki_open_server.app.main:create_app' \
  --factory --host 127.0.0.1 --port 8765
```

本地数据将写入 `.awiki-open-server/`，不要提交该目录。

## 5. 健康检查

```bash
curl --noproxy '*' http://127.0.0.1:8765/healthz
```

```json
{"status":"ok","edition":"community"}
```

`--noproxy '*'` 避免本地请求被开发机代理转发。

## 6. 第一次成功

### 6.1 ASGI smoke

不启动 Uvicorn 即可验证核心本地流程：

```bash
PYTHONPATH=src \
.venv/bin/python scripts/awiki_open_cli.py smoke-asgi \
  --data-dir /tmp/awiki-open-server-cli-asgi
```

### 6.2 本地 HTTP smoke

服务运行时：

```bash
PYTHONPATH=src \
.venv/bin/python scripts/awiki_open_cli.py smoke-local \
  --base-url http://127.0.0.1:8765 \
  --did-domain localhost
```

### 6.3 本地跨域 smoke

启动两个独立服务，验证 DID discovery、origin proof、service HTTP Signature 与双向 Inbox：

```bash
PYTHONPATH=src \
.venv/bin/python scripts/awiki_open_cli.py smoke-cross-domain-local \
  --data-root /tmp/awiki-open-server-cross-domain-local \
  --clean
```

此检查使用 loopback resolver map，只是本地协议 Gate，不替代真实公网互通。

## 7. 运行测试

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests -q
```

重点区域：

- ANP SDK 与签名；
- route/path 配置；
- User Service compatibility；
- Direct/Group/Attachment；
- Sync/Read State；
- 受保护的 public deployment system tests。

## 8. 连接 awiki-cli

使用独立 CLI workspace，避免污染日常身份：

```bash
export AWIKI_CLI_WORKSPACE_HOME_DIR=/tmp/awiki-cli-open-server-workspace

awiki-cli tenant setup local-community \
  --backend-base-url http://127.0.0.1:8765 \
  --did-host localhost

awiki-cli init
```

当前 Rust CLI 注册命令可能仍要求 `--phone` 或 `--email` 以保留命令形状；Open Server 默认不会发送真实 SMS/Email，也不会持久化生产联系验证状态。

仓库内重复 Gate：

```bash
PYTHONPATH=src \
.venv/bin/python scripts/awiki_open_cli.py smoke-rust-cli-local \
  --awiki-cli-bin /path/to/awiki-cli \
  --data-root /tmp/awiki-open-server-rust-cli-local \
  --clean
```

## 9. 重要开发开关

仅本地测试可能使用：

```text
AWIKI_ALLOW_UNSIGNED_PEER_DEV=true
AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=true
```

这些开关不能用于公网。真实部署必须保持 `false`。

## 10. 下一步

- 连接客户端：[客户端兼容性](client-compatibility.zh-CN.md)
- 部署公开域名：[公开部署](deployment.zh-CN.md)
- 配置全部变量：[配置参考](configuration.zh-CN.md)
- 验证跨域 ANP：[ANP 互通](anp-interop.zh-CN.md)
- 设计备份升级：[数据、备份与运维](operations.zh-CN.md)
