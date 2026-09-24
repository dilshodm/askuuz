from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant

from ..api.normalize_management import normalize_gas, normalize_management
from ..kommunal_coordinator import KommunalCoordinator

_LOGGER = logging.getLogger(__name__)


class ManagementDataUpdateCoordinator(KommunalCoordinator):
    """ASKU Management coordinator (with optional Gas extension)."""

    # ------------------------------------------------------------------
    # Base coordinator implementation
    # ------------------------------------------------------------------

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        username: str,
        password: str,
        account_id: str,
        *,
        enable_gas: bool = False,
        gas_account_id: str | None = None,
    ) -> None:
        self._enable_gas = enable_gas
        self._gas_account_id = gas_account_id

        super().__init__(
            hass,
            entry_id,
            username,
            password,
            account_id,
        )

    async def _fetch_data(self) -> dict[str, Any]:
        assert self._token is not None
        assert self._yandex_token is not None

        now = datetime.now()
        current_year = now.year
        last_month = now.month - 1 or 12
        last_month_year = current_year if now.month != 1 else current_year - 1

        dashboard = await self._api.get_dashboard(
            token=self._token,
            yandex_token=self._yandex_token,
            year=current_year,
        )

        accruals = await self._api.get_accruals(
            token=self._token,
            yandex_token=self._yandex_token,
            year=str(last_month_year),
        )

        data: dict[str, Any] = self._normalize_management(
            dashboard,
            accruals,
            last_month,
            last_month_year,
        )

        # --------------------------------------------------------------
        # GAS EXTENSION (service-specific, isolated, bottom of file)
        # --------------------------------------------------------------
        if self._enable_gas and self._gas_account_id:
            try:
                gas_raw = await self._api.get_gas_data(
                    token=self._token,
                    yandex_token=self._yandex_token,
                )
                data["gas"] = self._normalize_gas(gas_raw)
            except Exception as err:
                _LOGGER.warning(
                    "Failed to fetch gas data for account %s: %s",
                    self._gas_account_id,
                    err,
                )
                data["gas"] = None
        else:
            data["gas"] = None

        return data

    # ------------------------------------------------------------------
    # Normalization (lives in the API layer, see api/normalize_management.py)
    # ------------------------------------------------------------------

    def _normalize_management(
        self,
        dashboard: dict[str, Any],
        accruals: dict[str, Any],
        last_month: int,
        last_month_year: int,
    ) -> dict[str, Any]:
        return normalize_management(
            dashboard,
            accruals,
            self._account_id,
            last_month,
            last_month_year,
        )

    def _normalize_gas(self, raw: dict[str, Any]) -> dict[str, Any]:
        return normalize_gas(raw, self._gas_account_id)
