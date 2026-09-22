"""FastAPI authentication middleware."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from open_tam.auth.apikey import verify_api_key
from open_tam.persistence.database import Database
from open_tam.persistence.repositories import UserRepository

PUBLIC_PATHS = {"/health", "/api/health", "/alerts", "/"}
PUBLIC_PREFIXES = ("/static/", "/docs", "/openapi.json")


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, db: Database, enabled: bool = True) -> None:
        super().__init__(app)
        self.db = db
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if not self.enabled:
            request.state.user = None
            return await call_next(request)

        path = request.url.path
        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            request.state.user = None
            return await call_next(request)

        api_key = self._extract_api_key(request)
        if not api_key:
            return JSONResponse({"detail": "Missing API key"}, status_code=401)

        user_repo = UserRepository(self.db)
        users = user_repo.list_all()
        for user in users:
            if verify_api_key(api_key, user.api_key_hash):
                request.state.user = user
                return await call_next(request)

        return JSONResponse({"detail": "Invalid API key"}, status_code=401)

    def _extract_api_key(self, request: Request) -> str | None:
        header = request.headers.get("X-API-Key")
        if header:
            return header
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        return None


def get_current_user(request: Request) -> Any:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
