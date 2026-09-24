"""Normalization of the my.kommunal.uz payloads into the canonical model.

Kept out of the coordinator so it can be exercised without Home Assistant,
and to match the other services, where the API layer owns normalization.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .base import as_number


def normalize_management(
    dashboard: dict[str, Any],
    accruals: dict[str, Any],
    account_id: str,
    last_month: int,
    last_month_year: int,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the canonical management model from a dashboard and accrual payload."""
    moment = now or datetime.now()

    balance = as_number(dashboard.get("balance")) * -1
    my_area = as_number(dashboard.get("my_area"))
    tariff = as_number(dashboard.get("price"))
    accrual = tariff * my_area

    payments = dashboard.get("payments") or []
    last_payment = payments[0] if payments else None

    last_month_item = next(
        (
            x
            for x in accruals.get("current") or []
            if x.get("month") == last_month and x.get("year") == last_month_year
        ),
        None,
    )

    return {
        "account_id": account_id,
        "current_period": moment.strftime("%Y-%m"),
        "balance": balance,
        "consumption": my_area,
        "accrual": accrual,
        "last_payment": (
            {
                "amount": as_number(last_payment.get("payment_amount")),
                "date": last_payment.get("payment_date"),
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
                _last_month_block(last_month_item, my_area, last_month, last_month_year)
                if last_month_item
                else None
            ),
        },
    }


def _last_month_block(
    item: dict[str, Any],
    my_area: float,
    last_month: int,
    last_month_year: int,
) -> dict[str, Any]:
    """Build the previous-month block, deriving the per-m² tariff from its accrual."""
    accrual = as_number(item.get("monthly_accrual"))

    # An account with no registered area would otherwise divide by zero.
    tariff = accrual / my_area if my_area else 0.0

    return {
        "period": f"{last_month_year}-{str(last_month).zfill(2)}",
        "consumption": my_area,
        "accrual": accrual,
        "tariffs": [
            {
                "tariff": tariff,
                "consumption": my_area,
                "accrual": accrual,
            }
        ],
    }


def normalize_gas(raw: dict[str, Any], gas_account_id: str | None) -> dict[str, Any]:
    """Build the canonical gas model, verifying the payload is for this account."""
    if raw.get("customer_code") != gas_account_id:
        raise ValueError("Gas account mismatch")

    inter = raw.get("interraction") or []
    if not inter:
        raise ValueError("Gas interraction empty")

    current = inter[0]
    last = inter[1] if len(inter) > 1 else None

    return {
        "account_id": gas_account_id,
        "current_period": _period(current.get("period")),
        "balance": abs(as_number(raw.get("current_balance"))),
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
                    "period": _period(last.get("period")),
                    "consumption": last.get("gas_consume"),
                    "accrual": last.get("accrual"),
                }
                if last
                else None
            ),
        },
    }


def _period(value: str | None) -> str | None:
    """Convert a ``MM.YYYY`` period into ``YYYY-MM``."""
    if not value or "." not in value:
        return None

    month, year = value.split(".", 1)
    return f"{year}-{month.zfill(2)}"
