"""Payment reminders (TZ 7: Эслатмалар).

One background task per bot: every ``REMINDER_INTERVAL`` seconds it walks the
bot's registered users and sends
  • "тўлов яқинлашмоқда"  — 3 days before a due date
  • "бугун тўлов куни"     — on the due date
  • "тўлов кечикди"        — while an installment is overdue
Each (user, kind, due date) is sent at most once per calendar day.
"""
import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.config import REMINDER_INTERVAL
from app.models import User
from app.services.nasiya_api import NasiyaService, ServiceUnavailable, NasiyaError

logger = logging.getLogger(__name__)

_svc = NasiyaService()
_fmt_money = NasiyaService.fmt_money
_fmt_date = NasiyaService.fmt_date

# (bot_id, telegram_id, kind, due_iso) -> date sent (YYYY-MM-DD)
_sent: dict[tuple, str] = {}


def _mark_once(key: tuple, today_iso: str) -> bool:
    if _sent.get(key) == today_iso:
        return False
    _sent[key] = today_iso
    if len(_sent) > 20_000:
        for k in [k for k, v in _sent.items() if v != today_iso]:
            _sent.pop(k, None)
    return True


async def _check_user(bot: Bot, bot_id: int, creds: tuple, user: User) -> None:
    cab = await _svc.get_cabinet(*creds, user.client_id)
    if not cab or not cab.get("reminders_enabled", True):
        return
    rows = await _svc.get_schedule(*creds, user.client_id, status="all")
    today = datetime.now(timezone.utc).date()
    today_iso = today.isoformat()

    for r in rows:
        if r["status"] == "paid":
            continue
        days = (r["date"] - today).days
        if r["status"] == "overdue" or days < 0:
            kind, text = "overdue", (
                "🔴 <b>Тўлов муддати ўтган!</b>\n\n"
                f"📄 Шартнома: {r['contract_number']}\n"
                f"💰 Сумма: <b>{_fmt_money(r['amount'])}</b>\n"
                f"📅 Муддат: {_fmt_date(r['date'])} ({-days} кун кечикди)\n\n"
                "Илтимос, имкон қадар тезроқ тўланг: 💰 Тўлов қилиш"
            )
        elif days == 0:
            kind, text = "today", (
                "📅 <b>Бугун тўлов куни</b>\n\n"
                f"📄 Шартнома: {r['contract_number']}\n"
                f"💰 Сумма: <b>{_fmt_money(r['amount'])}</b>\n\n"
                "Тўлаш учун: 💰 Тўлов қилиш"
            )
        elif days == 3:
            kind, text = "soon", (
                "🔔 <b>Тўлов яқинлашмоқда</b>\n\n"
                f"📄 Шартнома: {r['contract_number']}\n"
                f"💰 Сумма: <b>{_fmt_money(r['amount'])}</b>\n"
                f"📅 Муддат: {_fmt_date(r['date'])} (3 кундан кейин)"
            )
        else:
            continue
        key = (bot_id, int(user.telegram_id), kind, r["date"].isoformat())
        if not _mark_once(key, today_iso):
            continue
        try:
            await bot.send_message(int(user.telegram_id), text)
        except Exception as e:  # blocked bot, deleted chat, etc.
            logger.debug("reminder send failed bot=%s tg=%s: %s", bot_id, user.telegram_id, e)


async def reminder_loop(bot: Bot, bot_id: int, creds: tuple, session_factory: async_sessionmaker[AsyncSession]) -> None:
    if REMINDER_INTERVAL <= 0:
        return
    await asyncio.sleep(15)  # let polling settle first
    while True:
        try:
            async with session_factory() as session:
                result = await session.execute(
                    select(User).where(User.bot_id == bot_id, User.client_id.is_not(None))
                )
                users = list(result.scalars().all())
            for user in users:
                try:
                    await _check_user(bot, bot_id, creds, user)
                except ServiceUnavailable as e:
                    logger.info("reminders: 1C %s not ready yet — skip this round", e.endpoint)
                    break
                except NasiyaError as e:
                    logger.debug("reminders: 1C error for tg=%s: %s", user.telegram_id, e)
                except Exception as e:
                    logger.warning("reminder check failed bot=%s tg=%s: %s", bot_id, user.telegram_id, e)
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("reminder loop error bot=%s: %s", bot_id, e)
        await asyncio.sleep(REMINDER_INTERVAL)
