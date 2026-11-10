"""API v1 router aggregation (section 10)."""

from fastapi import APIRouter

from app.api.v1 import health, jobs, media, projects, subtitles, system

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(system.router, tags=["system"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(media.router, tags=["media"])
api_router.include_router(jobs.router, tags=["jobs"])
api_router.include_router(subtitles.router, tags=["subtitles"])

__all__ = ["api_router"]
