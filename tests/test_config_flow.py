"""Tests for the config and reauthentication flows.

These need Home Assistant itself, so they run through
``pytest-homeassistant-custom-component``. The rest of the suite deliberately
does not.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.askuuz.api.base import ApiError, TransientApiError
from custom_components.askuuz.const import DOMAIN

WATER_LOGIN = "custom_components.askuuz.api.water.WaterApiClient.login"
CREDENTIALS = {"username": "12345678901234", "password": "secret", "account_id": "acc-1"}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Let Home Assistant load the integration from custom_components/."""
    return None


async def start_credentials_step(hass: HomeAssistant) -> dict[str, Any]:
    """Walk the flow as far as the credentials form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"service": "water"})


class TestCredentialErrors:
    """A refusal and an outage must not look the same to the user."""

    async def test_transient_failure_reports_cannot_connect(self, hass: HomeAssistant) -> None:
        """A timeout is a connection problem, not a wrong password."""
        form = await start_credentials_step(hass)

        with patch(WATER_LOGIN, side_effect=TransientApiError("Request timeout")):
            result = await hass.config_entries.flow.async_configure(
                form["flow_id"], dict(CREDENTIALS)
            )

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "cannot_connect"}

    async def test_refusal_reports_invalid_auth(self, hass: HomeAssistant) -> None:
        """A service that refuses the PIN means the credentials are wrong."""
        form = await start_credentials_step(hass)

        with patch(WATER_LOGIN, side_effect=ApiError("Invalid PIN_AUTH response")):
            result = await hass.config_entries.flow.async_configure(
                form["flow_id"], dict(CREDENTIALS)
            )

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_auth"}

    async def test_empty_token_reports_invalid_auth(self, hass: HomeAssistant) -> None:
        """A login that returns nothing usable is an auth failure."""
        form = await start_credentials_step(hass)

        with patch(WATER_LOGIN, return_value=""):
            result = await hass.config_entries.flow.async_configure(
                form["flow_id"], dict(CREDENTIALS)
            )

        assert result["errors"] == {"base": "invalid_auth"}

    async def test_the_form_keeps_what_was_typed(self, hass: HomeAssistant) -> None:
        """A failed attempt must not make the user retype the account number."""
        form = await start_credentials_step(hass)

        with patch(WATER_LOGIN, side_effect=TransientApiError("Request timeout")):
            result = await hass.config_entries.flow.async_configure(
                form["flow_id"], dict(CREDENTIALS)
            )

        suggested = {
            key.schema: key.description.get("suggested_value")
            for key in result["data_schema"].schema
            if key.description
        }
        assert suggested["username"] == CREDENTIALS["username"]
        assert suggested["account_id"] == CREDENTIALS["account_id"]


class TestEntryCreation:
    """The happy path still works."""

    async def test_entry_is_created(self, hass: HomeAssistant) -> None:
        """A successful login stores the credentials and names the entry."""
        form = await start_credentials_step(hass)

        with (
            patch(WATER_LOGIN, return_value="token-123"),
            patch("custom_components.askuuz.async_setup_entry", return_value=True),
        ):
            result = await hass.config_entries.flow.async_configure(
                form["flow_id"], dict(CREDENTIALS)
            )
            await hass.async_block_till_done()

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "ASKU Water acc-1"
        assert result["data"] == {"service": "water", **CREDENTIALS}

    async def test_duplicate_is_rejected(self, hass: HomeAssistant) -> None:
        """The same service, username and account cannot be added twice."""
        MockConfigEntry(domain=DOMAIN, data={"service": "water", **CREDENTIALS}).add_to_hass(hass)
        form = await start_credentials_step(hass)

        with patch(WATER_LOGIN, return_value="token-123"):
            result = await hass.config_entries.flow.async_configure(
                form["flow_id"], dict(CREDENTIALS)
            )

        assert result["errors"] == {"base": "already_configured"}


class TestReauth:
    """A changed password can be fixed without deleting the entry."""

    async def start(self, hass: HomeAssistant) -> tuple[MockConfigEntry, dict[str, Any]]:
        """Create an entry and open its reauth flow."""
        entry = MockConfigEntry(domain=DOMAIN, data={"service": "water", **CREDENTIALS})
        entry.add_to_hass(hass)

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
            data=dict(entry.data),
        )
        return entry, result

    async def test_reauth_step_is_supported(self, hass: HomeAssistant) -> None:
        """The flow offers a reauth form instead of failing with an unknown step."""
        _, result = await self.start(hass)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"
        # Home Assistant adds its own "name" placeholder alongside ours
        assert result["description_placeholders"]["username"] == CREDENTIALS["username"]

    async def test_new_password_is_stored(self, hass: HomeAssistant) -> None:
        """A valid new password updates the entry and ends the flow."""
        entry, result = await self.start(hass)

        with (
            patch(WATER_LOGIN, return_value="token-123"),
            patch("custom_components.askuuz.async_setup_entry", return_value=True),
        ):
            done = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"password": "new-secret"}
            )
            await hass.async_block_till_done()

        assert done["type"] is FlowResultType.ABORT
        assert done["reason"] == "reauth_successful"
        assert entry.data["password"] == "new-secret"
        assert entry.data["username"] == CREDENTIALS["username"]

    async def test_wrong_password_keeps_asking(self, hass: HomeAssistant) -> None:
        """A password the service refuses leaves the entry untouched."""
        entry, result = await self.start(hass)

        with patch(WATER_LOGIN, side_effect=ApiError("Invalid PIN_AUTH response")):
            again = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"password": "still-wrong"}
            )

        assert again["type"] is FlowResultType.FORM
        assert again["errors"] == {"base": "invalid_auth"}
        assert entry.data["password"] == CREDENTIALS["password"]

    async def test_outage_during_reauth_is_not_an_auth_error(self, hass: HomeAssistant) -> None:
        """A timeout while reauthenticating reports a connection problem."""
        _, result = await self.start(hass)

        with patch(WATER_LOGIN, side_effect=TransientApiError("Request timeout")):
            again = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"password": "secret"}
            )

        assert again["errors"] == {"base": "cannot_connect"}
