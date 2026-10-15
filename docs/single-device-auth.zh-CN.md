# 单设备身份认证与续期

本文件描述当前工作区的单设备协议适配。它不表示已经发布或完成真实 CLI 公网验收；执行状态见工作区 `awiki-plan/20260917-open-server-protocol-upgrade/execution.md`。

## 身份边界

本地域仍只创建 WBA 身份。带 `deviceManifest` 的注册必须携带有效根签名，e1 指纹绑定根公钥，且恰好有一个有效设备。Manifest 的 type、闭合设备字段、签名/密钥协商引用和 verification relationships 使用固定 ANP SDK 校验。根键与设备签名键、密钥协商键的材料必须不同；null/非法 Manifest 不回落到 Legacy 注册。携带私钥材料的文档拒绝发布。

Python ANP 1.0.6 直接校验当前 P1/P2 v1 + Group Base v2，以及 SDK 允许读取的历史 Manifest。
adapter 先验证原始 Manifest 的依赖和引用，再为 SDK 的密钥角色 builder 构造单独的 canonical
设备描述：历史 all-v2 foundation 和旧 P6 + Group Base v1 仅在这个描述中映射。
当前 Group Base v2 不降为 v1，原始签名文档、设备声明和公开 profile 均保持不变。
接受公开设备密钥声明不启用 P5/P6 或任何加密消息服务。

`single_device_accounts` 每 DID 一行，持久化稳定 account ID、device ID、根键/设备签名键引用、公钥材料指纹和授权代次。没有设备注册表产品、新设备加入、Root Transfer 或 Recovery API。`update_document` 可以更新同一根/设备的普通文档字段，不能替换根或设备、增删 Manifest 或借旧 token 换设备。

## Access token

注册与续期签发 EdDSA JWT，采用现有 Core 的 `awiki.device.access.v1` claims：

- `iss=user-service`，audience 同时含 `awiki-user-service` 和 `awiki-message-service`；
- `sub/did` 是完整 DID，`user_id` 是稳定 account ID；
- 精确 `device_id/key_id/auth_generation`；
- 唯一设备采用 ready-admin scopes：`device:manage`、`device:read`、`message:connect`。scope 不是能力声明，范围外设备管理方法仍不支持；
- `iat/nbf/exp/jti`，其中 `nbf=iat`，jti 每次签发唯一。

服务端仍首先核对数据库中的当前 token 和有效期，再校验签名、claims 及当前文档/持久绑定；不会因为 token 外观像 JWT 就接受。旧 `alg=none` 设备 token 不继续作为有效设备凭据。token、签名 proof 和私钥不进入日志。

已配置 Service Ed25519 key 时复用该受保护材料；未配置时，在 `AWIKI_DATA_DIR/auth-token-key.pem` 原子创建权限 0600 的本地签名键，重启复用。禁止以符号链接或公开权限文件替代。备份/恢复必须包含实际使用的 token 签名材料；切换签名键会使旧 token 失效，客户端需签名续期。

## 签名续期

`POST /user-service/v1/did-auth/rpc` 的 `get_me` 接受已注册唯一设备的 RFC 9421 HTTP Signature。验证实际公共 URL、请求正文 Content-Digest、有效时间和 nonce；根签名或其他授权键不能换取设备 token。

nonce 摘要保存在本地 SQLite，按 key ID 隔离并有期限；原始 nonce 和完整 Signature 不存入日志/表。相同签名重放在应用重建后也被拒绝。有效期最多 600 秒，时钟偏差最多 30 秒。失败请求不得通过 Bearer→签名隐式回落绕过；合法 Bearer `get_me` 只读取用户信息，不顺带续期。

成功设备注册/续期返回 body `access_token`，并在 `Authorization: Bearer ...` 响应头返回相同值，设置 `Cache-Control: no-store`。注册与续期的 account/device/key/generation 保持一致。

canonical DID-auth 凭据失效返回 HTTP 401；根键冒充设备返回 HTTP 403。显式 sync v2 的凭据失效使用 HTTP 401 和 `anp.unauthorized`，消息为 `session_unauthorized`；普通成员权限拒绝不能当作凭据过期反复登录。旧 local v1 façade 保留原响应格式。

