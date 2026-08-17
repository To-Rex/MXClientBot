"""Shared, connection-pooled HTTP client (one per process).

Reusing a single httpx.AsyncClient avoids a new TCP/TLS handshake on every
1C / auth request and keeps keep-alive connections warm.
"""
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_client: Optional[httpx.AsyncClient] = None


def get_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20, keepalive_expiry=60.0),
            http2=False,
        )
    return _client


async def close_http_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        try:
            await _client.aclose()
        except Exception as e:  # pragma: no cover
            logger.debug("http client close error: %s", e)
    _client = None
