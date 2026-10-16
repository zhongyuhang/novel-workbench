# ADR-004：局域网认证

## 状态
已采纳（M0）

## 决策
单用户 **会话/Token 认证**（口令哈希存于服务端配置或数据库；`APP_AUTH_SECRET` 签发会话）。

开发默认绑定 127.0.0.1；局域网部署必须开启认证。

## 实现说明（M6）

- 口令以 PBKDF2-HMAC-SHA256 哈希校验。生产环境设置 `APP_ACCESS_PASSWORD_HASH`（`python -m app.cli.hash_password` 生成）。若只设置了 `APP_ACCESS_PASSWORD`，进程在内存中哈希后再比较，不把明文写进数据库。
- 两者同时设置时，以哈希为准。
- `APP_ENV=production`，或 `APP_HOST` 不是 `127.0.0.1` / `localhost` / `::1` 时，必须配置非占位的 `APP_AUTH_SECRET`（至少 32 字符）和口令或口令哈希。生产环境另外拒绝弱口令、过低的哈希迭代次数、占位加密密钥、`CORS_ORIGINS=*` 和 `ALLOWED_HOSTS=*`。
- 只绑定 127.0.0.1 的开发和测试环境可以不设置口令。此时页面用空口令换取本机会话。
- 作品、章节、模型、记忆、质量和备份接口未带有效 Bearer 令牌时返回 401。`GET /api/v1/health` 保持公开。
- 示例口令不作为生产默认值。占位符和空口令在生产环境会拒绝启动。
