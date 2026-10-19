# 11 演进差距分析（E0）

审计日期：2026-10-19。对照文档：《AI 小说工作台演进开发任务书》E1–E6，以及仓库 `docs/01`–`docs/10`、ADR-001–ADR-005、README。

本文件只记录现状、差距和建议。E0 不改业务代码、不新增表、不改历史迁移。

## 1. 现状盘点

### 1.1 工程与启动

| 项 | 现状 |
|---|---|
| 后端 | Python 3.12、FastAPI、SQLAlchemy 2、Alembic。入口 `backend/app/main.py`，路由前缀 `/api/v1` |
| 前端 | React 19、TypeScript、Vite。哈希路由：`#/` 作品库、`#/settings` 模型设置、`#/novels/{id}` 与 `#/novels/{id}/chapters/{id}` 三栏工作台 |
| 数据库 | SQLite。迁移头 `0006_quality`（`0001_initial` → `0002_catalog` → `0003_chapter_versions` → `0004_ai` → `0005_memory` → `0006_quality`） |
| 检查 | `./scripts/check.sh`：venv、`alembic upgrade head`、Ruff、mypy、pytest、`npm ci`、Vitest、`tsc`+Vite 构建、oxlint |
| 启动 | 后端 `uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`；前端 `npm run dev`，默认 `127.0.0.1:43117`，`/api` 代理到 8000 |
| 部署 | `deploy/compose.yaml` + Caddy。本审计环境没有 Docker，未跑 Compose |

模型注册表：`Novel`、`Volume`、`Chapter`、`ChapterVersion`、`ModelConfig`、`AiTask`、`StoryEntity`、`EntityState`、`StoryEvent`、`ChapterSummary`、`MemoryChangeProposal`、`Foreshadowing`、`WritingGoal`。没有叙事规划表、人物关系表、上下文快照表、质量问题表。

`docs/03` 写了 `outlines` 表（`level` 为 book/volume/chapter/scene）。迁移和 ORM 都没有这张表。章节 `status` 里的 `outline` 是正文流程状态（界面标成「大纲」），不是规划文档。

### 1.2 已实现、可复用

这些能力已经进了代码和测试，后续阶段应扩展，不应另起一套：

- 作品 / 卷 / 章节 CRUD、软删除、排序、移动、复制、作品隔离。
- Tiptap JSON 权威正文、`revision` 乐观锁、手动保存快照、自动保存不写快照、恢复生成新修订。
- Markdown / TXT 全书导出（标题、简介、卷、章、正文，顺序与目录一致）。
- 模型配置、Fernet 加密的 `secret_ref`、响应只给脱敏尾号、模拟模型显式标识。
- AI 任务状态机 `queued → running → completed | failed | cancelled`。`completed` 只表示候选就绪。SSE 事件与取消。采纳 / 拒绝分离。采纳写 `change_source=ai_accepted`，修订冲突 `409`。
- 设定：实体类型 `character | location | organization | item | rule | other`，动态状态、事件、章节摘要、带证据的提案。接受 / 拒绝 / 撤回。修订变化把当前摘要和待审核提案标成 `stale`。
- 上下文组装已经有独立模块 `backend/app/services/context_builder.py`。创建任务时必经它。范围限定当前作品。检索是名称 / 别名精确匹配、事件 `LIKE`、相邻章节。没有向量库。
- 伏笔 CRUD、疑似冲突检查（不改正文、不改正式记忆）、字数统计、全本目标字数。
- 单用户会话、生产配置校验、SQLite 一致性备份、CLI 恢复。网页没有恢复按钮。

### 1.3 确实缺失

- 全书大纲、故事线、卷大纲、章节大纲、场景卡片，以及对应 API / UI。
- 可逐项查看的上下文编译结果：来源、修订、纳入 / 排除原因、预算警告、用户固定材料。
- 人物关系、状态有效时间、人物知情范围。
- 持久化的质量问题、修复候选、大纲执行检查。
- 版本差异、版本与 AI 任务的关联。
- 作品级导入，以及包含设定 / 伏笔 / 版本元数据的归档包。

## 2. 关键行为抽查

### 2.1 AI 任务、SSE、取消、采纳、revision

