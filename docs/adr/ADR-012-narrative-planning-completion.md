# ADR-012：补全故事线、卷大纲和大纲候选

## 状态

已采纳（E7，2026-10-20）

## 背景

ADR-006 落地了作品大纲、章节大纲和场景卡片，并明确当时不建 `story_arcs`、`volume_outlines`，也不生成大纲候选。E2 已经会把已确认的章节大纲和场景标成 stale，但编译器还读不到故事线和卷大纲。任务书 E1 剩下的就是这三项。

AI 任务的采纳会写章节正文。大纲候选如果做成新的任务类型，确认路径很容易碰到正文修订锁。

## 决策

1. 不改 `0001`–`0010`。新迁移是 `0011_story_arcs`，只建空表 `story_arcs` 和 `volume_outlines`。
2. 故事线属于作品。`arc_type` 为 `main` / `subplot` / `character` / `other`。有自己的 `sort_order`、`status` 和 `revision`。删除与场景卡片一样是硬删除，并重排剩余行。不软删除。
3. 卷大纲属于作品和卷，`volume_id` 唯一。目标、关键事件、起止状态可空。状态与章节大纲相同。它的 `revision` 不改 `volumes.title`，也不改 `chapters.revision`。
4. 已确认卷大纲的过期沿用 `mark_chapter_memory_stale`：该章正文修订变化时，所在卷的已确认卷大纲改为 `stale`。新建、复制、软删除或移动章节改变卷内结构时，也对涉及的卷调用同一条过期更新。只改卷名不标过期。删除卷之前删掉卷大纲行。
5. 大纲候选不扩展 AI 任务类型，也不走会写正文的采纳。`POST .../outline-candidate` 只返回预览；`accept` 才写入 `chapter_outlines` 和追加的 `scene_cards`，状态固定为 `draft`。模拟模型显式标成模拟。无模型时默认 `use_mock=true`，不访问网络。
6. ContextCompiler 版本改为 `e7.v1`。已确认故事线摘要和当前章节所在卷的已确认卷大纲以优先级 2 进入编译，与已确认章节大纲同类，且不可被预算截断。`draft` 可以列出，但 `included` 为 false。查询都带 `novel_id`。
7. 作品包仍是 `ai-novel-writer-portable-v1`，`format_version` 仍为 1。`planning.json` 增加可选的 `story_arcs` 和 `volume_outlines`；旧包没有这两项时按空列表导入。不支持的格式或版本仍返回 422，不写库。Markdown/TXT 导出不变。

## 不做

- 不把大纲候选写成 `confirmed`，也不改正文。
- 不建人物知情范围。
- 不引入向量库、图库、多 Agent 或消息队列。
- 不改写 ADR-006 和 ADR-011 的历史决定。本 ADR 只记录 E7 相对它们的增量。

## 替代方案

- 把故事线塞进关系表的 `storyline` 文本：那一列只是标签，不能排序、确认或隔离成规划行，否决。
- 把卷目标写进 `volumes.title`：会和目录标题缠在一起，否决。
- 新增 AI 任务类型再在采纳时写大纲：现有采纳事务写的是正文，否决。
- 把作品包升到 format version 2：旧包会变成不支持的版本。可选键保持版本 1，否决升版。

## 后果

旧库升级后新表为空，已有章节仍可写。SQLite 整库备份会带上新表。若要去掉这两张表，用新的降级迁移，不改 `0011` 的升级历史。
