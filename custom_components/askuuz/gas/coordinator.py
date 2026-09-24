from __future__ import annotations

import logging
from typing import Any

from ..api.normalize_management import normalize_gas
from ..kommunal_coordinator import KommunalCoordinator

_LOGGER = logging.getLogger(__name__)


class GasDataUpdateCoordinator(KommunalCoordinator):
    """ASKU Gas coordinator.

    Gas lives in the same my.kommunal.uz cabinet as the management company but
    needs nothing from it: the ``/gaz`` endpoint is keyed by the login's tokens
    alone, so a subscriber without a management contract can use it on its own.
    """

    async def _fetch_data(self) -> dict[str, Any]:
        assert self._token is not None
        assert self._yandex_token is not None

        raw = await self._api.get_gas_data(
            token=self._token,
            yandex_token=self._yandex_token,
        )

        return normalize_gas(raw, self._account_id)
