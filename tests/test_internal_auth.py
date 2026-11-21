"""Regression tests for the internal API fail-closed boundary.

The story/payment routers require a private bot-to-backend token.
End-to-end payment provider verification, database migrations, and delivery
recovery still need dedicated integration tests before deployment.
"""
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend.app.internal_auth import require_internal_token


class Settings:
    backend_internal_token = "Q" * 40


def test_missing_internal_secret_fails_closed():
    with patch("backend.app.internal_auth.get_settings", return_value=type("Empty", (), {"backend_internal_token": ""})()):
        with pytest.raises(HTTPException) as exc:
            require_internal_token("anything")
        assert exc.value.status_code == 503


def test_missing_or_bad_client_token_rejected():
    with patch("backend.app.internal_auth.get_settings", return_value=Settings()):
        for supplied in (None, "", "invalid"):
            with pytest.raises(HTTPException) as exc:
                require_internal_token(supplied)
            assert exc.value.status_code == 401


def test_good_token_accepted():
    with patch("backend.app.internal_auth.get_settings", return_value=Settings()):
        assert require_internal_token("Q" * 40) is None
