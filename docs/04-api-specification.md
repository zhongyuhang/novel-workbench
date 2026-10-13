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

### Model settings
- `GET /api/v1/settings/models`
- `POST /api/v1/settings/models`
- `PATCH /api/v1/settings/models/{config_id}`
- `POST /api/v1/settings/models/test`
- `DELETE /api/v1/settings/models/{config_id}`

响应中不返回 API Key 明文。

### Export / backup
- `POST /api/v1/novels/{novel_id}/export`
- `POST /api/v1/admin/backups`
- `GET /api/v1/admin/backups`
- 恢复操作第一版可以通过 CLI 完成，避免在 Web 页面暴露高风险恢复接口。

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
