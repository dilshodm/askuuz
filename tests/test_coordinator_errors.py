"""Tests for how a coordinator reports a failed login to Home Assistant.

``ConfigEntryAuthFailed`` puts the config entry into reauth and stops the
retry loop, so it must be reserved for credentials the service actually
refused. Everything temporary has to stay an ``UpdateFailed``.
"""

from __future__ import annotations

import asyncio

import aiohttp
import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.askuuz.api.base import ApiError, AuthError, TransientApiError
from custom_components.askuuz.base_coordinator import BaseASKUCoordinator


class TestLoginError:
    """Mapping a login exception onto the right Home Assistant error."""

    @pytest.mark.parametrize(
        "err",
        [
            TransientApiError("Request timeout"),
            TransientApiError("HTTP client error"),
            asyncio.TimeoutError(),
            aiohttp.ClientConnectionError(),
        ],
    )
    def test_transient_failures_stay_retryable(self, err: Exception) -> None:
        """A blip must not send a working entry into reauth."""
        assert isinstance(BaseASKUCoordinator._login_error(err), UpdateFailed)

    @pytest.mark.parametrize(
        "err",
        [
            AuthError("API error 401: unauthorized"),
            ApiError("Invalid PIN_AUTH response"),
            RuntimeError("Login failed"),
        ],
    )
    def test_refusals_ask_for_reauthentication(self, err: Exception) -> None:
        """A refused credential is what reauth exists for."""
        assert isinstance(BaseASKUCoordinator._login_error(err), ConfigEntryAuthFailed)

    def test_the_cause_is_kept_in_the_message(self) -> None:
        """The original reason survives into the log line."""
        mapped = BaseASKUCoordinator._login_error(ApiError("Invalid PIN_AUTH response"))

        assert "Invalid PIN_AUTH response" in str(mapped)
