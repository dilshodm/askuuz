"""Tests for the my.kommunal.uz normalization (management and gas).

The dashboard and gas payloads carry `null` in the same places the other
services do; before the fix a null balance, price or area raised ``TypeError``
straight out of the coordinator, and an account with no registered area hit a
``ZeroDivisionError`` while deriving the per-m² tariff.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from api.normalize_management import normalize_gas, normalize_management

NOW = datetime(2026, 3, 15, 12, 0, 0)
ACCOUNT = "acc-1"
GAS_ACCOUNT = "gas-9"


def dashboard(**overrides: Any) -> dict[str, Any]:
    """Build a dashboard payload, overriding individual fields."""
    payload: dict[str, Any] = {
        "balance": -50_000,
        "my_area": 60.0,
        "price": 1_500,
        "payments": [{"payment_amount": 120_000, "payment_date": "2026-03-01"}],
    }
    payload.update(overrides)
    return payload


def accruals(**overrides: Any) -> dict[str, Any]:
    """Build an accruals payload holding a single previous-month row."""
    row: dict[str, Any] = {"month": 2, "year": 2026, "monthly_accrual": 90_000}
    row.update(overrides)
    return {"current": [row]}


def gas_payload(**overrides: Any) -> dict[str, Any]:
    """Build a gas payload with one current and one previous period."""
    payload: dict[str, Any] = {
        "customer_code": GAS_ACCOUNT,
        "current_balance": -12_000,
        "last_payment_sum": 80_000,
        "last_payment_date": "2026-03-02",
        "interraction": [
            {"period": "3.2026", "gas_consume": 40.5, "accrual": 65_000},
            {"period": "2.2026", "gas_consume": 55.0, "accrual": 88_000},
        ],
    }
    payload.update(overrides)
    return payload


class TestManagementNullHandling:
    """Null fields must not break the management update."""

    @pytest.mark.parametrize("field", ["balance", "my_area", "price"])
    def test_null_numeric_fields(self, field: str) -> None:
        """Each numeric dashboard field may arrive as null."""
        result = normalize_management(
            dashboard(**{field: None}), accruals(), ACCOUNT, 2, 2026, now=NOW
        )

        assert result["balance"] is not None
        assert result["accrual"] is not None

    def test_null_payment_amount(self) -> None:
        """A payment row with a null sum reports zero and keeps its date."""
        result = normalize_management(
            dashboard(payments=[{"payment_amount": None, "payment_date": "2026-03-01"}]),
            accruals(),
            ACCOUNT,
            2,
            2026,
            now=NOW,
        )

        assert result["last_payment"] == {"amount": 0.0, "date": "2026-03-01"}

    def test_null_monthly_accrual(self) -> None:
        """A previous month with a null accrual reports zero."""
        result = normalize_management(
            dashboard(), accruals(monthly_accrual=None), ACCOUNT, 2, 2026, now=NOW
        )

        assert result["data"]["last_month"]["accrual"] == 0.0

    def test_zero_area_does_not_divide_by_zero(self) -> None:
        """An account with no registered area reports a zero tariff."""
        result = normalize_management(dashboard(my_area=0), accruals(), ACCOUNT, 2, 2026, now=NOW)

        assert result["data"]["last_month"]["tariffs"][0]["tariff"] == 0.0

    def test_null_area_does_not_divide_by_zero(self) -> None:
        """A null area behaves like a zero one rather than raising."""
        result = normalize_management(
            dashboard(my_area=None), accruals(), ACCOUNT, 2, 2026, now=NOW
        )

        assert result["data"]["last_month"]["tariffs"][0]["tariff"] == 0.0

    def test_missing_accrual_rows(self) -> None:
        """A null ``current`` list leaves the previous month empty."""
        result = normalize_management(dashboard(), {"current": None}, ACCOUNT, 2, 2026, now=NOW)

        assert result["data"]["last_month"] is None

    def test_accrual_row_without_month_key(self) -> None:
        """A malformed accrual row is skipped instead of raising ``KeyError``."""
        result = normalize_management(
            dashboard(), {"current": [{"monthly_accrual": 1}]}, ACCOUNT, 2, 2026, now=NOW
        )

        assert result["data"]["last_month"] is None


class TestManagementCanonicalModel:
    """The shape and values the coordinator consumes."""

    def test_full_payload(self) -> None:
        """A complete payload maps onto the canonical structure."""
        result = normalize_management(dashboard(), accruals(), ACCOUNT, 2, 2026, now=NOW)

        assert result["account_id"] == ACCOUNT
        assert result["current_period"] == "2026-03"
        # the API reports debt as positive, the canonical model inverts it
        assert result["balance"] == pytest.approx(50_000.0)
        assert result["consumption"] == pytest.approx(60.0)
        assert result["accrual"] == pytest.approx(90_000.0)
        assert result["last_payment"] == {"amount": 120_000.0, "date": "2026-03-01"}

        last = result["data"]["last_month"]
        assert last["period"] == "2026-02"
        assert last["accrual"] == pytest.approx(90_000.0)
        assert last["tariffs"][0]["tariff"] == pytest.approx(1_500.0)

    def test_no_payments(self) -> None:
        """An account that never paid reports no payment."""
        result = normalize_management(dashboard(payments=[]), accruals(), ACCOUNT, 2, 2026, now=NOW)

        assert result["last_payment"] is None


class TestGasNullHandling:
    """The gas payload gets the same treatment."""

    def test_null_balance(self) -> None:
        """``current_balance`` may be null; ``abs(None)`` used to raise."""
        result = normalize_gas(gas_payload(current_balance=None), GAS_ACCOUNT)

        assert result["balance"] == 0.0

    def test_balance_is_absolute(self) -> None:
        """The gas balance is reported without a sign."""
        result = normalize_gas(gas_payload(current_balance=-12_000), GAS_ACCOUNT)

        assert result["balance"] == pytest.approx(12_000.0)

    def test_missing_period_is_none(self) -> None:
        """A period that is absent or malformed yields ``None``, not a crash."""
        result = normalize_gas(
            gas_payload(interraction=[{"gas_consume": 1.0, "accrual": 2}]), GAS_ACCOUNT
        )

        assert result["current_period"] is None

    def test_full_payload(self) -> None:
        """A complete gas payload maps onto the canonical structure."""
        result = normalize_gas(gas_payload(), GAS_ACCOUNT)

        assert result["account_id"] == GAS_ACCOUNT
        assert result["current_period"] == "2026-03"
        assert result["consumption"] == pytest.approx(40.5)
        assert result["accrual"] == 65_000
        assert result["data"]["last_month"]["period"] == "2026-02"

    def test_single_period_has_no_last_month(self) -> None:
        """With only one period reported there is no previous month."""
        result = normalize_gas(
            gas_payload(interraction=[{"period": "3.2026", "gas_consume": 1.0, "accrual": 2}]),
            GAS_ACCOUNT,
        )

        assert result["data"]["last_month"] is None

    def test_account_mismatch_is_rejected(self) -> None:
        """A payload for another customer must not be published."""
        with pytest.raises(ValueError, match="Gas account mismatch"):
            normalize_gas(gas_payload(customer_code="someone-else"), GAS_ACCOUNT)

    def test_empty_interraction_is_rejected(self) -> None:
        """Without any period there is nothing to report."""
        with pytest.raises(ValueError, match="Gas interraction empty"):
            normalize_gas(gas_payload(interraction=[]), GAS_ACCOUNT)
