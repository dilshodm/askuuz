from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ManagementDataUpdateCoordinator
from ..const import DOMAIN

SENSORS = {
    "consumption": {
        "unit": "m²",
    },
    "accrual": {
        "device_class": SensorDeviceClass.MONETARY,
        "unit": "UZS",
    },
    "balance": {
        "device_class": SensorDeviceClass.MONETARY,
        "unit": "UZS",
        "attrs": True,
    },
}


async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities) -> None:
    coordinator: ManagementDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    account_id = entry.data["account_id"]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, f"management_{account_id}")},
        name=f"ASKU UZ Management {account_id}",
        manufacturer="ASKU UZ",
        model="Management Company",
    )

    entities = [
        ASKUMgmtSensor(
            coordinator,
            account_id,
            device_info,
            key,
            cfg,
        )
        for key, cfg in SENSORS.items()
    ]

    async_add_entities(entities, update_before_add=False)


class ASKUMgmtSensor(
    CoordinatorEntity[ManagementDataUpdateCoordinator],
    SensorEntity,
):
    _attr_has_entity_name = True

    def __init__(self, coordinator, account_id, device_info, key, cfg):
        super().__init__(coordinator)

        self._key = key
        self._with_attrs = cfg.get("attrs", False)

        self._attr_translation_key = key
        self._attr_device_class = cfg.get("device_class")
        self._attr_native_unit_of_measurement = cfg.get("unit")

        self._attr_unique_id = f"{DOMAIN}_management_{account_id}_{key}"
        self._attr_device_info = device_info

    @property
    def native_value(self):
        return self.coordinator.data.get(self._key)

    @property
    def extra_state_attributes(self):
        if not self._with_attrs:
            return None
        return self.coordinator.data