| 行为 | 结论 | 证据 |
|---|---|---|
| 状态机 | 已实现。终态不能再迁移 | `backend/app/ai/tasks.py`；`backend/tests/test_ai_tasks.py` |
| 创建时组装上下文 | 已实现。模拟模型和外部模型走同一条 `build_memory_context` | `backend/app/services/ai_tasks.py` `create_ai_task` |
| 快照 | 部分实现。`ai_tasks.input_snapshot` 存指令、选区、约束、目标修订、当时正文、完整 prompt、模型名。不存 API Key。响应不返回 snapshot，也没有逐条来源 | `AiTask` 模型；`_response` 只给出 `prompt_version` 和 `output_text` |
| SSE | 部分实现。数据库状态是权威状态。事件缓存在进程内 `TaskBroker`。同一进程内重连会从缓冲重放。进程重启后缓冲丢失，`GET /api/v1/ai/tasks/{id}` 仍能读到状态和 `output_text`。前端 `streamAiTask` 不断线重连，也没有在流结束后回查任务 | `backend/app/ai/broker.py`；`frontend/src/api/ai.ts`；`docs/04` 第 3 节 |
| 取消与迟到 token | 已实现。取消后不再把后续 token 写入候选或正文。取消的任务不能采纳 | `backend/app/ai/runner.py`；`backend/tests/test_m3_acceptance.py` `test_t009_...` |
| 采纳事务 | 已实现。先按 `append` / `insert` / `replace_selection` 生成新文档；选区不在正文里返回 `422 SELECTION_NOT_FOUND`，不写库。然后在同一 session 里更新正文、字数、revision、`chapter_versions`、任务 `resolution=accepted`，并标记记忆过期，一次 `commit`。失败 `rollback` | `accept_ai_task`、`apply_candidate_text`、`apply_accepted_candidate` |
| revision 冲突 | 已实现。创建任务和采纳都比对目标修订，不一致 `409 REVISION_CONFLICT` | `test_t004_...`、`test_t010_...` |
| 重复采纳 | 服务层已拒绝（`resolution` 非空则 `409 TASK_STATE`）。测试覆盖了一次采纳和一次拒绝，没有单独的「同一任务采纳两次」用例 | `accept_ai_task` |
| 拒绝 | 已实现。只改 `resolution`，不改正文 | `test_t011_...` |

`replace_selection` 在命中选区后用纯文本重建整章 Tiptap 文档。这会丢掉原有行内标记。现有设计如此，E5 若做差异预览应单独说明，不要在 E0 改语义。

### 2.2 记忆提案

| 行为 | 结论 | 证据 |
|---|---|---|
| 来源 | 已实现。提案有 `novel_id`、`source_chapter_id`、`source_revision`、`evidence_quote`、`certainty` | `MemoryChangeProposal`；`test_t013_...` |
| 无证据不升格 | 已实现。分析只写提案。证据对不上原文时降低确定性。不确定身份不会自动成正式实体 | `memory_extract.py`；`test_uncertain_identity_...`、`test_configured_model_without_evidence_...` |
| 接受 | 已实现，同一事务写入正式记忆并在 `payload.applied` 记下本次写下的行 | `accept_proposal` |
| 拒绝 | 已实现。不改正式设定 | `test_t012_...` |
| stale | 已实现。正文保存、恢复、采纳候选后，来源修订对不上的 `current` 摘要和 `pending` 提案改为 `stale`。已接受的提案不改状态。界面接受过期提案前会再确认 | `mark_chapter_memory_stale`；`test_revision_change_marks_summary_...`；`MemoryPanel.tsx` |
| 撤回 | 部分实现，和任务书 7.5 的安全要求有缺口。新建实体是软删除；状态行删除；事件软删除；摘要标 `rejected`。`entity_update` 用接受时保存的整份 `before` 覆盖实体。若接受之后作者又改过同一实体，撤回会盖掉这些后续修改。测试只覆盖「撤回新建的实体」 | `_revert_applied`、`_restore_entity`；`test_revert_removes_the_accepted_entity` |
| 隔离 | 已实现。列表和上下文都按 `novel_id` 过滤。摘要通过章节归属过滤 | `test_memory_queries_do_not_leak_across_novels`、`test_context_uses_previous_chapter_and_ignores_other_novels` |

任务书要求：现有撤回如果不能安全处理并发修改，先补事务和变更记录测试，再加更多记忆功能。E3 之前应先补这一层。阶段 B 的规划表不依赖撤回，不必被它挡住。

### 2.3 作品隔离、认证、密钥、备份

