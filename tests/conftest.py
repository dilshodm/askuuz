"""Shared fixtures for the askuuz test suite.

The API clients under ``custom_components/askuuz/api`` are plain HTTP and
parsing code that imports nothing from Home Assistant, so the tests exercise
them directly. ``pytest.ini`` puts ``custom_components/askuuz`` on the import
path, which makes ``api.water`` importable without executing the integration's
``__init__.py`` (and therefore without a full Home Assistant install).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import pytest
from api import water


class FakeTransport:
    """Stand-in for :meth:`api.base.BaseApiClient._request`.

    Maps a request path to a canned response. A response may be a callable,
    which is invoked with the request's JSON body; ``/CHRG_DTL`` is queried
    once per period and has to answer differently each time.
    """

    def __init__(self, responses: dict[str, Any]) -> None:
        """Store the canned responses keyed by request path."""
        self._responses = responses
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def __call__(self, *, method: str, path: str, **kwargs: Any) -> Any:
        """Record the call and return the canned response for ``path``."""
        body = kwargs.get("json")
        self.calls.append((path, body))

        if path not in self._responses:
            raise AssertionError(f"unexpected request to {path}")

        response = self._responses[path]
        if callable(response):
            return response(body)
        return response


@pytest.fixture
def freeze_now(monkeypatch: pytest.MonkeyPatch) -> Callable[[datetime], None]:
    """Return a helper pinning ``datetime.now()`` inside ``api.water``.

    The client derives the current and previous period ids from the wall
    clock, so every assertion about periods needs a fixed moment.
    """

    def _freeze(moment: datetime) -> None:
        class _FrozenClock:
            """Stands in for the ``datetime`` class; ``now()`` is all the client calls."""

            @staticmethod
            def now(tz: Any = None) -> datetime:
                """Return the pinned moment, ignoring the timezone argument."""
                return moment

        monkeypatch.setattr(water, "datetime", _FrozenClock)

    return _freeze


@pytest.fixture
def make_client() -> Callable[..., tuple[water.WaterApiClient, FakeTransport]]:
    """Return a factory building an authenticated client with a fake transport."""

    def _make(responses: dict[str, Any]) -> tuple[water.WaterApiClient, FakeTransport]:
        client = water.WaterApiClient(session=None)
        # get_data() refuses to run before login(); emulate a completed login
        # without going through the network.
        client._pid = "12345678901234"
        client._pin = "secret"

        transport = FakeTransport(responses)
        client._request = transport  # type: ignore[method-assign]
        return client, transport

    return _make
