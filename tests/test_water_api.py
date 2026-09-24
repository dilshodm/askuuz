"""Tests for the ASKU UZ Water API client.

The uzsuv.uz API returns ``null`` for amounts that do not apply to a billing
period — a correction that was never issued, a payment that was never made, a
volume that was never metered. Before the fix these nulls reached arithmetic
directly and the coordinator failed with::

    unsupported operand type(s) for +: 'int' and 'NoneType'

Most of the cases below pin that behaviour down.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import pytest
from api import water
from api.base import ApiError
from api.water import WaterApiClient

# 15 March 2026 → current period 2603, previous period 2602.
NOW = datetime(2026, 3, 15, 12, 0, 0)
CURRENT_PRD = 2603
LAST_PRD = 2602


def build_responses(
    *,
    sld_hst: list[dict[str, Any]] | None = None,
    pay_hst: dict[str, Any] | None = None,
    chrg_dtl: dict[int, dict[str, Any]] | None = None,
    sub_prf: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a full set of canned endpoint responses, overriding the defaults."""
    defaults_chrg: dict[int, dict[str, Any]] = {
        CURRENT_PRD: {"chrg": [{"om3": 12.5}], "corr": []},
        LAST_PRD: {"chrg": [{"om3": 30.0}], "corr": []},
    }
    chrg_dtl = defaults_chrg if chrg_dtl is None else chrg_dtl

    def chrg_for_period(body: dict[str, Any] | None) -> dict[str, Any]:
        assert body is not None
        return chrg_dtl[body["prd_id"]]

    return {
        "/PAY_HST": (
            {"data": [{"psum": 5_000_000, "pdt": "2026-03-01T10:00:00"}]}
            if pay_hst is None
            else pay_hst
        ),
        "/SLD_HST": (
            [{"prd_id": CURRENT_PRD, "chrg": 100_000, "corr": 0}] if sld_hst is None else sld_hst
        ),
        "/CHRG_DTL": chrg_for_period,
        "/SUB_PRF": ({"sld_sum": 250_000, "rtpl_sum": 2_500} if sub_prf is None else sub_prf),
    }


@pytest.mark.asyncio
class TestGetDataNullHandling:
    """Regression tests: null fields must not break the update."""

    async def test_null_correction_does_not_raise(
        self,
        freeze_clock: Callable[..., None],
        make_client: Callable[..., Any],
    ) -> None:
        """The reported crash: ``corr`` is null when no correction was issued."""
        freeze_clock(water, NOW)
        client, _ = make_client(
            build_responses(
                sld_hst=[{"prd_id": CURRENT_PRD, "chrg": 100_000, "corr": None}],
            )
        )

        result = await client.get_data(token="t", account_id="acc")

        assert result["accrual"] == pytest.approx(1_000.0)

    async def test_null_charge_falls_back_to_correction(
        self,
        freeze_clock: Callable[..., None],
        make_client: Callable[..., Any],
    ) -> None:
        """A null ``chrg`` alongside a real ``corr`` still yields the correction."""
        freeze_clock(water, NOW)
        client, _ = make_client(
            build_responses(
                sld_hst=[{"prd_id": CURRENT_PRD, "chrg": None, "corr": 45_000}],
            )
        )

        result = await client.get_data(token="t", account_id="acc")

        assert result["accrual"] == pytest.approx(450.0)

    async def test_both_amounts_null_gives_zero_accrual(
        self,
        freeze_clock: Callable[..., None],
        make_client: Callable[..., Any],
    ) -> None:
        """A period with nothing billed reports zero, not an error."""
        freeze_clock(water, NOW)
        client, _ = make_client(
            build_responses(
                sld_hst=[{"prd_id": CURRENT_PRD, "chrg": None, "corr": None}],
            )
        )

        result = await client.get_data(token="t", account_id="acc")

        assert result["accrual"] == 0.0

    async def test_missing_keys_are_tolerated(
        self,
        freeze_clock: Callable[..., None],
        make_client: Callable[..., Any],
    ) -> None:
        """An absent ``chrg``/``corr`` key behaves like a null one."""
        freeze_clock(water, NOW)
        client, _ = make_client(
            build_responses(sld_hst=[{"prd_id": CURRENT_PRD}]),
        )

        result = await client.get_data(token="t", account_id="acc")

        assert result["accrual"] == 0.0

    async def test_null_payment_amount(
        self,
        freeze_clock: Callable[..., None],
        make_client: Callable[..., Any],
    ) -> None:
        """A payment row carrying a null sum reports zero and keeps its date."""
        freeze_clock(water, NOW)
        client, _ = make_client(
            build_responses(
                pay_hst={"data": [{"psum": None, "pdt": "2026-03-01T10:00:00"}]},
            )
        )

        result = await client.get_data(token="t", account_id="acc")

        assert result["last_payment"] == {"amount": 0.0, "date": "2026-03-01"}

    async def test_null_metered_volume_is_skipped(
        self,
        freeze_clock: Callable[..., None],
        make_client: Callable[..., Any],
    ) -> None:
        """Null ``om3`` entries contribute nothing instead of raising."""
        freeze_clock(water, NOW)
        client, _ = make_client(
            build_responses(
                chrg_dtl={
                    CURRENT_PRD: {
                        "chrg": [{"om3": 10.0}, {"om3": None}],
                        "corr": [{"om3": None}, {"om3": 2.5}],
                    },
                    LAST_PRD: {"chrg": [], "corr": []},
                },
            )
        )

        result = await client.get_data(token="t", account_id="acc")

        assert result["consumption"] == pytest.approx(12.5)

    async def test_null_balance(
        self,
        freeze_clock: Callable[..., None],
        make_client: Callable[..., Any],
    ) -> None:
        """A null ``sld_sum`` reports a zero balance."""
        freeze_clock(water, NOW)
        client, _ = make_client(
            build_responses(sub_prf={"sld_sum": None, "rtpl_sum": 2_500}),
        )

        result = await client.get_data(token="t", account_id="acc")

        assert result["balance"] == 0.0


