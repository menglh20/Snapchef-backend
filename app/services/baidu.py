"""Baidu 果蔬识别 (fruit/vegetable ingredient recognition) client.

Two-step flow per Baidu's docs:
  1. Exchange API key + secret for a short-lived access_token (cached in-process).
  2. POST the base64-encoded image to the ingredient classify endpoint.

Docs: https://ai.baidu.com/ai-doc/IMAGERECOGNITION/wk3bcxevq
"""

import base64
import logging
import threading
import time

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
INGREDIENT_URL = "https://aip.baidubce.com/rest/2.0/image-classify/v1/classify/ingredient"

# Baidu's "this is not a fruit/vegetable" sentinel, returned as the top result name.
NON_PRODUCE_NAME = "非果蔬食材"

# Refresh a little before the real expiry to avoid using a token mid-expiration.
_TOKEN_EXPIRY_SKEW_S = 60
_HTTP_TIMEOUT_S = 10.0

_token_lock = threading.Lock()
_cached_token: str | None = None
_token_expires_at: float = 0.0


def _get_access_token() -> str:
    global _cached_token, _token_expires_at

    with _token_lock:
        now = time.time()
        if _cached_token and now < _token_expires_at:
            return _cached_token

        settings = get_settings()
        if not settings.baidu_api_key or not settings.baidu_secret_key:
            raise RuntimeError("Baidu credentials are not configured")

        resp = httpx.get(
            TOKEN_URL,
            params={
                "grant_type": "client_credentials",
                "client_id": settings.baidu_api_key,
                "client_secret": settings.baidu_secret_key,
            },
            timeout=_HTTP_TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json()

        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"Baidu token request failed: {data}")

        expires_in = float(data.get("expires_in", 2592000))
        _cached_token = token
        _token_expires_at = now + max(0.0, expires_in - _TOKEN_EXPIRY_SKEW_S)
        return token


def recognize_ingredient(image_bytes: bytes, top_num: int = 5) -> list[dict]:
    """Return Baidu's result list, e.g. [{"name": "西红柿", "score": 0.98}, ...].

    Sorted by Baidu in descending confidence. Empty list if nothing recognized.
    """
    token = _get_access_token()
    encoded = base64.b64encode(image_bytes).decode("ascii")

    resp = httpx.post(
        INGREDIENT_URL,
        params={"access_token": token},
        data={"image": encoded, "top_num": top_num},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=_HTTP_TIMEOUT_S,
    )
    resp.raise_for_status()
    data = resp.json()

    if "error_code" in data:
        raise RuntimeError(f"Baidu ingredient API error: {data}")

    return data.get("result") or []
