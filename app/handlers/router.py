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
    InputMediaPhoto,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.config import WEBAPP_URL
from app.models import CartItem, User, WebSession
from app.services.api import APIService

SESSION_TTL_HOURS = 24 * 30  # 30 days

logger = logging.getLogger(__name__)

# Track product messages per chat to delete when switching groups
_product_msg_ids: dict[int, list[int]] = {}
# Track akt sverka messages per chat to delete when switching periods
_akt_msg_ids: dict[int, list[int]] = {}


def _main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Profil"), KeyboardButton(text="ℹ️ Info")],
            [KeyboardButton(text="📦 Mahsulotlar"), KeyboardButton(text="📋 Buyurtmalar")],
            [KeyboardButton(text="💰 Balans"), KeyboardButton(text="📊 Akt sverka")],
            [KeyboardButton(text="🛒 Savat"), KeyboardButton(text="✍️ Shikoyat")],
        ],
        resize_keyboard=True,
    )

PROFILE_FIELD_LABELS = {
    "name": "Ism",
    "group": "Guruh",
    "branch": "Filial",
    "address": "Manzil",
    "category": "Kategoriya",
    "phone": "Telefon",
    "agent": "Agent",
    "status": "Status",
    "visit_days": "Tashrif kunlari",
    "activity_types": "Faoliyat turlari",
}

IMAGE_FIELD_NAMES = ("images", "photos", "rasmlar", "photos_list")


class EditOrderState(StatesGroup):
    waiting_edit_qty = State()


class OrderState(StatesGroup):
    waiting_qty = State()

class CartState(StatesGroup):
    waiting_cart_qty = State()

class ComplaintState(StatesGroup):
    waiting_note = State()
    waiting_comment = State()


def _format_profile(profile: dict) -> str:
    lines = ["<b>👤 Mening profilim</b>\n"]
    shown_labels = set()

    for field, label in PROFILE_FIELD_LABELS.items():
        value = profile.get(field)
        if value is not None and value != "":
            lines.append(f"▪️ <b>{label}:</b> {value}")
            shown_labels.add(label)

    for field, value in profile.items():
        if field in PROFILE_FIELD_LABELS:
            continue
        if field in IMAGE_FIELD_NAMES:
            continue
        if field in ("client_id", "id"):
            continue
        if value is not None and value != "" and isinstance(value, (str, int, float)):
            label = field.replace("_", " ").title()
            if label not in shown_labels:
                lines.append(f"▪️ <b>{label}:</b> {value}")
                shown_labels.add(label)

    return "\n".join(lines)


def _extract_images(profile: dict) -> list[str]:
    for field in IMAGE_FIELD_NAMES:
        value = profile.get(field)
        if isinstance(value, list) and value:
            return [str(img) for img in value if img]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
    return []


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


