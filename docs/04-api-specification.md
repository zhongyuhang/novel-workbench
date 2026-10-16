# 04 API 规范

## 1. 通用规范

- API 前缀：`/api/v1`。
- 请求和响应采用 JSON；AI 流式输出使用 SSE。
- 成功响应结构保持一致，错误返回稳定的 `code`、用户可理解的 `message` 和 `request_id`。
- 所有 ID 均为不透明字符串，客户端不得依赖 ID 格式。
- 所有写入接口都做输入校验。
- 需要认证的接口必须在路由层统一使用认证依赖。
- 长时间 AI 生成使用任务 ID；不要让一次 HTTP 请求无限等待。

建议错误格式：

```json
{
  "error": {
    "code": "REVISION_CONFLICT",
    "message": "章节已在其他操作中更新，请刷新并比较差异。",
    "request_id": "..."
  }
}
```

## 2. 资源接口

### Novels
- `GET /api/v1/novels`
- `POST /api/v1/novels`
- `GET /api/v1/novels/{novel_id}`
- `PATCH /api/v1/novels/{novel_id}`
- `DELETE /api/v1/novels/{novel_id}`（软删除）

### Volumes
- `GET /api/v1/novels/{novel_id}/volumes`
- `POST /api/v1/novels/{novel_id}/volumes`
- `PATCH /api/v1/volumes/{volume_id}`
- `DELETE /api/v1/volumes/{volume_id}`
- `POST /api/v1/volumes/reorder`

### Chapters
- `GET /api/v1/novels/{novel_id}/chapters`
- `POST /api/v1/novels/{novel_id}/chapters`
- `GET /api/v1/chapters/{chapter_id}`
- `PUT /api/v1/chapters/{chapter_id}`
- `POST /api/v1/chapters/{chapter_id}/duplicate`
- `POST /api/v1/chapters/{chapter_id}/move`
- `GET /api/v1/chapters/{chapter_id}/versions`
- `POST /api/v1/chapters/{chapter_id}/restore`

### AI
- `POST /api/v1/ai/tasks`
- `GET /api/v1/ai/tasks/{task_id}`
- `POST /api/v1/ai/tasks/{task_id}/cancel`
- `GET /api/v1/ai/tasks/{task_id}/events`（SSE）
- `POST /api/v1/ai/tasks/{task_id}/accept`
- `POST /api/v1/ai/tasks/{task_id}/reject`

采纳请求包含 `target_revision` 和 `apply_mode`（`append`、`insert`、`replace_selection`）。修订号不一致时返回 `409`，不覆盖正文。拒绝只标记任务，不改正文。任务类型为 `continue`、`rewrite`、`polish`、`expand`、`shrink`、`proofread`。显式 `use_mock=true` 或选择模拟配置时，响应里的 `provider_mode` 为 `mock`。`rewrite` 且带有非空 `selection_text` 时，`prompt_version` 为 `rewrite_selection_v1`，候选仍要等到采纳才写入正文。

创建任务请求至少包含：
- `novel_id`
- `chapter_id`（可选）
- `task_type`
- `instruction`
- `selection_text`（选区任务可选）
- `target_revision`
- `model_config_id`（可选，未指定则用任务默认模型）
- `constraints`（可选，字数、视角、语气、必须/禁止事项）

### Memory
- `GET /api/v1/novels/{novel_id}/entities`
- `POST /api/v1/novels/{novel_id}/entities`
- `PATCH /api/v1/entities/{entity_id}`
- `POST /api/v1/chapters/{chapter_id}/analyze`
- `GET /api/v1/novels/{novel_id}/memory-proposals`
- `POST /api/v1/memory-proposals/{proposal_id}/accept`
- `POST /api/v1/memory-proposals/{proposal_id}/reject`
- `POST /api/v1/memory-proposals/{proposal_id}/revert`
- `GET /api/v1/novels/{novel_id}/chapter-summaries`
- `GET /api/v1/novels/{novel_id}/events`

分析请求带 `revision`，可选 `model_config_id` 和 `use_mock`。它只创建提案。响应里的 `formal_memory_changed` 和 `manuscript_changed` 固定为 false。没有证据的条目 `certainty` 为 `inferred` 或 `uncertain`。接受才写入正式记忆，并且不改正文。拒绝不改正式设定。撤回只回滚该提案接受时写下的记忆。章节修订变化后，相关摘要和待审核提案变为 `stale`。

### Quality
- `GET /api/v1/novels/{novel_id}/foreshadowing`
- `POST /api/v1/novels/{novel_id}/foreshadowing`
- `PATCH /api/v1/foreshadowing/{foreshadowing_id}`
- `POST /api/v1/chapters/{chapter_id}/conflict-check`
- `GET /api/v1/novels/{novel_id}/stats`
- `PUT /api/v1/novels/{novel_id}/writing-goal`

伏笔状态为 `open`、`planned`、`resolved`、`abandoned`、`uncertain`，并且只属于一本作品。冲突检查只返回疑似冲突：类型、正文片段、已确认事实、来源章节与引用、严重程度、置信度、建议的人工处理。响应里的 `manuscript_changed` 和 `formal_memory_changed` 固定为 false。没有外部模型，或请求 `use_mock=true` 时，使用本地规则，`provider_mode` 为 `mock`。人物状态变化本身不算冲突。字数统计按正文字数函数计算每章和全书，目标字数是可选项。

### Model settings
- `GET /api/v1/settings/models`
- `POST /api/v1/settings/models`
- `PATCH /api/v1/settings/models/{config_id}`
- `POST /api/v1/settings/models/test`
- `DELETE /api/v1/settings/models/{config_id}`

响应中不返回 API Key 明文。

### Export / backup
- `POST /api/v1/novels/{novel_id}/export`
- `POST /api/v1/admin/backups`：做一次 SQLite 一致性备份。需要认证。响应只含 `id`、`app_version`、`alembic_revision`、`created_at`，不返回数据库文件。
- `GET /api/v1/admin/backups`：列出上述元数据，需要认证。
- 恢复操作第一版通过 CLI 完成：`python -m app.cli.restore --backup <目录> --database <新文件>`。不要在 Web 页面暴露恢复接口。目标文件已存在时命令拒绝覆盖，除非显式加上 `--force`（先把现有文件改名）。

## 3. SSE 协议

事件类型：
- `task.started`
- `token`
- `task.completed`
- `task.failed`
- `task.cancelled`
- `heartbeat`

规则：
- 文本片段必须按到达顺序拼接。
- `task.completed` 只发送一次。
- `task.failed` 不应把失败伪装为完成。
- 浏览器断开时任务状态仍由后端持久化管理。
- 重新连接时通过任务 ID 查询当前状态；第一版可以不支持从任意 token 精确续传，但必须明确展示任务最终状态。
- 用户取消后迟到的 token 不得进入正式正文。

## 4. HTTP 状态码

- `400`：请求格式错误。
- `401`：未认证。
- `403`：已认证但无权限。
- `404`：资源不存在。
- `409`：版本冲突或非法状态迁移。
- `422`：参数校验失败。
- `429`：请求频率限制。
- `502`：模型供应商返回无效响应。
- `503`：模型暂时不可用。
- `504`：模型请求超时。

## 5. API 验收要求

每个 endpoint 至少覆盖：正常请求、不存在的 ID、非法输入、未认证请求、数据库异常、版本冲突（正文写入）、错误消息不泄露密钥/路径/堆栈。
