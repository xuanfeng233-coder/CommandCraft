"""HTTP client for the WXpay bridge service (see INTEGRATION.md).

WXpay is a separate process that watches the WeChat 收款助手 window and
matches a 6-digit `order_id` written into the payment remark. We talk to it
over plain HTTP. In production it's expected to run on the same machine as
this backend (loopback) — see WXPAY_BASE_URL config.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class WxpayUnavailable(Exception):
    """WXpay service unreachable, timed out, or returned 5xx."""


class WxpayRateLimited(Exception):
    """WXpay returned 429."""

    def __init__(self, retry_after: float | None = None):
        super().__init__(f"WXpay rate limited (retry_after={retry_after})")
        self.retry_after = retry_after


class WxpayClient:
    """Async wrapper around the WXpay HTTP API."""

    def __init__(self, base_url: str, api_key: str):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None

    async def init(self) -> None:
        # trust_env=False so HTTP_PROXY etc. don't accidentally tunnel loopback.
        self._client = httpx.AsyncClient(timeout=5.0, trust_env=False)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        assert self._client is not None, "WxpayClient not initialized"
        return self._client

    def _auth_headers(self) -> dict[str, str]:
        return {"X-API-Key": self._api_key} if self._api_key else {}

    @staticmethod
    def _parse_retry_after(resp: httpx.Response) -> float | None:
        raw = resp.headers.get("Retry-After")
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    async def healthz(self) -> dict[str, Any]:
        """Return WXpay status. Raises WxpayUnavailable on transport error."""
        try:
            resp = await self.client.get(f"{self._base_url}/healthz")
        except httpx.HTTPError as e:
            raise WxpayUnavailable(f"healthz failed: {e}") from e
        if resp.status_code >= 500:
            raise WxpayUnavailable(f"healthz {resp.status_code}: {resp.text}")
        return resp.json()

    async def create_order(
        self,
        *,
        amount_cny: str,
        ttl_seconds: int,
        callback_url: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "expected_amount": amount_cny,
            "ttl_seconds": ttl_seconds,
        }
        if callback_url:
            body["callback_url"] = callback_url
        if metadata:
            body["metadata"] = metadata
        try:
            resp = await self.client.post(
                f"{self._base_url}/api/orders",
                headers={**self._auth_headers(), "Content-Type": "application/json"},
                json=body,
            )
        except httpx.HTTPError as e:
            raise WxpayUnavailable(f"create_order failed: {e}") from e
        if resp.status_code == 429:
            raise WxpayRateLimited(self._parse_retry_after(resp))
        if resp.status_code >= 500:
            raise WxpayUnavailable(f"create_order {resp.status_code}: {resp.text}")
        if resp.status_code >= 400:
            # 401 (bad key), 503 (couldn't allocate id) etc — surface as Unavailable
            raise WxpayUnavailable(f"create_order {resp.status_code}: {resp.text}")
        return resp.json()

    async def get_order(self, order_id: str) -> dict[str, Any] | None:
        """Fetch an order. Returns None if WXpay says 404."""
        try:
            resp = await self.client.get(f"{self._base_url}/api/orders/{order_id}")
        except httpx.HTTPError as e:
            raise WxpayUnavailable(f"get_order failed: {e}") from e
        if resp.status_code == 404:
            return None
        if resp.status_code == 429:
            raise WxpayRateLimited(self._parse_retry_after(resp))
        if resp.status_code >= 500:
            raise WxpayUnavailable(f"get_order {resp.status_code}: {resp.text}")
        if resp.status_code >= 400:
            raise WxpayUnavailable(f"get_order {resp.status_code}: {resp.text}")
        return resp.json()

    async def cancel_order(self, order_id: str) -> None:
        try:
            resp = await self.client.delete(
                f"{self._base_url}/api/orders/{order_id}",
                headers=self._auth_headers(),
            )
        except httpx.HTTPError as e:
            raise WxpayUnavailable(f"cancel_order failed: {e}") from e
        if resp.status_code == 409:
            # Already in terminal state — treat as no-op.
            return
        if resp.status_code == 404:
            return
        if resp.status_code == 429:
            raise WxpayRateLimited(self._parse_retry_after(resp))
        if resp.status_code >= 400:
            raise WxpayUnavailable(f"cancel_order {resp.status_code}: {resp.text}")


# Singleton — initialized in main.py lifespan.
wxpay_client: WxpayClient | None = None


def init_wxpay_client(base_url: str, api_key: str) -> WxpayClient:
    global wxpay_client
    wxpay_client = WxpayClient(base_url=base_url, api_key=api_key)
    return wxpay_client


def get_wxpay_client() -> WxpayClient:
    if wxpay_client is None:
        raise RuntimeError("WXpay not configured (WXPAY_API_KEY missing)")
    return wxpay_client
