"""Reject model base URLs that point at local or metadata services.

The check runs on the server. MODEL_BASE_URL_ALLOWLIST is a deployment
escape hatch for a local model, not a client-supplied flag.
"""

import ipaddress
import re
from urllib.parse import urlsplit

from app.core.config import get_settings

_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata",
        "metadata.google.internal",
        "metadata.google.com",
        "instance-data",
        "host.docker.internal",
        "kubernetes",
        "kubernetes.default",
        "kubernetes.default.svc",
    }
)
_OCTET = re.compile(r"0|[1-9]\d*|0[0-7]+")


class UnsafeModelUrl(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def assert_base_url_allowed(base_url: str) -> None:
    parts = urlsplit(base_url.strip())
    if parts.scheme not in {"http", "https"} or parts.hostname is None:
        raise UnsafeModelUrl("Base URL 需要以 http:// 或 https:// 开头。")
    if parts.username is not None or parts.password is not None:
        raise UnsafeModelUrl("Base URL 不能携带用户名或密码。")
    host = parts.hostname.rstrip(".").lower()
    if host == "":
        raise UnsafeModelUrl("Base URL 缺少主机名。")
    if _allowlisted(host):
        return
    if host in _BLOCKED_HOSTS or host.endswith(".local") or host.endswith(".internal"):
        raise UnsafeModelUrl("这个地址被安全策略拒绝。如需本地模型，请在部署环境配置允许名单。")
    address = _literal_ip(host)
    if address is not None and _blocked_ip(address):
        raise UnsafeModelUrl("这个地址被安全策略拒绝。如需本地模型，请在部署环境配置允许名单。")


def _allowlisted(host: str) -> bool:
    raw = get_settings().model_base_url_allowlist
    allowed = {item.strip().lower().rstrip(".") for item in raw.split(",") if item.strip()}
    return host in allowed


def _literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if re.fullmatch(r"\d{1,10}", host):
        number = int(host)
        if number <= 0xFFFFFFFF:
            return ipaddress.IPv4Address(number)
        return None
    parts = host.split(".")
    if len(parts) == 4 and all(_OCTET.fullmatch(part) for part in parts):
        numbers: list[int] = []
        for part in parts:
            base = 8 if len(part) > 1 and part.startswith("0") else 10
            try:
                number = int(part, base)
            except ValueError:
                return None
            if number > 255:
                return None
            numbers.append(number)
        return ipaddress.IPv4Address(".".join(str(number) for number in numbers))
    return None


def _blocked_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )
