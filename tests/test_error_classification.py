"""Tests for telling a refused login apart from a temporary transport failure.

Reporting a network blip as ``ConfigEntryAuthFailed`` sends the config entry
into reauth, where it stays until the user intervenes — so the distinction
decides whether a working installation survives a flaky connection.
"""

from __future__ import annotations

import asyncio

import aiohttp
import pytest
from api.base import ApiError, AuthError, TransientApiError, is_transient


class TestIsTransient:
    """Which failures are worth retrying."""

    @pytest.mark.parametrize(
        "err",
        [
            TransientApiError("Request timeout"),
            TransientApiError("HTTP client error"),
            asyncio.TimeoutError(),
            aiohttp.ClientConnectionError(),
            aiohttp.ClientOSError(),
        ],
    )
    def test_transport_failures_are_transient(self, err: BaseException) -> None:
        """Timeouts and connection errors are temporary, not bad credentials."""
        assert is_transient(err) is True

    @pytest.mark.parametrize(
        "err",
        [
            AuthError("API error 401: unauthorized"),
            ApiError("API error 404: not found"),
            ApiError("Invalid PIN_AUTH response"),
            RuntimeError("Login failed"),
            ValueError("nonsense"),
        ],
    )
    def test_refusals_are_not_transient(self, err: BaseException) -> None:
        """A refusal or a malformed response is not a transport problem."""
        assert is_transient(err) is False

    def test_auth_error_is_an_api_error(self) -> None:
        """Callers catching ApiError still catch AuthError."""
        assert issubclass(AuthError, ApiError)
        assert issubclass(TransientApiError, ApiError)
