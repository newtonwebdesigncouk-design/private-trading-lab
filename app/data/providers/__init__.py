"""Approved read-only network providers. No execution transports belong in this package."""

from app.data.providers.stooq import StooqReadOnlyProvider
from app.data.providers.yahoo import YahooReadOnlyProvider

__all__ = ["StooqReadOnlyProvider", "YahooReadOnlyProvider"]
