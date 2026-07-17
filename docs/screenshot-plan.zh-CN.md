# AWiki Open Server README 素材计划

[English](screenshot-plan.md) | [简体中文](screenshot-plan.zh-CN.md)

服务端项目以“真实运行证据”和“边界清晰”为主，不需要伪造管理后台截图。

## 1. Hero GIF：本地社区 Smoke

- 文件：`open-server-local-smoke.gif`；
- 时长：25–40 秒；
- 推荐尺寸：1400×800；
- 流程：启动 Uvicorn → `healthz` → `smoke-local` → 成功摘要；
- 使用 `localhost` 和临时数据目录；
- 不显示本机用户名、真实路径、token 或内部域名。

## 2. 两域互通终端图

- 文件：`open-server-cross-domain-smoke.png` 或 GIF；
- 展示：`smoke-cross-domain-local` 的两服务、DID discovery、双向 Inbox 成功摘要；
- 不展示 service private key 或完整签名 header；
- 适合放在 ANP 互通文档，不一定放主 README。

## 3. 架构图

README 使用 Mermaid 作为事实源。Social Preview 可导出简化图：

- 文件：`open-server-architecture.png`；
- 元素：Clients → FastAPI → SQLite/Object Files → Remote ANP Domain；
- 明确标注 `single process`、`no E2EE`；
- 不绘制所有 compatibility route。

## 4. Public Verify 结果（可选）

- 文件：`open-server-public-verify.png`；
- 展示：DID Document、最小 health、capability、已启用的 Direct/Group DID-discovery 模式与 relay/E2EE 禁用检查；
- 使用专门 demo 域或公开测试域；
- 不展示真实 token、recipient 或私有服务器路径。

## 5. Social Preview

- 文件：`open-server-social-preview.png`；
- 尺寸：1280×640；
- 文案：`Self-hosted AWiki Community Server`；
- 副标：`DID identity · Messaging · Attachments · ANP interop`；
- 角落明确 `v0.1 MVP / No E2EE`，避免误导。

## 6. 拍摄检查

- [ ] 使用当前 main commit；
- [ ] 全部数据目录为临时 demo；
- [ ] 无 private key、token、OTP、内部 IP；
- [ ] 不把 dev bypass 设为公网示例；
- [ ] 输出字号可读；
- [ ] 结果不是只通过 health 而未验证业务流程；
- [ ] Alt text 描述实际验证内容。
