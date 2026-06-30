"""Health and root endpoints."""

import logging

from fastapi import APIRouter, Request

from app.models.responses import HealthResponse, RootResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=RootResponse, tags=["root"])
async def root(request: Request) -> RootResponse:
    """Return basic service information."""
    settings = request.app.state.settings
    return RootResponse(service=settings.APP_NAME, status="running")


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health(request: Request) -> HealthResponse:
    """Health check endpoint."""
    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service=settings.APP_NAME,
        environment=settings.APP_ENV,
    )
