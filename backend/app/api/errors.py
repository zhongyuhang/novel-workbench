"""Map exceptions to the public error envelope. Responses never include secrets or traces."""

import logging
import re
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.core.errors import AppError
from app.core.logging import request_id_var

logger = logging.getLogger("app.api")

_STATUS_ERRORS: dict[int, tuple[str, str]] = {
    400: ("BAD_REQUEST", "请求格式错误。"),
    401: ("UNAUTHENTICATED", "未认证。"),
    403: ("FORBIDDEN", "没有权限执行此操作。"),
    404: ("NOT_FOUND", "请求的资源不存在。"),
    409: ("CONFLICT", "当前状态不允许此操作。"),
    422: ("VALIDATION_ERROR", "请求参数不符合要求。"),
    429: ("RATE_LIMITED", "请求过于频繁，请稍后再试。"),
    500: ("INTERNAL_ERROR", "服务器内部错误。"),
    502: ("BAD_GATEWAY", "模型服务返回了无效响应。"),
    503: ("SERVICE_UNAVAILABLE", "服务暂时不可用。"),
    504: ("GATEWAY_TIMEOUT", "模型请求超时。"),
}

_FRAMEWORK_DETAILS = {
    "Bad Request",
    "Unauthorized",
    "Forbidden",
    "Not Found",
    "Conflict",
    "Unprocessable Entity",
    "Too Many Requests",
    "Internal Server Error",
    "Bad Gateway",
    "Service Unavailable",
    "Gateway Timeout",
}

_SAFE_DETAIL = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9，。！？、：；“”\"'（）()\s._-]{1,200}$")


def current_request_id(request: Request | None = None) -> str:
    current = request_id_var.get()
    if current:
        return current
    if request is not None:
        stored = request.scope.get("request_id")
        if isinstance(stored, str) and stored:
            return stored
    return "missing"


def error_response(
    status_code: int,
    code: str,
    message: str,
    request: Request | None = None,
) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": current_request_id(request),
            }
        },
    )
    response.headers["X-Request-ID"] = current_request_id(request)
    return response


def _safe_http_message(status_code: int, detail: object) -> tuple[str, str]:
    code, message = _STATUS_ERRORS.get(status_code, ("HTTP_ERROR", "请求无法完成。"))
    if (
        isinstance(detail, str)
        and detail not in _FRAMEWORK_DETAILS
        and _SAFE_DETAIL.fullmatch(detail)
    ):
        return code, detail
    return code, message


def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    http_exc = cast(HTTPException, exc)
    code, message = _safe_http_message(http_exc.status_code, http_exc.detail)
    return error_response(http_exc.status_code, code, message, request)


def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del exc
    return error_response(422, "VALIDATION_ERROR", "请求参数不符合要求。", request)


def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    app_exc = cast(AppError, exc)
    logger.warning("application error", exc_info=app_exc)
    return error_response(app_exc.status_code, app_exc.code, app_exc.message, request)


def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    token = request_id_var.set(current_request_id(request))
    try:
        logger.exception("unhandled error", exc_info=exc)
        return error_response(500, "INTERNAL_ERROR", "服务器内部错误。", request)
    finally:
        request_id_var.reset(token)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
