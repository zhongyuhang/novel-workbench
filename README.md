# AI Novel Writer

个人长篇小说创作与管理工作台。第一版面向单人使用，部署在个人服务器或局域网，提供小说/卷/章节管理、三栏编辑工作台、兼容 OpenAI 格式的模型接入、候选生成审阅、版本管理、结构化设定与章节记忆。

## 文档导航

- [01 产品需求与范围](docs/01-product-requirements.md)
- [02 系统架构与工程约束](docs/02-architecture.md)
- [03 数据库设计](docs/03-database-design.md)
- [04 API 规范](docs/04-api-specification.md)
- [05 AI 记忆与上下文引擎](docs/05-ai-memory-system.md)
- [06 模型接入规范](docs/06-model-integration.md)
- [07 开发流程与代码规范](docs/07-development-guide.md)
- [08 测试与验收](docs/08-testing-guide.md)
- [09 部署、备份与恢复](docs/09-deployment-guide.md)
- [10 分阶段实施任务](docs/10-implementation-plan.md)
- [ADR](docs/adr/)

## 技术基线

- 前端：React + TypeScript + Vite
- 编辑器：Tiptap；正文权威格式为 Tiptap JSON（`tiptap_json`，version 1），见 ADR-001
- 后端：Python + FastAPI
- ORM / Migration：SQLAlchemy 2.x + Alembic
- 数据库：SQLite 起步，单写入者设计；需要高并发写入或多用户后再评估 PostgreSQL
- 测试：pytest；前端当前以 TypeScript 严格检查和构建为门槛
- 部署：Docker Compose 可选；单容器/单进程起步，持久化数据挂载到宿主机

## 项目状态规则

本仓库文档是目标规范，不代表所有功能已经实现。每个实施阶段都必须提交代码、测试、运行说明和验收记录；未实现的功能不得在 README 中标注为已完成。

## 当前实现（M1）

已实现：

- 前后端工程骨架、`GET /api/v1/health`、OpenAPI（`/docs`、`/openapi.json`）
- Alembic：`0001_initial` 基线，`0002_catalog` 创建 `novels`、`volumes`、`chapters`
- 作品、卷、章节的列表、创建、读取、更新和删除。作品与章节删除是软删除；删除卷时章节改为未分卷
- 卷重排，章节移动和复制
- 章节正文以 Tiptap JSON（`tiptap_json`，version 1）保存。`PUT /api/v1/chapters/{id}` 必须带客户端看到的 `revision`；不一致时返回 `409`，不会覆盖已保存正文
- 作品库页面，以及三栏工作台骨架：左侧目录、中间正文文本与 JSON、右侧写作辅助占位
- 单用户会话。开发环境和测试环境在未配置访问口令时可以用空口令换取令牌；配置了 `APP_ACCESS_PASSWORD` 后必须口令正确

尚未实现，不能当作可用功能：

- Tiptap 富文本编辑器、自动保存、版本快照和恢复、导出
- 模型配置、AI 生成、SSE 任务执行
- 记忆系统
- 局域网部署和备份恢复

## 环境要求

- Python 3.12 或更新的 3.12 兼容版本
- Node.js 22 LTS
- npm 10 或更新版本

不需要 Docker，也不需要模型 API Key 才能启动本地页面和健康检查。

## 本地开发

```bash
# backend
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# frontend
cd frontend
npm ci
npm run dev
```

前端开发服务器监听 `http://127.0.0.1:43117`，并把 `/api` 代理到 `http://127.0.0.1:8000`。后端 OpenAPI 在 `http://127.0.0.1:8000/docs`。

数据库文件默认写到仓库的 `data/ai_novel_writer.db`（已加入 `.gitignore`）。变量说明见 `backend/.env.example`。

开发环境可以不配置 `APP_ACCESS_PASSWORD`。这时作品库会自动申请本机会话，不需要模型 API Key。若 `APP_AUTH_SECRET` 仍是占位值，开发环境会在 `data/dev-auth-secret` 写入一把本机签名密钥。配置了 `APP_ACCESS_PASSWORD` 后，页面会要求口令。生产环境拒绝占位的认证密钥、加密密钥、访问口令，也拒绝 `CORS_ORIGINS=*`。模型密钥加密仍要等配置了 `APP_SECRET_ENCRYPTION_KEY` 才能使用，这一阶段还没有模型配置接口。

## 检查

```bash
./scripts/check.sh
```

脚本会安装后端依赖、执行迁移、运行 Ruff、mypy 和 pytest，然后构建并检查前端。`backend/requirements.lock` 记录了本次验证时解析到的依赖版本；日常安装仍使用上面的 `pip install -e ".[dev]"`。
