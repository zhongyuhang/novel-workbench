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

`chapters.status` 里的 `outline` 只表示写作进度（界面写成「提纲」），不是章节大纲。章节大纲在 `chapter_outlines`。

### 叙事规划

`docs/03` 早先写过一张按 `level` 分层的 `outlines` 表。那张表没有进入 `0001`–`0006`，现在也不补建。规划从 `0007_story_planning` 的三张表开始，E7 用 `0011_story_arcs` 补上故事线和卷大纲。决定见 [ADR-006](adr/ADR-006-story-planning.md) 和 [ADR-012](adr/ADR-012-narrative-planning-completion.md)。

备份是整份 SQLite 文件。这些表会随库备份和恢复。Markdown/TXT 导出仍然只含标题、简介、卷、章和正文，不含大纲。作品包格式仍是 `ai-novel-writer-portable-v1`、`format_version` 1；`planning.json` 可以多带 `story_arcs` 和 `volume_outlines`，缺了这两项就当空列表。不支持的格式或版本仍然是 422。

#### story_plans

每本作品最多一行。正文可空。状态默认 `draft`。`revision` 只属于这份大纲，不改 `chapters.revision`。

- `id` PK
- `novel_id` FK，唯一
- `logline` nullable
- `body` nullable
- `ending_intent` nullable
- `status` (`draft`, `confirmed`, `stale`, `archived`)
- `revision`（大于等于 1）
- `created_at`, `updated_at`

只有 `confirmed` 可以当作创作约束。`draft`、`stale`、`archived` 都不是强制事实。某一章的正文修订变化不会自动让作品级大纲过期。

#### chapter_outlines

每个章节最多一行，并冗余 `novel_id`，服务层要求它和章节属于同一作品。

- `id` PK
- `novel_id` FK
- `chapter_id` FK，唯一
- `goal`、`must_advance`、`required_events`、`allowed_reveals`、`forbidden_reveals`、`ending_hook` 均可空
- `target_words` nullable，空或大于等于 1。这是本章的可选目标，不改 `writing_goals`
- `status` 同上
- `revision`（大于等于 1）
- `created_at`, `updated_at`

索引：`(novel_id)`。

软删除章节后，大纲行留在库里，接口不再返回。不会改挂到别的作品。

#### scene_cards

- `id` PK
- `novel_id` FK
- `chapter_id` FK
- `sort_order`（大于等于 0）
- `goal`、`conflict`、`turning_point`、`expected_outcome`、`must_convey`、`must_not_reveal` 均可空
- `location_entity_id` nullable FK -> story_entities。必须是同一作品的 `location`
- `character_entity_ids` JSON，只存人物实体 ID，不存档案
- `status` 同上
- `revision`（大于等于 1）
- `created_at`, `updated_at`

索引：`(novel_id)`、`(chapter_id, sort_order)`。排序以重排后的 `sort_order` 为准。删除场景会腾出序号；软删除章节时场景行保留，接口隐藏。

#### story_arcs

故事线属于作品，不挂到某一章。类型是 `main`、`subplot`、`character`、`other`。删除是硬删除，删完按剩余行重排 `sort_order`，和场景卡片一样，不用软删除。

- `id` PK
- `novel_id` FK
- `arc_type`
- `title`
- `summary` nullable
- `sort_order`（大于等于 0）
- `status` 同上
- `revision`（大于等于 1）
- `created_at`, `updated_at`

索引：`(novel_id)`、`(novel_id, sort_order)`。只有 `confirmed` 的摘要会进入上下文编译。`draft` 可以出现在编译结果里，但 `included` 为 false，不当事实。

#### volume_outlines

每卷最多一行，并冗余 `novel_id`。服务层要求它和卷属于同一作品。`revision` 只属于这份卷大纲，不改 `volumes.title`，也不改 `chapters.revision`。

