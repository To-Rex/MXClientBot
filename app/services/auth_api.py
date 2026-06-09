import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

AUTH_API_BASE = "https://distr.mxsoft.uz/api/v1"


class AuthAPIService:
    @staticmethod
    async def login(email: str, password: str) -> Optional[dict]:
        url = f"{AUTH_API_BASE}/authentication/login"
        payload = {
            "email": email,
            "password": password,
            "device_id": "web-admin",
            "firebase_token": "web-admin",
        }

        async with httpx.AsyncClient(timeout=15) as client:
            try:
                response = await client.post(url, json=payload)
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

        async with httpx.AsyncClient(timeout=15) as client:
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error("auth profile failed: %s", e.response.status_code)
                return None
            except Exception as e:
                logger.error("auth profile error: %s", e)
                return None
