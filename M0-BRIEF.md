# M0 实施简报

仓库名：`ai-novel-writer`

本次只做 **M0：项目初始化与决策**，不要实现 M1+ 业务 CRUD。

## 必须交付
1. 完整 `docs/`（已附带源文件，复制进仓库并保持一致）。
2. `docs/adr/` 五份 ADR（已附带草案，可微调措辞但不要改结论，除非发现硬性冲突）。
3. 后端 FastAPI 骨架：`backend/`，分层目录 `api/services/repositories/models/schemas/ai/core/db`，健康检查 `GET /api/v1/health`，Alembic 已配置（可先有空/最小初始 migration），`.env.example`。
4. 前端 React+TS+Vite 骨架：`frontend/`，可打开的启动页/占位作品管理页，**不需要 API Key**。
5. 根 README 含环境要求与启动命令（按 docs 规范）。
6. `.gitignore` 排除 `data/`、`.env`、venv、node_modules、数据库、日志。
7. 基础测试：至少一个后端 health 测试；前端 `tsc`/build 可通过。
8. 统一检查脚本或最小 CI（如 `scripts/check.sh`）。
9. OpenAPI：FastAPI 自动生成可用。

## 明确不做（本阶段）
- novels/chapters 真实 CRUD（那是 M1）
- 编辑器完整能力、AI 生成、记忆系统、部署 Compose 完整生产方案

## 验收命令（完成后必须真实运行并报告输出）
```bash
# backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
pytest -q
uvicorn app.main:app --host 127.0.0.1 --port 8000  # 短暂启动验证 /api/v1/health

# frontend
cd frontend && npm ci && npm run build
```

## 交付报告格式
阶段 / 完成任务 / 代码变更 / 数据库迁移 / 测试命令与真实结果 / 未完成项 / 已知问题 / 下一阶段建议