- `id` PK
- `novel_id` FK
- `volume_id` FK，唯一
- `goal`、`key_events`、`start_state`、`end_state` 均可空
- `status` 同上
- `revision`（大于等于 1）
- `created_at`, `updated_at`

索引：`(novel_id)`。

这一卷里某章的正文修订变化时，已确认的卷大纲改为 `stale` 并增加自己的修订号，正文不变。新建、复制、软删除或移动章节改变卷内结构时，同样把该卷已确认大纲标成 `stale`。只改卷名不会。删卷时先删掉这份大纲行，避免外键悬空。作品级大纲不因此自动过期。

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
- `valid_from_text` nullable，故事内生效起点。空着不阻塞写作或记录状态
- `valid_until_text` nullable，故事内生效终点。空着同样不阻塞
- `created_at`

用于记录动态状态历史，不覆盖实体基础档案。`0008_story_bible` 给已有状态补上这两个可空列，旧行都是空。状态变化本身不是矛盾；有效时间重叠时的疑似冲突留到质量修复阶段，不在本阶段误报。

### entity_relations

同一作品里两个设定之间的有向关系。不引入图数据库。`storyline` 只是可选标签，不是 `story_arcs` 外键。故事线在 `story_arcs`，不从这里反查。

- `id` PK
- `novel_id` FK
- `from_entity_id`、`to_entity_id` FK -> story_entities，不能相同，且都必须属于 `novel_id` 下未删除的设定
- `relation_type`
- `story_time_text` nullable。空着可以保存
- `storyline` nullable
- `source_chapter_id` nullable FK -> chapters，若填写则必须是同一作品
- `source_revision` nullable
- `evidence_quote` nullable
- `status` (`active`, `ended`, `unknown`)
- `created_at`, `updated_at`, `deleted_at`

索引：`(novel_id)`、`(from_entity_id)`、`(to_entity_id)`。软删除后接口不再返回。

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

索引：`(novel_id)`、`(novel_id, status)`。

### writing_goals

每本作品最多一行，用来记可选的全本目标字数。它不保存正文。

- `id` PK
- `novel_id` FK，唯一
- `target_words`（大于等于 1）
- `created_at`, `updated_at`

### quality_issues

`0009_quality_issues` 新增。质量检查写入这里，不改正文，也不改正式设定。见 ADR-009。

- `id` PK
- `novel_id` FK
- `chapter_id` FK
- `issue_type`（`fact_continuity`、`time_continuity`、`character_continuity`、`foreshadowing`、`outline_execution`、`text_surface`）
- `severity`（`low`、`medium`、`high`）
- `confidence`：0 到 100 的整数，接口再换算成 0 到 1
- `status`（`pending`、`confirmed`、`ignored`、`fixed`、`expired`）
- `manuscript_snippet`：用来定位的正文片段，可为空字符串
- `target_revision` nullable：发现问题时的章节修订
- `location_note` nullable
- `evidence_status`（`sufficient`、`insufficient`）
- `evidence`、`related_refs` JSON
- `rule_id`、`rule_version`
- `analysis_version` nullable：只有模型检查写入
- `provider_mode`（`rule`、`mock`、`openai_compatible`）
- `suggested_action`
- `fingerprint`：与 `novel_id` 唯一，重复检查更新同一行
- `fixed_revision` nullable
- `recheck_count`
- `created_at`, `updated_at`

索引：`(novel_id)`、`(novel_id, status)`。

### quality_repair_candidates

一条修复建议。`proposed` 不会写入正文。

- `id` PK
- `issue_id` FK -> quality_issues
- `novel_id` FK
- `chapter_id` FK
- `target_revision`（大于等于 1）
- `apply_mode`（`replace_selection`、`append`）
- `applicable`
- `original_snippet`、`replacement_text`
- `rationale`
- `diff_preview`：纯文本差异，采纳前给作者看
- `provider_mode`（`rule`、`mock`、`openai_compatible`）
- `prompt_version`
- `status`（`proposed`、`accepted`、`rejected`、`conflict`）
- `created_at`, `updated_at`

