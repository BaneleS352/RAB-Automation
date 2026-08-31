"""Optional shared-secret access control for all HTTP routes."""

import hmac
import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings

logger = logging.getLogger(__name__)

_ACCESS_COOKIE = "rab_access_token"


class AccessTokenMiddleware(BaseHTTPMiddleware):
    """Require ``ACCESS_TOKEN`` on every route except ``/static`` when configured.

    The token may be supplied via ``Authorization: Bearer <token>``,
    ``X-API-Key: <token>``, the ``?access_token=<token>`` query string (used by
    the dashboard, which also sets a short-lived cookie for subsequent page
    loads), or the ``rab_access_token`` cookie.

    When ``ACCESS_TOKEN`` is empty the middleware is a no-op, so local dev and
    the test suite are unaffected until a token is configured.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        token = get_settings().ACCESS_TOKEN
        if not token:
            return await call_next(request)

        if request.url.path == "/static" or request.url.path.startswith("/static/"):
            return await call_next(request)

        if hmac.compare_digest(self._token_from(request), token):
            response = await call_next(request)
            if request.query_params.get("access_token"):
                response.set_cookie(
                    _ACCESS_COOKIE,
                    token,
                    max_age=3600,
                    httponly=True,
                    secure=request.url.scheme == "https",
                    samesite="lax",
                    path="/",
                )
            return response

        logger.warning("Unauthorized request to %s", request.url.path)
        return JSONResponse({"status": "error", "detail": "Unauthorized"}, status_code=401)

    @staticmethod
    def _token_from(request: Request) -> str:
        authz = request.headers.get("authorization", "")
        if authz.lower().startswith("bearer "):
            return authz[7:].strip()
        api_key = request.headers.get("x-api-key")
        if api_key:
            return api_key.strip()
        cookie = request.cookies.get(_ACCESS_COOKIE)
        if cookie:
            return cookie.strip()
        return (request.query_params.get("access_token") or "").strip()
