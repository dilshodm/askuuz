from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .electricity.coordinator import ElectricityDataUpdateCoordinator
from .gas.coordinator import GasDataUpdateCoordinator
from .management.coordinator import ManagementDataUpdateCoordinator
from .tbo.coordinator import TboDataUpdateCoordinator
from .water.coordinator import WaterDataUpdateCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_REFRESH_DATA = "refresh_data"

REFRESH_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})

    async def handle_refresh_data(call: ServiceCall) -> None:
        """Handle refresh data service call.

        If entry_id is provided, refresh only that configuration.
        If entry_id is not provided, refresh all configurations.
        """
        entry_id = call.data.get("entry_id")

        if entry_id:
            # Refresh specific configuration
            if entry_id in hass.data.get(DOMAIN, {}):
                coordinator = hass.data[DOMAIN][entry_id]
                await coordinator.async_request_refresh()
        else:
            # Refresh all configurations
            for coordinator in hass.data.get(DOMAIN, {}).values():
                await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_DATA,
        handle_refresh_data,
        schema=REFRESH_DATA_SCHEMA,
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    service = entry.data["service"]

    # -------------------------------------------------
    # ELECTRICITY
    # -------------------------------------------------
    if service == "electricity":
        coordinator = ElectricityDataUpdateCoordinator(
            hass,
            entry_id=entry.entry_id,
            username=entry.data["username"],
            password=entry.data["password"],
            account_id=entry.data["account_id"],
        )

    # -------------------------------------------------
    # WATER
    # -------------------------------------------------
    elif service == "water":
        coordinator = WaterDataUpdateCoordinator(
            hass,
            entry_id=entry.entry_id,
            username=entry.data["username"],
            password=entry.data["password"],
            account_id=entry.data["account_id"],
        )

    # -------------------------------------------------
    # TBO
    # -------------------------------------------------
    elif service == "tbo":
        coordinator = TboDataUpdateCoordinator(
            hass,
            entry_id=entry.entry_id,
            username=entry.data["username"],
            password=entry.data["password"],
            account_id=entry.data["account_id"],
        )
    # -------------------------------------------------
    # GAS (standalone, no management contract needed)
    # -------------------------------------------------
    elif service == "gas":
        coordinator = GasDataUpdateCoordinator(
            hass,
            entry_id=entry.entry_id,
            username=entry.data["username"],
            password=entry.data["password"],
            account_id=entry.data["account_id"],
        )

    # -------------------------------------------------
    # MANAGEMENT
    # -------------------------------------------------

    elif service == "management":
        coordinator = ManagementDataUpdateCoordinator(
            hass,
            entry.entry_id,
            entry.data["username"],
            entry.data["password"],
            entry.data["account_id"],
            enable_gas=entry.data.get("enable_gas", False),
            gas_account_id=entry.data.get("gas_account_id"),
        )
    else:
        return False

    # первый запрос данных
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "button"])

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["sensor", "button"])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