| 行为 | 结论 | 证据 |
|---|---|---|
| 隔离 | 已实现。作品、章节、实体、事件、提案、伏笔、AI 任务都校验归属。跨作品章节引用返回 `422` | 各 service 的 `_require_*`；`test_t014_...`、`test_foreshadowing_is_isolated_...` |
| 认证 | 已实现。除 `GET /api/v1/health` 和 `POST /api/v1/auth/session` 外，作品、AI、记忆、质量、模型、备份路由都依赖 `require_session`。未登录 `401`。生产环境拒绝占位密钥、弱口令、过低迭代次数、`CORS_ORIGINS=*`、`ALLOWED_HOSTS=*` | `backend/app/api/v1/*.py`；`backend/tests/test_auth.py`、`test_m6_acceptance.py`、`test_runtime.py` |
| 密钥 | 已实现。API Key 只以密文放在 `secret_ref`。列表和任务响应不回明文。日志有脱敏 | ADR-005；`test_secrets.py`；`test_t016_api_key_is_absent_...` |
| 备份恢复 | 已实现。`POST/GET /api/v1/admin/backups` 只返回元数据。备份目录含 SQLite 一致性副本和清单（格式版本、应用版本、迁移版本、时间）。恢复是 `python -m app.cli.restore`，目标已存在时拒绝覆盖，除非 `--force`。测试覆盖备份后恢复到新库 | `backend/app/services/backup.py`；`test_t017_backup_then_restore_...` |
| 备份界面 | 未实现。前端没有备份入口，也没有「最近一次成功备份」提示 | `frontend/src` 无 backup 调用 |
| 作品包导入 | 未实现。`change_source` 预留了 `import`，没有导入接口 | `ChapterVersion` 约束；`exporting.py` 只出 Markdown/TXT |

## 3. 差距表

现状取值：已实现 / 部分实现 / 未实现 / 与现有设计冲突。

### 3.1 E1 叙事规划

| 功能 | 现状 | 证据 | 缺口 | 建议改动（最小） | 优先级 |
|---|---|---|---|---|---|
| 作品级大纲 | 未实现 | 无 `story_plans`。`novels.synopsis` / `style_guide` 只是简介和风格，不是大纲 | 不能保存全书目标和结构 | 新表，每本作品最多一行。空表即可，不回填 | P0 |
| 故事线 | 未实现 | 模型与路由中无 arc | 不能表达主线 / 支线 / 人物线 | 阶段 B 可缓到 B 的下一刀；E2 之前要有，否则编译器没有线可引用 | P1 |
| 卷级大纲 | 未实现 | `Volume` 只有标题和排序 | 卷没有目标、关键事件、起止状态 | 与故事线同一刀。不要塞进 `volumes.title` | P1 |
| 章节大纲 | 未实现 | `Chapter` 无目标、必写事件、禁揭信息、钩子、大纲 revision。`status=outline` 只是写作状态 | 生成时不知道本章意图 | 新表，`chapter_id` 唯一。状态用 `draft/confirmed/stale/archived`，不要复用章节状态枚举 | P0 |
| 场景卡片 | 未实现 | 无场景模型。实体已有，可被引用 | 不能排序场景，也不能引用出场人物 | 新表，带 `novel_id`、`chapter_id`、`sort_order`。人物和地点存实体 ID，服务层校验同一作品 | P0 |
| 大纲候选生成 | 未实现 | AI 任务类型只有续写、改写、润色、扩写、缩写、校对 | 没有「先预览、确认后才写入大纲」 | 阶段 B 不做。沿用现有任务：新类型或独立预览接口，确认前不写正式大纲，更不改正文 | P1 |
| 大纲因正文或设定变化而复核 | 未实现 | 过期机制只覆盖摘要和待审核提案 | 大纲不会变 stale | 正文 revision 变化时把该章已确认大纲标 `stale`。复用 `mark_chapter_memory_stale` 的调用点，不自动改大纲正文 | P1 |
| 大纲视图 | 未实现 | 左栏只有目录。右栏是生成 / 设定 / 质量 | 不能编辑大纲，也不能和正文对照 | 左栏增加大纲视图，不替换目录。没有大纲的章节仍可写、存、导出 | P0 |
| `docs/03` 的 `outlines` 表 | 与现有设计冲突 | `docs/03` 有层级 `outlines`；代码从未迁移。任务书建议五张更细的表 | 两套规划模型会重复 | 不要补建那张未落地的粗表，也不要改 `0001`–`0006`。阶段 B 用任务书的字段建新表，并在当时用 ADR 说明 `docs/03` 的 `outlines` 草图被替代。见第 5 节 | P0 |

### 3.2 E2 ContextCompiler

