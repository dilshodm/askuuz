from __future__ import annotations

from typing import Any

from .base import ApiError, BaseApiClient, as_number


class ElectricityApiClient(BaseApiClient):
    """API client for ASKU Electricity service.

    Правила:
    - НЕ хранит токены
    - НЕ делает retry
    - НЕ знает про Home Assistant
    - Делает HTTP + парсинг + нормализацию под канон
    """

    BASE_URL = "https://cabinet-api.het.uz/household-consumer/v1/mobile-cabinet"

    def __init__(self, session) -> None:
        super().__init__(base_url=self.BASE_URL)
        self._session = session

    # ------------------------------------------------------------------
    # RAW endpoints
    # ------------------------------------------------------------------

    async def fetch_consumer_state(
        self,
        token: str,
        account_id: str,
    ) -> dict[str, Any]:
        coato_code = account_id[:5]

        return await self._request(
            method="GET",
            path="/consumer-state",
            headers={
                "Accept": "application/json, text/plain, */*",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Coato-Code": coato_code,
            },
        )

    async def fetch_monthly_consumption(
        self,
        token: str,
        year: int,
    ) -> dict[str, Any]:
        return await self._request(
            method="GET",
            path="/get-monthly-consumption-by-tariff-new",
            headers={
                "Accept": "application/json, text/plain, */*",
                "Authorization": f"Bearer {token}",
            },
            params={
                "year": year,
            },
        )

    # ------------------------------------------------------------------
    # High-level API (returns CANONICAL MODEL)
    # ------------------------------------------------------------------

    async def get_data(
        self,
        token: str,
        account_id: str,
    ) -> dict[str, Any]:
        raw = await self.fetch_consumer_state(token, account_id)

        try:
            data = raw["data"]

            result: dict[str, Any] = {
                "account_id": account_id,
                "current_period": data["currentPeriod"][:7],
                "balance": as_number(data["balance"]) / 100,
                "consumption": as_number(data["currentMonthCalcKwh"]) / 1000,
                "accrual": as_number(data["currentMonthCalcSum"]) / 100,
                "last_payment": (
                    {
                        "amount": as_number(data["lastPayment"]) / 100,
                        "date": data.get("lastPaymentDate"),
                    }
                    if data.get("lastPayment") is not None
                    else None
                ),
                "data": {
                    "current_month": {
                        "consumption": as_number(data["currentMonthCalcKwh"]) / 1000,
                        "accrual": as_number(data["currentMonthCalcSum"]) / 100,
                    }
                },
            }

            # ----------------------------------------------------------
            # Previous month (tariff-based consumption)
            # ----------------------------------------------------------

            year, month = map(int, result["current_period"].split("-"))
            monthly_year = year - 1 if month == 1 else year

            monthly_raw = await self.fetch_monthly_consumption(token, monthly_year)

            if (
                isinstance(monthly_raw, dict)
                and monthly_raw.get("status") == 1000
                and isinstance(monthly_raw.get("data"), list)
                and monthly_raw["data"]
            ):
                month_data = monthly_raw["data"][-1]

                monthly_block = {
                    "period": month_data["period"][:7],
                    "consumption": as_number(month_data["totalCalcKwh"]) / 1000,
                    "accrual": as_number(month_data["totalSum"]) / 100,
                    "tariffs": [],
                }

                for t in month_data.get("newMonthlyTariffAndSpendedKwhs") or []:
                    monthly_block["tariffs"].append(
                        {
                            "tariff": as_number(t["tarifPrice"]) / 100,
                            "consumption": as_number(t["consumedKwh"]) / 1000,
                            "accrual": as_number(t["totalSumByTariff"]) / 100,
                        }
                    )

                result["data"]["last_month"] = monthly_block

            return result

        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError("Failed to parse electricity consumer-state data") from exc
