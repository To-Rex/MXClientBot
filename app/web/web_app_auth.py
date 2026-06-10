import hashlib
import hmac
import json
import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

from fastapi import Header, HTTPException, Request
from sqlalchemy import select

from app.database import async_session
from app.models import Bot, WebSession

logger = logging.getLogger(__name__)


def verify_telegram_init_data(init_data: str, bot_token: str) -> bool:
    parsed = urllib.parse.parse_qs(init_data)
    hash_val = parsed.pop("hash", [None])[0]
    if not hash_val:
        return False

    data_check_arr = []
    for key in sorted(parsed.keys()):
        val = parsed[key][0]
        data_check_arr.append(f"{key}={val}")
    data_check_string = "\n".join(data_check_arr)

    secret_key = hmac.new(
        key=b"WebAppData",
        msg=bot_token.encode(),
        digestmod=hashlib.sha256,
    ).digest()

    computed_hash = hmac.new(
        key=secret_key,
        msg=data_check_string.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()

    return computed_hash == hash_val


def _parse_init_user(init_data: str) -> Optional[dict]:
    parsed = urllib.parse.parse_qs(init_data)
    user_raw = parsed.get("user", [None])[0]
    if not user_raw:
        return None
    try:
        return json.loads(user_raw)
    except json.JSONDecodeError:
        return None


def _bot_payload(bot: Bot) -> dict:
    return {
        "id": bot.id,
        "company_name": bot.company_name or "",
        "base_url": bot.base_url or "",
        "one_c_login": bot.one_c_login or "",
        "one_c_password": bot.one_c_password or "",
    }


async def _auth_by_session_token(token: str) -> Optional[dict]:
    async with async_session() as session:
        result = await session.execute(
            select(WebSession).where(WebSession.token == token)
        )
        ws = result.scalar_one_or_none()
        if not ws:
            return None

        expires_at = ws.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            return None

        bot_result = await session.execute(select(Bot).where(Bot.id == ws.bot_id))
        bot = bot_result.scalar_one_or_none()
        if not bot:
            return None

        return {
            "telegram_id": int(ws.telegram_id),
            "first_name": ws.first_name or "",
            "last_name": ws.last_name or "",
            "username": ws.username or "",
            "bot_id": bot.id,
            "bot_config": _bot_payload(bot),
        }


async def authenticate_webapp_user(
    request: Request,
    x_init_data: Optional[str] = Header(default=None, alias="X-Telegram-Init-Data"),
) -> dict:
    session_token = request.query_params.get("session")
    if session_token:
        auth = await _auth_by_session_token(session_token)
        if not auth:
            raise HTTPException(status_code=401, detail="Sessiya yaroqsiz yoki muddati o'tgan")
        return auth

    if not x_init_data:
        raise HTTPException(status_code=401, detail="Auth required")

    bot_id_str = request.query_params.get("bot_id")
    if not bot_id_str:
        raise HTTPException(status_code=400, detail="bot_id required")

    try:
        bot_id = int(bot_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid bot_id")

    async with async_session() as session:
        result = await session.execute(select(Bot).where(Bot.id == bot_id))
        bot = result.scalar_one_or_none()

    if not bot:
        raise HTTPException(status_code=400, detail="Bot not found")

    if not verify_telegram_init_data(x_init_data, bot.token):
        raise HTTPException(status_code=401, detail="Invalid Telegram init data")

    user_data = _parse_init_user(x_init_data)
    if not user_data or "id" not in user_data:
        raise HTTPException(status_code=401, detail="Invalid user data")

    return {
        "telegram_id": int(user_data["id"]),
        "first_name": user_data.get("first_name", ""),
        "last_name": user_data.get("last_name", ""),
        "username": user_data.get("username", ""),
        "bot_id": bot.id,
        "bot_config": _bot_payload(bot),
    }
