from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ElectricityDataUpdateCoordinator
from ..const import DOMAIN

SENSORS = {
    "consumption": {
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL,
        "unit": "kWh",
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
    coordinator: ElectricityDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    account_id = entry.data["account_id"]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, f"electricity_{account_id}")},
        name=f"ASKU UZ Electricity {account_id}",
        manufacturer="ASKU UZ",
        model="Electricity",
    )

    entities = [
        ASKUBaseSensor(
            coordinator,
            entry,
            device_info,
            key,
            cfg,
        )
        for key, cfg in SENSORS.items()
    ]

    async_add_entities(entities, update_before_add=False)


class ASKUBaseSensor(CoordinatorEntity[ElectricityDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, device_info, key, cfg):
        super().__init__(coordinator)

        self._key = key
        self._with_attrs = cfg.get("attrs", False)

        self._attr_translation_key = key
        self._attr_device_class = cfg.get("device_class")
        self._attr_state_class = cfg.get("state_class")
        self._attr_native_unit_of_measurement = cfg.get("unit")

        account_id = entry.data["account_id"]
        self._attr_unique_id = f"{DOMAIN}_electricity_{account_id}_{key}"
        self._attr_device_info = device_info

    @property
    def native_value(self):
        return self.coordinator.data.get(self._key)

    @property
    def extra_state_attributes(self):
        if not self._with_attrs:
            return None

        data = self.coordinator.data or {}
        return {
            "account_id": data.get("account_id"),
            "current_period": data.get("current_period"),
            "balance": data.get("balance"),
            "consumption": data.get("consumption"),
            "accrual": data.get("accrual"),
            "last_payment": data.get("last_payment"),
            "data": data.get("data"),
        }
