# 03 数据库设计

## 1. 通用约定

- 主键使用 UUID 或统一的字符串 ID，项目内不得混用自增整数和随机字符串。
- 所有业务表有 `created_at`、`updated_at`；必要时增加 `deleted_at`。
- 时间统一存 UTC，前端按本地时区显示。
- 外键和索引必须明确。
- 删除、恢复、状态迁移需要业务服务控制。
- JSON 字段仅用于灵活属性，不代替高频查询字段。
- 数据库迁移使用 Alembic；禁止只靠启动时 `create_all()` 维护生产结构。

## 2. 核心表

### novels
- `id` PK
- `title` NOT NULL
- `genre` nullable（自由文本，不限定题材枚举）
- `synopsis` nullable
- `style_guide` nullable
- `status` (`draft`, `active`, `archived`)
- `created_at`, `updated_at`, `deleted_at`

### volumes
- `id` PK
- `novel_id` FK -> novels
- `title`
- `sort_order`
- `created_at`, `updated_at`

### chapters
- `id` PK
- `novel_id` FK -> novels
- `volume_id` nullable FK -> volumes
- `title`
- `sort_order`
- `content`：权威正文；若采用 Tiptap JSON，使用 JSON 序列化并增加 `content_format_version`
- `content_format`
- `word_count`
- `status` (`outline`, `draft`, `revised`, `final`)
- `revision` integer，用于乐观锁
- `created_at`, `updated_at`, `deleted_at`

索引：`(novel_id, sort_order)`、`(volume_id, sort_order)`。

### outlines
- `id` PK
- `novel_id` FK
- `parent_id` nullable FK -> outlines
- `level` (`book`, `volume`, `chapter`, `scene`)
- `title`
- `content`
- `sort_order`
- `status`
- `created_at`, `updated_at`

### story_entities
- `id` PK
- `novel_id` FK
- `entity_type` 自由扩展但需校验（`character`, `location`, `organization`, `item`, `rule`, `other`）
- `name`
- `aliases` JSON
- `profile` JSON / 文本
- `status` (`active`, `inactive`, `unknown`)
- `created_at`, `updated_at`, `deleted_at`

唯一性建议：同一小说内对规范化名称建立应用层重复检查，不直接把所有别名做全局唯一。

### entity_states
- `id` PK
- `entity_id` FK -> story_entities
- `chapter_id` FK -> chapters
- `state_data` JSON
- `evidence_quote` nullable
- `source_type` (`manual`, `ai_proposal`, `import`)
- `source_revision` nullable，接受提案时写入，便于追溯到章节修订
- `proposal_id` nullable FK -> memory_change_proposals
- `created_at`

用于记录动态状态历史，不覆盖实体基础档案。

### story_events
- `id` PK
- `novel_id` FK
- `chapter_id` FK
- `event_time_text` nullable（故事内时间可能不精确）
- `description`
- `participants` JSON
- `evidence_quote`
- `certainty` (`confirmed`, `inferred`, `uncertain`)
- `source_revision` nullable
- `proposal_id` nullable FK -> memory_change_proposals
- `created_at`, `deleted_at`

### chapter_summaries
- `id` PK
- `chapter_id` FK
- `summary`
- `key_facts` JSON
- `source_revision`
- `model_name` nullable
- `status` (`current`, `stale`, `rejected`)
- `created_at`, `updated_at`

当章节 revision 改变时，相关摘要应标记为 stale，而不是假装仍与正文一致。

### foreshadowing
- `id` PK
- `novel_id` FK
- `introduced_chapter_id` FK
- `description`
- `status` (`open`, `planned`, `resolved`, `abandoned`, `uncertain`)
- `payoff_chapter_id` nullable FK
- `evidence_quote` nullable
- `created_at`, `updated_at`

### chapter_versions
- `id` PK
- `chapter_id` FK
- `revision`
- `content_snapshot`
- `content_format`
- `change_source` (`manual`, `ai_accepted`, `restore`, `import`)
- `change_note` nullable
- `created_at`

唯一约束：`(chapter_id, revision)`。

### model_configs
- `id` PK
- `display_name`
- `provider_type` (`openai_compatible`)
- `base_url`
- `model_name`
- `secret_ref`（密钥引用，不存明文于普通配置响应）
- `parameters` JSON
- `capabilities` JSON
- `is_enabled`
- `created_at`, `updated_at`

### ai_tasks
- `id` PK
- `novel_id` FK
- `chapter_id` nullable FK
- `task_type`
- `status` (`queued`, `running`, `completed`, `failed`, `cancelled`)
- `model_config_id` nullable FK
- `input_snapshot` JSON
- `prompt_version`
- `output_text` nullable
- `error_code` nullable
- `error_message_safe` nullable
- `input_tokens` / `output_tokens` nullable
- `resolution` nullable（`accepted`, `rejected`；空表示候选尚未处理）
- `started_at`, `finished_at`, `created_at`

`secret_ref` 保存的是主密钥加密后的 API Key 密文，不是明文，也不是可回传给前端的字段。`completed` 只表示候选已生成。`resolution=accepted` 才表示用户已经把候选写入正文。

### memory_change_proposals
- `id` PK
- `novel_id` FK
- `source_chapter_id` FK
- `source_revision`
- `proposal_type`
- `payload` JSON
- `evidence_quote`
- `certainty` (`confirmed`, `inferred`, `uncertain`)
- `status` (`pending`, `accepted`, `rejected`, `reverted`, `stale`)
- `review_note` nullable
- `created_at`, `reviewed_at`

章节修订变化后，仍为 `pending` 且 `source_revision` 对不上的提案改为 `stale`，不写入正式设定。`payload.applied` 记录接受时写下的行，供撤回使用。

## 3. 关系原则

- 一个 novel 有多个 volume、chapter、entity、event。
- chapter 可以没有 volume（例如尚未分卷的草稿）。
- chapter 可以有多个版本、摘要和记忆提案。
- entity 的静态档案与 entity_states 的动态历史分开。
- AI 提案必须引用源章节和源 revision。
- 删除章节时，优先软删除并保留历史证据；清理孤儿数据应由单独、可测试的操作执行。

## 4. 并发与保存

- `PUT /chapters/{id}` 必须提交客户端看到的 `revision`。
- 若数据库 revision 已变化，返回 `409 Conflict`，不能静默覆盖。
- 成功保存后 revision + 1，并按规则创建版本快照。
- 自动保存使用防抖，但后端仍必须有乐观锁保护。
- AI 候选结果采纳时，必须基于用户确认的目标 revision；revision 不匹配则要求重新比较。

## 5. 迁移和测试

每次 schema 变化都必须：
1. 添加 Alembic migration。
2. 测试空数据库升级。
3. 测试从上一版本数据库升级。
4. 验证关键索引、外键和唯一约束。
5. 不允许通过删除生产数据库来“解决”迁移问题。
