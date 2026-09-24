from __future__ import annotations

from homeassistant.core import HomeAssistant

from .api.management import ManagementApiClient
from .base_coordinator import TOKEN_TTL, BaseASKUCoordinator


class KommunalCoordinator(BaseASKUCoordinator):
    """Shared login for the my.kommunal.uz services (management and gas).

    Both call the same cabinet and need the pair of tokens its login returns:
    the bearer token and the ``yandex_`` value every later request carries.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        username: str,
        password: str,
        account_id: str,
        **kwargs,
    ) -> None:
        """Set up the coordinator with an empty second token."""
        self._yandex_token: str | None = None
        super().__init__(hass, entry_id, username, password, account_id, **kwargs)

    def _create_api_client(self, session) -> ManagementApiClient:
        return ManagementApiClient(session)

    async def _login(self) -> None:
        try:
            result = await self._api.login(self._username, self._password)
        except Exception as err:
            raise self._login_error(err) from err

        self._token = result["access_token"]
        self._yandex_token = result["yandex_token"]
        self._token_expires_at = self.hass.loop.time() + TOKEN_TTL