公开 DID 字符串在正式模式下不能作为 token。历史 unsigned-dev façade 只允许没有 Manifest/设备绑定的 Legacy 身份使用这一开发兼容方式，不能绕过设备授权。

## 旧数据与验证

新表为增量迁移，不改用户 DID、消息、群、已读或 sync installation。已有有效单设备文档但缺少新绑定的账号，必须通过当前设备签名续期才能建立绑定，不能从旧 token 字符串推断授权。非法旧 Manifest 不自动修补或授予权限；数据保留，具体修复属于逐账号迁移检查。

两端共享 `community-device-access-v1.json` 的公开 claim 模板；真实密钥在测试运行时生成。`tests/test_single_device_auth.py` 覆盖过期、应用重建、签名续期、持久 nonce、防篡改、generation fence、Manifest 负例和根/设备不可替换；`tests/test_community_sync_contract.py` 覆盖 sync v2 的认证错误 fixture。真实进程重启、正式 CLI 接入和公网验收按执行计划另行提供证据。

## release/0929 对齐安全检查（2026-10-13）

名称预检查是公开建议，不授予账号访问或占名；只返回本地名称的 active/inactive 分流，
不返回联系方式、邀请码或 token。限流使用 ASGI peer 的 SHA-256 摘要，忽略未经可信代理
处理的 `X-Forwarded-For`，每分钟最多 20 次且内存表有界。最终注册独立检查本地域和 ANP
名称格式，规范化名称后在 SQLite 事务中重新检查占用；预检查成功不绕过这些检查。
撤销或缺失文档的既有名称继续不可新建。测试见 `tests/test_registration_discovery.py`。

ANP 1.0.6 升级保留唯一设备、根键与设备键隔离、私钥材料禁止发布、签名验证与绑定 token
的边界。当前 mixed-profile 和历史只读 Manifest 的原始签名对象都由回归测试验证不被改写。
App `server-info` 不把本地 operator code 描述为手机号验证，不发布范围外托管能力。
CLI smoke 的验证材料通过 stdin 传递，输出前按实际材料脱敏，成功后移除对应本地 operator
code 文件。

release/1014 按 2026-10-15 用户要求撤销 2026-10-14 临时空流兼容。P5/P6 bootstrap 返回
`sync.lanes_not_supported`，delta 不接受相关游标，P6 delivery-context WebSocket 子协议
不接受；旧协商记录在服务重启后也不能重新启用。普通同步、Schema 3 Snapshot、唯一设备/
安装绑定及 token 校验保留。没有改变设备 Manifest 的原始签名或修改客户端源码。

历史上，在 `09d38fd` 临时兼容状态下，正式 CLI 1.0.58 的完整 listener/服务端重启门禁、真实 aWIKI ME 0.1.38+49
的注册及明文 Direct/Group 双向收发与 App 重启恢复、真实 MessageService 的 Direct 双向
及两个普通群 Host 方向均已验证。App 使用专用测试号码走免验证码注册；空手机号仍被
客户端本地校验拒绝。聚焦范围、初次失败与重试、制品和远端清理残留见
[客户端兼容性](client-compatibility.zh-CN.md)，这些记录不代表关闭 P5/P6 后的客户端接入或 App 全量功能通过。

业务 Origin Proof 保留 sender/target/profile/operation/body 的认证绑定，按 P1 Appendix A.3
排除 `trace_id` 和历史 `trace` 运维字段。这两个诊断字段不进入群操作幂等 digest 或 Receipt
payload digest；后者直接使用已成功验证的 Origin Proof `contentDigest`。
`tests/test_jsonrpc_binding.py`、`tests/test_direct_messages.py` 和 `tests/test_group_v2.py`
覆盖诊断字段不替代 sender、更换 hop trace 仍幂等、业务正文篡改被拒绝以及 Receipt digest
与业务 proof 一致；没有改变设备、token 或 peer HTTP Signature 的认证边界。
