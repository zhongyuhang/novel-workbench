"""Version 1 routes implemented so far."""

from fastapi import APIRouter

from app.api.v1 import ai, auth, chapters, health, memory, novels, quality, settings, volumes

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(auth.router)
router.include_router(novels.router)
router.include_router(volumes.router)
router.include_router(chapters.router)
router.include_router(settings.router)
router.include_router(ai.router)
router.include_router(memory.router)
router.include_router(quality.router)
