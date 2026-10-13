"""Request id propagation without buffering the response body."""

import logging
import re
from typing import cast
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_var

logger = logging.getLogger("app.request")

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def normalize_request_id(value: str) -> str:
    if _REQUEST_ID_RE.fullmatch(value):
        return value
    return str(uuid4())


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        header_value = _header(scope, b"x-request-id")
        request_id = normalize_request_id(header_value) if header_value else str(uuid4())
        scope["request_id"] = request_id
        token = request_id_var.set(request_id)
        status_code = 0

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = [
                    item
                    for item in message.get("headers", [])
                    if item[0].lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            logger.info(
                "request completed",
                extra={"path": str(scope.get("path", "")), "status_code": status_code},
            )
            request_id_var.reset(token)


def _header(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return cast(bytes, value).decode("latin-1").strip()
    return ""
