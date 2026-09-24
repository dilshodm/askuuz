from __future__ import annotations

import asyncio
from typing import Any

import aiohttp


def as_number(value: Any, default: float = 0.0) -> float:
    """Return ``value`` as a number, treating ``None`` as ``default``.

    Every ASKU backend sends ``null`` instead of ``0`` for amounts that do not
    apply: a correction that was never issued, a payment that was never made, a
    volume that was never metered. Arithmetic on those values raises
    ``TypeError``, so numeric fields coming from an API have to pass through
    here before they are used. Note that ``dict.get(key, 0)`` does not help —
    the key is present, its value is ``null``.
    """
    if value is None:
        return default
    return float(value)


class ApiError(Exception):
    """Base API error."""


class AuthError(ApiError):
    """Authentication failed."""


class TransientApiError(ApiError):
    """A temporary transport problem: timeout, connection error, 5xx.

    Distinguished from :class:`AuthError` so a network blip is retried instead
    of being reported to Home Assistant as bad credentials.
    """


def is_transient(err: BaseException) -> bool:
    """Whether ``err`` is a temporary transport problem rather than a refusal."""
    return isinstance(err, (TransientApiError, aiohttp.ClientError, asyncio.TimeoutError))


class BaseApiClient:
    def __init__(
        self,
        base_url: str,
        timeout: int = 30,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = await self._get_session()
        url = f"{self._base_url}{path}"

        try:
            async with session.request(
                method=method,
                url=url,
                headers=headers,
                json=json,
                params=params,
            ) as response:
                if response.status in (401, 403):
                    raise AuthError(f"API error {response.status}: unauthorized")

                if response.status >= 500:
                    text = await response.text()
                    raise TransientApiError(f"API error {response.status}: {text}")

                if response.status >= 400:
                    text = await response.text()
                    raise ApiError(f"API error {response.status}: {text}")

                return await response.json()

        except asyncio.TimeoutError as exc:
            raise TransientApiError("Request timeout") from exc

        except aiohttp.ClientError as exc:
            raise TransientApiError("HTTP client error") from exc
