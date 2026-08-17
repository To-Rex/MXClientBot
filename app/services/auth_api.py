import logging
from typing import Optional

import httpx

from app.config import AUTH_API_BASE
from app.services.http_client import get_http_client

logger = logging.getLogger(__name__)


class AuthAPIService:
    @staticmethod
    async def login(email: str, password: str) -> Optional[dict]:
        url = f"{AUTH_API_BASE}/authentication/login"
        payload = {
            "email": email,
            "password": password,
            "device_id": "web-bot-admin",
            "firebase_token": "web-admin",
        }

        client = get_http_client()
        try:
            response = await client.post(url, json=payload, timeout=15)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error("auth login failed: %s", e.response.status_code)
            return None
        except Exception as e:
            logger.error("auth login error: %s", e)
            return None

    @staticmethod
    async def get_profile(access_token: str) -> Optional[dict]:
        url = f"{AUTH_API_BASE}/authentication/profile"
        headers = {"Authorization": f"Bearer {access_token}"}

        client = get_http_client()
        try:
            response = await client.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error("auth profile failed: %s", e.response.status_code)
            return None
        except Exception as e:
            logger.error("auth profile error: %s", e)
            return None
