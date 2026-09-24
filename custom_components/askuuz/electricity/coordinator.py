from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed

from ..base_coordinator import BaseASKUCoordinator, TOKEN_TTL
from ..api.electricity import ElectricityApiClient
from ..api.base import ApiError

_LOGGER = logging.getLogger(__name__)


class ElectricityDataUpdateCoordinator(BaseASKUCoordinator):
    """ASKU Electricity coordinator."""

    # ------------------------------------------------------------------
    # Base coordinator implementation
    # ------------------------------------------------------------------

    def _create_api_client(self, session) -> ElectricityApiClient:
        return ElectricityApiClient(session=session)

    async def _login(self) -> None:
        try:
            response = await self._api._request(
                method="POST",
                path="/user-login",
                json={
                    "login": self._username,
                    "password": self._password,
                },
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json",
                },
            )
        except Exception as err:
            raise self._login_error(err) from err

        try:
            self._token = response["data"]["accessToken"]
            self._token_expires_at = self.hass.loop.time() + TOKEN_TTL
        except (KeyError, TypeError) as exc:
            raise ConfigEntryAuthFailed from exc

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

            # Rate limit → fallback handled в base
            if "Количество попыток закончилось" in message:
                raise err

            raise err
