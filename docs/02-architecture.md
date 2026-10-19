# 02 系统架构与工程约束

## 1. 逻辑架构

```text
Browser
  └── React + TypeScript
      ├── Novel Library
      ├── Three-column Workspace
      ├── Editor / Outline / Memory panels
      └── API client + SSE client
              │ HTTP / SSE
              ▼
FastAPI
  ├── API routers (validation only)
  ├── Application services (use cases)
  ├── Repositories (database access)
  ├── AI subsystem
  │   ├── Provider adapter
  │   ├── Prompt builder
  │   ├── Context builder
  │   └── Usage / task tracking
  └── SQLAlchemy + Alembic
              │
              ▼
SQLite + persistent data directory
```

## 2. 推荐技术栈

- Python：使用当前受支持的稳定版本；版本写入项目配置和 Docker 镜像。
- FastAPI + Pydantic：HTTP API 与输入输出校验。
- SQLAlchemy 2.x + Alembic：数据访问和迁移。
- React + TypeScript + Vite：前端工程。
- 编辑器：Tiptap 或同类成熟方案。必须在 ADR 中明确正文 canonical format。
- SQLite：个人使用 MVP。
- Docker Compose：可选部署包装；本地开发必须也能不依赖 Docker 启动。

## 3. 代码分层约束

- `api/`：路由、认证依赖、请求校验、响应编码；禁止放复杂业务流程。
- `services/`：业务用例与事务边界。
- `repositories/`：数据库读写；禁止让前端直接依赖 ORM 字段。
- `models/`：SQLAlchemy 数据库模型。
- `schemas/`：Pydantic 请求/响应模型。
- `ai/`：模型适配、提示词、上下文、用量统计。
- `tests/`：单元、集成、端到端测试。

禁止：
- 把所有逻辑写进 `main.py`。
- 在 API router 中直接调用模型 SDK 并修改章节正文。
- 在前端硬编码 API Key。
- 把模型供应商特有参数散落在业务代码中。
- 将 AI 输出直接写入正式正文或正式记忆。
- 以全局变量保存用户项目状态。
- 用无约束 `except Exception: pass` 吞掉错误。

## 4. 正文数据格式决策

在 M1 结束前必须记录 ADR，决定正文的唯一权威格式：
- 方案 A：纯 Markdown / 纯文本，简单、易迁移，但复杂格式能力有限。
- 方案 B：Tiptap JSON 文档，编辑体验更好，但导出、迁移和 AI 选区映射需要专门实现。

无论选择哪一种：
- 数据库中只能有一个权威正文来源。
- HTML 仅可作为渲染结果，不得成为未验证的可信输入。
- Markdown/TXT 导出必须可测试。
- 正文格式版本需要可识别，未来升级有迁移路径。
- 不能同时维护互不一致的 `content_html`、`content_markdown` 和 `content_json` 三份正文。

## 5. AI 任务生命周期

`queued -> running -> completed | failed | cancelled`

- 每个任务有唯一 ID。
- 每次生成记录输入快照或可复现的上下文引用。
- 前端断开连接不应导致数据库状态不确定。
- 取消请求要尽力中止底层生成；无法中止时，也必须将用户任务标为 cancelled 并丢弃迟到结果。
- 生成成功只表示候选结果已生成，不表示正文已采纳。
- 任务状态转移必须校验，终态不可被迟到事件覆盖。

## 6. 局域网部署原则

- 开发服务器默认绑定 `127.0.0.1`。
- 局域网部署时通过明确配置绑定 `0.0.0.0`，并开启认证。
- 仅开放必要端口；不默认暴露数据库文件、管理接口或调试端点。
- CORS 允许来源必须显式配置，不使用生产环境 `*`。
- 若未来开放公网，应增加 HTTPS、强认证、速率限制和安全更新流程。
- 单人使用不等于不需要认证：任何可访问局域网的人都可能读取小说和调用 API Key。

## 7. 数据库选择与升级

SQLite 是 MVP 默认选项，但需要：
- 事务边界明确。
- 配置合理的 busy timeout。
- 处理并发写入冲突并给用户可理解的提示。
- 不将 SQLite 数据库文件放在不可靠的网络共享盘上。
- 备份前保证数据一致性。
- 需要多个用户高并发写入、多个后端实例或复杂权限时，评估迁移 PostgreSQL。

## 8. 决策记录 ADR

至少记录：
- ADR-001：正文 canonical format。
- ADR-002：SQLite 和迁移触发条件。
- ADR-003：AI 任务使用同步流式还是后台任务。
- ADR-004：局域网认证方案。
- ADR-005：模型配置密钥加密/存储方案。
- ADR-006 到 ADR-009：大纲、上下文编译、小说圣经、质量修复。
- ADR-010：采纳事务、保存冲突、任务回查和版本来源。
- ADR-011：作品包导入导出。权威正文仍是包内的 Tiptap JSON；Markdown/TXT 导出保持只读投影。
