# Step 01：部署 systemd 与 nginx

主计划：[../plan.md](../plan.md)

状态：done
branch：main
started：2026-07-05
completed：2026-07-05
commit：随本次部署记录提交
review evidence：nginx 配置、systemd 配置、服务环境、health/DID 文档已检查
verification evidence：`verify-public`、公网 pytest、Rust CLI rwiki.cn E2E、rwiki.cn -> awiki.info 通过，awiki.info -> rwiki.cn 阻塞
next action：如需完整双向互通，先同步 `awiki.info` 服务 DID 文档

## 目标

将 `awiki-open-server` 作为系统服务运行，并通过 nginx 发布到 `https://rwiki.cn`。

## 设计方法

沿用单进程 Uvicorn，监听 `127.0.0.1:8766`；nginx 负责 TLS 和公网路由。systemd 使用明确 `PYTHONPATH`，确保加载本仓和 ANP SDK 0.8.8。

## 实现方法

1. 备份现有 systemd、nginx、env 配置。
2. 更新 `awiki-open-server.service` 的 `PYTHONPATH`。
3. 用 `deploy/nginx-rwiki.cn.conf.example` 对齐 nginx 路由，保留证书路径。
4. `systemctl daemon-reload`、`nginx -t`、重启服务、reload nginx。
5. 跑公网与 CLI 验证。

## 路径

- `awiki-open-server/deploy/nginx-rwiki.cn.conf.example`
- `awiki-open-server/deploy/awiki-open-server.service.example`
- host `awiki-open-server.service`
- host nginx `rwiki.cn` server block
- host `awiki-open-server.env`

## 验证方式

- `systemctl is-enabled awiki-open-server.service`
- `systemctl is-active awiki-open-server.service`
- `curl https://rwiki.cn/healthz`
- `curl https://rwiki.cn/.well-known/did.json`
- `python3 awiki-open-server/scripts/awiki_open_cli.py verify-public --base-url https://rwiki.cn --did-domain rwiki.cn`
- `AWIKI_RUN_PUBLIC_SYSTEM_TESTS=1 python3 -m pytest awiki-open-server/tests/test_rwiki_cn_system.py -q`
- Rust CLI 注册和 direct send/inbox/history。

## Review 环节

检查 nginx 不代理到 `awiki.info` 或相邻服务；检查 systemd 开机自启；检查 ANP SDK 版本；检查 contact verification 禁用；检查双向互通失败是否属于本仓部署问题。
