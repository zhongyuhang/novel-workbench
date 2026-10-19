# ADR-006：章节大纲与现有章节的关系

## 状态

已采纳（E1 / 阶段 B，2026-10-19）

## 背景

`docs/03` 曾草拟一张 `outlines` 表，用 `level` 表示 book / volume / chapter / scene，并用 `parent_id` 串成树。`0001` 到 `0006` 都没有创建这张表，ORM 里也没有它。

章节行已经有 `status=outline`。它表示写作进度，不是一份规划文档。正文修订号 `chapters.revision` 只保护正文的乐观锁。

任务书需要作品级大纲、章节大纲和场景卡片，并要求未确认的大纲不能当成强制事实。

## 决策

1. 不补建那张未落地的 `outlines` 表，也不改 `0001`–`0006`。
2. 从 `0007_story_planning` 起使用三张表：`story_plans`（每本作品一行）、`chapter_outlines`（每章一行）、`scene_cards`（一章多张，按 `sort_order`）。
3. 章节大纲通过 `chapter_id` 指向现有章节，并冗余 `novel_id`。它不是章节行上的新正文列。
4. 规划有自己的 `revision`。保存大纲、确认大纲、重排场景都不写 `chapters.content`，也不增加 `chapters.revision`，不产生 `chapter_versions`。
5. 状态使用 `draft` / `confirmed` / `stale` / `archived`，不复用章节状态枚举。只有 `confirmed` 的 `counts_as_fact` 为 true。作品大纲和章节大纲只能通过确认接口变成 `confirmed`。
6. 场景的地点和出场人物只存已有实体 ID。地点必须是同一作品的 `location`，人物必须是同一作品的 `character`。响应可以临时带上名称，名称不入库。
7. 章节软删除或在同一作品内移动时，规划行继续指向原来的 `chapter_id` 和 `novel_id`。软删除后的章节不再通过接口露出这些行。复制章节不复制大纲。
8. 没有大纲的旧章节保持可写、可保存、可导出。Markdown/TXT 导出不加入大纲文本。

## 不做

- 不建 `story_arcs`、`volume_outlines`。
- 不生成大纲候选，也不把模型输出直接写进大纲或正文。
- 正文或设定变化时，不自动把已确认大纲改成 `stale`。作者可以手动标成待复核。自动过期留到上下文编译器接入之前。
- 本阶段的上下文编译器不读取规划表。以后只应纳入 `counts_as_fact=true` 的行。

## 替代方案

- 把大纲塞进 `chapters.status` 或 `chapters.content`：会和写作进度、正文修订锁缠在一起，否决。
- 现在补建原来的粗 `outlines` 树：字段对不上目标、必写事件、禁揭信息和实体引用，还会和这三张表重复，否决。
- 场景人物用一段文本抄档案：档案一改就会分叉，否决。

## 后果

旧库升级只增加空表，已有正文、修订号和版本不变。SQLite 备份是整库文件，新表随备份恢复。若以后要删掉这三张表，用新的降级迁移，不改 `0007` 的升级历史。