| 功能 | 现状 | 证据 | 缺口 | 建议改动（最小） | 优先级 |
|---|---|---|---|---|---|
| 独立上下文模块 | 部分实现 | `context_builder.py` 的 `build_memory_context` / `assemble_context`。`create_ai_task` 调用它。模拟模型不绕过 | 返回的是一整段字符串，不是可测试的条目列表 | 在现有模块上增加结构化结果。不要平行再写一个编译器 | P0 |
| 条目来源与排除原因 | 未实现 | `ContextPiece` 只有 key、text、required、shrinkable、rank。没有 source、revision、certainty、exclusion_reason | 作者看不到用了什么、为什么没包进来 | 增加条目结构。未纳入的材料也留下原因 | P0 |
| 预算 | 部分实现 | 默认预算 6000，按字符数。可选材料先丢，必选材料可截到 80 字。超预算且无法再截时仍返回超长文本，没有警告 | 风格指南被标成必选且 `shrinkable=True`，可能被静默截短。与 `docs/05`「不能优先删硬约束」以及任务书「不静默截断硬规则」不一致 | 硬规则改为不可截断。放不下时保留全文并在结果里给警告。字符估算继续标明是估算，第一版不上 tokenizer | P0 |
| 大纲与场景 | 未实现 | 编译器不读规划数据（规划数据也不存在） | 已确认大纲进不了提示词 | E1 落地后，只把 `confirmed` 大纲和场景放进高优先级条目。`draft` 不得当事实 | P0 |
| 硬规则、相邻章、名称匹配 | 已实现 | 系统规则、本次指令、题材和风格、当前章约束、上一章结尾、下一章开头、实体名/别名、相关事件、较远 `current` 摘要 | 命中原因没有结构化字段。事件检索是 `LIKE`，不是语义检索 | 给现有命中补原因，例如「别名命中」「相邻章节」。不要把 `LIKE` 写成语义检索 | P0 |
| 伏笔 | 未实现 | `context_builder.py` 不查询 `foreshadowing` | 相关伏笔不会进入上下文 | 按当前章、出场实体或显式关联纳入，并标明状态 | P1 |
| 未确认提案默认排除 | 已实现 | 编译器只读正式实体、状态、事件和 `current` 摘要 | 无 | 保持。若以后展示待确认材料，必须单独标注 | P0 |
| 跨作品隔离 | 已实现 | 查询都带当前 `novel_id`。软删除实体和章节不进入 | 无 | 新条目继续带 `novel_id` 校验。补一条「其他作品的大纲也不能进入」的测试 | P0 |
| 上下文快照可回看 | 部分实现 | 完整 prompt 写在 `input_snapshot`，所以当时的拼接文本还在。接口不返回它，也没有条目级哈希或编译器版本 | 不能在任务详情里核对来源和排除项。只存 ID 会在设定后来被改后失真；现在存了 prompt，但不可解释 | 在 snapshot 里增加有长度上限的条目副本、编译器版本和警告。密钥继续禁止写入。旧任务没有这些字段时，界面说明「当时只保存了整段提示」 | P0 |
| 固定纳入 / 排除并重新编译 | 未实现 | 创建请求没有材料白名单或黑名单 | 用户不能调整本次上下文 | 选择只作用于本次任务，不写回设定或大纲 | P1 |
| 过期来源警告 | 部分实现 | 摘要进入上下文前已过滤掉非 `current`。实体状态只显示来源修订，不比较章节是否又改过 | 状态和事件的来源修订落后于正文时没有警告 | 编译时比较 `source_revision` 与章节当前 revision，写入 warnings | P1 |
| 编译失败不得静默变成无上下文 | 部分实现 | 作品不存在时函数返回空串，但创建任务在此之前已经 `404`。模块本身没有失败码 | 异常若被吞掉，会变成无材料生成 | 编译异常直接失败并返回可读错误。空材料若是数据真的为空，要和失败区分开 | P0 |
| 上下文查看 UI | 未实现 | `AiPanel` 只有候选、选区对比、采纳和拒绝 | 没有「本次上下文」 | 右栏增加入口，列出纳入、排除、冲突和过期 | P0 |
| 任务生命周期兼容 | 已实现 | 状态、取消、409、拒绝不改正文、采纳写版本，均已有测试 | 上下文改造不能改这些语义 | 编译器只准备材料。写入正文仍只走现有采纳 | P0 |

### 3.3 E3 小说圣经

