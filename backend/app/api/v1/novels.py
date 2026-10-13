"""Novel routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_session
from app.schemas.catalog import NovelCreate, NovelExportRequest, NovelResponse, NovelUpdate
from app.services import catalog as catalog_service
from app.services import exporting as export_service

router = APIRouter(
    prefix="/novels",
    tags=["novels"],
    dependencies=[Depends(require_session)],
)


@router.get("", response_model=list[NovelResponse])
def list_novels(session: Annotated[Session, Depends(get_db)]) -> list[NovelResponse]:
    return [NovelResponse.model_validate(novel) for novel in catalog_service.list_novels(session)]


@router.post("", response_model=NovelResponse, status_code=status.HTTP_201_CREATED)
def create_novel(
    payload: NovelCreate,
    session: Annotated[Session, Depends(get_db)],
) -> NovelResponse:
    return NovelResponse.model_validate(catalog_service.create_novel(session, payload))


@router.get("/{novel_id}", response_model=NovelResponse)
def get_novel(novel_id: str, session: Annotated[Session, Depends(get_db)]) -> NovelResponse:
    return NovelResponse.model_validate(catalog_service.get_novel(session, novel_id))


@router.patch("/{novel_id}", response_model=NovelResponse)
def update_novel(
    novel_id: str,
    payload: NovelUpdate,
    session: Annotated[Session, Depends(get_db)],
) -> NovelResponse:
    return NovelResponse.model_validate(catalog_service.update_novel(session, novel_id, payload))


@router.delete("/{novel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_novel(novel_id: str, session: Annotated[Session, Depends(get_db)]) -> Response:
    catalog_service.delete_novel(session, novel_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{novel_id}/export")
def export_novel(
    novel_id: str,
    payload: NovelExportRequest,
    session: Annotated[Session, Depends(get_db)],
) -> Response:
    exported = export_service.export_novel(session, novel_id, payload.format)
    return Response(
        content=exported.body.encode("utf-8"),
        media_type=exported.media_type,
        headers={"Content-Disposition": exported.disposition},
    )
