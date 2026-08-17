"""MX Nasiya Telegram bot — client's installment (nasiya) personal cabinet.

Sections (TZ):
  1. Login (phone → 1C checkNumber)          — unchanged, production
  2. 👤 Кабинет   3. 💳 Қарзим   4. 📅 Графигим   5. 💰 Тўлов қилиш / 🧾 Тўловлар
  6. 🛍 Харидлар  7. Эслатмалар (reminders task)  8. 📞 Ёрдам  9. 🎁 Акциялар
Data comes from ``NasiyaService`` (mock now, 1C later) — handlers stay the same.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.config import WEBAPP_URL
from app.models import CartItem, User, WebSession
from app.services.api import APIService
from app.services.nasiya_api import NasiyaService

SESSION_TTL_HOURS = 24 * 30  # 30 days

logger = logging.getLogger(__name__)

# ── menu labels (TZ) ────────────────────────────────────────────────────────
BTN_DEBT = "💳 Қарзим"
BTN_SCHEDULE = "📅 Графигим"
BTN_PAY = "💰 Тўлов қилиш"
BTN_PAYMENTS = "🧾 Тўловлар"
BTN_PURCHASES = "🛍 Харидлар"
BTN_CABINET = "👤 Кабинет"
BTN_HELP = "📞 Ёрдам"
BTN_PROMO = "🎁 Акциялар"
BTN_LOGOUT = "🚪 Чиқиш"
BTN_CANCEL = "❌ Бекор қилиш"
BTN_SEND_PHONE = "📱 Телефон рақамни юбориш"

fmt_money = NasiyaService.fmt_money
fmt_date = NasiyaService.fmt_date

STATUS_ICON = {"paid": "✅", "pending": "⏳", "overdue": "🔴"}

# Payment providers (demo): key -> (label, demo checkout url)
PAY_METHODS = {
    "payme": ("Payme", "https://checkout.paycom.uz/"),
    "click": ("Click", "https://my.click.uz/"),
    "paynet": ("Paynet", "https://app.paynet.uz/"),
}
CONTRACT_STATUS = {"active": "🟢 Фаол", "overdue": "🔴 Кечиккан", "closed": "✅ Ёпилган"}


class PayState(StatesGroup):
    waiting_amount = State()
    waiting_confirm = State()


class SupportState(StatesGroup):
    waiting_request = State()
    waiting_question = State()


# ── DB helpers (login flow — unchanged) ─────────────────────────────────────
async def _get_user(
    session_factory: async_sessionmaker[AsyncSession],
    telegram_id: int,
    bot_id: int,
) -> Optional[User]:
    async with session_factory() as session:
        stmt = select(User).where(
            User.telegram_id == telegram_id,
            User.bot_id == bot_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def _save_user(
    session_factory: async_sessionmaker[AsyncSession],
    telegram_id: int,
    bot_id: int,
    phone_number: str,
    client_id: str,
):
    async with session_factory() as session:
        stmt = select(User).where(
            User.telegram_id == telegram_id,
            User.bot_id == bot_id,
        )
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            user.phone_number = phone_number
            user.client_id = client_id
        else:
            user = User(
                telegram_id=telegram_id,
                phone_number=phone_number,
                client_id=client_id,
                bot_id=bot_id,
            )
            session.add(user)
        await session.commit()


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_DEBT), KeyboardButton(text=BTN_SCHEDULE)],
            [KeyboardButton(text=BTN_PAY), KeyboardButton(text=BTN_PAYMENTS)],
            [KeyboardButton(text=BTN_PURCHASES), KeyboardButton(text=BTN_CABINET)],
            [KeyboardButton(text=BTN_HELP), KeyboardButton(text=BTN_PROMO)],
            [KeyboardButton(text=BTN_LOGOUT)],
        ],
        resize_keyboard=True,
    )


def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_SEND_PHONE, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
    )


def _progress_bar(done: float, total: float, width: int = 10) -> str:
    if total <= 0:
        return "░" * width
    filled = int(round(width * min(done, total) / total))
    return "█" * filled + "░" * (width - filled)


def _human_days(days: Optional[int]) -> str:
    if days is None:
        return ""
    if days < 0:
        return f"{-days} кун кечиккан"
    if days == 0:
        return "бугун"
    if days == 1:
        return "эртага"
    return f"{days} кундан кейин"


def create_router(
    bot_config: dict,
    session_factory: async_sessionmaker[AsyncSession],
) -> Router:
    router = Router()
    api_service = APIService()
    svc = NasiyaService()

    bot_id = bot_config["id"]
    creds = (bot_config["base_url"], bot_config["one_c_login"], bot_config["one_c_password"])

    async def _logout_user(telegram_id: int):
        async with session_factory() as session:
            stmt = select(User).where(
                User.telegram_id == telegram_id,
                User.bot_id == bot_id,
            )
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if user:
                user.client_id = None
                user.phone_number = None
            await session.execute(
                delete(WebSession).where(
                    WebSession.telegram_id == telegram_id,
                    WebSession.bot_id == bot_id,
                )
            )
            await session.execute(
                delete(CartItem).where(
                    CartItem.telegram_id == telegram_id,
                    CartItem.bot_id == bot_id,
                )
            )
            await session.commit()

    async def _require_client(message: Message) -> Optional[str]:
        """Return client_id or send the 'register first' hint."""
        user = await _get_user(session_factory, message.from_user.id, bot_id)
        if not user or not user.client_id:
            await message.answer(
                "❌ Аввал рўйхатдан ўтишингиз керак. Илтимос, /start буйруғини босинг."
            )
            return None
        return user.client_id

    async def _client_from_callback(callback: CallbackQuery) -> Optional[str]:
        user = await _get_user(session_factory, callback.from_user.id, bot_id)
        if not user or not user.client_id:
            await callback.answer("❌ Аввал рўйхатдан ўтинг: /start", show_alert=True)
            return None
        return user.client_id

    # ════════════════════════════════════════════════════════════════════
    # 1. LOGIN — unchanged logic
    # ════════════════════════════════════════════════════════════════════
    @router.message(Command("start"))
    async def start_handler(message: Message, state: FSMContext):
        await state.clear()
        user = await _get_user(session_factory, message.from_user.id, bot_id)
        company = bot_config["company_name"]

        if user and user.client_id:
            await message.answer(
                f"Ассалому алайкум! {company} ботига хуш келибсиз.\n\n"
                "Бу — насия бўйича шахсий кабинетингиз. Менюдан керакли бўлимни танланг:",
                reply_markup=main_menu_keyboard(),
            )
            return

        await message.answer(
            f"Ассалому алайкум! {company} ботига хуш келибсиз.\n\n"
            "Илтимос, телефон рақамингизни юборинг.",
            reply_markup=phone_keyboard(),
        )

    @router.message(Command("getsession"))
    async def getsession_handler(message: Message):
        if not WEBAPP_URL:
            await message.answer("⚠️ WEBAPP_URL созланмаган. Администратор билан боғланинг.")
            return

        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)

        async with session_factory() as db:
            ws = WebSession(
                token=token,
                telegram_id=message.from_user.id,
                bot_id=bot_id,
                first_name=message.from_user.first_name or "",
                last_name=message.from_user.last_name or "",
                username=message.from_user.username or "",
                expires_at=expires_at,
            )
            db.add(ws)
            await db.commit()

        url = f"{WEBAPP_URL.rstrip('/')}/webapp?bot_id={bot_id}&session={token}"
        await message.answer(
            "🔗 <b>Браузер учун шахсий ҳавола</b>\n\n"
            f"<a href=\"{url}\">{url}</a>\n\n"
            "Бу ҳаволани ҳеч ким билан бўлишманг. "
            f"Муддати: {SESSION_TTL_HOURS // 24} кун.",
            disable_web_page_preview=True,
        )

    async def _do_logout(message: Message, state: FSMContext):
        await state.clear()
        await _logout_user(message.from_user.id)
        await message.answer(
            "Сиз тизимдан чиқдингиз.\n\n"
            "Қайтадан кириш учун телефон рақамингизни юборинг.",
            reply_markup=phone_keyboard(),
        )

    @router.message(Command("logout"))
    async def logout_command_handler(message: Message, state: FSMContext):
        await _do_logout(message, state)

    @router.message(F.text == BTN_LOGOUT)
    async def logout_button_handler(message: Message, state: FSMContext):
        await _do_logout(message, state)

    @router.message(F.contact)
    async def contact_handler(message: Message, state: FSMContext):
        if message.contact is None:
            return
        await state.clear()

        phone = message.contact.phone_number.lstrip("+").replace(" ", "").replace("-", "")

        logger.info(
            "🤖 Bot[%s] contact: telegram_id=%s phone=%s",
            bot_id, message.from_user.id, phone,
        )

        result = await api_service.register_device(*creds, phone, str(message.chat.id))

        logger.info(
            "🤖 Bot[%s] register_device result: %s",
            bot_id,
            f"id={result.get('id')}" if result else "None",
        )

        if result and result.get("id"):
            client_id = str(result["id"])

            await _save_user(session_factory, message.from_user.id, bot_id, phone, client_id)
            # let the cabinet show the real name/phone from 1C
            await svc.set_profile_basics(client_id, name=str(result.get("name") or ""), phone=phone)

            name = result.get("name") or ""
            hello = f"✅ Рўйхатдан муваффақиятли ўтдингиз{', ' + name if name else ''}!"
            await message.answer(
                hello + "\n\nМенюдан керакли бўлимни танланг:",
                reply_markup=main_menu_keyboard(),
            )
        else:
            await message.answer(
                "❌ Сиз топилмадингиз. Илтимос, қайтадан уриниб кўринг "
                "ёки администратор билан боғланинг."
            )

    # ════════════════════════════════════════════════════════════════════
    # 2. 👤 КАБИНЕТ
    # ════════════════════════════════════════════════════════════════════
    def _cabinet_text(cab: dict) -> str:
        lines = [
            "<b>👤 Шахсий кабинет</b>\n",
            f"▪️ <b>Ф.И.О:</b> {cab.get('name') or '—'}",
            f"▪️ <b>Телефон:</b> +{cab.get('phone')}" if cab.get("phone") else "▪️ <b>Телефон:</b> —",
            f"▪️ <b>Статус:</b> {cab.get('status', '—')}",
            f"▪️ <b>Мижоз ID:</b> {cab.get('client_id')}",
            f"▪️ <b>Мижоз бўлган сана:</b> {cab.get('registered_at', '—')}",
            "",
            f"📄 <b>Амалдаги шартномалар:</b> {cab['active_contracts']} та (жами {cab['total_contracts']})",
            f"💵 <b>Умумий насия суммаси:</b> {fmt_money(cab['total_nasiya'])}",
            f"✅ <b>Тўланган:</b> {fmt_money(cab['total_paid'])}",
            f"💳 <b>Қолган қарз:</b> {fmt_money(cab['remaining_debt'])}",
        ]
        if cab["overdue_amount"] > 0:
            lines.append(f"🔴 <b>Муддати ўтган:</b> {fmt_money(cab['overdue_amount'])} ({cab['overdue_count']} та тўлов)")
        lines.append("")
        lines.append(f"🔔 Эслатмалар: {'ёқилган' if cab.get('reminders_enabled') else 'ўчирилган'}")
        return "\n".join(lines)

    def _cabinet_kb(cab: dict) -> InlineKeyboardMarkup:
        toggle = "🔕 Эслатмаларни ўчириш" if cab.get("reminders_enabled") else "🔔 Эслатмаларни ёқиш"
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📄 Шартномаларим", callback_data="debt_list"),
             InlineKeyboardButton(text="📅 Кейинги тўлов", callback_data="sched_next")],
            [InlineKeyboardButton(text=toggle, callback_data="cab_toggle_rem")],
        ])

    @router.message(F.text == BTN_CABINET)
    async def cabinet_handler(message: Message):
        client_id = await _require_client(message)
        if not client_id:
            return
        cab = await svc.get_cabinet(*creds, client_id)
        if not cab:
            await message.answer("❌ Маълумот олинмади. Кейинроқ уриниб кўринг.")
            return
        await message.answer(_cabinet_text(cab), reply_markup=_cabinet_kb(cab))

    @router.callback_query(F.data == "cab_toggle_rem")
    async def cabinet_toggle_reminders(callback: CallbackQuery):
        client_id = await _client_from_callback(callback)
        if not client_id:
            return
        cab = await svc.get_cabinet(*creds, client_id)
        await svc.set_reminders(client_id, not cab.get("reminders_enabled"))
        cab = await svc.get_cabinet(*creds, client_id)
        await callback.answer("Эслатмалар ёқилди 🔔" if cab["reminders_enabled"] else "Эслатмалар ўчирилди 🔕")
        try:
            await callback.message.edit_text(_cabinet_text(cab), reply_markup=_cabinet_kb(cab))
        except Exception:
            pass

    # ════════════════════════════════════════════════════════════════════
    # 3. 💳 ҚАРЗИМ — contracts & debt
    # ════════════════════════════════════════════════════════════════════
    def _contracts_overview(contracts: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
        total_debt = sum(c["remaining_debt"] for c in contracts)
        overdue = sum(c["overdue_amount"] for c in contracts)
        active = [c for c in contracts if c["status"] != "closed"]
        lines = [
            "<b>💳 Қарзим</b>\n",
            f"💵 <b>Умумий қолган қарз:</b> {fmt_money(total_debt)}",
            f"📄 <b>Фаол шартномалар:</b> {len(active)} та",
        ]
        if overdue > 0:
            lines.append(f"🔴 <b>Муддати ўтган:</b> {fmt_money(overdue)}")
        lines.append("\nШартнома бўйича батафсил кўриш учун танланг:")
        buttons = []
        for c in contracts:
            icon = CONTRACT_STATUS[c["status"]].split()[0]
            buttons.append([InlineKeyboardButton(
                text=f"{icon} {c['number']} — {fmt_money(c['remaining_debt'])}",
                callback_data=f"ct_{c['contract_id']}",
            )])
        buttons.append([InlineKeyboardButton(text="💰 Тўлов қилиш", callback_data="pay_start")])
        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)

    def _contract_text(c: dict) -> str:
        lines = [
            f"<b>📄 Шартнома {c['number']}</b>",
            f"Ҳолати: {CONTRACT_STATUS[c['status']]}",
            f"Сана: {fmt_date(c['date'])}  •  Филиал: {c.get('branch', '—')}",
            "",
            "<b>🛍 Товарлар:</b>",
        ]
        for p in c["products"]:
            lines.append(f"  • {p['name']} × {p['qty']} — {fmt_money(p['sum'])}")
        paid_total = c["paid"] + c["initial_payment"]
        pct = min(100, round(paid_total / c["total"] * 100)) if c["total"] else 0
        lines += [
            "",
            f"💵 <b>Насия суммаси:</b> {fmt_money(c['total'])}",
            f"💰 <b>Бошланғич тўлов:</b> {fmt_money(c['initial_payment'])}",
            f"📆 <b>Муддат:</b> {c['months']} ой  •  ойига {fmt_money(c['monthly_payment'])}",
            f"🗓 <b>Якуний сана:</b> {fmt_date(c['end_date'])}",
            f"✅ <b>Тўланган:</b> {fmt_money(paid_total)} ({c['paid_count']}/{c['months']} тўлов)",
            f"💳 <b>Қолган қарз:</b> {fmt_money(c['remaining_debt'])}",
            f"{_progress_bar(paid_total, c['total'])} {pct}%",
        ]
        if c["overdue_amount"] > 0:
            lines.append(f"🔴 <b>Муддати ўтган:</b> {fmt_money(c['overdue_amount'])} ({c['overdue_count']} та)")
        if c["next_payment_date"]:
            lines.append(
                f"⏭ <b>Кейинги тўлов:</b> {fmt_money(c['next_payment_amount'])} — "
                f"{fmt_date(c['next_payment_date'])} ({_human_days(c['days_to_next'])})"
            )
        return "\n".join(lines)

    def _contract_kb(c: dict) -> InlineKeyboardMarkup:
        rows = [[InlineKeyboardButton(text="📅 Графиги", callback_data=f"sched_ct_{c['contract_id']}")]]
        if c["status"] != "closed":
            rows[0].append(InlineKeyboardButton(text="💰 Тўлаш", callback_data=f"pay_ct_{c['contract_id']}"))
        rows.append([InlineKeyboardButton(text="⬅️ Шартномалар", callback_data="debt_list")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @router.message(F.text == BTN_DEBT)
    async def debt_handler(message: Message):
        client_id = await _require_client(message)
        if not client_id:
            return
        contracts = await svc.get_contracts(*creds, client_id)
        if not contracts:
            await message.answer("📄 Сизда насия шартномалари йўқ.")
            return
        text, kb = _contracts_overview(contracts)
        await message.answer(text, reply_markup=kb)

    @router.callback_query(F.data == "debt_list")
    async def debt_list_callback(callback: CallbackQuery):
        client_id = await _client_from_callback(callback)
        if not client_id:
            return
        contracts = await svc.get_contracts(*creds, client_id)
        await callback.answer()
        if not contracts:
            await callback.message.answer("📄 Сизда насия шартномалари йўқ.")
            return
        text, kb = _contracts_overview(contracts)
        try:
            await callback.message.edit_text(text, reply_markup=kb)
        except Exception:
            await callback.message.answer(text, reply_markup=kb)

    @router.callback_query(F.data.startswith("ct_"))
    async def contract_callback(callback: CallbackQuery):
        client_id = await _client_from_callback(callback)
        if not client_id:
            return
        contract_id = int(callback.data.split("_", 1)[1])
        c = await svc.get_contract(*creds, client_id, contract_id)
        if not c:
            await callback.answer("❌ Шартнома топилмади.", show_alert=True)
            return
        await callback.answer()
        try:
            await callback.message.edit_text(_contract_text(c), reply_markup=_contract_kb(c))
        except Exception:
            await callback.message.answer(_contract_text(c), reply_markup=_contract_kb(c))

    # ════════════════════════════════════════════════════════════════════
    # 4. 📅 ГРАФИГИМ — payment schedule
    # ════════════════════════════════════════════════════════════════════
    SCHED_FILTERS = [("all", "Барчаси"), ("paid", "Тўланган"), ("pending", "Кутилаётган"), ("overdue", "Муддати ўтган")]

    def _schedule_kb(current: str, contract_id: Optional[int] = None) -> InlineKeyboardMarkup:
        suffix = f"_{contract_id}" if contract_id else ""
        row = []
        for key, label in SCHED_FILTERS:
            mark = "• " if key == current else ""
            row.append(InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"sched_{key}{suffix}"))
        rows = [row[:2], row[2:]]
        rows.append([InlineKeyboardButton(text="💰 Тўлов қилиш", callback_data="pay_start")])
        if contract_id:
            rows.append([
                InlineKeyboardButton(text="⬅️ Шартнома", callback_data=f"ct_{contract_id}"),
                InlineKeyboardButton(text="📋 Бошқа шартнома", callback_data="sched_pick"),
            ])
        else:
            rows.append([InlineKeyboardButton(text="📋 Шартнома танлаш", callback_data="sched_pick")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def _schedule_text(client_id: str, status: str, contract_id: Optional[int] = None) -> str:
        rows = await svc.get_schedule(*creds, client_id, status=status, contract_id=contract_id)
        nxt = await svc.get_next_payment(*creds, client_id)
        title = dict(SCHED_FILTERS)[status]
        today = datetime.now(timezone.utc).date()
        lines = ["<b>📅 Тўлов графиги</b>" + (f" — {title}" if status != "all" else "")]
        if contract_id and rows:
            lines[0] += f"\nШартнома: {rows[0]['contract_number']}"
        if nxt and not contract_id:
            days = (nxt["date"] - today).days
            icon = "🔴" if nxt["status"] == "overdue" else "⏭"
            lines.append(
                f"\n{icon} <b>Келгуси тўлов:</b> {fmt_money(nxt['amount'])} — "
                f"{fmt_date(nxt['date'])} ({_human_days(days)})\n"
                f"   Шартнома: {nxt['contract_number']}"
            )
        elif not nxt and not contract_id:
            lines.append("\n✅ Барча тўловлар амалга оширилган.")
        lines.append("")
        if not rows:
            lines.append("Бу бўлимда тўловлар йўқ.")
        else:
            total = 0.0
            for r in rows[:40]:
                icon = STATUS_ICON[r["status"]]
                extra = ""
                if r["status"] == "paid" and r.get("paid_date"):
                    extra = f" (тўланди {fmt_date(r['paid_date'])})"
                elif r["status"] == "overdue":
                    extra = f" ({_human_days((r['date'] - today).days)})"
                ct = "" if contract_id else f" • {r['contract_number']}"
                lines.append(f"{icon} {fmt_date(r['date'])} — {fmt_money(r['amount'])}{ct}{extra}")
                total += r["amount"]
            if len(rows) > 40:
                lines.append(f"… ва яна {len(rows) - 40} та")
            lines.append(f"\n<b>Жами:</b> {fmt_money(total)} ({len(rows)} та тўлов)")
        return "\n".join(lines)

    @router.message(F.text == BTN_SCHEDULE)
    async def schedule_handler(message: Message):
        client_id = await _require_client(message)
        if not client_id:
            return
        await _schedule_entry(message, client_id)

    async def _schedule_entry(target: Message, client_id: str, edit: bool = False):
        """📅 Графигим: 1 contract → its schedule directly; several → pick first."""
        contracts = await svc.get_contracts(*creds, client_id)
        if not contracts:
            text, kb = "📄 Сизда насия шартномалари йўқ.", None
        elif len(contracts) == 1:
            cid = contracts[0]["contract_id"]
            text, kb = await _schedule_text(client_id, "all", cid), _schedule_kb("all", cid)
        else:
            text, kb = _schedule_pick_view(contracts)
        if edit:
            try:
                await target.edit_text(text, reply_markup=kb)
                return
            except Exception:
                pass
        await target.answer(text, reply_markup=kb)

    def _schedule_pick_view(contracts: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
        lines = ["<b>📅 Тўлов графиги</b>\n", "Қайси шартнома бўйича графикни кўрасиз?"]
        buttons = []
        for c in contracts:
            icon = CONTRACT_STATUS[c["status"]].split()[0]
            nxt = f" • {fmt_date(c['next_payment_date'])}" if c["next_payment_date"] else ""
            buttons.append([InlineKeyboardButton(
                text=f"{icon} {c['number']} — {fmt_money(c['remaining_debt'])}{nxt}",
                callback_data=f"sched_ct_{c['contract_id']}",
            )])
        buttons.append([InlineKeyboardButton(text="📊 Барча шартномалар графиги", callback_data="sched_all")])
        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)

    @router.callback_query(F.data == "sched_pick")
    async def schedule_pick_callback(callback: CallbackQuery):
        client_id = await _client_from_callback(callback)
        if not client_id:
            return
        await callback.answer()
        await _schedule_entry(callback.message, client_id, edit=True)

    @router.callback_query(F.data == "sched_next")
    async def schedule_next_callback(callback: CallbackQuery):
        client_id = await _client_from_callback(callback)
        if not client_id:
            return
        await callback.answer()
        await callback.message.answer(await _schedule_text(client_id, "pending"), reply_markup=_schedule_kb("pending"))

    @router.callback_query(F.data.startswith("sched_"))
    async def schedule_filter_callback(callback: CallbackQuery):
        client_id = await _client_from_callback(callback)
        if not client_id:
            return
        parts = callback.data.split("_")  # sched_<status>[_<contract_id>] | sched_ct_<id>
        contract_id: Optional[int] = None
        if parts[1] == "ct":
            status = "all"
            contract_id = int(parts[2])
        else:
            status = parts[1]
            if len(parts) > 2:
                contract_id = int(parts[2])
        if status not in dict(SCHED_FILTERS):
            await callback.answer()
            return
        await callback.answer()
        text = await _schedule_text(client_id, status, contract_id)
        try:
            await callback.message.edit_text(text, reply_markup=_schedule_kb(status, contract_id))
        except Exception:
            pass  # same content → Telegram rejects the edit

    # ════════════════════════════════════════════════════════════════════
    # 5. 💰 ТЎЛОВ ҚИЛИШ — online payment (mock)  /  🧾 ТЎЛОВЛАР — history
    # ════════════════════════════════════════════════════════════════════
    async def _pay_pick_contract(target: Message, client_id: str, edit: bool = False):
        contracts = [c for c in await svc.get_contracts(*creds, client_id) if c["status"] != "closed"]
        if not contracts:
            text = "✅ Сизда очиқ қарз йўқ — барча шартномалар ёпилган."
            if edit:
                try:
                    await target.edit_text(text)
                    return
                except Exception:
                    pass
            await target.answer(text)
            return
        buttons = [[InlineKeyboardButton(
            text=f"{c['number']} — қарз {fmt_money(c['remaining_debt'])}",
            callback_data=f"pay_ct_{c['contract_id']}",
        )] for c in contracts]
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        text = "<b>💰 Тўлов қилиш</b>\n\nҚайси шартнома бўйича тўлайсиз?"
        if edit:
            try:
                await target.edit_text(text, reply_markup=kb)
                return
            except Exception:
                pass
        await target.answer(text, reply_markup=kb)

    @router.message(F.text == BTN_PAY)
    async def pay_handler(message: Message, state: FSMContext):
        client_id = await _require_client(message)
        if not client_id:
            return
        await state.clear()
        await _pay_pick_contract(message, client_id)

    @router.callback_query(F.data == "pay_start")
    async def pay_start_callback(callback: CallbackQuery, state: FSMContext):
        client_id = await _client_from_callback(callback)
        if not client_id:
            return
        await state.clear()
        await callback.answer()
        await _pay_pick_contract(callback.message, client_id)

    @router.callback_query(F.data.startswith("pay_ct_"))
    async def pay_contract_callback(callback: CallbackQuery, state: FSMContext):
        client_id = await _client_from_callback(callback)
        if not client_id:
            return
        contract_id = int(callback.data.rsplit("_", 1)[1])
        c = await svc.get_contract(*creds, client_id, contract_id)
        if not c or c["status"] == "closed":
            await callback.answer("Бу шартнома бўйича қарз йўқ.", show_alert=True)
            return
        await callback.answer()
        await state.update_data(pay_contract_id=contract_id)
        rows = []
        if c["overdue_amount"] > 0:
            rows.append([InlineKeyboardButton(
                text=f"🔴 Муддати ўтганни тўлаш — {fmt_money(c['overdue_amount'])}",
                callback_data=f"pay_amt_{contract_id}_{int(c['overdue_amount'])}",
            )])
        if c["next_payment_amount"] > 0:
            rows.append([InlineKeyboardButton(
                text=f"⏭ Навбатдаги тўлов — {fmt_money(c['next_payment_amount'])}",
                callback_data=f"pay_amt_{contract_id}_{int(c['next_payment_amount'])}",
            )])
        rows.append([InlineKeyboardButton(
            text=f"💳 Тўлиқ қарзни ёпиш — {fmt_money(c['remaining_debt'])}",
            callback_data=f"pay_amt_{contract_id}_{int(c['remaining_debt'])}",
        )])
        rows.append([InlineKeyboardButton(text="✏️ Бошқа сумма", callback_data=f"pay_custom_{contract_id}")])
        rows.append([InlineKeyboardButton(text="⬅️ Орқага", callback_data="pay_start")])
        text = (
            f"<b>💰 Тўлов — {c['number']}</b>\n\n"
            f"💳 Қолган қарз: {fmt_money(c['remaining_debt'])}\n"
            + (f"⏭ Кейинги тўлов: {fmt_money(c['next_payment_amount'])} — {fmt_date(c['next_payment_date'])}\n" if c["next_payment_date"] else "")
            + "\nТўлов суммасини танланг:"
        )
        try:
            await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        except Exception:
            await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    @router.callback_query(F.data.startswith("pay_custom_"))
    async def pay_custom_callback(callback: CallbackQuery, state: FSMContext):
        client_id = await _client_from_callback(callback)
        if not client_id:
            return
        contract_id = int(callback.data.rsplit("_", 1)[1])
        await state.update_data(pay_contract_id=contract_id)
        await state.set_state(PayState.waiting_amount)
        await callback.answer()
        await callback.message.answer(
            "✏️ Тўлов суммасини сўмда киритинг (масалан: <code>500000</code>):",
            reply_markup=cancel_keyboard(),
        )

    @router.message(PayState.waiting_amount, F.text == BTN_CANCEL)
    async def pay_cancel_amount(message: Message, state: FSMContext):
        await state.clear()
        await message.answer("❌ Тўлов бекор қилинди.", reply_markup=main_menu_keyboard())

    @router.message(PayState.waiting_amount)
    async def pay_amount_entered(message: Message, state: FSMContext):
        raw = (message.text or "").replace(" ", "").replace(",", ".").replace("сўм", "")
        try:
            amount = float(raw)
            if amount <= 0:
                raise ValueError
        except ValueError:
            await message.answer("❌ Нотўғри сумма. Фақат рақам киритинг, масалан: <code>500000</code>")
            return
        data = await state.get_data()
        contract_id = data.get("pay_contract_id")
        client_id = await _require_client(message)
        if not client_id or not contract_id:
            await state.clear()
            return
        c = await svc.get_contract(*creds, client_id, contract_id)
        if not c:
            await state.clear()
            await message.answer("❌ Шартнома топилмади.", reply_markup=main_menu_keyboard())
            return
        if amount > c["remaining_debt"] + 0.5:
            amount = c["remaining_debt"]
            await message.answer(f"ℹ️ Сумма қолган қарздан кўп эди — {fmt_money(amount)} га туширилди.")
        await message.answer("Тасдиқланг:", reply_markup=main_menu_keyboard())
        await _pay_confirm(message, state, client_id, contract_id, amount)

    @router.callback_query(F.data.startswith("pay_amt_"))
    async def pay_amount_callback(callback: CallbackQuery, state: FSMContext):
        client_id = await _client_from_callback(callback)
        if not client_id:
            return
        _, _, contract_id, amount = callback.data.split("_")
        await callback.answer()
        await _pay_confirm(callback.message, state, client_id, int(contract_id), float(amount), edit=True)

    async def _pay_confirm(target: Message, state: FSMContext, client_id: str, contract_id: int, amount: float, edit: bool = False):
        c = await svc.get_contract(*creds, client_id, contract_id)
        if not c:
            await target.answer("❌ Шартнома топилмади.")
            return
        await state.set_state(PayState.waiting_confirm)
        await state.update_data(pay_contract_id=contract_id, pay_amount=amount, pay_method=None)
        after = max(0.0, c["remaining_debt"] - amount)
        text = (
            "<b>💳 Тўлов усулини танланг</b>\n\n"
            f"📄 Шартнома: {c['number']}\n"
            f"💰 Сумма: <b>{fmt_money(amount)}</b>\n"
            f"💳 Тўловдан кейин қолган қарз: {fmt_money(after)}\n\n"
            "Қайси тизим орқали тўлайсиз?"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🟦 Payme", callback_data="pay_method_payme"),
             InlineKeyboardButton(text="🔵 Click", callback_data="pay_method_click"),
             InlineKeyboardButton(text="🟩 Paynet", callback_data="pay_method_paynet")],
            [InlineKeyboardButton(text="❌ Бекор қилиш", callback_data="pay_cancel")],
        ])
        if edit:
            try:
                await target.edit_text(text, reply_markup=kb)
                return
            except Exception:
                pass
        await target.answer(text, reply_markup=kb)

    @router.callback_query(F.data.startswith("pay_method_"))
    async def pay_method_callback(callback: CallbackQuery, state: FSMContext):
        client_id = await _client_from_callback(callback)
        if not client_id:
            return
        method = callback.data.rsplit("_", 1)[1]
        if method not in PAY_METHODS:
            await callback.answer()
            return
        data = await state.get_data()
        contract_id, amount = data.get("pay_contract_id"), data.get("pay_amount")
        if not contract_id or not amount:
            await callback.answer("Тўлов маълумоти топилмади. Қайтадан бошланг.", show_alert=True)
            await state.clear()
            return
        c = await svc.get_contract(*creds, client_id, int(contract_id))
        if not c:
            await callback.answer("❌ Шартнома топилмади.", show_alert=True)
            return
        await state.set_state(PayState.waiting_confirm)
        await state.update_data(pay_method=method)
        label, url = PAY_METHODS[method]
        # demo checkout link: real integration will return a provider-generated URL
        checkout_url = f"{url}?merchant=mxnasiya&contract={c['number']}&amount={int(float(amount)) * 100}"
        await callback.answer()
        text = (
            f"<b>🧾 {label} орқали тўлов</b>\n\n"
            f"📄 Шартнома: {c['number']}\n"
            f"💰 Сумма: <b>{fmt_money(float(amount))}</b>\n"
            f"🏦 Усул: {label}\n\n"
            f"1️⃣ «🔗 {label} да тўлаш» тугмасини босиб тўловни амалга оширинг.\n"
            "2️⃣ Сўнг «✅ Тўладим — тасдиқлаш» тугмасини босинг.\n\n"
            "<i>ℹ️ Демо режим: ҳавола намунавий, тўлов ботда симуляция қилинади.</i>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🔗 {label} да тўлаш", url=checkout_url)],
            [InlineKeyboardButton(text="✅ Тўладим — тасдиқлаш", callback_data="pay_confirm")],
            [InlineKeyboardButton(text="🔄 Бошқа усул", callback_data="pay_back_method"),
             InlineKeyboardButton(text="❌ Бекор қилиш", callback_data="pay_cancel")],
        ])
        try:
            await callback.message.edit_text(text, reply_markup=kb)
        except Exception:
            await callback.message.answer(text, reply_markup=kb)

    @router.callback_query(F.data == "pay_back_method")
    async def pay_back_method_callback(callback: CallbackQuery, state: FSMContext):
        client_id = await _client_from_callback(callback)
        if not client_id:
            return
        data = await state.get_data()
        contract_id, amount = data.get("pay_contract_id"), data.get("pay_amount")
        if not contract_id or not amount:
            await callback.answer("Қайтадан бошланг.", show_alert=True)
            await state.clear()
            return
        await callback.answer()
        await _pay_confirm(callback.message, state, client_id, int(contract_id), float(amount), edit=True)

    @router.callback_query(F.data == "pay_cancel")
    async def pay_cancel_callback(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        await callback.answer("Бекор қилинди")
        try:
            await callback.message.edit_text("❌ Тўлов бекор қилинди.")
        except Exception:
            pass

    @router.callback_query(F.data == "pay_confirm")
    async def pay_confirm_callback(callback: CallbackQuery, state: FSMContext):
        client_id = await _client_from_callback(callback)
        if not client_id:
            return
        data = await state.get_data()
        contract_id = data.get("pay_contract_id")
        amount = data.get("pay_amount")
        method = data.get("pay_method")
        if not contract_id or not amount:
            await callback.answer("Тўлов маълумоти топилмади. Қайтадан бошланг.", show_alert=True)
            await state.clear()
            return
        if method not in PAY_METHODS:
            await callback.answer("Аввал тўлов усулини танланг.", show_alert=True)
            return
        method_label = PAY_METHODS[method][0]
        await callback.answer("Тўлов текширилмоқда…")
        result = await svc.make_payment(*creds, client_id, int(contract_id), float(amount), method=method_label)
        await state.clear()
        if not result or not result.get("success"):
            await callback.message.answer("❌ Тўлов амалга ошмади. Кейинроқ уриниб кўринг ёки оператор билан боғланинг.")
            return
        lines = [
            "<b>✅ Тўлов муваффақиятли амалга оширилди!</b>\n",
            "<b>🧾 Квитанция</b>",
            f"№ {result['receipt_no']}",
            f"📅 Сана: {fmt_date(result['date'])}",
            f"📄 Шартнома: {result['contract_number']}",
            f"💰 Сумма: <b>{fmt_money(result['amount'])}</b>",
            f"🏦 Усул: {method_label}",
            "",
            f"💳 <b>Қолган қарз:</b> {fmt_money(result['remaining_debt'])}",
        ]
        if result.get("closed"):
            lines.append("🎉 Шартнома тўлиқ ёпилди! Раҳмат!")
        elif result.get("next_payment_date"):
            lines.append(f"⏭ Кейинги тўлов: {fmt_money(result['next_payment_amount'])} — {fmt_date(result['next_payment_date'])}")
        if svc.is_mock():
            lines.append("\n<i>ℹ️ Тест режими: тўлов ҳақиқий эмас (mock).</i>")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Графигим", callback_data="sched_all"),
             InlineKeyboardButton(text="🧾 Тўловлар", callback_data="payments_list")],
        ])
        try:
            await callback.message.edit_text("\n".join(lines), reply_markup=kb)
        except Exception:
            await callback.message.answer("\n".join(lines), reply_markup=kb)

    async def _payments_text(client_id: str) -> str:
        payments = await svc.get_payments(*creds, client_id)
        cab = await svc.get_cabinet(*creds, client_id)
        lines = [
            "<b>🧾 Тўловлар</b>\n",
            f"✅ <b>Жами тўланган:</b> {fmt_money(cab['total_paid'])}",
            f"💳 <b>Қолган қарз:</b> {fmt_money(cab['remaining_debt'])}",
            "",
            "<b>Тўловлар тарихи:</b>",
        ]
        if not payments:
            lines.append("Ҳали тўловлар йўқ.")
        for p in payments[:25]:
            lines.append(
                f"• {fmt_date(p['date'])} — <b>{fmt_money(p['amount'])}</b>\n"
                f"   {p['contract_number']} • {p['method']} • {p.get('note', '')}\n"
                f"   Квитанция: <code>{p['receipt_no']}</code>"
            )
        if len(payments) > 25:
            lines.append(f"… ва яна {len(payments) - 25} та")
        return "\n".join(lines)

    @router.message(F.text == BTN_PAYMENTS)
    async def payments_handler(message: Message):
        client_id = await _require_client(message)
        if not client_id:
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💰 Тўлов қилиш", callback_data="pay_start")]])
        await message.answer(await _payments_text(client_id), reply_markup=kb)

    @router.callback_query(F.data == "payments_list")
    async def payments_callback(callback: CallbackQuery):
        client_id = await _client_from_callback(callback)
        if not client_id:
            return
        await callback.answer()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💰 Тўлов қилиш", callback_data="pay_start")]])
        await callback.message.answer(await _payments_text(client_id), reply_markup=kb)

    # ════════════════════════════════════════════════════════════════════
    # 6. 🛍 ХАРИДЛАР — purchase history
    # ════════════════════════════════════════════════════════════════════
    @router.message(F.text == BTN_PURCHASES)
    async def purchases_handler(message: Message):
        client_id = await _require_client(message)
        if not client_id:
            return
        rows = await svc.get_purchases(*creds, client_id)
        if not rows:
            await message.answer("🛍 Харидлар тарихи бўш.")
            return
        lines = ["<b>🛍 Харидлар тарихи</b>\n"]
        buttons = []
        for r in rows:
            lines.append(f"📅 <b>{fmt_date(r['date'])}</b> • Шартнома {r['contract_number']} • {r['branch']}")
            for p in r["products"]:
                lines.append(f"   • {p['name']} × {p['qty']} — {fmt_money(p['sum'])}")
            lines.append(f"   💵 Жами: <b>{fmt_money(r['total'])}</b>\n")
            buttons.append([InlineKeyboardButton(text=f"📄 {r['contract_number']}", callback_data=f"ct_{r['contract_id']}")])
        lines.append(f"Жами харидлар: {len(rows)} та • {fmt_money(sum(r['total'] for r in rows))}")
        await message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

    # ════════════════════════════════════════════════════════════════════
    # 8. 📞 ЁРДАМ — support
    # ════════════════════════════════════════════════════════════════════
    def _help_kb() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📞 Оператор билан боғланиш", callback_data="help_operator")],
            [InlineKeyboardButton(text="✍️ Мурожаат қолдириш", callback_data="help_request"),
             InlineKeyboardButton(text="💡 Савол / таклиф", callback_data="help_question")],
            [InlineKeyboardButton(text="🏢 Компания контактлари", callback_data="help_contacts"),
             InlineKeyboardButton(text="📍 Филиаллар", callback_data="help_branches")],
        ])

    @router.message(F.text == BTN_HELP)
    async def help_handler(message: Message, state: FSMContext):
        await state.clear()
        info = await svc.get_company_info(*creds)
        await message.answer(
            f"<b>📞 Ёрдам — {info['name']}</b>\n\n"
            f"Иш вақти: {info['working_hours']}\n"
            f"Телефон: {info['phone']}\n\n"
            "Керакли бўлимни танланг:",
            reply_markup=_help_kb(),
        )

    @router.callback_query(F.data == "help_operator")
    async def help_operator(callback: CallbackQuery):
        info = await svc.get_company_info(*creds)
        await callback.answer()
        await callback.message.answer(
            "<b>📞 Оператор билан боғланиш</b>\n\n"
            f"☎️ Телефон: {info['operator_phone']}\n"
            f"💬 Telegram: {info['operator_username']}\n"
            f"🕘 Иш вақти: {info['working_hours']}\n\n"
            "Ёки «✍️ Мурожаат қолдириш» тугмаси орқали ёзиб қолдиринг — оператор сиз билан боғланади.",
            reply_markup=_help_kb(),
        )

    @router.callback_query(F.data == "help_contacts")
    async def help_contacts(callback: CallbackQuery):
        info = await svc.get_company_info(*creds)
        await callback.answer()
        await callback.message.answer(
            f"<b>🏢 {info['name']} — контактлар</b>\n\n"
            f"☎️ {info['phone']}\n"
            f"✉️ {info['email']}\n"
            f"📍 {info['address']}\n"
            f"🕘 {info['working_hours']}",
            reply_markup=_help_kb(),
        )

    @router.callback_query(F.data == "help_branches")
    async def help_branches(callback: CallbackQuery):
        info = await svc.get_company_info(*creds)
        await callback.answer()
        lines = ["<b>📍 Филиаллар</b>\n"]
        for b in info["branches"]:
            lines.append(f"<b>{b['name']}</b>\n   📍 {b['address']}\n   ☎️ {b['phone']}\n   🕘 {b['hours']}\n")
        await callback.message.answer("\n".join(lines), reply_markup=_help_kb())

    @router.callback_query(F.data.in_({"help_request", "help_question"}))
    async def help_write(callback: CallbackQuery, state: FSMContext):
        client_id = await _client_from_callback(callback)
        if not client_id:
            return
        await callback.answer()
        if callback.data == "help_request":
            await state.set_state(SupportState.waiting_request)
            await callback.message.answer(
                "✍️ <b>Мурожаат қолдириш</b>\n\nМурожаатингизни битта хабарда ёзиб юборинг:",
                reply_markup=cancel_keyboard(),
            )
        else:
            await state.set_state(SupportState.waiting_question)
            await callback.message.answer(
                "💡 <b>Савол / таклиф</b>\n\nСавол ёки таклифингизни ёзиб юборинг:",
                reply_markup=cancel_keyboard(),
            )

    @router.message(SupportState.waiting_request, F.text == BTN_CANCEL)
    @router.message(SupportState.waiting_question, F.text == BTN_CANCEL)
    async def help_cancel(message: Message, state: FSMContext):
        await state.clear()
        await message.answer("❌ Бекор қилинди.", reply_markup=main_menu_keyboard())

    @router.message(SupportState.waiting_request)
    @router.message(SupportState.waiting_question)
    async def help_received(message: Message, state: FSMContext):
        client_id = await _require_client(message)
        if not client_id:
            await state.clear()
            return
        cur = await state.get_state()
        kind = "request" if cur == SupportState.waiting_request.state else "question"
        text = (message.text or message.caption or "").strip()
        if not text:
            await message.answer("Илтимос, матн юборинг.")
            return
        res = await svc.create_request(*creds, client_id, kind, text, telegram_id=message.from_user.id)
        await state.clear()
        if res and res.get("success"):
            label = "Мурожаатингиз" if kind == "request" else "Савол/таклифингиз"
            await message.answer(
                f"✅ {label} қабул қилинди (№ {res['id']}). Операторларимиз тез орада сиз билан боғланади.",
                reply_markup=main_menu_keyboard(),
            )
        else:
            await message.answer("❌ Юборишда хатолик. Кейинроқ уриниб кўринг.", reply_markup=main_menu_keyboard())

    # ════════════════════════════════════════════════════════════════════
    # 9. 🎁 АКЦИЯЛАР ВА ХАБАРЛАР
    # ════════════════════════════════════════════════════════════════════
    PROMO_TYPES = [("all", "Барчаси"), ("promo", "Акциялар"), ("new", "Янги товарлар"), ("special", "Махсус таклифлар"), ("news", "Хабарлар")]

    def _promo_kb(current: str) -> InlineKeyboardMarkup:
        row = [InlineKeyboardButton(text=("• " if k == current else "") + t, callback_data=f"promo_{k}") for k, t in PROMO_TYPES]
        return InlineKeyboardMarkup(inline_keyboard=[row[:3], row[3:]])

    async def _promo_text(kind: str) -> str:
        items = await svc.get_promotions(*creds)
        if kind != "all":
            items = [i for i in items if i["type"] == kind]
        lines = ["<b>🎁 Акциялар ва хабарлар</b>\n"]
        if not items:
            lines.append("Ҳозирча маълумот йўқ.")
        for i in items:
            lines.append(f"<b>{i['title']}</b>\n{i['text']}" + (f"\n<i>Амал қилиш муддати: {i['valid_until']}</i>" if i["valid_until"] else "") + "\n")
        return "\n".join(lines)

    @router.message(F.text == BTN_PROMO)
    async def promo_handler(message: Message):
        await message.answer(await _promo_text("all"), reply_markup=_promo_kb("all"))

    @router.callback_query(F.data.startswith("promo_"))
    async def promo_callback(callback: CallbackQuery):
        kind = callback.data.split("_", 1)[1]
        await callback.answer()
        try:
            await callback.message.edit_text(await _promo_text(kind), reply_markup=_promo_kb(kind))
        except Exception:
            pass

    # ── generic cancel outside of a state ───────────────────────────────
    @router.message(F.text == BTN_CANCEL)
    async def cancel_any(message: Message, state: FSMContext):
        await state.clear()
        await message.answer("Асосий меню:", reply_markup=main_menu_keyboard())

    return router
