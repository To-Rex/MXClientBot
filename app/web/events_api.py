"""1C → bot voqealari (docs/1C_NASIYA_API.md §8.2).

1C yangi shartnoma rasmiylashtirilganda yoki to'lov (do'konda/naqd) qabul
qilinganda shu endpointga push yuboradi; bot mijozga Telegram orqali xabar
beradi. Autentifikatsiya talab qilinmaydi (mijoz talabiga ko'ra) — himoya
sifatida faqat ro'yxatdan o'tgan chat_id larga xabar yuboriladi.
"""
import logging
import time
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.database import async_session
from app.models import User
from app.services import api_log
from app.services.nasiya_api import NasiyaService, _parse_date, _to_float

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/1c")

_fmt_money = NasiyaService.fmt_money
_fmt_date = NasiyaService.fmt_date

EVENTS = {"contract_created", "payment_received"}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


class EventIn(BaseModel):
    event: str
    chat_id: str
    bot_id: Optional[int] = None       # checkNumber'da yuborilgan botID — aniq bot tanlash uchun
    client_id: Optional[int] = None
    contract_id: Optional[int] = None
    contract_number: Optional[str] = None
    amount: Optional[float] = None
    date: Optional[str] = None


def _compose(ev: EventIn) -> str:
    d = _parse_date(ev.date)
    when = _fmt_date(d) if d else ""
    if ev.event == "contract_created":
        lines = ["🎉 <b>Янги шартнома расмийлаштирилди!</b>", ""]
        if ev.contract_number:
            lines.append(f"📄 Шартнома: {ev.contract_number}")
        if ev.amount:
            lines.append(f"💵 Сумма: <b>{_fmt_money(_to_float(ev.amount))}</b>")
        if when:
            lines.append(f"📅 Сана: {when}")
        lines += ["", "Батафсил: 💳 Қарзим бўлими."]
    else:  # payment_received
        lines = ["✅ <b>Тўловингиз қабул қилинди!</b>", ""]
        if ev.amount:
            lines.append(f"💰 Сумма: <b>{_fmt_money(_to_float(ev.amount))}</b>")
        if ev.contract_number:
            lines.append(f"📄 Шартнома: {ev.contract_number}")
        if when:
            lines.append(f"📅 Сана: {when}")
        lines += ["", "Янгиланган ҳолат: 📅 Графигим бўлими."]
    return "\n".join(lines)


@router.post("/events")
async def receive_event(request: Request, payload: EventIn):
    started = time.monotonic()

    def _log(status: int, response: dict, outcome: str, error: str = ""):
        api_log.record(
            endpoint="1c→bot events", method="POST", url=str(request.url.path),
            request_body=payload.model_dump(exclude_none=True),
            status_code=status, response_body=response, outcome=outcome, error=error,
            duration_ms=(time.monotonic() - started) * 1000,
        )

    if payload.event not in EVENTS:
        resp = {"error": {"code": "VALIDATION_ERROR", "message": f"event noto'g'ri: {payload.event!r} (contract_created | payment_received)"}}
        _log(400, resp, "error", "VALIDATION_ERROR")
        return JSONResponse(status_code=400, content=resp)

    try:
        chat_id = int(payload.chat_id)
    except (TypeError, ValueError):
        resp = {"error": {"code": "VALIDATION_ERROR", "message": "chat_id butun son bo'lishi kerak"}}
        _log(400, resp, "error", "VALIDATION_ERROR")
        return JSONResponse(status_code=400, content=resp)

    # Qaysi botdan yuborish: 1C bot_id yuborgan bo'lsa — aynan o'sha bot.
    bm = request.app.state.bot_manager
    instance = None
    if payload.bot_id is not None:
        instance = bm.get_instance(int(payload.bot_id))
        if instance is None:
            resp = {"error": {"code": "BOT_NOT_FOUND", "message": f"bot_id={payload.bot_id} ishlamayapti yoki mavjud emas"}}
            _log(404, resp, "error", "BOT_NOT_FOUND")
            return JSONResponse(status_code=404, content=resp)
    else:
        # eski usul (bot_id yuborilmagan): chat_id ro'yxatdan o'tgan botni topamiz
        async with async_session() as session:
            result = await session.execute(select(User).where(User.telegram_id == chat_id))
            users = list(result.scalars().all())
        if payload.client_id is not None and len(users) > 1:
            matched = [u for u in users if u.client_id == str(payload.client_id)]
            users = matched or users
        for u in users:
            instance = bm.get_instance(u.bot_id)
            if instance:
                break
        if instance is None and bm.running_count == 1:
            instance = next(iter(bm._instances.values()))
        if instance is None:
            resp = {"error": {"code": "CHAT_NOT_FOUND", "message": "Bu chat_id uchun ishlayotgan bot topilmadi"}}
            _log(404, resp, "error", "CHAT_NOT_FOUND")
            return JSONResponse(status_code=404, content=resp)

    text = _compose(payload)
    delivered = True
    try:
        await instance.bot.send_message(chat_id, text)
    except Exception as e:  # bot bloklangan, chat o'chirilgan va h.k.
        delivered = False
        logger.warning("1c event yetkazilmadi chat=%s: %s", chat_id, e)

    resp = {"success": True, "delivered": delivered}
    _log(200, resp, "ok" if delivered else "error", "" if delivered else "Telegram'ga yetkazilmadi (bot bloklangan bo'lishi mumkin)")
    return resp
