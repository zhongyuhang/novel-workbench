# ADR-013：正文与资料同步

## 状态

已采纳

## 背景

正式设定只在提案被确认后改变。分析原先只覆盖新实体、实体更新、状态、事件和章节摘要。关系要手写，伏笔直接成为正式行。质量问题全部记成疑似，伏笔也没有把发生时间、埋设位置、角色发现和向读者揭示分开。

自动保存已经会写章节。若每次自动保存都调用模型，作者改一个字就会产生一批候选，也把模型费用绑在保存频率上。

## 决策

1. 不更换存储和接口风格。新迁移是 `0013_manuscript_material_sync`，接在 `0012_model_config_center` 之后。
2. 完整分析仍是 `POST /chapters/{id}/analyze`，`scope` 为 `full`。作者点击分析，或章节状态第一次变成定稿时触发。指定 `model_config_id` 用该配置，否则用默认模型。调用走现有的模型适配器。
3. `scope=light` 只在本地抽取关系、伏笔、设定补充和潜在冲突。它不调用模型。手动保存请求一次。自动保存不请求。
4. 新候选类型是 `entity_relation`、`foreshadowing`、`setting_supplement`、`potential_conflict`。每条带来源章节和原文证据。确认前不写正式资料。
5. 审核动作为确认、修改后确认、忽略、延后、标成有意安排的矛盾。忽略和延后不写正式资料。潜在冲突在确认或标成有意矛盾时只写质量问题。
6. 伏笔增加三列可空文本：`event_time_text`、`character_discovered_text`、`reader_revealed_text`。埋设仍用章节，回收仍用状态。
7. 质量问题增加 `finding_class`：`deterministic`、`suspected`、`creative_risk`。旧问题默认是疑似。规则版本号不改，以免把已有指纹全部换成新问题。
8. 暗线记在故事线的 `thread_visibility=hidden`，不新增故事线类型。
9. 修改已确认设定后的影响分析是只读的 `GET /novels/{id}/material-impact`。它不改正文，也不改正式资料。

## 不做

- 不在自动保存里调用模型。
- 不把未确认候选写进正文或正式设定。
- 不把伏笔的五个时间维度收成一个日期字段。
- 不因为这次检查去自动改稿。
