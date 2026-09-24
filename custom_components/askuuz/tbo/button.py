from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import TboDataUpdateCoordinator
from ..const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities for TBO service."""
    coordinator: TboDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    account_id = entry.data["account_id"]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, f"tbo_{account_id}")},
        name=f"ASKU UZ TBO {account_id}",
        manufacturer="ASKU UZ",
        model="TBO",
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


class RefreshDataButton(CoordinatorEntity[TboDataUpdateCoordinator], ButtonEntity):
    """Button to refresh TBO data."""

    _attr_has_entity_name = True
    _attr_device_class = ButtonDeviceClass.UPDATE
    _attr_translation_key = "refresh_data"

    def __init__(self, coordinator, entry, device_info):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = device_info

        account_id = entry.data["account_id"]
        self._attr_unique_id = f"{DOMAIN}_tbo_{account_id}_refresh"

    async def async_press(self) -> None:
        """Handle button press."""
        await self.coordinator.async_request_refresh()
