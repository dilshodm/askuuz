"""Tests for the ASKU Electricity API client.

het.uz sends `null` for amounts that do not apply — most importantly
``lastPayment`` on a consumer who has never paid, which used to abort the whole
update with a misleading "Failed to parse" error.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest
from api.electricity import ElectricityApiClient

CONSUMER_STATE = "/consumer-state"
MONTHLY = "/get-monthly-consumption-by-tariff-new"


def consumer_state(**overrides: Any) -> dict[str, Any]:
    """Build a consumer-state payload, overriding individual fields."""
    data: dict[str, Any] = {
        "currentPeriod": "2026-03-01",
        "balance": 250_000,
        "currentMonthCalcKwh": 120_000,
        "currentMonthCalcSum": 180_000,
        "lastPayment": 500_000,
        "lastPaymentDate": "2026-03-02",
    }
    data.update(overrides)
    return {"data": data}


def monthly(**overrides: Any) -> dict[str, Any]:
    """Build a monthly-consumption payload with one month and one tariff."""
    month: dict[str, Any] = {
        "period": "2026-02-01",
        "totalCalcKwh": 300_000,
        "totalSum": 450_000,
        "newMonthlyTariffAndSpendedKwhs": [
            {"tarifPrice": 15_000, "consumedKwh": 300_000, "totalSumByTariff": 450_000}
        ],
    }
    month.update(overrides)
    return {"status": 1000, "data": [month]}


@pytest.fixture
def electricity_client(make_transport: Callable[..., Any]) -> Callable[..., Any]:
    """Return a factory building a client backed by canned responses."""

    def _make(responses: dict[str, Any]) -> tuple[ElectricityApiClient, Any]:
        client = ElectricityApiClient(session=None)
        transport = make_transport(responses)
        client._request = transport  # type: ignore[method-assign]
        return client, transport

    return _make


@pytest.mark.asyncio
class TestNullHandling:
    """Null amounts must not abort the update."""

    async def test_never_paid_reports_no_payment(
        self, electricity_client: Callable[..., Any]
    ) -> None:
        """A null ``lastPayment`` yields ``None`` rather than an ApiError."""
        client, _ = electricity_client(
            {CONSUMER_STATE: consumer_state(lastPayment=None), MONTHLY: monthly()}
        )

        result = await client.get_data(token="t", account_id="12345678")

        assert result["last_payment"] is None

    @pytest.mark.parametrize("field", ["balance", "currentMonthCalcKwh", "currentMonthCalcSum"])
    async def test_null_numeric_fields(
        self, electricity_client: Callable[..., Any], field: str
    ) -> None:
        """Each numeric field may arrive as null."""
        client, _ = electricity_client(
            {CONSUMER_STATE: consumer_state(**{field: None}), MONTHLY: monthly()}
        )

        result = await client.get_data(token="t", account_id="12345678")

        assert result["balance"] is not None
        assert result["consumption"] is not None
        assert result["accrual"] is not None

    async def test_null_monthly_values(self, electricity_client: Callable[..., Any]) -> None:
        """Null totals in the previous month report as zero."""
        client, _ = electricity_client(
            {
                CONSUMER_STATE: consumer_state(),
                MONTHLY: monthly(totalCalcKwh=None, totalSum=None),
            }
        )

        result = await client.get_data(token="t", account_id="12345678")

        assert result["data"]["last_month"]["consumption"] == 0.0
        assert result["data"]["last_month"]["accrual"] == 0.0


@pytest.mark.asyncio
class TestCanonicalModel:
    """The shape and values the coordinator consumes."""

    async def test_full_payload(self, electricity_client: Callable[..., Any]) -> None:
        """A complete response maps onto the canonical structure."""
        client, transport = electricity_client(
            {CONSUMER_STATE: consumer_state(), MONTHLY: monthly()}
        )

        result = await client.get_data(token="t", account_id="12345678")

        assert result["account_id"] == "12345678"
        assert result["current_period"] == "2026-03"
        assert result["balance"] == pytest.approx(2_500.0)
        assert result["consumption"] == pytest.approx(120.0)
        assert result["accrual"] == pytest.approx(1_800.0)
        assert result["last_payment"] == {"amount": 5_000.0, "date": "2026-03-02"}

        last = result["data"]["last_month"]
        assert last["period"] == "2026-02"
        assert last["tariffs"] == [
            {
                "tariff": pytest.approx(150.0),
                "consumption": pytest.approx(300.0),
                "accrual": pytest.approx(4_500.0),
            }
        ]

    async def test_january_requests_the_previous_year(
        self, electricity_client: Callable[..., Any]
    ) -> None:
        """In January the monthly breakdown comes from the year before."""
        client, transport = electricity_client(
            {
                CONSUMER_STATE: consumer_state(currentPeriod="2026-01-01"),
                MONTHLY: monthly(period="2025-12-01"),
            }
        )

        await client.get_data(token="t", account_id="12345678")

        years = [call.get("params", {}).get("year") for call in transport.requests]
        assert 2025 in years

    async def test_monthly_failure_leaves_current_month_intact(
        self, electricity_client: Callable[..., Any]
    ) -> None:
        """An unusable monthly response drops the block but keeps the rest."""
        client, _ = electricity_client(
            {CONSUMER_STATE: consumer_state(), MONTHLY: {"status": 500, "data": None}}
        )

        result = await client.get_data(token="t", account_id="12345678")

        assert "last_month" not in result["data"]
        assert result["data"]["current_month"]["consumption"] == pytest.approx(120.0)
