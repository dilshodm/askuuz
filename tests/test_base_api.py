"""Tests for the shared API helpers in ``api.base``."""

from __future__ import annotations

from typing import Any

import pytest
from api.base import as_number


class TestAsNumber:
    """Unit tests for the ``as_number`` coercion helper."""

    def test_none_becomes_zero(self) -> None:
        """``None`` is the case the API actually sends; it must not propagate."""
        assert as_number(None) == 0.0

    def test_none_honours_custom_default(self) -> None:
        """A caller may pick a different stand-in for a missing value."""
        assert as_number(None, default=-1.0) == -1.0

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (0, 0.0),
            (42, 42.0),
            (-17, -17.0),
            (3.5, 3.5),
            ("125", 125.0),
            ("12.75", 12.75),
        ],
    )
    def test_numbers_pass_through(self, value: Any, expected: float) -> None:
        """Real values are returned unchanged, as floats."""
        assert as_number(value) == pytest.approx(expected)

    def test_zero_is_not_confused_with_missing(self) -> None:
        """A genuine zero must stay a zero rather than hit the default."""
        assert as_number(0, default=99.0) == 0.0
