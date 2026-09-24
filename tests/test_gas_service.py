"""Tests for gas as a service of its own.

Gas shares the my.kommunal.uz cabinet with the management company but needs
nothing from it, so it can be configured without a management contract. The
same meter must not end up configured twice — once standalone and once as the
management entry's gas extension — because both produce the same entity ids.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.askuuz.api.base import TransientApiError
from custom_components.askuuz.const import DOMAIN

LOGIN = "custom_components.askuuz.api.management.ManagementApiClient.login"
GAS_DATA = "custom_components.askuuz.api.management.ManagementApiClient.get_gas_data"
DASHBOARD = "custom_components.askuuz.api.management.ManagementApiClient.get_dashboard"
ACCRUALS = "custom_components.askuuz.api.management.ManagementApiClient.get_accruals"
TOKENS = {"access_token": "bearer-1", "yandex_token": "yandex-1"}
GAS_ACCOUNT = "gas-9"
CREDENTIALS = {"username": "user", "password": "secret", "account_id": GAS_ACCOUNT}

GAS_PAYLOAD = {
    "customer_code": GAS_ACCOUNT,
    "current_balance": -12_000,
    "last_payment_sum": 80_000,
    "last_payment_date": "2026-03-02",
    "interraction": [
        {"period": "3.2026", "gas_consume": 40.5, "accrual": 65_000},
        {"period": "2.2026", "gas_consume": 55.0, "accrual": 88_000},
    ],
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Let Home Assistant load the integration from custom_components/."""
    return None


async def choose_gas(hass: HomeAssistant) -> dict[str, Any]:
    """Walk the flow to the credentials form with gas selected."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"service": "gas"})


class TestConfigFlow:
    """Adding gas on its own."""

    async def test_gas_is_offered_as_a_service(self, hass: HomeAssistant) -> None:
        """The dropdown lists gas alongside the other services."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        options = list(result["data_schema"].schema.values())[0].config["options"]
        assert "gas" in options

    async def test_entry_is_created_without_a_management_account(self, hass: HomeAssistant) -> None:
        """No management contract is involved in setting gas up."""
        form = await choose_gas(hass)

        with (
            patch(LOGIN, return_value=TOKENS),
            patch("custom_components.askuuz.async_setup_entry", return_value=True),
        ):
            result = await hass.config_entries.flow.async_configure(
                form["flow_id"], dict(CREDENTIALS)
            )
            await hass.async_block_till_done()

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == f"ASKU Gas {GAS_ACCOUNT}"
        assert result["data"] == {"service": "gas", **CREDENTIALS}

    async def test_outage_is_reported_as_cannot_connect(self, hass: HomeAssistant) -> None:
        """Gas gets the same error classification as every other service."""
        form = await choose_gas(hass)

        with patch(LOGIN, side_effect=TransientApiError("Request timeout")):
            result = await hass.config_entries.flow.async_configure(
                form["flow_id"], dict(CREDENTIALS)
            )

        assert result["errors"] == {"base": "cannot_connect"}


class TestDuplicateMeters:
    """The same meter must not be configured through both paths."""

    async def test_standalone_rejects_a_meter_held_by_management(self, hass: HomeAssistant) -> None:
        """A management entry already covering this gas account blocks it."""
        MockConfigEntry(
            domain=DOMAIN,
            data={
                "service": "management",
                "username": "user",
                "password": "secret",
                "account_id": "mgmt-1",
                "enable_gas": True,
                "gas_account_id": GAS_ACCOUNT,
            },
        ).add_to_hass(hass)

        form = await choose_gas(hass)

        with patch(LOGIN, return_value=TOKENS):
            result = await hass.config_entries.flow.async_configure(
                form["flow_id"], dict(CREDENTIALS)
            )

        assert result["errors"] == {"base": "already_configured"}

    async def test_management_rejects_a_meter_held_standalone(self, hass: HomeAssistant) -> None:
        """A standalone gas entry blocks the management gas extension."""
        MockConfigEntry(domain=DOMAIN, data={"service": "gas", **CREDENTIALS}).add_to_hass(hass)

        start = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        form = await hass.config_entries.flow.async_configure(
            start["flow_id"], {"service": "management"}
        )

        with patch(LOGIN, return_value=TOKENS):
            gas_step = await hass.config_entries.flow.async_configure(
                form["flow_id"],
                {
                    "username": "user",
                    "password": "secret",
                    "account_id": "mgmt-1",
                    "enable_gas": True,
                },
            )
            result = await hass.config_entries.flow.async_configure(
                gas_step["flow_id"], {"gas_account_id": GAS_ACCOUNT}
            )

        assert result["step_id"] == "gas"
        assert result["errors"] == {"base": "already_configured"}

    async def test_a_different_meter_is_accepted(self, hass: HomeAssistant) -> None:
        """An unrelated gas account is not blocked by an existing one."""
        MockConfigEntry(domain=DOMAIN, data={"service": "gas", **CREDENTIALS}).add_to_hass(hass)

        form = await choose_gas(hass)

        with (
            patch(LOGIN, return_value=TOKENS),
            patch("custom_components.askuuz.async_setup_entry", return_value=True),
        ):
            result = await hass.config_entries.flow.async_configure(
                form["flow_id"], {**CREDENTIALS, "account_id": "gas-other"}
            )
            await hass.async_block_till_done()

        assert result["type"] is FlowResultType.CREATE_ENTRY


