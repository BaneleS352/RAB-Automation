"""Central router that aggregates all API sub-routers."""

from fastapi import APIRouter

from app.api.dashboard import router as dashboard_router
from app.api.health import router as health_router
from app.api.rab import router as rab_router
from app.api.teams import router as teams_router
from app.api.webhooks import router as webhooks_router

api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(webhooks_router)
api_router.include_router(teams_router)
api_router.include_router(rab_router)
api_router.include_router(dashboard_router)
