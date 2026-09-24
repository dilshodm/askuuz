"""Tests for the ASKU UZ TBO (Tozamakon) API client.

The house and statistics payloads carry the same nulls as the other services.
A statistics row without an ``accrual`` key also used to raise ``KeyError``,
which the surrounding ``except (TypeError, ValueError)`` did not catch.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import pytest
from api import tbo
from api.base import ApiError
from api.tbo import TboApiClient

# 15 March 2026 -> the statistics rows for the previous month read "2.2026"
NOW = datetime(2026, 3, 15, 12, 0, 0)
LAST_PERIOD_API = "2.2026"

ACCOUNT = "4455"
RESIDENT = 77
HOUSES = "/user-service/mobile/users/houses"
PAYMENTS = f"/billing-service/payment/resident/{RESIDENT}"
STATS = f"/billing-service/resident-balances/{RESIDENT}/income-statistics"


def houses(**overrides: Any) -> dict[str, Any]:
    """Build a houses payload holding the account under test."""
    house: dict[str, Any] = {
        "id": RESIDENT,
        "accountNumber": ACCOUNT,
        "rate": 12_000,
        "inhabitantCount": 3,
        "balance": 36_000,
    }
    house.update(overrides)
    return {"houses": [house]}


def payments(**overrides: Any) -> dict[str, Any]:
    """Build a payment-history payload with a single record."""
    item: dict[str, Any] = {"amount": 50_000, "dateTime": "2026-03-04T08:00:00"}
    item.update(overrides)
    return {"content": [item]}


@pytest.fixture
def tbo_client(make_transport: Callable[..., Any]) -> Callable[..., Any]:
    """Return a factory building a client backed by canned responses."""

    def _make(
        *,
        houses_payload: dict[str, Any] | None = None,
        payments_payload: dict[str, Any] | None = None,
        stats_payload: Any = None,
    ) -> tuple[TboApiClient, Any]:
        client = TboApiClient(session=None)
        transport = make_transport(
            {
                HOUSES: houses() if houses_payload is None else houses_payload,
                PAYMENTS: payments() if payments_payload is None else payments_payload,
                STATS: [] if stats_payload is None else stats_payload,
            }
        )
        client._request = transport  # type: ignore[method-assign]
        return client, transport

    return _make


@pytest.mark.asyncio
class TestNullHandling:
    """Null fields must not break the update."""

    async def test_null_rate(self, tbo_client: Callable[..., Any]) -> None:
        """A house without a rate accrues zero instead of raising."""
        client, _ = tbo_client(houses_payload=houses(rate=None))

        result = await client.get_data(token="t", account_id=ACCOUNT)

        assert result["accrual"] == 0.0

    async def test_null_balance(self, tbo_client: Callable[..., Any]) -> None:
        """A null balance reports zero."""
        client, _ = tbo_client(houses_payload=houses(balance=None))

        result = await client.get_data(token="t", account_id=ACCOUNT)

        assert result["balance"] == 0.0

    async def test_null_inhabitant_count(self, tbo_client: Callable[..., Any]) -> None:
        """A null inhabitant count reports zero residents."""
        client, _ = tbo_client(houses_payload=houses(inhabitantCount=None))

        result = await client.get_data(token="t", account_id=ACCOUNT)

        assert result["consumption"] == 0

    async def test_null_payment_amount(self, tbo_client: Callable[..., Any]) -> None:
        """A payment row with a null amount reports zero."""
        client, _ = tbo_client(payments_payload=payments(amount=None))

        result = await client.get_data(token="t", account_id=ACCOUNT)

        assert result["last_payment"] == {"amount": 0.0, "date": "2026-03-04"}

    async def test_statistics_row_without_accrual_key(
        self, tbo_client: Callable[..., Any], freeze_clock: Callable[..., None]
    ) -> None:
        """A row missing ``accrual`` falls back to the current accrual."""
        freeze_clock(tbo, NOW)
        client, _ = tbo_client(stats_payload=[{"period": LAST_PERIOD_API}])

        result = await client.get_data(token="t", account_id=ACCOUNT)

        assert result["data"]["last_month"]["accrual"] == pytest.approx(36_000.0)

    async def test_statistics_row_with_null_accrual(
        self, tbo_client: Callable[..., Any], freeze_clock: Callable[..., None]
    ) -> None:
        """A row whose accrual is null falls back the same way."""
        freeze_clock(tbo, NOW)
        client, _ = tbo_client(stats_payload=[{"period": LAST_PERIOD_API, "accrual": None}])

        result = await client.get_data(token="t", account_id=ACCOUNT)

        assert result["data"]["last_month"]["accrual"] == pytest.approx(36_000.0)


@pytest.mark.asyncio
class TestCanonicalModel:
    """The shape and values the coordinator consumes."""

    async def test_full_payload(self, tbo_client: Callable[..., Any]) -> None:
        """A complete response maps onto the canonical structure."""
        client, _ = tbo_client()

        result = await client.get_data(token="t", account_id=ACCOUNT)

        assert result["account_id"] == ACCOUNT
        # the API reports debt as positive, the canonical model inverts it
        assert result["balance"] == pytest.approx(-36_000.0)
        assert result["consumption"] == 3
        assert result["accrual"] == pytest.approx(36_000.0)
        assert result["last_payment"] == {"amount": 50_000.0, "date": "2026-03-04"}

    async def test_no_payment_history(self, tbo_client: Callable[..., Any]) -> None:
        """An empty payment list reports no payment."""
        client, _ = tbo_client(payments_payload={"content": []})

        result = await client.get_data(token="t", account_id=ACCOUNT)

        assert result["last_payment"] is None

    async def test_unknown_account_is_rejected(self, tbo_client: Callable[..., Any]) -> None:
        """An account that is not among the houses is an error, not empty data."""
        client, _ = tbo_client(houses_payload=houses(accountNumber="9999"))

        with pytest.raises(ApiError, match="not found"):
            await client.get_data(token="t", account_id=ACCOUNT)

    async def test_statistics_row_is_used_when_present(
        self, tbo_client: Callable[..., Any], freeze_clock: Callable[..., None]
    ) -> None:
        """A well-formed row for the previous month overrides the fallback."""
        freeze_clock(tbo, NOW)
        client, _ = tbo_client(stats_payload=[{"period": LAST_PERIOD_API, "accrual": 99_000}])

        result = await client.get_data(token="t", account_id=ACCOUNT)

        assert result["data"]["last_month"]["accrual"] == pytest.approx(99_000.0)
        assert result["data"]["last_month"]["period"] == "2026-02"
