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
- `POST /api/v1/ai/tasks/context/compile`：只编译上下文，不创建任务，不改正文、正式设定或大纲。
- `POST /api/v1/ai/tasks`
- `GET /api/v1/ai/tasks/{task_id}`
- `GET /api/v1/ai/tasks/{task_id}/context`：返回该任务保存的上下文条目。旧任务没有条目时 `legacy=true`，`items` 为空，并说明当时只保存了整段提示。
- `POST /api/v1/ai/tasks/{task_id}/cancel`
- `GET /api/v1/ai/tasks/{task_id}/events`（SSE）
- `POST /api/v1/ai/tasks/{task_id}/accept`
- `POST /api/v1/ai/tasks/{task_id}/reject`

采纳请求包含 `target_revision` 和 `apply_mode`（`append`、`insert`、`replace_selection`）。修订号不一致时返回 `409`，不覆盖正文。拒绝只标记任务，不改正文。任务类型为 `continue`、`rewrite`、`polish`、`expand`、`shrink`、`proofread`。显式 `use_mock=true` 或选择模拟配置时，响应里的 `provider_mode` 为 `mock`。模拟模型也走同一个上下文编译器。`rewrite` 且带有非空 `selection_text` 时，`prompt_version` 为 `rewrite_selection_v1`，候选仍要等到采纳才写入正文。

创建任务和编译请求包含：
- `novel_id`
- `chapter_id`（可选；创建任务时若关联章节则必填）
- `task_type`
- `instruction`
- `selection_text`（选区任务可选）
- `target_revision`
- `model_config_id`（创建任务可选，未指定则用任务默认模型；编译接口不需要模型）
- `constraints`（可选，字数、视角、语气、必须/禁止事项）
- `context_budget`（可选，200 到 20000，默认 6000。这是字符估算，不是分词器计数）
- `pinned_include` / `pinned_exclude`（可选材料编号。只影响这一次编译或这一次任务）

编译结果里每条材料有 `kind`、`content`、`source_type`、`source_id`、`source_revision`、`certainty`、`priority`、`token_estimate`、`included`、`exclusion_reason`、`hit_reason`、`warnings`。整体还有 `budget`、`warnings`、`compiler_version`、`context_hash`。只有 `counts_as_fact=true` 的作品大纲、章节大纲和场景卡片会默认纳入。草稿、过期和归档大纲会出现在未纳入列表里，并写明原因。

上下文编译失败返回 `422 CONTEXT_COMPILE_FAILED`，任务不会创建，也不会退回成无上下文生成。作品不存在仍是 `404`。章节不属于该作品是 `422 INVALID_REFERENCE`。关联章节时修订号不一致是 `409`。未登录是 `401`。

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

### Planning

作品级大纲、章节大纲和场景卡片。都要认证。服务层校验作品和章节属于同一本小说；场景引用的地点、人物也必须是这本作品里未删除的对应实体。规划写入不改章节正文，也不增加 `chapters.revision`。

- `GET /api/v1/novels/{novel_id}/story-plan`：作品还没有大纲时 `plan` 为 null，不是 404。
- `PUT /api/v1/novels/{novel_id}/story-plan`：创建或更新。已有大纲时必须带 `expected_revision`，不一致返回 `409 REVISION_CONFLICT`。
- `POST /api/v1/novels/{novel_id}/story-plan/confirm`：把状态改为 `confirmed`。这是标成已确认的唯一入口。
- `GET /api/v1/novels/{novel_id}/chapter-outlines`：只列出未软删除章节的大纲。
- `GET /api/v1/chapters/{chapter_id}/outline`：没有大纲时 `outline` 为 null。
- `PUT /api/v1/chapters/{chapter_id}/outline`
- `POST /api/v1/chapters/{chapter_id}/outline/confirm`
- `GET /api/v1/chapters/{chapter_id}/scenes`
- `POST /api/v1/chapters/{chapter_id}/scenes`
- `PATCH /api/v1/scenes/{scene_id}`
- `DELETE /api/v1/scenes/{scene_id}`
- `POST /api/v1/chapters/{chapter_id}/scenes/reorder`：请求体是这一章全部 `scene_ids`，按新顺序排列。缺项、重复或其他章节的卡片返回 `422`。

状态是 `draft`、`confirmed`、`stale`、`archived`。响应里的 `counts_as_fact` 只有 `confirmed` 为 true。作品大纲和章节大纲的普通保存不能把状态写成 `confirmed`；内容有变化且没有另选状态时，已确认的大纲会回到 `draft`。场景卡片可以在创建或修改时自带状态。

跨作品的章节、地点或人物引用返回 `422 INVALID_REFERENCE`。软删除后的章节再读大纲或场景返回 `404`，库里的规划行仍指向原来的 `novel_id` 和 `chapter_id`。未登录返回 `401`。

本阶段没有故事线、卷大纲，也没有「生成大纲候选」接口。上下文编译器只读取 `counts_as_fact=true` 的作品大纲、当前章节大纲和场景卡片。章节正文修订变化时，该章已确认的章节大纲和场景卡片改为 `stale`，正文不变；作品级大纲不因此自动过期。

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
- `422`：参数校验失败，或上下文编译失败（`CONTEXT_COMPILE_FAILED`）。
- `429`：请求频率限制。
- `502`：模型供应商返回无效响应。
- `503`：模型暂时不可用。
- `504`：模型请求超时。

## 5. API 验收要求

每个 endpoint 至少覆盖：正常请求、不存在的 ID、非法输入、未认证请求、数据库异常、版本冲突（正文写入）、错误消息不泄露密钥/路径/堆栈。
