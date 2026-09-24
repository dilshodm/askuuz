from __future__ import annotations

import logging
from typing import Any


from ..base_coordinator import BaseASKUCoordinator, TOKEN_TTL
from ..api.tbo import TboApiClient
from ..api.base import ApiError

_LOGGER = logging.getLogger(__name__)


class TboDataUpdateCoordinator(BaseASKUCoordinator):
    """ASKU TBO coordinator."""

    # ------------------------------------------------------------------
    # Base coordinator implementation
    # ------------------------------------------------------------------

    def _create_api_client(self, session) -> TboApiClient:
        return TboApiClient(session=session)

    async def _login(self) -> None:
        try:
            token = await self._api.login(
                pid=self._username,
                pin=self._password,
            )
        except Exception as err:
            raise self._login_error(err) from err

        self._token = token
        # API не отдаёт expires → берём запас, как в electricity
        self._token_expires_at = self.hass.loop.time() + TOKEN_TTL

    async def _fetch_data(self) -> dict[str, Any]:
        assert self._token is not None

        try:
            data = await self._api.get_data(
                token=self._token,
                account_id=self._account_id,
            )
            return data

        except ApiError as err:
            message = str(err)

            # 401 / 403 → проброс для retry в BaseASKUCoordinator
            if "401" in message or "403" in message:
                raise PermissionError from err

            # Любая временная ошибка → fallback в base
            raise err