class TestEntities:
    """What the entry produces once it is set up."""

    async def test_sensors_and_button_are_created(self, hass: HomeAssistant) -> None:
        """A standalone gas entry gets its own device, sensors and button."""
        entry = MockConfigEntry(
            domain=DOMAIN, data={"service": "gas", **CREDENTIALS}, title="ASKU Gas gas-9"
        )
        entry.add_to_hass(hass)

        with patch(LOGIN, return_value=TOKENS), patch(GAS_DATA, return_value=GAS_PAYLOAD):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        balance = hass.states.get("sensor.asku_uz_gas_gas_9_balance")
        assert balance is not None
        assert float(balance.state) == pytest.approx(12_000.0)

        consumption = hass.states.get("sensor.asku_uz_gas_gas_9_consumption")
        assert float(consumption.state) == pytest.approx(40.5)

        assert hass.states.get("button.asku_uz_gas_gas_9_refresh_data") is not None

    async def test_the_device_does_not_hang_off_a_management_device(
        self, hass: HomeAssistant
    ) -> None:
        """Standalone gas must not reference a management device that is absent."""
        entry = MockConfigEntry(domain=DOMAIN, data={"service": "gas", **CREDENTIALS})
        entry.add_to_hass(hass)

        with patch(LOGIN, return_value=TOKENS), patch(GAS_DATA, return_value=GAS_PAYLOAD):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        registry = dr.async_get(hass)
        devices = dr.async_entries_for_config_entry(registry, entry.entry_id)

        assert len(devices) == 1
        assert (DOMAIN, f"gas_{GAS_ACCOUNT}") in devices[0].identifiers
        assert devices[0].via_device_id is None


class TestManagementStillWorks:
    """The management service keeps its own gas extension.

    Management and gas now share a login base class, so this guards the path
    that existing installations are already using.
    """

    async def test_management_with_gas_extension(self, hass: HomeAssistant) -> None:
        """One management entry still yields both its own and gas entities."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                "service": "management",
                "username": "user",
                "password": "secret",
                "account_id": "mgmt-1",
                "enable_gas": True,
                "gas_account_id": GAS_ACCOUNT,
            },
        )
        entry.add_to_hass(hass)

        dashboard = {
            "balance": -50_000,
            "my_area": 60.0,
            "price": 1_500,
            "payments": [{"payment_amount": 120_000, "payment_date": "2026-03-01"}],
        }

        with (
            patch(LOGIN, return_value=TOKENS),
            patch(DASHBOARD, return_value=dashboard),
            patch(ACCRUALS, return_value={"current": []}),
            patch(GAS_DATA, return_value=GAS_PAYLOAD),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        management_balance = hass.states.get("sensor.asku_uz_management_mgmt_1_balance")
        assert management_balance is not None
        assert float(management_balance.state) == pytest.approx(50_000.0)

        gas_balance = hass.states.get("sensor.asku_uz_gas_gas_9_balance")
        assert gas_balance is not None
        assert float(gas_balance.state) == pytest.approx(12_000.0)

    async def test_management_without_gas(self, hass: HomeAssistant) -> None:
        """Without the extension enabled no gas entity appears."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                "service": "management",
                "username": "user",
                "password": "secret",
                "account_id": "mgmt-2",
            },
        )
        entry.add_to_hass(hass)

        dashboard = {"balance": 0, "my_area": 50.0, "price": 1_000, "payments": []}

        with (
            patch(LOGIN, return_value=TOKENS),
            patch(DASHBOARD, return_value=dashboard),
            patch(ACCRUALS, return_value={"current": []}),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        assert hass.states.get("sensor.asku_uz_management_mgmt_2_balance") is not None
        assert hass.states.get("sensor.asku_uz_gas_gas_9_balance") is None
