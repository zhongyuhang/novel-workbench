# ADR-005：模型密钥存储

## 状态
已采纳（M0）

## 决策
使用环境变量主密钥（如 `APP_SECRET_ENCRYPTION_KEY`）对模型 API Key 做加密存储；API 响应仅返回已配置状态或脱敏尾号；日志禁止明文密钥。