@pytest.mark.asyncio
class TestGetDataCanonicalModel:
    """The shape and values the coordinator consumes."""

    async def test_full_payload(
        self,
        freeze_clock: Callable[..., None],
        make_client: Callable[..., Any],
    ) -> None:
        """A complete response maps onto the canonical structure."""
        freeze_clock(water, NOW)
        client, _ = make_client(
            build_responses(
                sld_hst=[
                    {"prd_id": CURRENT_PRD, "chrg": 100_000, "corr": 5_000},
                    {"prd_id": LAST_PRD, "chrg": 200_000, "corr": None},
                ],
            )
        )

        result = await client.get_data(token="t", account_id="acc-1")

        assert result["account_id"] == "acc-1"
        assert result["current_period"] == "2026-03"
        assert result["balance"] == pytest.approx(2_500.0)
        assert result["consumption"] == pytest.approx(12.5)
        assert result["accrual"] == pytest.approx(1_050.0)
        assert result["last_payment"] == {"amount": 50_000.0, "date": "2026-03-01"}

        current = result["data"]["current_month"]
        assert current == {
            "consumption": pytest.approx(12.5),
            "accrual": pytest.approx(1_050.0),
        }

        last = result["data"]["last_month"]
        assert last["period"] == "2026-02"
        assert last["consumption"] == pytest.approx(30.0)
        assert last["accrual"] == pytest.approx(2_000.0)
        assert last["tariffs"] == [
            {
                "tariff": 2_500,
                "consumption": pytest.approx(30.0),
                "accrual": pytest.approx(2_000.0),
            }
        ]

    async def test_missing_tariff_yields_empty_list(
        self,
        freeze_clock: Callable[..., None],
        make_client: Callable[..., Any],
    ) -> None:
        """Without ``rtpl_sum`` the tariff breakdown is omitted, not faked."""
        freeze_clock(water, NOW)
        client, _ = make_client(build_responses(sub_prf={"sld_sum": 250_000}))

        result = await client.get_data(token="t", account_id="acc")

        assert result["data"]["last_month"]["tariffs"] == []

    async def test_no_payment_history(
        self,
        freeze_clock: Callable[..., None],
        make_client: Callable[..., Any],
    ) -> None:
        """An account that never paid reports ``None`` rather than a blank record."""
        freeze_clock(water, NOW)
        client, _ = make_client(build_responses(pay_hst={"data": []}))

        result = await client.get_data(token="t", account_id="acc")

        assert result["last_payment"] is None

    async def test_unknown_periods_are_ignored(
        self,
        freeze_clock: Callable[..., None],
        make_client: Callable[..., Any],
    ) -> None:
        """Rows for other periods leave the current and previous months at zero."""
        freeze_clock(water, NOW)
        client, _ = make_client(
            build_responses(
                sld_hst=[{"prd_id": 2512, "chrg": 999_000, "corr": 0}],
            )
        )

        result = await client.get_data(token="t", account_id="acc")

        assert result["accrual"] == 0.0
        assert result["data"]["last_month"]["accrual"] == 0.0

    async def test_january_rolls_back_to_previous_december(
        self,
        freeze_clock: Callable[..., None],
        make_client: Callable[..., Any],
    ) -> None:
        """In January the previous period is December of the year before."""
        freeze_clock(water, datetime(2026, 1, 10, 9, 0, 0))
        client, transport = make_client(
            build_responses(
                sld_hst=[{"prd_id": 2512, "chrg": 300_000, "corr": None}],
                chrg_dtl={
                    2601: {"chrg": [{"om3": 1.0}], "corr": []},
                    2512: {"chrg": [{"om3": 40.0}], "corr": []},
                },
            )
        )

        result = await client.get_data(token="t", account_id="acc")

        assert result["current_period"] == "2026-01"
        assert result["data"]["last_month"]["period"] == "2025-12"
        assert result["data"]["last_month"]["accrual"] == pytest.approx(3_000.0)
        assert result["data"]["last_month"]["consumption"] == pytest.approx(40.0)

        requested = [body["prd_id"] for path, body in transport.calls if path == "/CHRG_DTL"]
        assert requested == [2601, 2512]


@pytest.mark.asyncio
class TestAuth:
    """Login and the authentication guard on ``get_data``."""

    async def test_login_returns_token(self, make_client: Callable[..., Any]) -> None:
        """A successful PIN_AUTH hands back the token."""
        client, transport = make_client({"/PIN_AUTH": {"token": "abc123"}})

        token = await client.login(pid="12345678901234", pin="secret")

        assert token == "abc123"
        assert transport.calls == [("/PIN_AUTH", {"pid": "12345678901234", "pin": "secret"})]

    async def test_login_without_token_raises(self, make_client: Callable[..., Any]) -> None:
        """A response missing the token is reported as an API error."""
        client, _ = make_client({"/PIN_AUTH": {"error": "bad pin"}})

        with pytest.raises(ApiError, match="Invalid PIN_AUTH response"):
            await client.login(pid="12345678901234", pin="wrong")

    async def test_get_data_requires_login(self) -> None:
        """``get_data`` refuses to build requests before credentials are known."""
        client = WaterApiClient(session=None)

        with pytest.raises(ApiError, match="not authenticated"):
            await client.get_data(token="t", account_id="acc")
