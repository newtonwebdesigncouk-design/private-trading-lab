"""The sole GET-only HTTP transport allowlisted for historical market-data providers."""

from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ProviderTransportError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ReadOnlyMarketDataTransport(Protocol):
    def get(self, url: str, *, timeout_seconds: float) -> bytes: ...


class UrllibReadOnlyMarketDataTransport:
    """GET-only transport with no cookie, credential, account, or write support."""

    def get(self, url: str, *, timeout_seconds: float) -> bytes:
        request = Request(
            url,
            headers={
                "Accept": "application/json,text/csv",
                "User-Agent": "private-trading-lab/0.2 read-only",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return bytes(response.read())
        except HTTPError as exc:
            raise ProviderTransportError(
                f"read-only provider returned HTTP {exc.code}", status_code=exc.code
            ) from exc
        except URLError as exc:
            raise ProviderTransportError("read-only provider request failed") from exc
