from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ManagementDataUpdateCoordinator
from ..const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities for Management service."""
    coordinator: ManagementDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    account_id = entry.data["account_id"]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, f"management_{account_id}")},
        name=f"ASKU UZ Management {account_id}",
        manufacturer="ASKU UZ",
        model="Management",
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


class RefreshDataButton(CoordinatorEntity[ManagementDataUpdateCoordinator], ButtonEntity):
    """Button to refresh management data."""

    _attr_has_entity_name = True
    _attr_device_class = ButtonDeviceClass.UPDATE
    _attr_translation_key = "refresh_data"

    def __init__(self, coordinator, entry, device_info):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = device_info

        account_id = entry.data["account_id"]
        self._attr_unique_id = f"{DOMAIN}_management_{account_id}_refresh"

    async def async_press(self) -> None:
        """Handle button press."""
        await self.coordinator.async_request_refresh()
