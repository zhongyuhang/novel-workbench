# ADR-003：AI 任务生命周期

## 状态
已采纳（M0）

## 决策
统一使用 **任务 ID + 后台执行 + SSE 事件流**：
`queued -> running -> completed | failed | cancelled`。

生成成功仅表示候选结果就绪，不表示正文已采纳。
