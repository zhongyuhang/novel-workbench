"""Version 1 routes implemented so far."""

from fastapi import APIRouter

from app.api.v1 import auth, chapters, health, novels, volumes

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(auth.router)
router.include_router(novels.router)
router.include_router(volumes.router)
router.include_router(chapters.router)
