from __future__ import annotations

from typing import Any
from datetime import datetime

from .base import ApiError, BaseApiClient, as_number


class WaterApiClient(BaseApiClient):
    """API client for ASKU UZ Water (uzsuv.uz).

    Правила:
    - НЕ хранит токены
    - НЕ делает retry
    - Делает HTTP + парсинг + приведение к канону
    """

    BASE_URL = "https://cabinet.uzsuv.uz/api/web"

    def __init__(self, session) -> None:
        super().__init__(
            base_url=self.BASE_URL,
            timeout=30,
        )
        self._session = session
        self._pid: str | None = None
        self._pin: str | None = None

    # ------------------------------------------------------------------
    # AUTH
    # ------------------------------------------------------------------

    async def login(self, *, pid: str, pin: str) -> str:
        self._pid = pid
        self._pin = pin

        response = await self._request(
            method="POST",
            path="/PIN_AUTH",
            params={"lang": "ru"},
            json={"pid": pid, "pin": pin},
        )

        try:
            return response["token"]
        except (KeyError, TypeError) as exc:
            raise ApiError("Invalid PIN_AUTH response") from exc

    # ------------------------------------------------------------------
    # HIGH-LEVEL DATA (returns CANONICAL MODEL)
    # ------------------------------------------------------------------

    async def get_data(
        self,
        *,
        token: str,
        account_id: str,
    ) -> dict[str, Any]:
        if not self._pid or not self._pin:
            raise ApiError("Water API client not authenticated")

        now = datetime.now()
        current_period = now.strftime("%Y-%m")

        current_prd_id = int(now.strftime("%y%m"))

        year = now.year
        month = now.month - 1
        if month == 0:
            month = 12
            year -= 1

        last_prd_id = int(f"{str(year)[2:]}{month:02d}")
        last_period = f"{year}-{month:02d}"

        # --------------------------------------------------------------
        # PAY_HST → last_payment
        # --------------------------------------------------------------

        pay_hst = await self._request(
            method="POST",
            path="/PAY_HST",
            params={"lang": "ru"},
            headers={"Token": token},
            json={"pid": self._pid},
        )

        last_payment = None
        if pay_hst.get("data"):
            p = pay_hst["data"][0]
            last_payment = {
                "amount": as_number(p["psum"]) / 100,
                "date": p["pdt"][:10],
            }

        # --------------------------------------------------------------
        # SLD_HST → accrual (current + last)
        # --------------------------------------------------------------

        sld_hst = await self._request(
            method="POST",
            path="/SLD_HST",
            params={"lang": "ru"},
            headers={"Token": token},
            json={},
        )

        current_accrual = 0.0
        last_accrual = 0.0

        for row in sld_hst:
            if row.get("prd_id") == current_prd_id:
                current_accrual = (as_number(row.get("chrg")) + as_number(row.get("corr"))) / 100
            elif row.get("prd_id") == last_prd_id:
                last_accrual = (as_number(row.get("chrg")) + as_number(row.get("corr"))) / 100

        # --------------------------------------------------------------
        # CHRG_DTL → consumption (current + last)
        # --------------------------------------------------------------

        async def _get_consumption(prd_id: int) -> float:
            resp = await self._request(
                method="POST",
                path="/CHRG_DTL",
                params={"lang": "ru"},
                headers={"Token": token},
                json={"prd_id": prd_id},
            )

            total = 0.0
            for item in resp.get("corr", []):
                total += as_number(item.get("om3"))
            for item in resp.get("chrg", []):
                total += as_number(item.get("om3"))
            return total

        current_consumption = await _get_consumption(current_prd_id)
        last_consumption = await _get_consumption(last_prd_id)

        # --------------------------------------------------------------
        # SUB_PRF → tariff + balance
        # --------------------------------------------------------------

        sub_prf = await self._request(
            method="POST",
            path="/SUB_PRF",
            params={"lang": "ru"},
            headers={"Token": token},
            json={},
        )

        tariff = sub_prf.get("rtpl_sum")

        # --------------------------------------------------------------
        # FINAL CANONICAL STRUCTURE
        # --------------------------------------------------------------

        return {
            "account_id": account_id,
            "current_period": current_period,
            "balance": as_number(sub_prf.get("sld_sum")) / 100,
            "consumption": current_consumption,
            "accrual": current_accrual,
            "last_payment": last_payment,
            "data": {
                "current_month": {
                    "consumption": current_consumption,
                    "accrual": current_accrual,
                },
                "last_month": {
                    "period": last_period,
                    "consumption": last_consumption,
                    "accrual": last_accrual,
                    "tariffs": (
                        [
                            {
                                "tariff": tariff,
                                "consumption": last_consumption,
                                "accrual": last_accrual,
                            }
                        ]
                        if tariff is not None
                        else []
                    ),
                },
            },
        }
