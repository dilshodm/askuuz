from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

from .api.base import AuthError, is_transient
from .api.electricity import ElectricityApiClient
from .api.management import ManagementApiClient
from .api.tbo import TboApiClient
from .api.water import WaterApiClient
from .const import DOMAIN


class ASKUUZConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._service: str | None = None
        self._data: dict = {}
        self._reauth_entry: ConfigEntry | None = None

    # ------------------------------------------------------------------
    # Credential validation
    # ------------------------------------------------------------------

    async def _validate_credentials(self, username: str, password: str, service: str) -> str | None:
        """Try to log in; return an error key, or ``None`` when the login worked.

        A refusal by the service means the credentials are wrong. Anything
        temporary — a timeout, a connection error, a 5xx — is reported as
        ``cannot_connect``, so the user is not told their password is bad when
        their internet is simply down.
        """
        session = async_get_clientsession(self.hass)

        try:
            if service == "electricity":
                api = ElectricityApiClient(session=session)
                response = await api._request(
                    method="POST",
                    path="/user-login",
                    json={
                        "login": username,
                        "password": password,
                    },
                    headers={
                        "Accept": "application/json, text/plain, */*",
                        "Content-Type": "application/json",
                    },
                )
                ok = "data" in response and "accessToken" in response.get("data", {})

            elif service == "water":
                api = WaterApiClient(session=session)
                token = await api.login(pid=username, pin=password)
                ok = isinstance(token, str) and len(token) > 0

            elif service == "tbo":
                api = TboApiClient(session=session)
                token = await api.login(pid=username, pin=password)
                ok = isinstance(token, str) and len(token) > 0

            elif service in ("management", "gas"):
                api = ManagementApiClient(session=session)
                result = await api.login(username, password)
                ok = "access_token" in result and "yandex_token" in result

            else:
                return "unknown"

        except AuthError:
            return "invalid_auth"

        except Exception as err:
            return "cannot_connect" if is_transient(err) else "invalid_auth"

        return None if ok else "invalid_auth"

    # ------------------------------------------------------------------
    # Schemas
    # ------------------------------------------------------------------

    def _credentials_schema(self, user_input: dict[str, Any] | None = None) -> vol.Schema:
        """Build the credentials form, keeping what the user already typed."""
        previous = user_input or {}

        schema: dict[Any, Any] = {
            vol.Required(
                "username",
                description={"suggested_value": previous.get("username")},
            ): str,
            vol.Required("password"): str,
            vol.Required(
                "account_id",
                description={"suggested_value": previous.get("account_id")},
            ): str,
        }

        if self._service == "management":
            schema[vol.Optional("enable_gas", default=previous.get("enable_gas", False))] = (
                cv.boolean
            )

        return vol.Schema(schema)

    # ------------------------------------------------------------------
    # Duplicate detection
    # ------------------------------------------------------------------

    def _is_already_configured(self, username: str, account_id: str) -> bool:
        """Whether this service and account are configured already.

        A gas account can arrive two ways — as its own entry, or as the gas
        extension of a management entry — so those two are checked against
        each other as well.
        """
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            service = entry.data.get("service")

            if (
                service == self._service
                and entry.data.get("username") == username
                and entry.data.get("account_id") == account_id
            ):
                return True

            # the same meter, added the other way round
            if self._service == "gas" and entry.data.get("gas_account_id") == account_id:
                return True

        return False

    def _gas_account_taken(self, gas_account_id: str) -> bool:
        """Whether a standalone gas entry already covers this meter."""
        return any(
            entry.data.get("service") == "gas" and entry.data.get("account_id") == gas_account_id
            for entry in self.hass.config_entries.async_entries(DOMAIN)
        )

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    async def async_step_user(self, user_input=None):
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("service"): SelectSelector(
                            SelectSelectorConfig(
                                options=["electricity", "water", "tbo", "gas", "management"],
                                mode="dropdown",
                                translation_key="service",
                            )
                        )
                    }
                ),
                errors={},
            )

        self._service = user_input["service"]
        return await self.async_step_credentials()

    async def async_step_credentials(self, user_input=None):
        if user_input is None:
            return self.async_show_form(
                step_id="credentials",
                data_schema=self._credentials_schema(),
                errors={},
            )

        if not user_input["username"] or not user_input["password"]:
            return self.async_show_form(
                step_id="credentials",
                data_schema=self._credentials_schema(user_input),
                errors={"base": "invalid_auth"},
            )

        error = await self._validate_credentials(
            user_input["username"],
            user_input["password"],
            self._service,
        )
        if error:
            return self.async_show_form(
                step_id="credentials",
                data_schema=self._credentials_schema(user_input),
                errors={"base": error},
            )

        self._data = {
            "service": self._service,
            "username": user_input["username"],
            "password": user_input["password"],
            "account_id": user_input["account_id"],
        }

        # One configuration per service + username + account
        if self._is_already_configured(user_input["username"], user_input["account_id"]):
            return self.async_show_form(
                step_id="credentials",
                data_schema=self._credentials_schema(user_input),
                errors={"base": "already_configured"},
            )

        if self._service != "management" or not user_input.get("enable_gas"):
            return self._create_entry(self._data)

        self._data["enable_gas"] = True
        return await self.async_step_gas()

    async def async_step_gas(self, user_input=None):
        if user_input is None or not user_input.get("gas_account_id"):
            return self.async_show_form(
                step_id="gas",
                data_schema=vol.Schema({vol.Required("gas_account_id"): str}),
                errors={} if user_input is None else {"base": "invalid_gas_account"},
            )

        if self._gas_account_taken(user_input["gas_account_id"]):
            return self.async_show_form(
                step_id="gas",
                data_schema=vol.Schema({vol.Required("gas_account_id"): str}),
                errors={"base": "already_configured"},
            )

        self._data["gas_account_id"] = user_input["gas_account_id"]
        return self._create_entry(self._data)

    # ------------------------------------------------------------------
    # Reauthentication
    # ------------------------------------------------------------------

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Start reauthentication after the service refused the stored password."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        self._service = entry_data.get("service")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None) -> FlowResult:
        """Ask for the password again and put the entry back to work."""
        assert self._reauth_entry is not None
        username = self._reauth_entry.data["username"]
        schema = vol.Schema({vol.Required("password"): str})

        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=schema,
                description_placeholders={"username": username},
                errors={},
            )

        error = await self._validate_credentials(
            username,
            user_input["password"],
            self._reauth_entry.data["service"],
        )
        if error:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=schema,
                description_placeholders={"username": username},
                errors={"base": error},
            )

        self.hass.config_entries.async_update_entry(
            self._reauth_entry,
            data={**self._reauth_entry.data, "password": user_input["password"]},
        )
        await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
        return self.async_abort(reason="reauth_successful")

    def _create_entry(self, data: dict):
        return self.async_create_entry(
            title=f"ASKU {data['service'].capitalize()} {data['account_id']}",
            data=data,
        )
