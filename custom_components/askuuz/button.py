from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Dispatch button setup to service-specific implementation."""

    service = entry.data.get("service")

    if service == "electricity":
        from .electricity.button import async_setup_entry as electricity_setup

        await electricity_setup(hass, entry, async_add_entities)
        return

    elif service == "water":
        from .water.button import async_setup_entry as water_setup

        await water_setup(hass, entry, async_add_entities)
        return

    elif service == "tbo":
        from .tbo.button import async_setup_entry as tbo_setup

        await tbo_setup(hass, entry, async_add_entities)
        return

    elif service == "gas":
        from .gas.button import async_setup_entry as gas_setup

        await gas_setup(hass, entry, async_add_entities)
        return

    elif service == "management":
        from .management.button import async_setup_entry as management_setup

        await management_setup(hass, entry, async_add_entities)
        return

    # Safety fallback — should never happen if config_flow is correct
    raise ValueError(f"Unsupported service type '{service}' for {DOMAIN} integration")
