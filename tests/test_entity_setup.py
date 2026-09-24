"""Tests for platform setup when the coordinator has little or no data.

The account number identifies the device and the entities, and it is known
from the config entry. Reading it out of the coordinator's payload instead
meant that a fetch which returned nothing took the whole platform down with
``'NoneType' object is not subscriptable``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.askuuz.const import DOMAIN

WATER_FETCH = "custom_components.askuuz.water.coordinator.WaterDataUpdateCoordinator._fetch_data"
WATER_LOGIN = "custom_components.askuuz.water.coordinator.WaterDataUpdateCoordinator._login"
ENTRY_DATA = {
    "service": "water",
    "username": "12345678901234",
    "password": "secret",
    "account_id": "acc-1",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Let Home Assistant load the integration from custom_components/."""
    return None


async def setup_with_payload(hass: HomeAssistant, payload: dict[str, Any]) -> MockConfigEntry:
    """Set the water entry up with a coordinator returning ``payload``."""
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, title="ASKU Water acc-1")
    entry.add_to_hass(hass)

    with patch(WATER_LOGIN, return_value=None), patch(WATER_FETCH, return_value=payload):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return entry


async def test_entities_are_created_from_a_full_payload(hass: HomeAssistant) -> None:
    """The ordinary case still produces the three sensors and the button."""
    await setup_with_payload(hass, {"account_id": "acc-1", "balance": 1_000.0})

    assert hass.states.get("sensor.asku_uz_water_acc_1_balance") is not None
    assert hass.states.get("button.asku_uz_water_acc_1_refresh_data") is not None


async def test_payload_without_account_id_still_sets_up(hass: HomeAssistant) -> None:
    """A payload missing the account number must not take the platform down."""
    await setup_with_payload(hass, {"balance": 1_000.0})

    registry = hass.data["entity_registry"]
    unique_ids = {
        entity.unique_id for entity in registry.entities.values() if entity.platform == DOMAIN
    }

    # the identity comes from the config entry, not from the fetched payload
    assert f"{DOMAIN}_water_acc-1_balance" in unique_ids
