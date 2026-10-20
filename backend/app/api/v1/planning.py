"""Story plan, chapter outline, and scene card routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_session
from app.schemas.planning import (
    ChapterOutlineResponse,
    ChapterOutlineView,
    ChapterOutlineWrite,
    OutlineCandidateAccept,
    OutlineCandidateAcceptResult,
    OutlineCandidatePreview,
    OutlineCandidateRequest,
    PlanningConfirm,
    SceneCardPatch,
    SceneCardResponse,
    SceneCardWrite,
    SceneReorder,
    StoryArcCreate,
    StoryArcPatch,
    StoryArcReorder,
    StoryArcResponse,
    StoryPlanResponse,
    StoryPlanView,
    StoryPlanWrite,
    VolumeOutlineResponse,
    VolumeOutlineView,
    VolumeOutlineWrite,
)
from app.services import planning as planning_service

router = APIRouter(tags=["planning"], dependencies=[Depends(require_session)])


@router.get("/novels/{novel_id}/story-plan", response_model=StoryPlanView)
def get_story_plan(
    novel_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> StoryPlanView:
    return planning_service.get_story_plan(session, novel_id)


@router.put("/novels/{novel_id}/story-plan", response_model=StoryPlanResponse)
def save_story_plan(
    novel_id: str,
    payload: StoryPlanWrite,
    session: Annotated[Session, Depends(get_db)],
) -> StoryPlanResponse:
    return planning_service.save_story_plan(session, novel_id, payload)


@router.post("/novels/{novel_id}/story-plan/confirm", response_model=StoryPlanResponse)
def confirm_story_plan(
    novel_id: str,
    payload: PlanningConfirm,
    session: Annotated[Session, Depends(get_db)],
) -> StoryPlanResponse:
    return planning_service.confirm_story_plan(session, novel_id, payload)


@router.get(
    "/novels/{novel_id}/chapter-outlines",
    response_model=list[ChapterOutlineResponse],
)
def list_chapter_outlines(
    novel_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> list[ChapterOutlineResponse]:
    return planning_service.list_chapter_outlines(session, novel_id)


@router.get("/chapters/{chapter_id}/outline", response_model=ChapterOutlineView)
def get_chapter_outline(
    chapter_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> ChapterOutlineView:
    return planning_service.get_chapter_outline(session, chapter_id)


@router.put("/chapters/{chapter_id}/outline", response_model=ChapterOutlineResponse)
def save_chapter_outline(
    chapter_id: str,
    payload: ChapterOutlineWrite,
    session: Annotated[Session, Depends(get_db)],
) -> ChapterOutlineResponse:
    return planning_service.save_chapter_outline(session, chapter_id, payload)


@router.post("/chapters/{chapter_id}/outline/confirm", response_model=ChapterOutlineResponse)
def confirm_chapter_outline(
    chapter_id: str,
    payload: PlanningConfirm,
    session: Annotated[Session, Depends(get_db)],
) -> ChapterOutlineResponse:
    return planning_service.confirm_chapter_outline(session, chapter_id, payload)


@router.get("/chapters/{chapter_id}/scenes", response_model=list[SceneCardResponse])
def list_scenes(
    chapter_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> list[SceneCardResponse]:
    return planning_service.list_scenes(session, chapter_id)


@router.post(
    "/chapters/{chapter_id}/scenes",
    response_model=SceneCardResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_scene(
    chapter_id: str,
    payload: SceneCardWrite,
    session: Annotated[Session, Depends(get_db)],
) -> SceneCardResponse:
    return planning_service.create_scene(session, chapter_id, payload)


@router.patch("/scenes/{scene_id}", response_model=SceneCardResponse)
def update_scene(
    scene_id: str,
    payload: SceneCardPatch,
    session: Annotated[Session, Depends(get_db)],
) -> SceneCardResponse:
    return planning_service.update_scene(session, scene_id, payload)


@router.delete("/scenes/{scene_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scene(
    scene_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> Response:
    planning_service.delete_scene(session, scene_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/chapters/{chapter_id}/scenes/reorder", response_model=list[SceneCardResponse])
def reorder_scenes(
    chapter_id: str,
    payload: SceneReorder,
    session: Annotated[Session, Depends(get_db)],
) -> list[SceneCardResponse]:
    return planning_service.reorder_scenes(session, chapter_id, payload)


@router.get("/novels/{novel_id}/story-arcs", response_model=list[StoryArcResponse])
def list_story_arcs(
    novel_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> list[StoryArcResponse]:
    return planning_service.list_story_arcs(session, novel_id)


@router.post(
    "/novels/{novel_id}/story-arcs",
    response_model=StoryArcResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_story_arc(
    novel_id: str,
    payload: StoryArcCreate,
    session: Annotated[Session, Depends(get_db)],
) -> StoryArcResponse:
    return planning_service.create_story_arc(session, novel_id, payload)


@router.patch("/story-arcs/{arc_id}", response_model=StoryArcResponse)
def update_story_arc(
    arc_id: str,
    payload: StoryArcPatch,
    session: Annotated[Session, Depends(get_db)],
) -> StoryArcResponse:
    return planning_service.update_story_arc(session, arc_id, payload)


@router.delete("/story-arcs/{arc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_story_arc(
    arc_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> Response:
    planning_service.delete_story_arc(session, arc_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/novels/{novel_id}/story-arcs/reorder", response_model=list[StoryArcResponse])
def reorder_story_arcs(
    novel_id: str,
    payload: StoryArcReorder,
    session: Annotated[Session, Depends(get_db)],
) -> list[StoryArcResponse]:
    return planning_service.reorder_story_arcs(session, novel_id, payload)


@router.post("/story-arcs/{arc_id}/confirm", response_model=StoryArcResponse)
def confirm_story_arc(
    arc_id: str,
    payload: PlanningConfirm,
    session: Annotated[Session, Depends(get_db)],
) -> StoryArcResponse:
    return planning_service.confirm_story_arc(session, arc_id, payload)


@router.get(
    "/novels/{novel_id}/volume-outlines",
    response_model=list[VolumeOutlineResponse],
)
def list_volume_outlines(
    novel_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> list[VolumeOutlineResponse]:
    return planning_service.list_volume_outlines(session, novel_id)


@router.get("/volumes/{volume_id}/outline", response_model=VolumeOutlineView)
def get_volume_outline(
    volume_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> VolumeOutlineView:
    return planning_service.get_volume_outline(session, volume_id)


@router.put("/volumes/{volume_id}/outline", response_model=VolumeOutlineResponse)
def save_volume_outline(
    volume_id: str,
    payload: VolumeOutlineWrite,
    session: Annotated[Session, Depends(get_db)],
) -> VolumeOutlineResponse:
    return planning_service.save_volume_outline(session, volume_id, payload)


@router.post("/volumes/{volume_id}/outline/confirm", response_model=VolumeOutlineResponse)
def confirm_volume_outline(
    volume_id: str,
    payload: PlanningConfirm,
    session: Annotated[Session, Depends(get_db)],
) -> VolumeOutlineResponse:
    return planning_service.confirm_volume_outline(session, volume_id, payload)


@router.post(
    "/chapters/{chapter_id}/outline-candidate",
    response_model=OutlineCandidatePreview,
)
def preview_outline_candidate(
    chapter_id: str,
    payload: OutlineCandidateRequest,
    session: Annotated[Session, Depends(get_db)],
) -> OutlineCandidatePreview:
    return planning_service.preview_outline_candidate(session, chapter_id, payload)


@router.post(
    "/chapters/{chapter_id}/outline-candidate/accept",
    response_model=OutlineCandidateAcceptResult,
)
def accept_outline_candidate(
    chapter_id: str,
    payload: OutlineCandidateAccept,
    session: Annotated[Session, Depends(get_db)],
) -> OutlineCandidateAcceptResult:
    return planning_service.accept_outline_candidate(session, chapter_id, payload)
