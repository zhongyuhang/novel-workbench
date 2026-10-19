"""Authenticated administration routes. Restore stays on the CLI."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import require_session
from app.core.config import Settings, get_settings
from app.schemas.backup import BackupListResponse, BackupResponse
from app.services import backup as backup_service
from app.services.backup import BackupManifest

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_session)],
)


def _response(manifest: BackupManifest) -> BackupResponse:
    return BackupResponse(
        id=manifest.backup_id,
        app_version=manifest.app_version,
        alembic_revision=manifest.alembic_revision,
        created_at=manifest.created_at,
    )


@router.post("/backups", response_model=BackupResponse, status_code=status.HTTP_201_CREATED)
def create_backup(settings: Annotated[Settings, Depends(get_settings)]) -> BackupResponse:
    return _response(backup_service.create_backup(settings))


@router.get("/backups", response_model=BackupListResponse)
def list_backups(settings: Annotated[Settings, Depends(get_settings)]) -> BackupListResponse:
    items = [_response(item) for item in backup_service.list_backups(settings)]
    latest = items[0].created_at if items else None
    return BackupListResponse(items=items, latest_success_at=latest)
