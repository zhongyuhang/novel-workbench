"""Volume routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_session
from app.schemas.catalog import (
    VolumeCreate,
    VolumeReorder,
    VolumeResponse,
    VolumeUpdate,
)
from app.services import catalog as catalog_service

router = APIRouter(tags=["volumes"], dependencies=[Depends(require_session)])


@router.get("/novels/{novel_id}/volumes", response_model=list[VolumeResponse])
def list_volumes(
    novel_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> list[VolumeResponse]:
    volumes = catalog_service.list_volumes(session, novel_id)
    return [VolumeResponse.model_validate(volume) for volume in volumes]


@router.post(
    "/novels/{novel_id}/volumes",
    response_model=VolumeResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_volume(
    novel_id: str,
    payload: VolumeCreate,
    session: Annotated[Session, Depends(get_db)],
) -> VolumeResponse:
    return VolumeResponse.model_validate(catalog_service.create_volume(session, novel_id, payload))


@router.post("/volumes/reorder", response_model=list[VolumeResponse])
def reorder_volumes(
    payload: VolumeReorder,
    session: Annotated[Session, Depends(get_db)],
) -> list[VolumeResponse]:
    volumes = catalog_service.reorder_volumes(session, payload)
    return [VolumeResponse.model_validate(volume) for volume in volumes]


@router.patch("/volumes/{volume_id}", response_model=VolumeResponse)
def update_volume(
    volume_id: str,
    payload: VolumeUpdate,
    session: Annotated[Session, Depends(get_db)],
) -> VolumeResponse:
    return VolumeResponse.model_validate(catalog_service.update_volume(session, volume_id, payload))


@router.delete("/volumes/{volume_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_volume(volume_id: str, session: Annotated[Session, Depends(get_db)]) -> Response:
    catalog_service.delete_volume(session, volume_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
