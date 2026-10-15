"""Bearer token check for /api. Constant-time comparison over SHA-256 digests."""

from __future__ import annotations

import hashlib
import hmac

from fastapi import Header, HTTPException, Request, status


def tokens_match(provided: str, expected: str) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(hashlib.sha256(provided.encode()).digest(), hashlib.sha256(expected.encode()).digest())


def require_dashboard_token(request: Request, authorization: str | None = Header(default=None)) -> None:
    expected: str = request.app.state.settings.dashboard_token
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "DASHBOARD_TOKEN no configurado: todas las rutas /api están cerradas")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta Authorization: Bearer <token>",
                            headers={"WWW-Authenticate": "Bearer"})
    if not tokens_match(authorization[7:].strip(), expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido", headers={"WWW-Authenticate": "Bearer"})
