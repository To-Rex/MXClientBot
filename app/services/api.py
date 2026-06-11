import base64
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class APIService:
    @staticmethod
    async def register_device(
        base_url: str, login: str, password: str, phone_number: str, chat_id: str
    ) -> Optional[dict]:
        url = f"{base_url.rstrip('/')}/hs/client/api/device"
        credentials = base64.b64encode(f"{login}:{password}".encode()).decode()
        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        }
        try:
            phone_int = int(phone_number)
        except ValueError:
            phone_int = phone_number
        payload = {"phone_number": phone_int, "chat_id": chat_id}

        logger.info(
            "📡 register_device REQUEST\n"
            "   URL: %s\n"
            "   Auth: Basic %s (login=%s, pass=%s)\n"
            "   Body: %s",
            url, credentials, login, "*" * len(password) if password else "<empty>", payload,
        )

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
                logger.info(
                    "📡 register_device RESPONSE\n"
                    "   Status: %s %s\n"
                    "   Headers: %s\n"
                    "   Body: %s",
                    response.status_code, response.reason_phrase,
                    dict(response.headers),
                    response.text[:2000],
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "❌ register_device FAILED\n"
                    "   URL: %s\n"
                    "   Status: %s\n"
                    "   Response: %s",
                    url, e.response.status_code, e.response.text[:1000],
                )
                try: return e.response.json()
                except Exception: return None
            except Exception as e:
                logger.error("❌ register_device EXCEPTION for %s: %s", url, e)
                return None

    @staticmethod
    async def get_client_info(
        base_url: str, login: str, password: str, client_id: str
    ) -> Optional[dict]:
        url = f"{base_url.rstrip('/')}/hs/client/api/get_client_info?client_id={client_id}"
        credentials = base64.b64encode(f"{login}:{password}".encode()).decode()
        headers = {"Authorization": f"Basic {credentials}"}

        logger.info(
            "📡 get_client_info REQUEST\n"
            "   URL: %s\n"
            "   Auth: Basic %s",
            url, credentials,
        )

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.get(url, headers=headers)
                logger.info(
                    "📡 get_client_info RESPONSE\n"
                    "   Status: %s %s\n"
                    "   Body: %s",
                    response.status_code, response.reason_phrase,
                    response.text[:2000],
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "❌ get_client_info FAILED\n"
                    "   URL: %s\n"
                    "   Status: %s\n"
                    "   Response: %s",
                    url, e.response.status_code, e.response.text[:1000],
                )
                try: return e.response.json()
                except Exception: return None
            except Exception as e:
                logger.error("❌ get_client_info EXCEPTION for %s: %s", url, e)
                return None

    @staticmethod
    async def get_products(
        base_url: str, login: str, password: str
    ) -> Optional[dict]:
        url = f"{base_url.rstrip('/')}/hs/client/api/Getproductsbygroup"
        credentials = base64.b64encode(f"{login}:{password}".encode()).decode()
        headers = {"Authorization": f"Basic {credentials}"}

        logger.info("📡 get_products REQUEST\n   URL: %s\n   Auth: Basic %s", url, credentials)

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.get(url, headers=headers)
                logger.info(
                    "📡 get_products RESPONSE\n   Status: %s %s",
                    response.status_code, response.reason_phrase,
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "❌ get_products FAILED\n   URL: %s\n   Status: %s\n   Response: %s",
                    url, e.response.status_code, e.response.text[:500],
                )
                try: return e.response.json()
                except Exception: return None
            except Exception as e:
                logger.error("❌ get_products EXCEPTION for %s: %s", url, e)
                return None

    @staticmethod
    async def create_order(
        base_url: str, login: str, password: str,
        client_id: int, product_id: int, price: float, qty: float = 1.0,
    ) -> Optional[dict]:
        url = f"{base_url.rstrip('/')}/hs/client/api/CreateOrder"
        credentials = base64.b64encode(f"{login}:{password}".encode()).decode()
        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        }
        payload = {
            "client_id": client_id,
            "products": [{
                "product_id": product_id,
                "price": price,
                "qty": qty,
                "sum": price * qty,
            }],
        }

        logger.info(
            "📡 create_order REQUEST\n   URL: %s\n   Body: %s",
            url, payload,
        )

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
                logger.info(
                    "📡 create_order RESPONSE\n   Status: %s %s\n   Body: %s",
                    response.status_code, response.reason_phrase, response.text[:500],
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "❌ create_order FAILED\n   Status: %s\n   Response: %s",
                    e.response.status_code, e.response.text[:500],
                )
                try: return e.response.json()
                except Exception: return None
            except Exception as e:
                logger.error("❌ create_order EXCEPTION for %s: %s", url, e)
                return None

    @staticmethod
    async def create_bulk_order(
        base_url: str, login: str, password: str,
        client_id: int, products: list[dict],
    ) -> Optional[dict]:
        url = f"{base_url.rstrip('/')}/hs/client/api/CreateOrder"
        credentials = base64.b64encode(f"{login}:{password}".encode()).decode()
        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        }
        items = []
        for p in products:
            price = float(p["price"])
            qty = float(p["qty"])
            items.append({
                "product_id": int(p["product_id"]),
                "price": price,
                "qty": qty,
                "sum": price * qty,
            })
        payload = {
            "client_id": client_id,
            "products": items,
        }

        logger.info(
            "📡 create_bulk_order REQUEST\n   URL: %s\n   Body: %s",
            url, payload,
        )

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
                logger.info(
                    "📡 create_bulk_order RESPONSE\n   Status: %s %s\n   Body: %s",
                    response.status_code, response.reason_phrase, response.text[:500],
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "❌ create_bulk_order FAILED\n   Status: %s\n   Response: %s",
                    e.response.status_code, e.response.text[:500],
                )
                try: return e.response.json()
                except Exception: return None
            except Exception as e:
                logger.error("❌ create_bulk_order EXCEPTION for %s: %s", url, e)
                return None

    @staticmethod
    async def get_orders(
        base_url: str, login: str, password: str, client_id: str
    ) -> Optional[dict]:
        url = f"{base_url.rstrip('/')}/hs/client/api/Getlistorders?client_id={client_id}"
        credentials = base64.b64encode(f"{login}:{password}".encode()).decode()
        headers = {"Authorization": f"Basic {credentials}"}

        logger.info("📡 get_orders REQUEST\n   URL: %s", url)

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.get(url, headers=headers)
                logger.info(
                    "📡 get_orders RESPONSE\n   Status: %s %s",
                    response.status_code, response.reason_phrase,
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "❌ get_orders FAILED\n   Status: %s\n   Response: %s",
                    e.response.status_code, e.response.text[:500],
                )
                try: return e.response.json()
                except Exception: return None
            except Exception as e:
                logger.error("❌ get_orders EXCEPTION for %s: %s", url, e)
                return None

    @staticmethod
    async def delete_order(
        base_url: str, login: str, password: str, order_id: int,
    ) -> Optional[dict]:
        url = f"{base_url.rstrip('/')}/hs/client/api/delete_order"
        credentials = base64.b64encode(f"{login}:{password}".encode()).decode()
        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        }
        payload = {"id_doc": str(order_id)}

        logger.info("📡 delete_order REQUEST\n   URL: %s\n   Body: %s", url, payload)

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
                logger.info(
                    "📡 delete_order RESPONSE\n   Status: %s %s\n   Body: %s",
                    response.status_code, response.reason_phrase, response.text[:500],
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "❌ delete_order FAILED\n   Status: %s\n   Response: %s",
                    e.response.status_code, e.response.text[:500],
                )
                try: return e.response.json()
                except Exception: return None
            except Exception as e:
                logger.error("❌ delete_order EXCEPTION for %s: %s", url, e)
                return None

    @staticmethod
    async def edit_order(
        base_url: str, login: str, password: str,
        order_id: int, products: list[dict],
    ) -> Optional[dict]:
        url = f"{base_url.rstrip('/')}/hs/client/api/EditOrder"
        credentials = base64.b64encode(f"{login}:{password}".encode()).decode()
        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        }
        payload = {"id_doc": str(order_id), "products": products}

        logger.info("📡 edit_order REQUEST\n   URL: %s\n   Body: %s", url, payload)

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.patch(url, json=payload, headers=headers)
                logger.info(
                    "📡 edit_order RESPONSE\n   Status: %s %s\n   Body: %s",
                    response.status_code, response.reason_phrase, response.text[:500],
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "❌ edit_order FAILED\n   Status: %s\n   Response: %s",
                    e.response.status_code, e.response.text[:500],
                )
                try: return e.response.json()
                except Exception: return None
            except Exception as e:
                logger.error("❌ edit_order EXCEPTION for %s: %s", url, e)
                return None

    @staticmethod
    async def get_akt_sverka(
        base_url: str, login: str, password: str, client_id: str,
        date_begin: str = "", date_end: str = "",
    ) -> Optional[dict]:
        if not date_begin or not date_end:
            from datetime import datetime
            now = datetime.now()
            date_begin = f"{now.year}0101"
            date_end = now.strftime("%Y%m%d")

        url = (
            f"{base_url.rstrip('/')}/hs/client/api/akt_sverka"
            f"?valyuta_id=1&date_begin={date_begin}&date_end={date_end}&client_id={client_id}"
        )
        credentials = base64.b64encode(f"{login}:{password}".encode()).decode()
        headers = {"Authorization": f"Basic {credentials}"}

        logger.info("📡 akt_sverka REQUEST\n   URL: %s", url)

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.get(url, headers=headers)
                logger.info(
                    "📡 akt_sverka RESPONSE\n   Status: %s %s",
                    response.status_code, response.reason_phrase,
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "❌ akt_sverka FAILED\n   Status: %s\n   Response: %s",
                    e.response.status_code, e.response.text[:500],
                )
                try: return e.response.json()
                except Exception: return None
            except Exception as e:
                logger.error("❌ akt_sverka EXCEPTION for %s: %s", url, e)
                return None

    @staticmethod
    async def create_note(
        base_url: str, login: str, password: str,
        client_id: int, note: str, comment: str = "",
    ) -> Optional[dict]:
        url = f"{base_url.rstrip('/')}/hs/client/api/create_note"
        credentials = base64.b64encode(f"{login}:{password}".encode()).decode()
        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        }
        payload = {
            "client_id": client_id,
            "note": note,
            "comment": comment,
        }

        logger.info(
            "📡 create_note REQUEST\n   URL: %s\n   Body: %s",
            url, payload,
        )

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
                logger.info(
                    "📡 create_note RESPONSE\n   Status: %s %s\n   Body: %s",
                    response.status_code, response.reason_phrase, response.text[:500],
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "❌ create_note FAILED\n   Status: %s\n   Response: %s",
                    e.response.status_code, e.response.text[:500],
                )
                try: return e.response.json()
                except Exception: return None
            except Exception as e:
                logger.error("❌ create_note EXCEPTION for %s: %s", url, e)
                return None

    @staticmethod
    async def get_balance(
        base_url: str, login: str, password: str, client_id: str,
    ) -> Optional[dict]:
        url = f"{base_url.rstrip('/')}/hs/client/api/get_balance?client_id={client_id}"
        credentials = base64.b64encode(f"{login}:{password}".encode()).decode()
        headers = {"Authorization": f"Basic {credentials}"}

        logger.info("📡 get_balance REQUEST\n   URL: %s", url)

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.get(url, headers=headers)
                logger.info(
                    "📡 get_balance RESPONSE\n   Status: %s %s\n   Body: %s",
                    response.status_code, response.reason_phrase, response.text[:500],
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "❌ get_balance FAILED\n   Status: %s\n   Response: %s",
                    e.response.status_code, e.response.text[:500],
                )
                try: return e.response.json()
                except Exception: return None
            except Exception as e:
                logger.error("❌ get_balance EXCEPTION for %s: %s", url, e)
                return None
