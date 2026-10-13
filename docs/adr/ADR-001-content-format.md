# ADR-001：正文 canonical format

## 状态
已采纳（M0）

## 决策
采用 **Tiptap JSON** 作为章节正文唯一权威格式（`content_format=tiptap_json`，`content_format_version=1`）。

## 理由
技术基线建议 Tiptap；JSON 文档利于选区映射与结构化编辑；导出层负责 Markdown/TXT。

## 约束
- 数据库只存一份权威 `content`（JSON 序列化）。
- HTML 仅作渲染结果。
- 必须实现可测试的 Markdown/TXT 导出。
- 未来格式升级通过 `content_format_version` + 迁移。
