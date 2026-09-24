from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from ..base_coordinator import BaseASKUCoordinator, TOKEN_TTL
from ..api.management import ManagementApiClient

_LOGGER = logging.getLogger(__name__)


class ManagementDataUpdateCoordinator(BaseASKUCoordinator):
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

        self._yandex_token: str | None = None

        super().__init__(
            hass,
            entry_id,
            username,
            password,
            account_id,
        )

    def _create_api_client(self, session) -> ManagementApiClient:
        return ManagementApiClient(session)

    async def _login(self) -> None:
        try:
            result = await self._api.login(self._username, self._password)
        except Exception as err:
            raise self._login_error(err) from err

        self._token = result["access_token"]
        self._yandex_token = result["yandex_token"]
        self._token_expires_at = self.hass.loop.time() + TOKEN_TTL

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
    # Management normalization
    # ------------------------------------------------------------------

    def _normalize_management(
        self,
        dashboard: dict[str, Any],
        accruals: dict[str, Any],
        last_month: int,
        last_month_year: int,
    ) -> dict[str, Any]:
        balance = dashboard["balance"] * -1
        my_area = dashboard["my_area"]
        tariff = float(dashboard["price"])
        accrual = tariff * my_area

        last_payment = dashboard["payments"][0] if dashboard.get("payments") else None

        last_month_item = next(
            (
                x
                for x in accruals.get("current", [])
                if x["month"] == last_month and x["year"] == last_month_year
            ),
            None,
        )

        data = {
            "account_id": self._account_id,
            "current_period": datetime.now().strftime("%Y-%m"),
            "balance": balance,
            "consumption": my_area,
            "accrual": accrual,
            "last_payment": (
                {
                    "amount": float(last_payment["payment_amount"]),
                    "date": last_payment["payment_date"],
                }
                if last_payment
                else None
            ),
            "data": {
                "current_month": {
                    "consumption": my_area,
                    "accrual": accrual,
                },
                "last_month": (
                    {
                        "period": f"{last_month_year}-{str(last_month).zfill(2)}",
                        "consumption": my_area,
                        "accrual": float(last_month_item["monthly_accrual"]),
                        "tariffs": [
                            {
                                "tariff": float(last_month_item["monthly_accrual"]) / my_area,
                                "consumption": my_area,
                                "accrual": float(last_month_item["monthly_accrual"]),
                            }
                        ],
                    }
                    if last_month_item
                    else None
                ),
            },
        }

        return data

    # ------------------------------------------------------------------
    # GAS normalization (isolated, bottom)
    # ------------------------------------------------------------------

    def _normalize_gas(self, raw: dict[str, Any]) -> dict[str, Any]:
        # обязательная защита
        if raw.get("customer_code") != self._gas_account_id:
            raise ValueError("Gas account mismatch")

        inter = raw.get("interraction") or []
        if not inter:
            raise ValueError("Gas interraction empty")

        current = inter[0]
        last = inter[1] if len(inter) > 1 else None

        def _period(val: str) -> str:
            m, y = val.split(".")
            return f"{y}-{m.zfill(2)}"

        return {
            "account_id": self._gas_account_id,
            "current_period": _period(current["period"]),
            "balance": abs(raw.get("current_balance", 0)),
            "consumption": current.get("gas_consume"),
            "accrual": current.get("accrual"),
            "last_payment": {
                "amount": raw.get("last_payment_sum"),
                "date": raw.get("last_payment_date"),
            },
            "data": {
                "current_month": {
                    "consumption": current.get("gas_consume"),
                    "accrual": current.get("accrual"),
                },
                "last_month": (
                    {
                        "period": _period(last["period"]),
                        "consumption": last.get("gas_consume"),
                        "accrual": last.get("accrual"),
                    }
                    if last
                    else None
                ),
            },
        }
