"""Novel package routes. Markdown/TXT export stays on the novels router."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_session
from app.core.errors import PackageInvalid
from app.schemas.catalog import NovelResponse
from app.schemas.portable import (
    PortableCounts,
    PortableImportResponse,
    PortablePreviewResponse,
)
from app.services import portable as portable_service
from app.services.portable import PackagePlan

router = APIRouter(tags=["novels"], dependencies=[Depends(require_session)])


def _read_upload(upload: UploadFile) -> bytes:
    raw = upload.file.read(portable_service.MAX_UPLOAD_BYTES + 1)
    if not isinstance(raw, bytes):
        raise PackageInvalid("作品包无法读取。没有写入任何数据。")
    if len(raw) == 0:
        raise PackageInvalid("作品包是空的。没有写入任何数据。")
    if len(raw) > portable_service.MAX_UPLOAD_BYTES:
        raise PackageInvalid("作品包超过 64MB。没有写入任何数据。")
    return raw


def _preview_model(plan: PackagePlan) -> PortablePreviewResponse:
    public_map = dict(list(plan.conflict_map.items())[:500])
    return PortablePreviewResponse(
        format=portable_service.FORMAT,
        format_version=plan.format_version,
        novel_title=plan.novel_title,
        can_import=plan.can_import,
        message=plan.message,
        created=PortableCounts.model_validate(plan.created.as_dict()),
        skipped=PortableCounts.model_validate(plan.skipped.as_dict()),
        conflicts=PortableCounts.model_validate(plan.conflicts.as_dict()),
        invalid=PortableCounts.model_validate(plan.invalid.as_dict()),
        warnings=plan.warnings,
        invalid_reasons=plan.invalid_reasons,
        conflict_map=public_map,
    )


@router.post("/novels/{novel_id}/portable-export")
def export_portable_novel(
    novel_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> Response:
    exported = portable_service.export_novel_package(session, novel_id)
    return Response(
        content=exported.body,
        media_type=exported.media_type,
        headers={"Content-Disposition": exported.disposition},
    )


@router.post("/novels/import/preview", response_model=PortablePreviewResponse)
def preview_portable_import(
    session: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
) -> PortablePreviewResponse:
    return _preview_model(portable_service.preview_package(session, _read_upload(file)))


@router.post(
    "/novels/import",
    response_model=PortableImportResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_portable_novel(
    session: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
) -> PortableImportResponse:
    novel, plan = portable_service.import_package(session, _read_upload(file))
    return PortableImportResponse(
        novel=NovelResponse.model_validate(novel),
        preview=_preview_model(plan),
    )
