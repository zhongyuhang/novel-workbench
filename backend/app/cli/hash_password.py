"""Print a PBKDF2 hash for APP_ACCESS_PASSWORD_HASH. The passphrase is not echoed."""

import getpass
import hmac
import sys

from app.core.passwords import hash_password, is_weak_password


def main(argv: list[str] | None = None) -> int:
    if argv:
        print("不要把口令放在命令行参数里。直接运行后按提示输入。", file=sys.stderr)
        return 2
    first = getpass.getpass("访问口令: ")
    second = getpass.getpass("再输入一次: ")
    if not hmac_equal(first, second):
        print("两次输入不一致。", file=sys.stderr)
        return 2
    if is_weak_password(first):
        print("口令太弱。至少 12 位，且不能使用常见口令或纯数字。", file=sys.stderr)
        return 2
    print(hash_password(first))
    return 0


def hmac_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


if __name__ == "__main__":
    raise SystemExit(main())
