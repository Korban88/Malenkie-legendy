"""Fail-closed protection for internal bot-to-backend API operations.

Never reuse a leaked Telegram/API key as this credential. Use an independent,
cryptographically random 32+ character secret stored outside the repository.
"""
import hmac

from fastapi import Header, HTTPException

from .config import get_settings


def require_internal_token(
    x_legend_internal_key: str | None = Header(default=None, alias="X-Legend-Internal-Key"),
) -> None:
    expected = get_settings().backend_internal_token
    if not expected or len(expected) < 32:
        raise HTTPException(status_code=503, detail="Internal API access is not configured")
    if not x_legend_internal_key or not hmac.compare_digest(x_legend_internal_key, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")