| 功能 | 现状 | 证据 | 缺口 | 建议改动（最小） | 优先级 |
|---|---|---|---|---|---|
| 实体档案与类型 | 已实现 | `StoryEntity` 六类枚举、别名、profile、状态；设定页可新建和修改 | 无关系、无筛选故事线 | 不改枚举名。圣经视图复用现有列表 | P0 |
| 动态状态 | 部分实现 | `EntityState` 有章节、来源修订、证据、`source_type`。冲突检查已规定「状态变化本身不是矛盾」 | 没有故事内生效区间。取「最新状态」只按 `created_at` | 先加可空的生效说明或起止字段，空着不阻塞写作。重叠且规则不允许时才报疑似矛盾 | P1 |
| 故事事件 | 部分实现 | `StoryEvent` 有 `event_time_text`、参与者字符串、证据、确定性、来源修订 | 参与者不是实体外键。没有章节顺序之外的时间线视图 | 参与者改为可选的实体 ID 列表，并校验同作品。保留原来的文本时间 | P1 |
| 人物关系 | 未实现 | 无关系表。profile JSON 可以随便写，但没有类型、有效时间和来源 | 不能按关系筛选，也不能让编译器引用关系 | 新表，两端都引用 `story_entities`，带 `novel_id` | P1 |
| 章节摘要 | 已实现 | `current/stale/rejected`，带来源修订。摘要不是正文权威版本 | 摘要没有 `novel_id` 列，隔离靠章节连接 | 保持。不要把摘要升格为事实 | P0 |
| 提案接受 / 拒绝 / stale | 已实现 | 见第 2.2 节。过期提案可以在确认后接受，符合 `docs/05`「重新分析或人工确认」 | 无 | 保持确认步骤。不要让模型自动接受 | P0 |
| 撤回不覆盖后续人工修改 | 与现有设计冲突 | `_restore_entity` 整份恢复 `before`。任务书禁止这种回滚 | 并发修改会丢 | E3 前先记「本次提案改了哪些字段」。撤回只动这些字段；字段已被后改则拒绝撤回并说明。先补测试再扩大记忆功能 | P0 |
| 人物知情范围 | 未实现 | 无字段、无提示词区分读者已知和人物已知 | 悬疑题材可能把作者已知写进人物行为 | 第一阶段允许为空。生成提示里加一条约束即可，不必先建复杂图 | P2 |
| 圣经 UI | 部分实现 | 右栏「设定」有实体、事件、摘要、提案、证据和模拟分析标记 | 没有关系，没有按章 / 按线 / 按状态的完整筛选，实体详情不够集中 | 仍放在设定标签里扩展，不新开一级菜单 | P1 |
| 作品隔离 | 已实现 | 见第 2.3 节 | 新关系和新大纲必须同样校验 | 服务层校验，不靠前端 | P0 |

### 3.4 E4 质量修复

> E0 审计时的差距。E4 已落地，行为以 ADR-009 和 `docs/10` 为准。

| 功能 | 现状 | 证据 | 缺口 | 建议改动（最小） | 优先级 |
|---|---|---|---|---|---|
| 疑似冲突、不自动改稿 | 已实现 | `POST /chapters/{id}/conflict-check`。结果不落库。`manuscript_changed` 与 `formal_memory_changed` 固定为 false。无模型走本地规则 | 只覆盖「属性说法不一致」和「否定已确认事实」，依据是已确认事件的证据句 | 保留现有检查。新检查继续只出疑似问题 | P0 |
| 事实 / 时间 / 人物动机 / 大纲执行 / 文本问题 | 未实现 | 冲突类型常量只有上述两种。伏笔没有逾期扫描。没有名称不一致或重复段检查 | 任务书第 8.2 节的大部分类别没有 | 按类分步加规则。无证据就写「证据不足」，不下性格或逻辑断言 | P1 |
| 伏笔台账 | 已实现 | `foreshadowing` 的五种状态、同作品回收章节、设定页可改 | 不会因为计划回收章已过而主动提示。编译器也不读它 | 用现有行做逾期规则，不必新表 | P1 |
| 问题对象与状态 | 未实现 | 检查结果只在当次响应里 | 不能标记待处理、忽略、已修复、已过期，也不能复查 | 新表保存问题、证据、规则版本、目标 revision。定位用片段加 revision，不用字符偏移 | P1 |
| 修复候选 | 未实现 | 没有「生成修复建议」。选区改写是另一条 AI 任务，不挂在问题上 | 不能从问题预览差异再采纳 | 复用现有 AI 任务和采纳事务。候选不直接写正文。修订变了就 409 或要求重查 | P1 |
| 评测样例 | 部分实现 | `backend/tests/fixtures/eval/samples.json` 有续写、选区改写、摘要。冲突有正反规则测试 | 没有质量检查的正例、反例和无法判断样例 | 在现有 fixtures 上加质量样例，离线、可重复 | P1 |
| 字数与目标 | 已实现 | `GET /novels/{id}/stats`、`writing_goals`。目标不改正文 | 目标是全本一个数，不是章节目的字数 | 章节目的字数放到章节大纲的可选字段，不改 `writing_goals` 语义 | P2 |

