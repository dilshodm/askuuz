from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN
from .coordinator import GasDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities for Gas service."""
    coordinator: GasDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    account_id = entry.data["account_id"]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, f"gas_{account_id}")},
        name=f"ASKU UZ Gas {account_id}",
        manufacturer="ASKU UZ",
        model="Gas Supply",
    )

    async_add_entities(
        [
            RefreshDataButton(
                coordinator,
                entry,
                device_info,
            )
        ],
        update_before_add=False,
    )


class RefreshDataButton(CoordinatorEntity[GasDataUpdateCoordinator], ButtonEntity):
    """Button to refresh gas data."""

    _attr_has_entity_name = True
    _attr_device_class = ButtonDeviceClass.UPDATE
    _attr_translation_key = "refresh_data"

    def __init__(self, coordinator, entry, device_info):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = device_info

        account_id = entry.data["account_id"]
        self._attr_unique_id = f"{DOMAIN}_gas_{account_id}_refresh"

    async def async_press(self) -> None:
        """Handle button press."""
        await self.coordinator.async_request_refresh()
