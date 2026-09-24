from __future__ import annotations

from typing import Any
from datetime import datetime

from .base import ApiError, BaseApiClient, as_number


class TboApiClient(BaseApiClient):
    """API client for ASKU UZ TBO (Tozamakon / ASKUT).

    Правила:
    - НЕ хранит токены
    - НЕ делает retry
    - Делает HTTP + парсинг + приведение к канону
    """

    BASE_URL = "https://api.tozamakon.eco"

    def __init__(self, session) -> None:
        super().__init__(
            base_url=self.BASE_URL,
            timeout=30,
        )
        self._session = session

    # ------------------------------------------------------------------
    # AUTH
    # ------------------------------------------------------------------

    async def login(self, *, pid: str, pin: str) -> str:
        response = await self._request(
            method="POST",
            path="/user-service/mobile/login/confirm-code",
            json={
                "login": pid,
                "password": pin,
                "fcmToken": "string",
                "uuid": "string",
                "deviceName": "WEB",
            },
        )

        try:
            return response["access_token"]
        except (KeyError, TypeError) as exc:
            raise ApiError("Invalid ASKUT login response") from exc

    # ------------------------------------------------------------------
    # HIGH-LEVEL DATA (returns CANONICAL MODEL)
    # ------------------------------------------------------------------

    async def get_data(
        self,
        *,
        token: str,
        account_id: str,
    ) -> dict[str, Any]:

        headers = {
            "Authorization": f"Bearer {token}",
        }

        # --------------------------------------------------------------
        # HOUSES → find by accountNumber
        # --------------------------------------------------------------

        raw = await self._request(
            method="GET",
            path="/user-service/mobile/users/houses",
            headers=headers,
        )

        try:
            houses = raw["houses"]
        except (KeyError, TypeError) as exc:
            raise ApiError("Invalid ASKUT houses response") from exc

        house = next(
            (h for h in houses if str(h.get("accountNumber")) == str(account_id)),
            None,
        )

        if house is None:
            raise ApiError(f"ASKUT house with accountNumber={account_id} not found")

        try:
            resident_id = house["id"]
            rate = as_number(house.get("rate"))
            people = int(as_number(house.get("inhabitantCount")))
            api_balance = as_number(house.get("balance"))
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError("Invalid ASKUT house fields") from exc

        # --------------------------------------------------------------
        # NORMALIZATION
        # --------------------------------------------------------------
        # API:
        #   balance < 0 -> overpayment
        #   balance > 0 -> debt
        #
        # Our model:
        #   balance > 0 -> overpayment
        #   balance < 0 -> debt
        balance = -1 * api_balance

        accrual_current = rate * people

        now = datetime.now()
        current_period = now.strftime("%Y-%m")

        # previous month
        year = now.year
        month = now.month - 1
        if month == 0:
            month = 12
            year -= 1

        last_period_iso = f"{year}-{month:02d}"
        last_period_api = f"{month}.{year}"

        # --------------------------------------------------------------
        # LAST PAYMENT
        # --------------------------------------------------------------

        last_payment = None
        payments = await self._request(
            method="GET",
            path=f"/billing-service/payment/resident/{resident_id}",
            params={"sort": "id,desc"},
            headers=headers,
        )

        try:
            item = payments["content"][0]
            last_payment = {
                "amount": as_number(item["amount"]),
                "date": item["dateTime"][:10],
            }
        except (KeyError, IndexError, TypeError):
            last_payment = None

        # --------------------------------------------------------------
        # LAST MONTH ACCRUAL
        # --------------------------------------------------------------

        last_month_accrual = accrual_current

        stats = await self._request(
            method="GET",
            path=f"/billing-service/resident-balances/{resident_id}/income-statistics",
            headers=headers,
        )

        try:
            for row in stats:
                if row.get("period") == last_period_api:
                    last_month_accrual = as_number(row.get("accrual"), last_month_accrual)
                    break
        except (TypeError, ValueError):
            pass

        # --------------------------------------------------------------
        # FINAL CANONICAL STRUCTURE
        # --------------------------------------------------------------

        return {
            "account_id": account_id,
            "current_period": current_period,
            "balance": balance,
            "consumption": people,
            "accrual": accrual_current,
            "last_payment": last_payment,
            "data": {
                "current_month": {
                    "consumption": people,
                    "accrual": accrual_current,
                },
                "last_month": {
                    "period": last_period_iso,
                    "consumption": people,
                    "accrual": last_month_accrual,
                    "tariffs": [
                        {
                            "tariff": rate,
                            "consumption": people,
                            "accrual": last_month_accrual,
                        }
                    ],
                },
            },
        }
