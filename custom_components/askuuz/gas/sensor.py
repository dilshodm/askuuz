from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN
from .coordinator import GasDataUpdateCoordinator

SENSORS = {
    "consumption": {
        "device_class": SensorDeviceClass.GAS,
        "state_class": SensorStateClass.TOTAL,
        "unit": "m³",
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
    coordinator: GasDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    account_id = entry.data["account_id"]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, f"gas_{account_id}")},
        name=f"ASKU UZ Gas {account_id}",
        manufacturer="ASKU UZ",
        model="Gas Supply",
    )

    entities = [
        ASKUGasSensor(
            coordinator,
            account_id,
            device_info,
            key,
            cfg,
        )
        for key, cfg in SENSORS.items()
    ]

    async_add_entities(entities, update_before_add=False)


class ASKUGasSensor(
    CoordinatorEntity[GasDataUpdateCoordinator],
    SensorEntity,
):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        account_id: str,
        device_info: DeviceInfo,
        key: str,
        cfg: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)

        self._key = key
        self._with_attrs = cfg.get("attrs", False)

        self._attr_translation_key = key
        self._attr_device_class = cfg.get("device_class")
        self._attr_state_class = cfg.get("state_class")
        self._attr_native_unit_of_measurement = cfg.get("unit")

        self._attr_unique_id = f"{DOMAIN}_gas_{account_id}_{key}"
        self._attr_device_info = device_info

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return data.get(self._key)

    @property
    def extra_state_attributes(self):
        if not self._with_attrs:
            return None
        return self.coordinator.data
