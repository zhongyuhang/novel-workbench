# 06 模型接入规范

## 1. 目标

支持多个兼容 OpenAI Chat Completions 或项目明确支持的兼容协议的模型服务，通过配置切换，不在业务代码中绑定供应商。

## 2. 配置字段

- `display_name`, `base_url`, `api_key` / `secret_ref`, `model_name`
- `timeout_seconds`, `max_retries`, `temperature`, `max_output_tokens`
- `supports_streaming`, `supports_json_output`, `task_defaults`, `enabled`

不同服务商支持的参数不一致。请求构造必须按能力配置筛选参数；遇到不支持参数时要提供清晰错误或安全降级。

## 3. 接口抽象

统一接口：`validate_config`, `test_connection`, `generate`, `stream`, `estimate_usage`, `normalize_error`。业务服务只依赖该抽象。

## 4. 失败处理

- 设置连接与读取超时。
- 只对可重试的网络错误、429、部分 5xx 做有限重试。
- 不对参数错误、认证错误无限重试。
- 指数退避并限制最大等待时间。
- 不在日志中记录 Authorization header、API Key 或完整敏感提示词。
- 用户可见错误提供安全、可操作的说明。
- 失败任务保留状态和错误码，不能生成空白“成功”结果。

## 5. 流式生成

- 后端将供应商流转换成统一 SSE 事件。
- 前端按 `task_id` 维护生成状态。
- 支持取消；取消后停止将新片段写入 UI。
- 生成内容在用户采纳前仅作为候选输出。
- 对异常中断要标记 failed/cancelled，不得静默变成 completed。

## 6. 密钥管理

优先级：
1. 由服务器环境变量注入主密钥，应用对配置密钥进行加密存储。
2. 如果 MVP 使用单机配置文件存储，文件必须限制权限并排除 Git，文档必须明确风险。
3. API 返回只显示已配置状态或脱敏尾号。
4. 日志、异常、导出、前端状态不得包含明文密钥。
5. 备份若包含密钥密文，应同时保护加密主密钥。

## 7. 模型评测

维护固定的小说测试集：延续前章、遵守设定、按字数生成、选区改写、摘要事实、JSON schema、断流超时恢复。质量评价由可重复测试和人工审阅共同组成。
