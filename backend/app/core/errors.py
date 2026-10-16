"""Domain errors mapped to the public API error envelope."""


class AppError(Exception):
    """Base error with a stable client-facing code and message."""

    status_code = 500
    code = "INTERNAL_ERROR"
    message = "服务器内部错误。"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or type(self).message
        super().__init__(self.message)


class DatabaseUnavailable(AppError):
    status_code = 503
    code = "DATABASE_UNAVAILABLE"
    message = "数据库暂时不可用。"


class NotFound(AppError):
    status_code = 404
    code = "NOT_FOUND"
    message = "请求的资源不存在。"


class RevisionConflict(AppError):
    status_code = 409
    code = "REVISION_CONFLICT"
    message = "章节已在其他操作中更新，请刷新并比较差异。"


class InvalidDocument(AppError):
    status_code = 422
    code = "INVALID_DOCUMENT"
    message = "正文必须是 Tiptap JSON 文档。"


class InvalidReference(AppError):
    status_code = 422
    code = "INVALID_REFERENCE"
    message = "请求引用了无效的作品结构。"


class PasswordRequired(AppError):
    status_code = 401
    code = "PASSWORD_REQUIRED"
    message = "需要本机访问口令。"


class InvalidPassword(AppError):
    status_code = 401
    code = "INVALID_PASSWORD"
    message = "口令不正确。"


class ModelNotConfigured(AppError):
    status_code = 409
    code = "MODEL_NOT_CONFIGURED"
    message = "还没有可用的模型配置。请先到模型设置里填写服务信息。"


class ModelConfigInvalid(AppError):
    status_code = 422
    code = "MODEL_CONFIG_INVALID"
    message = "模型配置不完整。"


class SecretStorageUnavailable(AppError):
    status_code = 503
    code = "SECRET_STORAGE_UNAVAILABLE"
    message = "服务器还没有配置密钥加密主密钥，暂时不能保存模型 API Key。"


class SelectionNotFound(AppError):
    status_code = 422
    code = "SELECTION_NOT_FOUND"
    message = "选区已经不在正文里，没有改写正文。"


class TaskStateError(AppError):
    status_code = 409
    code = "TASK_STATE"
    message = "当前任务状态不能执行这个操作。"


class ProviderRequestFailed(AppError):
    """Safe provider failure. The message must not contain secrets or response bodies."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)
