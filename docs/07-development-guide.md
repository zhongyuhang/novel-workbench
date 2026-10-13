# 07 开发流程与代码规范

## 1. 推荐仓库结构

```text
ai-novel-writer/
  README.md
  docs/
  backend/
    pyproject.toml
    alembic.ini
    alembic/
    app/
      main.py
      core/
      db/
      models/
      schemas/
      api/
      services/
      repositories/
      ai/
    tests/
  frontend/
    package.json
    src/
      api/
      components/
      pages/
      features/
      editor/
      stores/
    tests/
  deploy/
    compose.yaml
    Caddyfile.example
  data/                 # 本地运行数据；加入 .gitignore
```

## 2. 开发环境

- Python 版本固定在项目配置中。
- Node.js 使用受支持的 LTS 版本。
- Python 依赖通过 `pyproject.toml` 管理并锁定。
- 前端依赖提交 lockfile。
- `.env.example` 提供变量名和示例，不放真实密钥。
- `data/`、数据库、日志、导出和用户小说文件默认加入 `.gitignore`。

## 3. 后端编码约束

- 使用类型注解。
- Pydantic schema 与 SQLAlchemy model 分离。
- 所有写操作明确事务边界。
- 服务层返回明确的领域结果或抛出可映射异常。
- 使用结构化日志并附 request_id / task_id。
- 所有数据库变更走 Alembic。
- 重要状态机有单元测试。
- 不使用隐式全局 Session。
- 不把模型调用放进数据库事务中长时间占锁。

## 4. 前端编码约束

- TypeScript 开启严格模式。
- API 调用集中管理。
- 三栏布局窄屏允许折叠侧栏。
- 编辑器维护 dirty state、保存状态、当前 revision。
- 自动保存必须防抖并处理失败。
- 切换章节前检查未保存变更。
- AI 候选结果和正式正文使用不同状态。

## 5. Git 约定

- `main`：始终可运行。
- `feat/<name>`：功能分支。
- `fix/<name>`：缺陷修复。

## 6. Definition of Done

1. 需求可映射到明确的验收标准。
2. 代码实现已提交。
3. 相关单元/集成测试通过。
4. 关键 UI 流程可手工或端到端验证。
5. 错误和边界情况已处理。
6. 文档与实际行为一致。
7. 无密钥、用户数据或调试产物误提交。