索引：`(issue_id)`。

### chapter_versions
- `id` PK
- `chapter_id` FK
- `revision`
- `content_snapshot`
- `content_format`
- `change_source` (`manual`, `ai_accepted`, `restore`, `import`)
- `change_note` nullable
- `ai_task_id` nullable FK -> ai_tasks，`ON DELETE SET NULL`。`0010_version_provenance` 起才有。旧快照为空
- `repair_candidate_id` nullable FK -> quality_repair_candidates，`ON DELETE SET NULL`。质量修复采纳时填写。旧快照为空
- `created_at`

唯一约束：`(chapter_id, revision)`。自动保存不写这张表。记忆分析提案不存在版本行上，按提案的 `source_chapter_id` 和 `source_revision` 关联。见 ADR-010。

### model_configs
- `id` PK
- `display_name`
- `provider`：服务商预设标识，默认 `custom`。预设列表来自数据文件，不是接口白名单
- `provider_type`（`openai_compatible` 或 `mock`）
- `base_url`
- `model_name`
- `secret_ref`：API Key 的 Fernet 密文。响应不返回明文
- `encrypted_custom_headers`：自定义 Header 的 Fernet 密文，可空
- `parameters` JSON：超时、重试、默认温度、默认最大输出
- `capabilities` JSON
- `is_enabled`
- `is_default`：最多一条为真。部分唯一索引 `uq_model_configs_one_default`
- `last_test_status`（`untested`、`success`、`failed`、`stale`）
- `last_tested_at`、`last_test_error_code` 可空
- `created_at`, `updated_at`

`0012_model_config_center` 接在 `0011_story_arcs` 之后追加这些列。旧行的测试状态是 `untested`，不是默认模型。超时、温度和最大输出仍放在 `parameters`，避免和原字段双写。

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

`input_snapshot` 继续放在任务行里，E2 不另建快照表。新任务会在这份 JSON 里写入 `compiler_version`、`context_items`、`context_warnings`、`context_budget`、`context_hash` 和实际使用的 `prompt`。材料副本单条超过 4000 字时缩短显示正文，字符估算仍按全文。整份快照序列化超过约 18 万字时，先去掉排除项正文，再缩短纳入项副本和章节正文副本；提示词全文保留，因为生成器读的就是它。快照随任务行保留，没有单独的过期删除。API Key 和 `secret_ref` 不写入快照。旧任务没有这些字段时，接口说明当时只保存了整段提示。详见 ADR-007。

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

章节修订变化后，仍为 `pending` 且 `source_revision` 对不上的提案改为 `stale`，不写入正式设定。`payload.applied` 记录接受时写下的行。`entity_update` 从接受之时起另写 `payload.field_changes`：只列出这次真正改过的字段，以及该字段接受前、接受后的值。撤回只回滚这些字段。某个字段如果之后又被改过，整次撤回拒绝，正式设定保持原样。没有 `field_changes` 的旧提案不能自动撤回，避免用整份 `before` 盖掉后来的手工修改。`before` 仍会留下，但不再当作回滚快照。

## 3. 关系原则

- 一个 novel 有多个 volume、chapter、entity、event、story_arcs，最多一份 `story_plans`。
- 一个 volume 最多一份 `volume_outlines`。
- chapter 可以没有 volume（例如尚未分卷的草稿）。
- chapter 可以没有大纲和场景卡片。没有大纲不影响正文、版本和导出。
- chapter 可以有多个版本、摘要和记忆提案，以及最多一份 `chapter_outlines`。
- 场景卡片的地点和人物必须引用同一作品里的实体。
- entity 的静态档案与 entity_states 的动态历史分开。
- 人物关系的两端必须是同一作品的实体。故事时间、来源章节和证据都可以空。
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
