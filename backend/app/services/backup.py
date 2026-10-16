"""Consistent SQLite backups and CLI restore.

Backup bytes stay under the data directory. API responses carry metadata only.
"""

import json
import logging
import secrets
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine.url import make_url

from app import __version__
from app.core.config import Settings
from app.core.errors import BackupFailed, RestoreTargetExists

logger = logging.getLogger("app.backup")

BACKUP_FORMAT = "ai-novel-writer-backup-v1"
_DATABASE_NAME = "database.sqlite"
_MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True)
class BackupManifest:
    backup_id: str
    app_version: str
    alembic_revision: str
    created_at: datetime

    def as_json(self) -> dict[str, str]:
        return {
            "format": BACKUP_FORMAT,
            "id": self.backup_id,
            "app_version": self.app_version,
            "alembic_revision": self.alembic_revision,
            "created_at": self.created_at.isoformat(),
        }


def backups_dir(settings: Settings) -> Path:
    return settings.resolved_data_dir / "backups"


def create_backup(settings: Settings, *, now: datetime | None = None) -> BackupManifest:
    source = sqlite_database_path(settings.resolved_database_url)
    if not source.is_file():
        raise BackupFailed("数据库文件还不存在，无法备份。")

    created_at = datetime.now(UTC) if now is None else now
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    backup_id = _new_backup_id(created_at)
    directory = backups_dir(settings) / backup_id
    directory.mkdir(parents=True, exist_ok=False)
    _restrict(directory)
    try:
        _checkpoint(source)
        copy_sqlite(source, directory / _DATABASE_NAME)
        revision = read_alembic_revision(directory / _DATABASE_NAME)
        manifest = BackupManifest(
            backup_id=backup_id,
            app_version=__version__,
            alembic_revision=revision,
            created_at=created_at,
        )
        manifest_path = directory / _MANIFEST_NAME
        manifest_path.write_text(
            json.dumps(manifest.as_json(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _restrict(manifest_path)
    except BackupFailed:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(directory, ignore_errors=True)
        logger.exception("backup failed id=%s", backup_id)
        raise BackupFailed("备份没有完成。") from exc
    logger.info("backup created id=%s", backup_id)
    return manifest


def list_backups(settings: Settings) -> list[BackupManifest]:
    root = backups_dir(settings)
    if not root.is_dir():
        return []
    found: list[BackupManifest] = []
    for child in root.iterdir():
        if not child.is_dir() or not _safe_backup_id(child.name):
            continue
        if not (child / _MANIFEST_NAME).is_file() or not (child / _DATABASE_NAME).is_file():
            continue
        try:
            found.append(read_manifest(child))
        except BackupFailed:
            logger.warning("skipping unreadable backup id=%s", child.name)
    found.sort(key=lambda item: item.created_at, reverse=True)
    return found


def restore_backup(
    backup_dir: Path,
    database_path: Path,
    *,
    replace: bool = False,
) -> BackupManifest:
    if not backup_dir.is_dir() or not _safe_backup_id(backup_dir.name):
        raise BackupFailed("找不到这份备份。")
    manifest = read_manifest(backup_dir)
    source = backup_dir / _DATABASE_NAME
    if not source.is_file():
        raise BackupFailed("备份里没有数据库文件。")

    destination = database_path.expanduser()
    if not destination.is_absolute():
        destination = Path.cwd() / destination
    if destination.exists():
        if not replace:
            raise RestoreTargetExists()
        _retire_existing(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    copy_sqlite(source, destination)
    restored = read_alembic_revision(destination)
    if restored != manifest.alembic_revision:
        destination.unlink(missing_ok=True)
        raise BackupFailed("恢复后的迁移版本与备份清单不一致。")
    logger.info("backup restored id=%s", manifest.backup_id)
    return manifest


def read_manifest(backup_dir: Path) -> BackupManifest:
    path = backup_dir / _MANIFEST_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise BackupFailed("备份清单无法读取。") from exc
    if not isinstance(payload, dict):
        raise BackupFailed("备份清单无法读取。")
    if payload.get("format") != BACKUP_FORMAT:
        raise BackupFailed("备份格式无法识别。")
    backup_id = _required_text(payload.get("id"))
    app_version = _required_text(payload.get("app_version"))
    revision = _required_text(payload.get("alembic_revision"))
    created_raw = _required_text(payload.get("created_at"))
    if backup_id is None or app_version is None or revision is None or created_raw is None:
        raise BackupFailed("备份清单无法读取。")
    if backup_id != backup_dir.name or not _safe_backup_id(backup_id):
        raise BackupFailed("备份清单与目录不一致。")
    try:
        created_at = datetime.fromisoformat(created_raw)
    except ValueError as exc:
        raise BackupFailed("备份清单无法读取。") from exc
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return BackupManifest(
        backup_id=backup_id,
        app_version=app_version,
        alembic_revision=revision,
        created_at=created_at,
    )


def sqlite_database_path(database_url: str) -> Path:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise BackupFailed("当前只支持 SQLite 备份。")
    database = url.database
    if database is None or database == ":memory:" or not database.strip():
        raise BackupFailed("内存数据库不能备份。")
    path = Path(database)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def copy_sqlite(source: Path, destination: Path) -> None:
    if destination.exists():
        destination.unlink()
    source_conn = sqlite3.connect(source, timeout=30)
    try:
        destination_conn = sqlite3.connect(destination, timeout=30)
        try:
            source_conn.backup(destination_conn)
        finally:
            destination_conn.close()
    except sqlite3.Error as exc:
        destination.unlink(missing_ok=True)
        raise BackupFailed("备份没有完成。") from exc
    finally:
        source_conn.close()
    _restrict(destination)


def read_alembic_revision(database: Path) -> str:
    connection = sqlite3.connect(database, timeout=30)
    try:
        try:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.Error as exc:
            raise BackupFailed("数据库没有迁移版本。") from exc
    finally:
        connection.close()
    if row is None or not isinstance(row[0], str) or not row[0].strip():
        raise BackupFailed("数据库没有迁移版本。")
    return row[0]


def _checkpoint(source: Path) -> None:
    connection = sqlite3.connect(source, timeout=30)
    try:
        connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
    except sqlite3.Error:
        logger.warning("sqlite checkpoint skipped")
    finally:
        connection.close()


def _new_backup_id(now: datetime) -> str:
    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(3)}"


def _required_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _safe_backup_id(value: str) -> bool:
    if len(value) < 8 or len(value) > 80 or not value.isascii():
        return False
    return all(character.isalnum() or character in {"-", "_"} for character in value)


def _restrict(path: Path) -> None:
    mode = 0o700 if path.is_dir() else 0o600
    try:
        path.chmod(mode)
    except OSError:
        logger.warning("could not restrict backup permissions")


def _retire_existing(destination: Path) -> None:
    retired = destination.with_name(destination.name + ".before-restore")
    suffix = 1
    while retired.exists():
        retired = destination.with_name(f"{destination.name}.before-restore-{suffix}")
        suffix += 1
    destination.replace(retired)
    logger.info("existing database renamed before restore")
