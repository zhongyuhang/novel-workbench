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
- 测试：pytest；前端 Vitest、TypeScript 严格检查、构建和 oxlint
- 部署：Docker Compose 可选；单容器/单进程起步，持久化数据挂载到宿主机

## 项目状态规则

本仓库文档是目标规范，不代表所有功能已经实现。每个实施阶段都必须提交代码、测试、运行说明和验收记录；未实现的功能不得在 README 中标注为已完成。

## 当前实现（M5）

已实现：

- 前后端工程骨架、`GET /api/v1/health`、OpenAPI（`/docs`、`/openapi.json`）
- Alembic：`0001_initial` 基线，`0002_catalog` 创建 `novels`、`volumes`、`chapters`，`0003_chapter_versions` 创建版本快照表，`0004_ai` 创建 `model_configs` 与 `ai_tasks`，`0005_memory` 创建 `story_entities`、`entity_states`、`story_events`、`chapter_summaries`、`memory_change_proposals`
- 作品、卷、章节的列表、创建、读取、更新和删除。作品与章节删除是软删除；删除卷时章节改为未分卷
- 卷重排，章节移动和复制
- 章节正文的权威格式是 Tiptap JSON（`content_format=tiptap_json`，`content_format_version=1`）。工作台中间栏用 Tiptap 编辑，保存时只写这一份 JSON
- 手动保存和停笔后的防抖自动保存。编辑器显示未保存、保存中、已保存或失败。自动保存失败时正文留在编辑器里，可以重试。切换章节、返回作品库或关闭页面前，未保存修改会先确认
- `PUT /api/v1/chapters/{id}` 必须带客户端看到的 `revision`。不一致时返回 `409`，不会覆盖已保存正文，也不会写入被拒绝的那一版快照。`save_kind=autosave` 只更新当前正文；`save_kind=manual` 在正文相对上一份快照有变化时写入 `chapter_versions`
- `GET /api/v1/chapters/{id}/versions` 列出版本。`POST /api/v1/chapters/{id}/restore` 在确认后把所选快照写成新修订，旧版本保留
- `POST /api/v1/novels/{id}/export` 导出 Markdown 或 TXT。顺序与目录一致：先未分卷，再按卷的 `sort_order`，卷内按章节 `sort_order`。导出包含标题、简介、卷名、章节标题和正文
- 模型设置：添加、修改、测试和删除 OpenAI 兼容配置。API Key 用 `APP_SECRET_ENCRYPTION_KEY` 加密后写入 `secret_ref`。接口只返回是否已配置和脱敏尾号
- AI 任务：续写、改写、润色、扩写、缩写、校对。`POST /api/v1/ai/tasks` 创建任务，`GET /api/v1/ai/tasks/{id}/events` 用 SSE 推送 `task.started`、`token`、`task.completed`、`task.failed`、`task.cancelled` 和 `heartbeat`。可以取消。完成只表示候选就绪。创建任务时会按当前作品组装上下文：硬规则、当前章节约束、相邻章节、已确认设定，以及在预算内的摘要。检索只用名称匹配、LIKE 和相邻章节，不使用向量库，也不会读到其他作品的设定
- 采纳候选会按当前修订号做乐观锁更新正文，并写入 `change_source=ai_accepted` 的版本。修订号不一致返回 `409`，不覆盖。放弃候选不改正文
- 没有可用的外部模型时，右侧「续写」会提示去模型设置，不会假装已经生成。可以单独使用模拟模型，界面会标明「模拟输出」
- 设定与记忆：可以按作品列出、新建和修改实体。`POST /api/v1/chapters/{id}/analyze` 针对提交的修订号做分析，只写入提案。没有外部模型时用模拟分析，界面标明「模拟分析」。每条提案带有来源章节、来源修订、证据原文和 certainty。没有证据或证据不在原文中的条目会标成不确定，不会自动变成正式设定
- 接受提案会在一个事务里更新正式设定、状态、事件或摘要，并保留章节和修订来源。拒绝提案不改正式设定。已接受的提案可以撤回。章节修订变化后，旧修订上的当前摘要和待审核提案会变成 `stale`，需要重新分析或由人确认后才接受
- 工作台右侧有「生成」「设定」和「质量」。目录里可以对章节点「分析记忆」。设定页列出实体、过期摘要和提案，接受或拒绝都是明确操作
- 伏笔：按作品列出、新建和修改。状态可以是 `open`、`planned`、`resolved`、`abandoned`、`uncertain`。一本作品的伏笔不会出现在另一本里。回收章节必须属于同一本作品
- 冲突提示：`POST /api/v1/chapters/{id}/conflict-check` 只返回疑似冲突，包含类型、正文片段、已确认事实、来源章节和引用、严重程度、置信度、建议的人工处理。没有外部模型时走本地规则，不访问网络。人物状态变化本身不会被当成矛盾。检查不会改正文，也不会改正式记忆
- 选区改写：在正文里选中文字后，用现有 AI 任务的 `rewrite` 和 `selection_text` 生成候选。带选区时提示词版本是 `rewrite_selection_v1`。候选要比较后再采纳或放弃。采纳使用 `replace_selection`，修订号不一致返回 `409`
- 字数统计：`GET /api/v1/novels/{id}/stats` 用正文的字数函数统计每章和全书。可以另存一个全本目标字数，目标不会改写正文
- 评测样例：`backend/tests/fixtures/eval/samples.json` 固定了续写、选区改写和摘要三条虚构短句，由模拟模型重复跑，不访问网络
- 作品库页面和三栏工作台。模型设置在 `#/settings`
- 单用户会话。开发环境和测试环境在未配置访问口令时可以用空口令换取令牌；配置了 `APP_ACCESS_PASSWORD` 后必须口令正确

尚未实现，不能当作可用功能：

- 局域网部署、认证加固和备份恢复（M6）

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

开发环境可以不配置 `APP_ACCESS_PASSWORD`。这时作品库会自动申请本机会话，不需要模型 API Key。若 `APP_AUTH_SECRET` 仍是占位值，开发环境会在 `data/dev-auth-secret` 写入一把本机签名密钥。配置了 `APP_ACCESS_PASSWORD` 后，页面会要求口令。生产环境拒绝占位的认证密钥、加密密钥、访问口令，也拒绝 `CORS_ORIGINS=*`。保存真实模型 API Key 前，要把 `APP_SECRET_ENCRYPTION_KEY` 设成 Fernet 密钥。没有外部模型时，工作台仍可打开，也可以显式使用模拟模型。

## 检查

```bash
./scripts/check.sh
```

脚本会安装后端依赖、执行迁移、运行 Ruff、mypy 和 pytest，然后运行前端测试、构建和 oxlint。`backend/requirements.lock` 记录了本次验证时解析到的依赖版本；日常安装仍使用上面的 `pip install -e ".[dev]"`。
