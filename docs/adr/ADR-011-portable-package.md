# ADR-011：作品包导入导出

## 状态

已采纳（E6 / 阶段 F 中的可移植性部分，2026-10-19）

## 背景

Markdown/TXT 导出和整库 SQLite 备份已经能带走正文，但作者换机器时仍绑在某一份数据库上。整库备份会连同其他作品、密钥密文和本机配置一起走。E6 要单独交出一本作品：结构、正文和已经落库的创作资产可以离开当前数据库，再导入成一本新作品。E0–E5 已落地的作品级数据都应尽量进包。不新开向量库、图库或多 Agent。

## 决策

1. 不新增表，也不改写 `0001`–`0010`。迁移头仍是 `0010_version_provenance`。作品包是文件，不是新的持久化模型。
2. 归档格式是 ZIP，清单里的 `format` 为 `ai-novel-writer-portable-v1`，`format_version` 为整数 `1`。成员包括 `manifest.json`、`catalog.json`、`planning.json`、`memory.json`、`quality.json`、`versions.json`、`ai.json`，以及 `manuscript/toc.json` 和按目录顺序编号的 `manuscript/000N.md`、`manuscript/000N.txt`。JSON 里的 Tiptap 正文是导入时的权威内容。Markdown 和 TXT 是给人读的投影，必须存在，且顺序与目录一致。现有 `POST /api/v1/novels/{id}/export` 的 Markdown/TXT 内容不变。
3. 包内覆盖作品、卷、章节（含正文格式、修订号和软删除时间）、作品大纲、章节大纲、场景卡片、实体、动态状态、人物关系、事件、摘要、记忆提案、伏笔、字数目标、质量问题、修复候选、章节版本元数据和快照、AI 任务。软删除的章节和关联行留在 JSON 里，避免外键悬空；目录只列未删除章节。已删除的作品导入后 `deleted_at` 置空，使它出现在作品库，并在预览里警告。
4. 导出递归去掉名为密钥的字段，包括 `api_key`、`secret_ref`、`password`、`access_token` 等。正文文本节点不按字面值打码。模型配置只保留非敏感字段，并标明需要重新配置；导入时不写入 `model_configs`，任务上的 `model_config_id` 置空。访问口令、认证密钥和加密主密钥不进包。整库备份仍可能含密钥密文，继续按 ADR-005 保护主密钥。
5. 导入始终插入一本新作品。某一行的主键若已在对应表里存在，就换成新的 UUID，并记下冲突映射。不会更新已有行。包内重复的主键视为无效。跨作品引用、指向包外的编号、以及剪枝后仍悬空的关联会使该行无效。模型配置的无效计数不阻止导入。
6. `POST /api/v1/novels/import/preview` 只读，返回 `can_import` 和新增、跳过、冲突、无效的计数。不支持的 `format` 或 `format_version` 返回 `422 UNSUPPORTED_PACKAGE`，消息写明版本号，并且不写库。存在无效行时预览为 `can_import=false`；正式导入返回 `422 PACKAGE_INVALID`，不写库。`POST /api/v1/novels/import` 在通过预检后于一次事务中写入。中途失败回滚，返回 `500 PACKAGE_IMPORT_FAILED`，消息为「导入没有完成，没有留下半成品。」
7. 章节 `revision` 按包内原值保留。已有快照的 `change_source` 保持原样。当前修订还没有快照时，补一条 `change_source=import` 的快照，不因此增加修订号。导入后的正文保存仍走原来的乐观锁。状态为 `queued` 或 `running` 的任务改为 `failed`，`error_code=PORTABLE_IMPORT`，避免导入后继续生成。
8. 上传限制：压缩包 64MB，单个成员 16MB，解压合计 160MB，成员不超过 4000，每一类行不超过 5000。拒绝路径穿越。
9. 整库备份格式仍是 `ai-novel-writer-backup-v1`。`GET /api/v1/admin/backups` 增加 `latest_success_at`，取最新一份清单的 `created_at`，没有备份时为 null。作品库显示这个时间。恢复仍只用 `python -m app.cli.restore`，网页不提供恢复。

## 不做

- 不用导入覆盖已有作品，也不提供「合并进当前作品」。
- 不把 API Key 或访问口令放进作品包。
- 不改 Markdown/TXT 导出的正文和顺序。
- 不在网页上恢复整库。
- 不引入向量库、图库或多 Agent。

## 替代方案

- 只靠整库 SQLite 备份换机器：会带走其他作品和密钥密文，否决作为单本作品的迁移方式。备份继续负责整库演练。
- 把 Markdown 当作导入权威：会丢掉 Tiptap 结构和修订元数据，否决。Markdown/TXT 留在包里只供阅读。
- 冲突时覆盖同 ID 行：会改掉已经在库里的作品，否决。
- 为作品包单独建表：现有表已经能表达这些行，否决新迁移。