### 3.5 E5 可靠性

| 功能 | 现状 | 证据 | 缺口 | 建议改动（最小） | 优先级 |
|---|---|---|---|---|---|
| 采纳单事务 | 已实现 | 见第 2.1 节 | 无专门的「采纳两次」测试 | 补一条重复提交测试，不改语义 | P0 |
| 自动保存失败留在编辑器 | 已实现 | `useChapterAutosave.ts`：失败可重试；进行中的保存不会被旧请求覆盖；冲突阶段停止再存 | 冲突时只能「载入服务器正文」，没有并排比较 | 保留本地草稿。比较可以等到版本差异一起做 | P1 |
| 离开确认 | 已实现 | `leaveGuard.ts`、`beforeunload`、切章和回作品库 | 无 | 保持 | P0 |
| 手动保存与自动保存 | 已实现 | `save_kind=manual` 才在内容变化时写 `chapter_versions` | 无 | 保持 | P0 |
| SSE 断线可恢复 | 部分实现 | 任务行有最终状态和候选正文。文档要求重连后查询任务。前端流中断会当成失败，不会 `GET` 任务 | 刷新或重启后，界面可能丢掉已经生成的候选 | 流没有终态时回查 `GET /ai/tasks/{id}`。broker 仍只做通知 | P0 |
| 取消、密钥不进日志 | 已实现 | 见第 2.1、2.3 节 | 无 | 上下文快照沿用同一脱敏 | P0 |
| 版本差异 | 未实现 | 版本列表有时间、`change_source` 中文标签、截断预览。没有两版 diff | 不能在恢复前看清改了什么 | 用现有纯文本做差异，恢复仍创建新修订 | P1 |
| 恢复不删历史 | 已实现 | `restore_chapter`；`test_t005_...` | 无 | 保持 | P0 |
| 版本关联 AI 任务或记忆分析 | 未实现 | `chapter_versions` 没有 `ai_task_id`。提案另有来源修订 | 不能从版本跳回那次采纳 | 可空外键。旧版本保持为空 | P2 |

### 3.6 E6 可移植性

| 功能 | 现状 | 证据 | 缺口 | 建议改动（最小） | 优先级 |
|---|---|---|---|---|---|
| 正文导出 | 已实现 | `POST /novels/{id}/export`，Markdown 或 TXT | 不含大纲、设定、关系、事件、伏笔、摘要、版本元数据 | 保留这个导出。另做归档包，不要偷偷改变现有文件内容 | P1 |
| 作品包导入与预检 | 未实现 | 无导入路由。`import` 只出现在枚举里 | 不能把一份作品导入成新作品 | 有版本号的 JSON 加正文文件。预检后一次事务写入。失败不留半成品。ID 重映射，不覆盖现有作品 | P1 |
| 密钥不进包 | 已实现于现有导出（导出里没有模型配置） | `exporting.py` | 将来的包必须继续排除 API Key 和访问口令 | 模型只导出非敏感字段，密钥重新配置 | P0 |
| 库级备份恢复 | 已实现 | 见第 2.3 节。新表只要在 SQLite 里，就会随备份走 | 界面没有最近成功备份时间。本环境未跑 Docker 演练 | 作品库或健康信息旁显示最近一次备份时间。恢复仍走 CLI | P1 |
| 不支持的包版本 | 未实现 | 备份清单有 `ai-novel-writer-backup-v1`，没有作品包 | 无清晰的格式错误 | 导入时先读版本号，不认识就拒绝且不写库 | P1 |

## 4. 受影响文件（后续阶段，本轮不改）

阶段 B 预计新增，而不改历史迁移：

