"""Model configuration routes. Payloads never echo an API key."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_session
from app.schemas.ai import (
    ModelConfigPatch,
    ModelConfigResponse,
    ModelConfigWrite,
    ModelTestRequest,
    ModelTestResponse,
    ProviderPresetResponse,
)
from app.services import model_configs as model_service

router = APIRouter(
    prefix="/settings/models",
    tags=["settings"],
    dependencies=[Depends(require_session)],
)


@router.get("/presets", response_model=list[ProviderPresetResponse])
def list_presets() -> list[ProviderPresetResponse]:
    return model_service.list_provider_presets()


@router.get("", response_model=list[ModelConfigResponse])
def list_models(session: Annotated[Session, Depends(get_db)]) -> list[ModelConfigResponse]:
    return model_service.list_model_configs(session)


@router.post("", response_model=ModelConfigResponse, status_code=status.HTTP_201_CREATED)
def create_model(
    payload: ModelConfigWrite,
    session: Annotated[Session, Depends(get_db)],
) -> ModelConfigResponse:
    return model_service.create_model_config(session, payload)


@router.post("/test", response_model=ModelTestResponse)
def test_model(
    payload: ModelTestRequest,
    session: Annotated[Session, Depends(get_db)],
) -> ModelTestResponse:
    return model_service.test_model_config(session, payload)


@router.get("/{config_id}", response_model=ModelConfigResponse)
def get_model(
    config_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> ModelConfigResponse:
    return model_service.get_model_config(session, config_id)


@router.patch("/{config_id}", response_model=ModelConfigResponse)
def update_model(
    config_id: str,
    payload: ModelConfigPatch,
    session: Annotated[Session, Depends(get_db)],
) -> ModelConfigResponse:
    return model_service.update_model_config(session, config_id, payload)


@router.post("/{config_id}/test", response_model=ModelTestResponse)
def test_saved_model(
    config_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> ModelTestResponse:
    return model_service.test_saved_model_config(session, config_id)


@router.put("/{config_id}/default", response_model=ModelConfigResponse)
def set_default_model(
    config_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> ModelConfigResponse:
    return model_service.set_default_model_config(session, config_id)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model(config_id: str, session: Annotated[Session, Depends(get_db)]) -> Response:
    model_service.delete_model_config(session, config_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