def create_router(
    bot_config: dict,
    session_factory: async_sessionmaker[AsyncSession],
) -> Router:
    router = Router()
    api_service = APIService()

    bot_id = bot_config["id"]

    async def _cart_items(telegram_id: int) -> list[CartItem]:
        async with session_factory() as session:
            result = await session.execute(
                select(CartItem)
                .where(
                    CartItem.bot_id == bot_id,
                    CartItem.telegram_id == telegram_id,
                )
                .order_by(CartItem.created_at, CartItem.id)
            )
            return list(result.scalars().all())

    async def _cart_count(telegram_id: int) -> int:
        items = await _cart_items(telegram_id)
        return len(items)

    async def _cart_total(telegram_id: int) -> float:
        items = await _cart_items(telegram_id)
        return sum(float(it.price) * float(it.qty) for it in items)

    async def _cart_get_item(telegram_id: int, product_id: int) -> Optional[CartItem]:
        async with session_factory() as session:
            result = await session.execute(
                select(CartItem).where(
                    CartItem.bot_id == bot_id,
                    CartItem.telegram_id == telegram_id,
                    CartItem.product_id == product_id,
                )
            )
            return result.scalar_one_or_none()

    async def _cart_upsert(
        telegram_id: int,
        product_id: int,
        name: str,
        price: float,
        qty: float,
        mode: str,
    ) -> CartItem:
        async with session_factory() as session:
            result = await session.execute(
                select(CartItem).where(
                    CartItem.bot_id == bot_id,
                    CartItem.telegram_id == telegram_id,
                    CartItem.product_id == product_id,
                )
            )
            item = result.scalar_one_or_none()
            if item:
                if mode == "edit":
                    item.qty = qty
                else:
                    item.qty = float(item.qty) + qty
                item.price = price
                item.product_name = name
            else:
                item = CartItem(
                    bot_id=bot_id,
                    telegram_id=telegram_id,
                    product_id=product_id,
                    product_name=name,
                    price=price,
                    qty=qty,
                )
                session.add(item)
            await session.commit()
            await session.refresh(item)
            return item

    async def _cart_remove_item(telegram_id: int, product_id: int) -> Optional[CartItem]:
        async with session_factory() as session:
            result = await session.execute(
                select(CartItem).where(
                    CartItem.bot_id == bot_id,
                    CartItem.telegram_id == telegram_id,
                    CartItem.product_id == product_id,
                )
            )
            item = result.scalar_one_or_none()
            if not item:
                return None
            removed_snapshot = CartItem(
                bot_id=item.bot_id,
                telegram_id=item.telegram_id,
                product_id=item.product_id,
                product_name=item.product_name,
                price=item.price,
                qty=item.qty,
            )
            await session.delete(item)
            await session.commit()
            return removed_snapshot

    async def _cart_clear(telegram_id: int) -> int:
        async with session_factory() as session:
            result = await session.execute(
                delete(CartItem).where(
                    CartItem.bot_id == bot_id,
                    CartItem.telegram_id == telegram_id,
                )
            )
            await session.commit()
            return result.rowcount or 0

    @router.message(Command("start"))
    async def start_handler(message: Message, state: FSMContext):
        await state.clear()
        user = await _get_user(session_factory, message.from_user.id, bot_config["id"])

        if user and user.client_id:
            company = bot_config["company_name"]
            await message.answer(
                f"Assalomu alaykum! {company} botiga xush kelibsiz.\n\n"
                "Menyudan kerakli bo'limni tanlang:",
                reply_markup=_main_menu_keyboard(),
            )
            return

        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        company = bot_config["company_name"]
        await message.answer(
            f"Assalomu alaykum! {company} botiga xush kelibsiz.\n\n"
            "Iltimos, telefon raqamingizni yuboring.",
            reply_markup=keyboard,
        )

    @router.message(Command("getsession"))
    async def getsession_handler(message: Message):
        if not WEBAPP_URL:
            await message.answer(
                "⚠️ WEBAPP_URL sozlanmagan. Administrator bilan bog'laning."
            )
            return

        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)

        async with session_factory() as db:
            ws = WebSession(
                token=token,
                telegram_id=message.from_user.id,
                bot_id=bot_config["id"],
                first_name=message.from_user.first_name or "",
                last_name=message.from_user.last_name or "",
                username=message.from_user.username or "",
                expires_at=expires_at,
            )
            db.add(ws)
            await db.commit()

        url = f"{WEBAPP_URL.rstrip('/')}/webapp?bot_id={bot_config['id']}&session={token}"
        await message.answer(
            "🔗 <b>Brauzer uchun shaxsiy havola</b>\n\n"
            f"<a href=\"{url}\">{url}</a>\n\n"
            "Bu havolani hech kim bilan bo'lishmang. "
            f"Muddati: {SESSION_TTL_HOURS // 24} kun.",
            disable_web_page_preview=True,
        )

    @router.message(F.contact)
    async def contact_handler(message: Message):
        if message.contact is None:
            return

        phone = message.contact.phone_number.lstrip("+").replace(" ", "").replace("-", "")

        logger.info(
            "🤖 Bot[%s] contact: telegram_id=%s phone=%s",
            bot_config["id"], message.from_user.id, phone,
        )

        result = await api_service.register_device(
            bot_config["base_url"],
            bot_config["one_c_login"],
            bot_config["one_c_password"],
            phone,
        )

        logger.info(
            "🤖 Bot[%s] register_device result: %s",
            bot_config["id"],
            f"id={result.get('id')}" if result else "None",
        )

        if result and result.get("id"):
            client_id = str(result["id"])

            await _save_user(
                session_factory,
                message.from_user.id,
                bot_config["id"],
                phone,
                client_id,
            )

            await message.answer(
                "✅ Ro'yxatdan muvaffaqiyatli o'tdingiz!",
                reply_markup=_main_menu_keyboard(),
            )
        else:
            await message.answer(
                "❌ Siz topilmadingiz. Iltimos, qaytadan urinib ko'ring "
                "yoki administrator bilan bog'laning."
            )

    @router.message(F.text == "👤 Profil")
    async def profile_handler(message: Message):
        user = await _get_user(session_factory, message.from_user.id, bot_config["id"])

        if not user or not user.client_id:
            await message.answer(
                "❌ Avval ro'yxatdan o'tishingiz kerak. Iltimos, /start buyrug'ini bosing."
            )
            return

        profile = await api_service.get_client_info(
            bot_config["base_url"],
            bot_config["one_c_login"],
            bot_config["one_c_password"],
            user.client_id,
        )

        if profile is None:
            await message.answer(
                "❌ Ma'lumotlarni olishda xatolik yuz berdi. Keyinroq urinib ko'ring."
            )
            return

        if not profile:
            await message.answer("❌ Profil ma'lumotlari topilmadi.")
            return

        text = _format_profile(profile)
        await message.answer(text)

        images = _extract_images(profile)
        if images:
            try:
                media = [InputMediaPhoto(media=url) for url in images[:10]]
                if media:
                    await message.answer_media_group(media)
            except Exception as e:
                logger.error("Failed to send media group for bot %d: %s", bot_config["id"], e)

    @router.message(F.text == "📦 Mahsulotlar")
    async def products_handler(message: Message):
        user = await _get_user(session_factory, message.from_user.id, bot_config["id"])
        if not user or not user.client_id:
            await message.answer(
                "❌ Avval ro'yxatdan o'tishingiz kerak. Iltimos, /start buyrug'ini bosing."
            )
            return

        data = await api_service.get_products(
            bot_config["base_url"],
            bot_config["one_c_login"],
            bot_config["one_c_password"],
        )

        if not data or not data.get("data"):
            await message.answer("❌ Mahsulotlar topilmadi.")
            return

        groups = data["data"]
        buttons = []
        for g in groups:
            count = len(g.get("products", []))
            label = f"{g['group_name']} ({count} ta)"
            buttons.append([InlineKeyboardButton(
                text=label,
                callback_data=f"grp_{g['group_id']}",
            )])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer(
            f"<b>📦 Mahsulot guruhlari</b>\nJami: {len(groups)} ta guruh",
            reply_markup=keyboard,
        )

    async def _clear_product_messages(chat_id: int, bot):
        msg_ids = _product_msg_ids.pop(chat_id, [])
        for msg_id in msg_ids:
            try:
                await bot.delete_message(chat_id, msg_id)
            except Exception:
                pass

    async def _send_product_batch(chat_id: int, bot, group: dict):
        products = group.get("products", [])
        group_id = group.get("group_id")
        new_ids = []

        for product in products:
            product_id = product.get("id")
            name = product.get("name", "Nomsiz")

            price_val = 0.0
            price_str = ""
            prices = product.get("typePrice", [])
            if prices:
                p = prices[0]
                price_val = float(p["price"])
                price_str = f"{price_val:,.0f} {p['cry']}".replace(",", " ")

            qty_str = ""
            sklads = product.get("sklad", [])
            if sklads:
                s = sklads[0]
                qty_str = f"Qoldiq: {s['qty']} ta"

            status = product.get("status", "")
            status_icon = {"green": "🟢", "red": "🔴", "yellow": "🟡"}.get(status, "")

            caption = f"{status_icon} <b>{name}</b>\n💰 {price_str}\n📦 {qty_str}"

            order_btn = InlineKeyboardButton(
                text="🛒 Buyurtma berish",
                callback_data=f"order_{product_id}_{price_val}",
            )
            cart_btn = InlineKeyboardButton(
                text="➕ Savatga qo'shish",
                callback_data=f"cadd_{group_id}_{product_id}_{price_val}",
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[order_btn], [cart_btn]])

            images = product.get("img", [])
            if images:
                url = images[0].get("URL", "")
                if url:
                    try:
                        sent = await bot.send_photo(
                            chat_id=chat_id,
                            photo=url,
                            caption=caption,
                            reply_markup=keyboard,
                        )
                        new_ids.append(sent.message_id)
                        continue
                    except Exception:
                        pass

            sent = await bot.send_message(
                chat_id=chat_id, text=caption, reply_markup=keyboard,
            )
            new_ids.append(sent.message_id)

        _product_msg_ids[chat_id] = new_ids

    @router.callback_query(F.data.startswith("grp_"))
    async def products_group_callback(callback: CallbackQuery):
        group_id = int(callback.data.split("_", 1)[1])

        data = await api_service.get_products(
            bot_config["base_url"],
            bot_config["one_c_login"],
            bot_config["one_c_password"],
        )

        if not data or not data.get("data"):
            await callback.answer("❌ Mahsulotlar topilmadi.", show_alert=True)
            return

        group = next((g for g in data["data"] if g["group_id"] == group_id), None)
        if not group:
            await callback.answer("❌ Guruh topilmadi.", show_alert=True)
            return

        await callback.answer()

        # Clear old product messages
        await _clear_product_messages(callback.message.chat.id, callback.bot)

        # Update navigation: show all groups with current highlighted
        groups = data["data"]
        buttons = []
        for g in groups:
            prefix = "✅ " if g["group_id"] == group_id else ""
            count = len(g.get("products", []))
            label = f"{prefix}{g['group_name']} ({count} ta)"
            buttons.append([InlineKeyboardButton(
                text=label,
                callback_data=f"grp_{g['group_id']}",
            )])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        group_name = group.get("group_name", "Guruh")
        await callback.message.edit_text(
            f"<b>📦 {group_name}</b>\nJami: {len(groups)} ta guruh",
            reply_markup=keyboard,
        )

        # Send product messages with images
        await _send_product_batch(callback.message.chat.id, callback.bot, group)

    @router.callback_query(F.data.startswith("order_"))
    async def order_callback(callback: CallbackQuery, state: FSMContext):
        user = await _get_user(session_factory, callback.from_user.id, bot_config["id"])
        if not user or not user.client_id:
            await callback.answer("❌ Avval ro'yxatdan o'ting. /start", show_alert=True)
            return

        try:
            _, product_id, price = callback.data.split("_", 2)
            product_id = int(product_id)
            price = float(price)
        except (ValueError, IndexError):
            await callback.answer("❌ Xatolik yuz berdi.", show_alert=True)
            return

        import re
        caption = callback.message.html_text or ""
        match = re.search(r"<b>(.+?)</b>", caption)
        product_name = match.group(1) if match else "Mahsulot"

        await state.update_data(product_id=product_id, price=price, product_name=product_name)
        await state.set_state(OrderState.waiting_qty)

        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await callback.answer()
        await callback.message.answer(
            f"📦 <b>Miqdor kiriting</b>\n\n"
            f"Mahsulot: <b>{product_name}</b>\n"
            f"Narx: {price:,.0f} UZS\n\n"
            "Nechta kerakligini raqamda yuboring.".replace(",", " "),
            reply_markup=keyboard,
        )

    @router.message(OrderState.waiting_qty, F.text == "❌ Bekor qilish")
    async def cancel_order_qty(message: Message, state: FSMContext):
        await state.clear()
        await message.answer("❌ Buyurtma bekor qilindi.", reply_markup=_main_menu_keyboard())

    @router.message(OrderState.waiting_qty)
    async def process_qty(message: Message, state: FSMContext):
        try:
            qty = float(message.text.strip().replace(",", "."))
            if qty <= 0:
                raise ValueError
        except ValueError:
            await message.answer("❌ Iltimos, musbat raqam yuboring. Masalan: 3")
            return

        data = await state.get_data()
        product_id = data["product_id"]
        price = data["price"]
        product_name = data.get("product_name", "Mahsulot")
        await state.clear()

        user = await _get_user(session_factory, message.from_user.id, bot_config["id"])

        result = await api_service.create_order(
            bot_config["base_url"],
            bot_config["one_c_login"],
            bot_config["one_c_password"],
            client_id=int(user.client_id),
            product_id=product_id,
            price=price,
            qty=qty,
        )

        if result and not result.get("error"):
            order_id = result.get("id", "?")
            total = price * qty
            await message.answer(
                f"✅ <b>Buyurtma qabul qilindi!</b>\n"
                f"▪️ Mahsulot: {product_name}\n"
                f"▪️ Buyurtma ID: {order_id}\n"
                f"▪️ Miqdor: {qty:g} ta\n"
                f"▪️ Jami: {total:,.0f} UZS".replace(",", " "),
                reply_markup=_main_menu_keyboard(),
            )
        else:
            error = (result or {}).get("error") or (result or {}).get("message", "Noma'lum xatolik")
            await message.answer(f"❌ Buyurtma yuborilmadi: {error}")

    async def _format_cart_text(telegram_id: int) -> str:
        items = await _cart_items(telegram_id)
        if not items:
            return "🛒 <b>Savat bo'sh</b>\n\nMahsulotlar bo'limidan tovar qo'shing."
        lines = ["🛒 <b>Savat</b>\n"]
        total = 0.0
        for idx, it in enumerate(items, 1):
            price = float(it.price)
            qty = float(it.qty)
            item_sum = price * qty
            total += item_sum
            lines.append(
                f"<b>{idx}.</b> {it.product_name}\n"
                f"   {qty:g} ta × {price:,.0f} = "
                f"{item_sum:,.0f} UZS".replace(",", " ")
            )
        lines.append("")
        lines.append(f"━━━━━━━━━━━━━━")
        lines.append(f"<b>Jami: {total:,.0f} UZS</b>".replace(",", " "))
        return "\n".join(lines)

    async def _build_cart_keyboard(telegram_id: int) -> Optional[InlineKeyboardMarkup]:
        items = await _cart_items(telegram_id)
        if not items:
            return None
        rows = []
        for it in items:
            name_short = it.product_name
            if len(name_short) > 22:
                name_short = name_short[:21] + "…"
            qty = float(it.qty)
            rows.append([
                InlineKeyboardButton(
                    text=f"✏️ {name_short} ({qty:g} ta)",
                    callback_data=f"cqty_{it.product_id}",
                ),
                InlineKeyboardButton(
                    text="🗑",
                    callback_data=f"crm_{it.product_id}",
                ),
            ])
        rows.append([
            InlineKeyboardButton(text="🧹 Tozalash", callback_data="cclear"),
            InlineKeyboardButton(text="✅ Buyurtma berish", callback_data="csubmit"),
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @router.callback_query(F.data.startswith("cadd_"))
    async def cart_add_callback(callback: CallbackQuery, state: FSMContext):
        user = await _get_user(session_factory, callback.from_user.id, bot_config["id"])
        if not user or not user.client_id:
            await callback.answer("❌ Avval ro'yxatdan o'ting. /start", show_alert=True)
            return

        try:
            parts = callback.data.split("_")
            if len(parts) == 4:
                _, group_id_s, product_id_s, price_s = parts
                group_id = int(group_id_s)
            elif len(parts) == 3:
                _, product_id_s, price_s = parts
                group_id = None
            else:
                raise ValueError("Bad callback format")
            product_id = int(product_id_s)
            price = float(price_s)
        except (ValueError, IndexError):
            await callback.answer("❌ Xatolik yuz berdi.", show_alert=True)
            return

        import re
        caption = callback.message.html_text or ""
        match = re.search(r"<b>(.+?)</b>", caption)
        product_name = match.group(1) if match else "Mahsulot"

        existing_item = await _cart_get_item(callback.from_user.id, product_id)
        existing_qty = float(existing_item.qty) if existing_item else 0.0

        await state.update_data(
            cart_pid=product_id,
            cart_price=price,
            cart_name=product_name,
            cart_mode="add",
            cart_group_id=group_id,
        )
        await state.set_state(CartState.waiting_cart_qty)

        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await callback.answer()
        extra = ""
        if existing_qty:
            extra = f"\n<i>Savatda hozir: {existing_qty:g} ta (yangi miqdor ustiga qo'shiladi)</i>"
        await callback.message.answer(
            f"➕ <b>Savatga qo'shish</b>\n\n"
            f"Mahsulot: <b>{product_name}</b>\n"
            f"Narx: {price:,.0f} UZS{extra}\n\n"
            "Nechta qo'shishni raqamda yuboring.".replace(",", " "),
            reply_markup=keyboard,
        )

    @router.callback_query(F.data.startswith("cqty_"))
    async def cart_qty_edit_callback(callback: CallbackQuery, state: FSMContext):
        try:
            pid = int(callback.data.split("_", 1)[1])
        except (ValueError, IndexError):
            await callback.answer("❌ Xatolik yuz berdi.", show_alert=True)
            return

        item = await _cart_get_item(callback.from_user.id, pid)
        if not item:
            await callback.answer("❌ Mahsulot savatda topilmadi.", show_alert=True)
            return

        await state.update_data(
            cart_pid=pid,
            cart_price=float(item.price),
            cart_name=item.product_name,
            cart_mode="edit",
        )
        await state.set_state(CartState.waiting_cart_qty)

        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await callback.answer()
        await callback.message.answer(
            f"✏️ <b>Miqdorni o'zgartirish</b>\n\n"
            f"Mahsulot: <b>{item.product_name}</b>\n"
            f"Joriy miqdor: {float(item.qty):g} ta\n\n"
            "Yangi miqdorni raqamda yuboring.",
            reply_markup=keyboard,
        )

    @router.message(CartState.waiting_cart_qty, F.text == "❌ Bekor qilish")
    async def cancel_cart_qty(message: Message, state: FSMContext):
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=_main_menu_keyboard())

    @router.message(CartState.waiting_cart_qty)
    async def process_cart_qty(message: Message, state: FSMContext):
        try:
            qty = float(message.text.strip().replace(",", "."))
            if qty <= 0:
                raise ValueError
        except ValueError:
            await message.answer("❌ Iltimos, musbat raqam yuboring. Masalan: 3")
            return

        data = await state.get_data()
        pid = data["cart_pid"]
        price = data["cart_price"]
        name = data.get("cart_name", "Mahsulot")
        mode = data.get("cart_mode", "add")
        await state.clear()

        saved = await _cart_upsert(
            telegram_id=message.from_user.id,
            product_id=pid,
            name=name,
            price=price,
            qty=qty,
            mode=mode,
        )
        action_text = "✏️ Miqdor yangilandi" if mode == "edit" else "✅ Savatga qo'shildi"

        total_count = await _cart_count(message.from_user.id)
        cart_total = await _cart_total(message.from_user.id)
        new_qty = float(saved.qty)

        await message.answer(
            f"{action_text}\n\n"
            f"▪️ {name}\n"
            f"▪️ Miqdor: {new_qty:g} ta\n"
            f"▪️ Narx: {price:,.0f} UZS\n\n"
            f"<b>Savatda: {total_count} ta tovar | "
            f"{cart_total:,.0f} UZS</b>\n\n".replace(",", " ")
            + "Buyurtma berish uchun «🛒 Savat» menyusiga o'ting.",
            reply_markup=_main_menu_keyboard(),
        )

        group_id = data.get("cart_group_id")
        if mode == "add" and group_id is not None:
            try:
                products_data = await api_service.get_products(
                    bot_config["base_url"],
                    bot_config["one_c_login"],
                    bot_config["one_c_password"],
                )
                if products_data and products_data.get("data"):
                    group = next(
                        (g for g in products_data["data"] if g.get("group_id") == group_id),
                        None,
                    )
                    if group:
                        await _clear_product_messages(message.chat.id, message.bot)
                        await _send_product_batch(message.chat.id, message.bot, group)
            except Exception as e:
                logger.error(
                    "Failed to re-send products after cart add (bot=%d, group=%s): %s",
                    bot_config["id"], group_id, e,
                )

    @router.message(F.text == "🛒 Savat")
    async def cart_handler(message: Message):
        user = await _get_user(session_factory, message.from_user.id, bot_config["id"])
        if not user or not user.client_id:
            await message.answer(
                "❌ Avval ro'yxatdan o'tishingiz kerak. Iltimos, /start buyrug'ini bosing."
            )
            return

        text = await _format_cart_text(message.from_user.id)
        kb = await _build_cart_keyboard(message.from_user.id)
        await message.answer(text, reply_markup=kb)

    @router.callback_query(F.data.startswith("crm_"))
    async def cart_remove_callback(callback: CallbackQuery):
        try:
            pid = int(callback.data.split("_", 1)[1])
        except (ValueError, IndexError):
            await callback.answer("❌ Xatolik yuz berdi.", show_alert=True)
            return

        removed = await _cart_remove_item(callback.from_user.id, pid)
        if not removed:
            await callback.answer("❌ Mahsulot savatda topilmadi.", show_alert=True)
            return

        await callback.answer(f"🗑 {removed.product_name} olib tashlandi")
        text = await _format_cart_text(callback.from_user.id)
        kb = await _build_cart_keyboard(callback.from_user.id)
        try:
            await callback.message.edit_text(text, reply_markup=kb)
        except Exception:
            await callback.message.answer(text, reply_markup=kb)

    @router.callback_query(F.data == "cclear")
    async def cart_clear_callback(callback: CallbackQuery):
        removed_count = await _cart_clear(callback.from_user.id)
        if removed_count == 0:
            await callback.answer("Savat allaqachon bo'sh", show_alert=True)
            return
        await callback.answer("🧹 Savat tozalandi")
        try:
            await callback.message.edit_text(
                "🛒 <b>Savat bo'sh</b>\n\nMahsulotlar bo'limidan tovar qo'shing.",
            )
        except Exception:
            await callback.message.answer(
                "🛒 <b>Savat bo'sh</b>\n\nMahsulotlar bo'limidan tovar qo'shing.",
            )

    @router.callback_query(F.data == "csubmit")
    async def cart_submit_callback(callback: CallbackQuery):
        user = await _get_user(session_factory, callback.from_user.id, bot_config["id"])
        if not user or not user.client_id:
            await callback.answer("❌ Avval ro'yxatdan o'ting. /start", show_alert=True)
            return

        items = await _cart_items(callback.from_user.id)
        if not items:
            await callback.answer("Savat bo'sh", show_alert=True)
            return

        await callback.answer("⏳ Buyurtma yuborilmoqda...")

        snapshot = [
            {
                "product_id": it.product_id,
                "name": it.product_name,
                "price": float(it.price),
                "qty": float(it.qty),
            }
            for it in items
        ]

        result = await api_service.create_bulk_order(
            bot_config["base_url"],
            bot_config["one_c_login"],
            bot_config["one_c_password"],
            client_id=int(user.client_id),
            products=snapshot,
        )

        if result and not result.get("error"):
            order_id = result.get("id", "?")
            total = sum(it["price"] * it["qty"] for it in snapshot)
            items_summary_lines = []
            for it in snapshot:
                items_summary_lines.append(
                    f"  ▪️ {it['name']} — {it['qty']:g} ta × "
                    f"{it['price']:,.0f} = {it['price']*it['qty']:,.0f} UZS".replace(",", " ")
                )
            await _cart_clear(callback.from_user.id)
            success_text = (
                f"✅ <b>Buyurtma qabul qilindi!</b>\n"
                f"▪️ Buyurtma ID: {order_id}\n"
                f"▪️ Mahsulotlar: {len(snapshot)} xil\n"
                + "\n".join(items_summary_lines) + "\n\n"
                f"<b>Jami: {total:,.0f} UZS</b>".replace(",", " ")
            )
            try:
                await callback.message.edit_text(success_text)
            except Exception:
                await callback.message.answer(success_text)
        else:
            error = (result or {}).get("error") or (result or {}).get("message", "Noma'lum xatolik")
            await callback.message.answer(f"❌ Buyurtma yuborilmadi: {error}")

    @router.message(F.text == "📋 Buyurtmalar")
    async def orders_handler(message: Message):
        user = await _get_user(session_factory, message.from_user.id, bot_config["id"])
        if not user or not user.client_id:
            await message.answer(
                "❌ Avval ro'yxatdan o'tishingiz kerak. Iltimos, /start buyrug'ini bosing."
            )
            return

        data = await api_service.get_orders(
            bot_config["base_url"],
            bot_config["one_c_login"],
            bot_config["one_c_password"],
            user.client_id,
        )

        if not data or not data.get("data"):
            await message.answer("📋 Sizda hozircha buyurtmalar mavjud emas.")
            return

        orders = data["data"]
        for order in orders:
            order_id = order.get("id", "?")
            name = order.get("name", "")
            total_qty = order.get("qty", 0)
            total_sum = order.get("summa", 0)
            goods = order.get("list_goods", [])

            lines = [
                f"<b>📋 Buyurtma #{order_id}</b>",
                f"👤 {name}",
                f"📦 Jami: {total_qty} ta | 💰 {total_sum:,} UZS".replace(",", " "),
                "",
                "<b>Mahsulotlar:</b>",
            ]

            for item in goods:
                item_name = item.get("name", "-")
                item_qty = item.get("qty", 0)
                item_sum = item.get("summa", 0)
                lines.append(f"  ▪️ {item_name} — {item_qty} ta ({item_sum:,} UZS)".replace(",", " "))

            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="✏️ Tahrirlash",
                    callback_data=f"edit_{order_id}",
                ),
                InlineKeyboardButton(
                    text="🗑 O'chirish",
                    callback_data=f"del_{order_id}",
                ),
            ]])

            await message.answer("\n".join(lines), reply_markup=keyboard)

    async def _fetch_order(client_id: str, order_id: int) -> Optional[dict]:
        data = await api_service.get_orders(
            bot_config["base_url"],
            bot_config["one_c_login"],
            bot_config["one_c_password"],
            client_id,
        )
        if not data:
            return None
        for o in data.get("data", []):
            try:
                if int(o.get("id")) == int(order_id):
                    return o
            except (TypeError, ValueError):
                continue
        return None

    def _item_unit_price(item: dict) -> float:
        qty = item.get("qty", 0) or 0
        summa = item.get("summa", 0) or 0
        try:
            qty_f = float(qty)
        except (TypeError, ValueError):
            qty_f = 0.0
        try:
            summa_f = float(summa)
        except (TypeError, ValueError):
            summa_f = 0.0
        if qty_f <= 0:
            return 0.0
        return summa_f / qty_f

    async def _ask_edit_qty(
        message_or_callback,
        state: FSMContext,
        order_id: int,
        item: dict,
    ):
        pid = int(item.get("id"))
        name = item.get("name", "Mahsulot")
        cur_qty = item.get("qty", 0)
        unit_price = _item_unit_price(item)

        await state.update_data(
            edit_order_id=order_id,
            edit_product_id=pid,
            edit_price=unit_price,
            edit_product_name=name,
            edit_current_qty=cur_qty,
        )
        await state.set_state(EditOrderState.waiting_edit_qty)

        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        text = (
            f"✏️ <b>Yangi miqdor kiriting</b>\n\n"
            f"Buyurtma: #{order_id}\n"
            f"Mahsulot: <b>{name}</b>\n"
            f"Joriy miqdor: {cur_qty} ta\n\n"
            "Yangi miqdorni raqamda yuboring."
        )
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.answer(text, reply_markup=keyboard)
        else:
            await message_or_callback.answer(text, reply_markup=keyboard)

    @router.callback_query(F.data.startswith("edit_"))
    async def edit_order_callback(callback: CallbackQuery, state: FSMContext):
        try:
            parts = callback.data.split("_")
            order_id = int(parts[1])
        except (ValueError, IndexError):
            await callback.answer("❌ Xatolik yuz berdi.", show_alert=True)
            return

        user = await _get_user(session_factory, callback.from_user.id, bot_config["id"])
        if not user or not user.client_id:
            await callback.answer("❌ Avval ro'yxatdan o'ting. /start", show_alert=True)
            return

        order = await _fetch_order(user.client_id, order_id)
        if not order:
            await callback.answer("❌ Buyurtma topilmadi.", show_alert=True)
            return

        goods = order.get("list_goods", []) or []
        if not goods:
            await callback.answer("❌ Buyurtmada mahsulotlar yo'q.", show_alert=True)
            return

        await callback.answer()

        if len(goods) == 1:
            await _ask_edit_qty(callback, state, order_id, goods[0])
            return

        buttons = []
        for item in goods:
            pid = item.get("id")
            name = item.get("name", "-")
            qty = item.get("qty", 0)
            short = name if len(name) <= 25 else name[:24] + "…"
            buttons.append([InlineKeyboardButton(
                text=f"✏️ {short} ({qty} ta)",
                callback_data=f"epick_{order_id}_{pid}",
            )])

        await callback.message.answer(
            f"✏️ <b>Buyurtma #{order_id} — tahrirlash</b>\n\n"
            "Qaysi mahsulotni tahrirlamoqchisiz?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )

    @router.callback_query(F.data.startswith("epick_"))
    async def edit_pick_product_callback(callback: CallbackQuery, state: FSMContext):
        try:
            _, order_id, product_id = callback.data.split("_", 2)
            order_id = int(order_id)
            product_id = int(product_id)
        except (ValueError, IndexError):
            await callback.answer("❌ Xatolik yuz berdi.", show_alert=True)
            return

        user = await _get_user(session_factory, callback.from_user.id, bot_config["id"])
        if not user or not user.client_id:
            await callback.answer("❌ Avval ro'yxatdan o'ting. /start", show_alert=True)
            return

        order = await _fetch_order(user.client_id, order_id)
        if not order:
            await callback.answer("❌ Buyurtma topilmadi.", show_alert=True)
            return

        target = None
        for item in order.get("list_goods", []) or []:
            try:
                if int(item.get("id")) == product_id:
                    target = item
                    break
            except (TypeError, ValueError):
                continue

        if not target:
            await callback.answer("❌ Mahsulot topilmadi.", show_alert=True)
            return

        await callback.answer()
        await _ask_edit_qty(callback, state, order_id, target)

    @router.message(EditOrderState.waiting_edit_qty, F.text == "❌ Bekor qilish")
    async def cancel_edit_qty(message: Message, state: FSMContext):
        await state.clear()
        await message.answer("❌ Tahrirlash bekor qilindi.", reply_markup=_main_menu_keyboard())

    @router.message(EditOrderState.waiting_edit_qty)
    async def process_edit_qty(message: Message, state: FSMContext):
        try:
            qty = float(message.text.strip().replace(",", "."))
            if qty <= 0:
                raise ValueError
        except ValueError:
            await message.answer("❌ Iltimos, musbat raqam yuboring. Masalan: 3")
            return

        data = await state.get_data()
        order_id = data["edit_order_id"]
        edit_product_id = data["edit_product_id"]
        edit_price = data["edit_price"]
        edit_name = data.get("edit_product_name", "Mahsulot")
        await state.clear()

        user = await _get_user(session_factory, message.from_user.id, bot_config["id"])
        if not user or not user.client_id:
            await message.answer(
                "❌ Avval ro'yxatdan o'ting. /start",
                reply_markup=_main_menu_keyboard(),
            )
            return

        order = await _fetch_order(user.client_id, order_id)
        if not order:
            await message.answer(
                "❌ Buyurtma topilmadi. Qaytadan urinib ko'ring.",
                reply_markup=_main_menu_keyboard(),
            )
            return

        products = []
        replaced = False
        for item in order.get("list_goods", []) or []:
            try:
                pid = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            if pid == edit_product_id:
                use_qty = qty
                use_price = edit_price if edit_price > 0 else _item_unit_price(item)
                replaced = True
            else:
                try:
                    use_qty = float(item.get("qty", 0))
                except (TypeError, ValueError):
                    use_qty = 0.0
                use_price = _item_unit_price(item)
            products.append({
                "product_id": pid,
                "price": use_price,
                "qty": use_qty,
                "sum": use_price * use_qty,
            })

        if not replaced:
            products.append({
                "product_id": edit_product_id,
                "price": edit_price,
                "qty": qty,
                "sum": edit_price * qty,
            })

        result = await api_service.edit_order(
            bot_config["base_url"],
            bot_config["one_c_login"],
            bot_config["one_c_password"],
            order_id=order_id,
            products=products,
        )

        if result and not result.get("error"):
            total = sum(p["sum"] for p in products)
            await message.answer(
                f"✅ <b>Buyurtma yangilandi!</b>\n"
                f"▪️ Buyurtma ID: {order_id}\n"
                f"▪️ O'zgartirilgan: {edit_name} — {qty:g} ta\n"
                f"▪️ Mahsulotlar: {len(products)} xil\n"
                f"▪️ Jami: {total:,.0f} UZS".replace(",", " "),
                reply_markup=_main_menu_keyboard(),
            )
        else:
            error = (result or {}).get("error") or (result or {}).get("message", "Noma'lum xatolik")
            await message.answer(
                f"❌ Yangilash amalga oshmadi: {error}",
                reply_markup=_main_menu_keyboard(),
            )

    @router.callback_query(F.data.startswith("del_"))
    async def delete_order_callback(callback: CallbackQuery):
        try:
            order_id = int(callback.data.split("_", 1)[1])
        except (ValueError, IndexError):
            await callback.answer("❌ Xatolik yuz berdi.", show_alert=True)
            return

        await callback.answer("⏳ O'chirilmoqda...")

        result = await api_service.delete_order(
            bot_config["base_url"],
            bot_config["one_c_login"],
            bot_config["one_c_password"],
            order_id,
        )

        if result and not result.get("error"):
            await callback.message.edit_text(
                callback.message.html_text + "\n\n<b>✅ O'chirildi</b>"
            )
        else:
            error = (result or {}).get("error") or (result or {}).get("message", "Noma'lum xatolik")
            await callback.answer(f"❌ {error}", show_alert=True)

    @router.message(F.text == "ℹ️ Info")
    async def info_handler(message: Message):
        user = await _get_user(session_factory, message.from_user.id, bot_config["id"])
        if not user or not user.client_id:
            await message.answer(
                "❌ Avval ro'yxatdan o'tishingiz kerak. Iltimos, /start buyrug'ini bosing."
            )
            return

        company = bot_config["company_name"]

        lines = [
            f"<b>ℹ️ {company} — Bot haqida</b>",
            "",
            f"Ushbu bot {company} kompaniyasining mijozlar uchun mo'ljallangan rasmiy boti bo'lib, uning yordamida siz mahsulotlarni ko'rishingiz, buyurtma berishingiz hamda barcha hisob-kitoblaringizni nazorat qilishingiz mumkin.",
            "",
            "<b>📋 Quyidagi tugmalar mavjud:</b>",
            "",
            "━━━ <b>👤 Profil</b> ━━━",
            "Shaxsiy ma'lumotlaringizni ko'rish: ism, guruh, filial, kategorya, telefon raqam, agent, status va boshqa ma'lumotlar.",
            "",
            "━━━ <b>📦 Mahsulotlar</b> ━━━",
            "Barcha mahsulotlar guruhlarga ajratilgan holda ko'rsatiladi. Guruhni tanlab, ichidagi mahsulotlarni narxlari bilan ko'rishingiz va buyurtma berishingiz mumkin. Mahsulot qoldiqlari ham ko'rsatiladi.",
            "",
            "━━━ <b>📋 Buyurtmalar</b> ━━━",
            "Buyurtmalaringiz ro'yxati va ularning holati. Buyurtma ID, mahsulot nomi, miqdori, summasi ko'rsatiladi. Xar bir buyurtmani tahrirlash yoki o'chirish imkoniyati mavjud.",
            "",
            "━━━ <b>💰 Balans</b> ━━━",
            "Joriy moliyaviy holatingizni tekshirish. Manfiy balans (masalan, -50 000 UZS) — siz haqdorsiz (kompaniya sizdan qarzdor), musbat balans — qarzdorlik mavjud.",
            "",
            "━━━ <b>📊 Akt sverka</b> ━━━",
            "Hisob-kitoblar bo'yicha batafsil ko'chirma. 1, 2 yoki 3 oylik muddatni tanlab, barcha buyurtma va to'lovlar ro'yxatini, balans o'zgarishlarini va umumiy qarzdorlikni ko'rishingiz mumkin.",
            "",
            "━━━ <b>✍️ Shikoyat</b> ━━━",
            "Fikr, shikoyat yoki takliflaringizni qoldiring. Matn va qo'shimcha izoh kiritishingiz mumkin. Xabaringiz tez orada ko'rib chiqiladi.",
            "",
            "<b>🌐 Web-sahifa</b>",
            f"Barcha funksiyalar bilan qulay interfeys orqali tanishish uchun {company} botidagi <code>/start</code> tugmasini bosing va <b>\"Web-sahifani ochish\"</b> havolasidan foydalaning. Telefon va kompyuterda ishlaydi.",
        ]

        profile = await api_service.get_client_info(
            bot_config["base_url"],
            bot_config["one_c_login"],
            bot_config["one_c_password"],
            user.client_id,
        )

        if profile:
            info_lines = []
            branch = profile.get("filial_name") or profile.get("branch", "")
            group_name = profile.get("group_name") or profile.get("group", "")
            agent_data = profile.get("agent", {})
            agent_name = agent_data.get("agent_name", "") if isinstance(agent_data, dict) else ""
            status_name = profile.get("status_name") or profile.get("status", "")

            if branch:
                info_lines.append(f"▪️ <b>Filial:</b> {branch}")
            if group_name:
                info_lines.append(f"▪️ <b>Guruh:</b> {group_name}")
            if agent_name:
                info_lines.append(f"▪️ <b>Agent:</b> {agent_name}")
            if status_name:
                info_lines.append(f"▪️ <b>Status:</b> {status_name}")
            if info_lines:
                lines.append("")
                lines.append("<b>👤 Sizning ma'lumotlaringiz:</b>")
                lines.extend(info_lines)

        await message.answer("\n".join(lines))

    @router.message(F.text == "💰 Balans")
    async def balance_handler(message: Message):
        user = await _get_user(session_factory, message.from_user.id, bot_config["id"])
        if not user or not user.client_id:
            await message.answer(
                "❌ Avval ro'yxatdan o'tishingiz kerak. Iltimos, /start buyrug'ini bosing."
            )
            return

        data = await api_service.get_balance(
            bot_config["base_url"],
            bot_config["one_c_login"],
            bot_config["one_c_password"],
            user.client_id,
        )

        if not data or not data.get("balance"):
            await message.answer("❌ Balansni olishda xatolik yuz berdi.")
            return

        balance = data["balance"].strip()
        is_negative = balance.startswith("-")
        emoji = "🟢" if is_negative else "🔴"
        await message.answer(
            f"<b>💰 Balans</b>\n\n"
            f"{emoji} Joriy balans: <b>{balance}</b>"
        )

    async def _submit_complaint(message: Message, note: str, comment: str):
        user = await _get_user(session_factory, message.from_user.id, bot_config["id"])
        if not user or not user.client_id:
            await message.answer("❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.")
            return
        result = await api_service.create_note(
            bot_config["base_url"],
            bot_config["one_c_login"],
            bot_config["one_c_password"],
            client_id=int(user.client_id),
            note=note,
            comment=comment,
        )
        if result and not result.get("error"):
            await message.answer(
                "✅ Xabaringiz yuborildi. Rahmat!",
                reply_markup=_main_menu_keyboard(),
            )
        else:
            error = (result or {}).get("message") or (result or {}).get("error", "Noma'lum xatolik")
            await message.answer(
                f"❌ Xatolik: {error}",
                reply_markup=_main_menu_keyboard(),
            )

    @router.message(F.text == "✍️ Shikoyat")
    async def complaint_start(message: Message, state: FSMContext):
        user = await _get_user(session_factory, message.from_user.id, bot_config["id"])
        if not user or not user.client_id:
            await message.answer(
                "❌ Avval ro'yxatdan o'tishingiz kerak. Iltimos, /start buyrug'ini bosing."
            )
            return
        await state.set_state(ComplaintState.waiting_note)
        await message.answer(
            "✍️ <b>Shikoyat / Taklif</b>\n\n"
            "Fikr, shikoyat yoki taklifingizni yozing:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
                resize_keyboard=True,
                one_time_keyboard=True,
            ),
        )

    @router.message(ComplaintState.waiting_note, F.text == "❌ Bekor qilish")
    async def cancel_complaint_note(message: Message, state: FSMContext):
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=_main_menu_keyboard())

    @router.message(ComplaintState.waiting_note)
    async def complaint_note_received(message: Message, state: FSMContext):
        note = message.text.strip()
        if not note:
            await message.answer("❌ Matn kiritilishi shart. Qaytadan yozing:")
            return
        await state.update_data(note=note)
        await state.set_state(ComplaintState.waiting_comment)
        await message.answer(
            "Qo'shimcha izohingiz bormi? (yo'q bo'lsa \"O'tkazib yuborish\" tugmasini bosing)",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="O'tkazib yuborish")]],
                resize_keyboard=True,
                one_time_keyboard=True,
            ),
        )

    @router.message(ComplaintState.waiting_comment, F.text == "O'tkazib yuborish")
    async def complaint_skip_comment(message: Message, state: FSMContext):
        data = await state.get_data()
        await _submit_complaint(message, data["note"], "")
        await state.clear()

    @router.message(ComplaintState.waiting_comment)
    async def complaint_comment_received(message: Message, state: FSMContext):
        data = await state.get_data()
        comment = message.text.strip()
        await _submit_complaint(message, data["note"], comment)
        await state.clear()

    @router.message(F.text == "📊 Akt sverka")
    async def akt_sverka_handler(message: Message):
        user = await _get_user(session_factory, message.from_user.id, bot_config["id"])
        if not user or not user.client_id:
            await message.answer(
                "❌ Avval ro'yxatdan o'tishingiz kerak. Iltimos, /start buyrug'ini bosing."
            )
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1 oylik", callback_data="akt_1")],
            [InlineKeyboardButton(text="2 oylik", callback_data="akt_2")],
            [InlineKeyboardButton(text="3 oylik", callback_data="akt_3")],
        ])
        await message.answer(
            "<b>📊 Akt sverka</b>\nDavrni tanlang:",
            reply_markup=keyboard,
        )

    @router.callback_query(F.data.startswith("akt_"))
    async def akt_sverka_callback(callback: CallbackQuery):
        user = await _get_user(session_factory, callback.from_user.id, bot_config["id"])
        if not user or not user.client_id:
            await callback.answer("❌ Avval ro'yxatdan o'ting.", show_alert=True)
            return

        months = int(callback.data.split("_")[1])
        await callback.answer()

        from datetime import datetime, timedelta
        end = datetime.now()
        start = end - timedelta(days=months * 30)
        date_begin = start.strftime("%Y%m%d")
        date_end = end.strftime("%Y%m%d")

        # Clear old report messages
        old_ids = _akt_msg_ids.pop(callback.message.chat.id, [])
        for msg_id in old_ids:
            try:
                await callback.bot.delete_message(callback.message.chat.id, msg_id)
            except Exception:
                pass

        # Update selector message
        await callback.message.edit_text(
            f"<b>📊 Akt sverka</b> — {months} oylik\nBoshqa davrni tanlang:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="1 oylik", callback_data="akt_1")],
                [InlineKeyboardButton(text="2 oylik", callback_data="akt_2")],
                [InlineKeyboardButton(text="3 oylik", callback_data="akt_3")],
            ]),
        )

        data = await api_service.get_akt_sverka(
            bot_config["base_url"],
            bot_config["one_c_login"],
            bot_config["one_c_password"],
            user.client_id,
            date_begin=date_begin,
            date_end=date_end,
        )

        new_ids = []

        if not data or not data.get("data"):
            sent = await callback.message.answer(
                f"📊 <b>{months} oylik</b> — operatsiyalar mavjud emas."
            )
            new_ids.append(sent.message_id)
        else:
            for doc in data["data"]:
                doc_id = doc.get("id_doc", "?")
                doc_date = doc.get("date_doc", "")
                doc_type = doc.get("type_doc", "")
                doc_debt = doc.get("debt", 0)
                doc_credit = doc.get("credit", 0)
                doc_balance = doc.get("balance", 0)
                details = doc.get("detals", [])

                if doc_debt > 0:
                    direction = "🛒 Buyurtma"
                elif doc_credit > 0:
                    direction = "💰 To'lov"
                else:
                    direction = doc_type

                lines = [
                    f"<b>📄 {direction}</b>",
                    f"▪️ Hujjat: #{doc_id} | {doc_date}",
                ]
                if doc_debt:
                    lines.append(f"▪️ Summa: {doc_debt:,} UZS".replace(",", " "))
                if doc_credit:
                    lines.append(f"▪️ Summa: {doc_credit:,} UZS".replace(",", " "))
                lines.append(f"▪️ Balans: {doc_balance:,} UZS".replace(",", " "))

                if details:
                    lines.append("")
                    for d in details:
                        d_name = d.get("osnova", "-")
                        d_qty = d.get("qty", "0")
                        d_debt = d.get("debt", 0)
                        d_credit = d.get("credit", 0)
                        lines.append(
                            f"  ▫️ {d_name} — {d_qty} ta "
                            f"(Summa: {d_debt or d_credit:,} UZS)".replace(",", " ")
                        )

                sent = await callback.message.answer("\n".join(lines))
                new_ids.append(sent.message_id)

        _akt_msg_ids[callback.message.chat.id] = new_ids

    return router