| 路径 | 作用 |
|---|---|
| `backend/alembic/versions/0007_story_planning.py` | 新迁移。编号以当时的真实迁移头为准，现在的头是 `0006_quality` |
| `backend/app/models/planning.py` | 规划 ORM |
| `backend/app/schemas/planning.py` | 请求和响应 |
| `backend/app/services/planning.py` | 归属校验、排序、确认 |
| `backend/app/api/v1/planning.py` | REST。风格对齐现有路由 |
| `backend/tests/test_planning.py` | API 与排序 |
| `backend/tests/test_migrations.py` | 增加从 `0006_quality` 升级的用例，保留原有升级测试 |
| `frontend/src/api/planning.ts` | 客户端 |
| `frontend/src/components/OutlinePanel.tsx` | 大纲与场景编辑 |
| `frontend/src/pages/WorkspacePage.tsx` | 大纲视图入口。目录、编辑器、右栏保留 |

阶段 B 会小改：`backend/app/models/__init__.py`、`backend/app/api/v1/router.py`。不改 `chapters.content`、`revision`、AI 采纳和记忆撤回。

阶段 C 主要改 `context_builder.py`、`ai_tasks.py` 的 snapshot、`schemas/ai.py`、`AiPanel.tsx`，以及对应测试。阶段 D 触及 `memory.py` 的撤回和设定页。阶段 E 新增质量问题模型，并复用 `ai_tasks` 采纳。阶段 F 在 `exporting.py` 之外新增归档模块，备份服务只加「最近一次」查询。

## 5. 与现有设计的冲突和推荐

这些冲突在本轮只记录，不改代码。

1. **`docs/03` 的 `outlines` 与任务书的五张规划表。**  
   推荐：规划数据用任务书的字段（目标、必写事件、禁揭信息、场景顺序、实体引用、大纲 revision）。不补建从未迁移的粗 `outlines`。阶段 B 写 ADR，并改 `docs/03`，说明该草图被替代。章节 `status=outline` 继续只表示写作进度。

2. **硬规则可以被截到 80 字。**  
   `docs/05` 要求预算不足时先裁远摘要，保留硬约束。代码把风格指南标成可截断。推荐：E2 改编译器，硬规则不截断；放不下就警告。不改优先级顺序，也不引入向量库。

3. **实体更新的撤回会覆盖后续人工修改。**  
   推荐：E3 之前补字段级变更记录。撤回失败时保持正式记忆不变。阶段 B 不动这段代码。

4. **`docs/05` 写了 SQLite FTS，实现是 `LIKE`。**  
   推荐：E2 继续用名称匹配、相邻章节和有限 `LIKE`，并写明命中原因。不把 `LIKE` 叫做语义检索。只有真的不够用时再加 FTS。第一阶段不上向量库。

5. **重连应查询任务，前端没有做。**  
   `docs/04` 已允许第一版不精确续传 token，但要求能看到最终状态。推荐：E5 在现有 `GET /ai/tasks/{id}` 上补前端回查。不把 SSE 缓冲写成第二份权威状态。

6. **`change_source=import` 还没有导入功能。**  
   推荐：保留枚举。作品包导入写入新作品时使用它。不要为了整齐删掉这个值。

## 6. 数据迁移草案

当前头：`0006_quality`。下一编号应为 `0007_...`。禁止修改 `0001`–`0006`。

阶段 B 的 `0007` 只建新表，例如：

- `story_plans`：`novel_id` 唯一，大纲正文可空，状态默认 `draft`，自带 revision。
- `chapter_outlines`：`chapter_id` 唯一，并冗余 `novel_id` 以便校验。目标、必写事件、禁揭信息可空。状态默认 `draft`。
- `scene_cards`：`novel_id` + `chapter_id` + `sort_order`。地点和人物用 JSON 存实体 ID，或用关联表。删除章节时规划行随软删除章节隐藏，不跨作品悬挂；硬删除不在本阶段。

旧库升级后这些表为空。已有章节的正文、revision、版本、记忆都不变。无大纲的章节继续可写。

索引只建会用来列表和排序的列：`novel_id`，以及 `(chapter_id, sort_order)`。不要给每个文本列建索引。

后续迁移继续追加，例如上下文快照若不能安全塞进现有 JSON，再用 `0008` 加可空列或新表。新增非空列必须有默认值。升级测试要覆盖「已有 `0006` 数据库升到新头」，不只覆盖空库。迁移失败时部署不能报成功，这一点保持 `deploy/entrypoint.sh` 的现有行为。

撤回改造如果需要新列，也用新迁移，并为旧提案提供「没有字段级记录则拒绝自动撤回」的路径。不静默删数据。

SQLite 备份会带上新表。恢复流程不用改格式，只要清单里的迁移版本跟着变。

