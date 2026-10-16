"""Restore a backup into a SQLite file. Stop the app before running this."""

import argparse
import sys
from pathlib import Path

from app.core.errors import BackupFailed, RestoreTargetExists
from app.services.backup import restore_backup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把一份备份恢复到新的 SQLite 文件。")
    parser.add_argument("--backup", required=True, type=Path, help="备份目录，内含 manifest.json")
    parser.add_argument("--database", required=True, type=Path, help="恢复后的数据库文件路径")
    parser.add_argument(
        "--force",
        action="store_true",
        help="目标已存在时先把现有文件改名，再写入恢复结果",
    )
    args = parser.parse_args(argv)
    try:
        manifest = restore_backup(args.backup, args.database, replace=args.force)
    except RestoreTargetExists as exc:
        print(exc.message, file=sys.stderr)
        return 2
    except BackupFailed as exc:
        print(exc.message, file=sys.stderr)
        return 1
    print(
        "已恢复 "
        f"{manifest.backup_id} "
        f"（应用 {manifest.app_version}，迁移 {manifest.alembic_revision}）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
