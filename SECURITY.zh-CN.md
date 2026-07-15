# AWiki Open Server Security Policy

[English](SECURITY.md) | [简体中文](SECURITY.zh-CN.md)

## 当前安全定位

AWiki Open Server 是单节点 Community Server MVP，不提供 Direct 或 Group E2EE。服务器能够处理并持久化消息 payload，因此不适合未经额外保护的高敏感通信。

## 报告漏洞

不要在公开 Issue、README 评论、消息或公共互通测试中披露未修复漏洞、service key、token、用户消息或可利用步骤。

<!-- TODO(security-contact): 启用 GitHub Private Vulnerability Reporting，或填写组织正式安全邮箱/表单。 -->

报告建议包含：

- 受影响 commit/version；
- 部署模式和配置（秘密需脱敏）；
- 最小复现；
- 影响范围；
- 是否涉及身份、消息、附件、签名或 token；
- 建议缓解方式。

## 高风险资产

- Service Ed25519 private key；
- access/refresh token；
- WebSocket ticket；
- attachment upload token/download ticket；
- origin proof 与 HTTP Signature 上下文；
- SQLite 中的身份、消息和关系数据；
- committed object files；
- `.env` 和公网路由配置。

这些资产不得进入 Git、公开日志、截图、Issue 或测试 fixture。

## 公网强制配置

```text
AWIKI_ALLOW_UNSIGNED_PEER_DEV=false
AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false
```

优先使用：

```text
AWIKI_SERVICE_PRIVATE_KEY_PATH=/secure/path/service-ed25519.pem
```

而不是内联 private key 环境变量。

## 认证与签名

- 上传 DID Document 默认需要有效 proof；
- verification method 必须属于 DID 并被正确授权；
- public Direct/Group Join 需要业务 origin proof 与服务间 HTTP Signature；
- Contact Verification shim 不是生产身份提供方；
- revoke 后相关 token、DID verify、WebSocket 和 active DID route 必须失效。

## 数据保护

- 备份 SQLite 与对象文件时保持一致性；
- 备份 service key 使用独立加密和访问控制；
- 日志默认不记录完整 message body、token 或签名材料；
- Attachment MIME/size/digest 必须验证；
- Single-process realtime 不提供 HA 安全保证；
- 公开部署需要 TLS、最小权限和反向代理边界。

## 不受支持的安全假设

当前版本不能保证：

- 消息对服务器不可见；
- 多节点一致性或 failover；
- 生产短信/邮件身份验证；
- 完整 federation trust management；
- remote object E2EE/relay；
- 完整 Group policy/admin；
- 自动安全升级或在线 migration。

采用者必须根据这些边界评估风险。