## 7. 阶段 B 最小可交付范围

对应任务书阶段 B，而不是一次做完 E1–E6。

做：

- 作品级大纲的读取和更新。
- 章节大纲的创建、修改、确认。
- 场景卡片的增删改和重排，顺序以数据库为准。
- 左栏或章节区能编辑这些内容，并标明草稿 / 已确认。AI 生成的文字在确认前不得显示成已确认。
- 没有大纲的旧章节仍能写作、自动保存、手动保存、导出。
- 迁移、从 `0006` 升级的测试、API 测试、前端交互测试。
- 更新 `docs/03`、`docs/04` 和一条 ADR，记录规划表替代未落地的 `outlines` 草图。

不做：

- 大纲候选生成、故事线、卷大纲（放到阶段 B 之后、E2 之前的一小步）。
- ContextCompiler 结构化改造。
- 记忆撤回改造、关系、故事时间。
- 质量问题表和修复候选。
- 作品包导入导出。
- 向量库、图数据库、多 Agent、消息队列。

自由创作保持默认：没有大纲也能生成。大纲约束模式等 E2 再接进编译器，而且只纳入已确认大纲。

## 8. 风险清单

| 风险 | 说明 | 控制 |
|---|---|---|
| 把章节状态 `outline` 当成大纲 | 界面已把该状态标成「大纲」 | 规划状态单独枚举，文案写成「章节大纲」 |
| 两套规划表 | `docs/03` 草图与任务书模型不一致 | 只建一套，并写 ADR |
| 改坏 revision / 采纳 | 规划保存若复用章节保存，可能误增正文修订 | 规划用自己的 revision，不写 `chapters.revision` |
| 跨作品悬挂引用 | 场景卡片引用实体 | 服务层校验 `novel_id`，测试覆盖 |
| 撤回覆盖后改 | 现有 `entity_update` 撤回 | E3 前先修；阶段 B 不调用这段 |
| 上下文静默截断硬规则 | 现有预算行为 | E2 改成警告，并加预算测试 |
| SSE 重启后界面丢候选 | 缓冲不在数据库里 | 回查任务行；不把未完成的流显示成失败终态 |
| 旧任务没有条目快照 | 只有整段 prompt | 界面区分新旧任务，不假装有来源列表 |
| 导入半成品 | 将来的作品包 | 单事务，失败回滚 |
| 削弱旧测试 | 演进时为了通过而改断言 | 只追加测试。冲突先在文档里说明 |

## 9. 基线测试结果

命令：`./scripts/check.sh`  
工作树：审计开始时的 `main`（`7734017`，M6）。本文件加入前后，检查范围都不包含 Markdown，因此文档提交不改变下述结果。

环境：

- Python 3.12.3，Node.js v22.14.0。
- 第一次执行失败：系统没有 `python3-venv`，`ensurepip` 不可用，脚本在创建 `backend/.venv` 时退出，退出码 1。安装 `python3.12-venv` 并删掉半成品虚拟环境后重跑。
- Docker 不可用（`docker` 不在 PATH）。`check.sh` 本身不调用 Docker。Compose 与局域网演练未在本环境执行，部署行为以 `test_compose_file_persists_data_and_does_not_enable_reload` 和 `docs/09` 为准。

重跑结果：退出码 0。

| 步骤 | 结果 |
|---|---|
| `alembic upgrade head` | 空库从 `0001_initial` 升到 `0006_quality` |
| `ruff check .` | 通过 |
| `ruff format --check .` | 104 个文件已格式化 |
| `mypy app` | 74 个源文件无问题 |
| `pytest -q` | 111 passed，1 warning（Starlette 提示 `TestClient` 将来改用 httpx2）。9.88s |
| `npm ci` | 155 个包，0 漏洞 |
| `npm test`（Vitest） | 7 个文件，19 个测试通过 |
| `npm run build` | `tsc -b` 与 Vite 构建通过。有一块 JS 大于 500 kB 的体积警告 |
| `npm run lint`（oxlint） | 退出码 0。4 个文件共 6 条既有警告（自动保存 memo、`ChapterEditor` 依赖、`WorkspacePage` 的 effect 写状态）。脚本没有把警告当成失败 |

未覆盖：真实外部模型、Docker Compose 启动、另一台机器上的恢复演练。模拟模型测试可离线重复。

## 10. 本阶段明确不做

不实现 E1 及之后的表、API 和 UI。不修改已应用迁移。不删除或放宽既有测试。不引入向量库、图库、多 Agent 或消息队列。
