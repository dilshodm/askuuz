from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import ConfigEntryAuthFailed

from .api.base import is_transient

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(hours=12)
TOKEN_TTL = 60 * 60 * 12  # если API не даёт expires


class BaseASKUCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Canonical ASKU coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        username: str,
        password: str,
        account_id: str,
        *,
        options: dict | None = None,
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id

        self._username = username
        self._password = password
        self._account_id = account_id
        self._options = options or {}

        self._session = async_get_clientsession(hass)
        self._api = self._create_api_client(self._session)

        self._token: str | None = None
        self._token_expires_at: float | None = None

        self._last_success_data: dict[str, Any] | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=f"asku_{self._account_id}",
            update_interval=UPDATE_INTERVAL,
        )

    # ---------------------------------------------------------------------
    # API / Token helpers
    # ---------------------------------------------------------------------

    def _create_api_client(self, session):
        """Return service-specific ApiClient."""
        raise NotImplementedError

    def _token_valid(self) -> bool:
        return (
            self._token is not None
            and self._token_expires_at is not None
            and self.hass.loop.time() < self._token_expires_at
        )

    def _reset_token(self) -> None:
        self._token = None
        self._token_expires_at = None

    async def _login(self) -> None:
        """Service-specific login. MUST set token + expires."""
        raise NotImplementedError

    @staticmethod
    def _login_error(err: Exception) -> Exception:
        """Map a login failure onto the right Home Assistant error.

        Only a refusal by the service means the credentials are wrong. A
        timeout or a 5xx is temporary: reporting it as an auth failure sends
        the entry into reauth, where it stays until the user intervenes.
        """
        if is_transient(err):
            return UpdateFailed(f"Login failed temporarily: {err}")
        return ConfigEntryAuthFailed(str(err))

    # ---------------------------------------------------------------------
    # Update flow (ЕДИНСТВЕННЫЙ вход)
    # ---------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            if not self._token_valid():
                await self._login()

            try:
                data = await self._fetch_data()
            except PermissionError:
                # 401 / 403
                self._reset_token()
                await self._login()
                data = await self._fetch_data()

            self._last_success_data = data
            return data

        except ConfigEntryAuthFailed:
            # пробрасываем наверх — HA сам переспросит логин
            raise

        except Exception as err:
            _LOGGER.warning("Coordinator update failed: %s", err)
            if self._last_success_data is not None:
                return self._last_success_data
            raise UpdateFailed(err) from err

    # ---------------------------------------------------------------------
    # Fetch & normalize
    # ---------------------------------------------------------------------

    async def _fetch_data(self) -> dict[str, Any]:
        """Fetch RAW data from API. No normalization here."""
        raise NotImplementedError

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------

    @staticmethod
    def _period_from_dot(value: str) -> str:
        """Convert 'MM.YYYY' -> 'YYYY-MM'."""
        month, year = value.split(".")
        return f"{year}-{month.zfill(2)}"
