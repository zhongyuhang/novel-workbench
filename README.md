# AI Novel Writer

个人长篇小说创作工作台：浏览器里写作，作者做决定，AI 辅助生成和整理。

## 核心功能

- 作品、卷、章节；正文自动保存、版本和导出
- 大纲、故事线、卷大纲、人物、世界观、编年史和伏笔
- 续写、润色、改写、扩写；大纲候选确认后才写入草稿
- 从正文提取资料候选，并做一致性检查
- 模型配置：增删改、测试、默认模型、按任务切换
- 单用户登录、密钥加密、整库备份与恢复

## 快速启动

### Docker

```bash
cp .env.example .env
cd backend && python -m app.cli.hash_password
mkdir -p data && chmod 700 data
docker compose --env-file .env -f deploy/compose.yaml up --build -d
```

浏览器打开 `http://<主机>:8080`。

### 本地开发

```bash
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" && cp .env.example .env && alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```bash
cd frontend && npm ci && npm run dev
```

页面在 `http://127.0.0.1:43117`。检查：`./scripts/check.sh`。

## 必需环境变量

| 变量 | 作用 |
|---|---|
| `APP_ENV` | `development` 或 `production` |
| `APP_AUTH_SECRET` | 会话签名，至少 32 位随机串 |
| `APP_ACCESS_PASSWORD_HASH` | 访问口令哈希。本机开发可留空 |
| `APP_SECRET_ENCRYPTION_KEY` | Fernet 主密钥。缺失则拒绝启动，不把 API Key 存成明文。必须单独备份，丢失后模型密文无法解密 |
| `DATA_DIR` / `DATABASE_URL` | 数据目录和 SQLite |
| `ALLOWED_HOSTS` / `CORS_ORIGINS` | 生产必填，不能用 `*` |
| `MODEL_BASE_URL_ALLOWLIST` | 可选。允许访问的内网模型主机，逗号分隔 |

生成密钥和口令哈希、Compose 与恢复步骤见 [部署文档](docs/09-deployment-guide.md)。

## 文档

- [产品需求](docs/01-product-requirements.md)
- [架构](docs/02-architecture.md)
- [数据库](docs/03-database-design.md)
- [API](docs/04-api-specification.md)
- [记忆与上下文](docs/05-ai-memory-system.md)
- [模型接入](docs/06-model-integration.md)
- [开发](docs/07-development-guide.md)
- [测试](docs/08-testing-guide.md)
- [部署、备份与恢复](docs/09-deployment-guide.md)
- [实施记录](docs/10-implementation-plan.md)
- [差距分析](docs/11-evolution-gap-analysis.md)
- [模型配置中心](docs/12-model-config-center.md)
- [正文与资料同步](docs/13-manuscript-material-sync.md)
- [release 1.0.0 方案](docs/release-1.0.0-plan.md)
- [决策记录](docs/adr/)
