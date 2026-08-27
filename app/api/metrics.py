"""Operational metrics endpoint (JSON), shared with the dashboard."""

import time

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["metrics"])

_requests_total: int = 0
_request_duration_sum: float = 0.0
_failures_total: int = 0
_start_time: float = time.time()


class MetricsResponse(BaseModel):
    uptime_seconds: float
    requests_total: int
    requests_failed: int
    avg_duration_ms: float


@router.get("/metrics", response_model=MetricsResponse)
async def metrics() -> MetricsResponse:
    return MetricsResponse(**get_metrics_data())


def get_metrics_data() -> dict:
    """Return current operational counters (shared by the JSON endpoint and dashboard)."""
    avg_ms = (_request_duration_sum / _requests_total * 1000) if _requests_total > 0 else 0.0
    return {
        "uptime_seconds": time.time() - _start_time,
        "requests_total": _requests_total,
        "requests_failed": _failures_total,
        "avg_duration_ms": round(avg_ms, 2),
    }


class MetricsMiddleware:
    """ASGI middleware to track request metrics."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        global _requests_total, _request_duration_sum, _failures_total
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.time()
        _requests_total += 1
        try:
            await self.app(scope, receive, send)
        except Exception:
            _failures_total += 1
            raise
        finally:
            _request_duration_sum += time.time() - start
