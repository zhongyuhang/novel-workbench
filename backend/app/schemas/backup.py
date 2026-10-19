"""Backup metadata returned to an authenticated client. Database bytes stay on disk."""

from datetime import datetime

from pydantic import BaseModel


class BackupResponse(BaseModel):
    id: str
    app_version: str
    alembic_revision: str
    created_at: datetime


class BackupListResponse(BaseModel):
    items: list[BackupResponse]
    latest_success_at: datetime | None = None
