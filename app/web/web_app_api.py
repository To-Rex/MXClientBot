"""WebApp JSON API — MX Nasiya personal cabinet (mirrors the Telegram bot).

Auth: Telegram initData (X-Telegram-Init-Data) or ?session=<token> from /getsession.
Data: ``NasiyaService`` (mock now, 1C later) — same service the bot uses.
"""
import logging
from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select

from app.database import async_session
from app.models import CartItem, User, WebSession
from app.services.api import APIService
from app.services.nasiya_api import NasiyaService
from app.web.web_app_auth import authenticate_webapp_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webapp/api")

api_service = APIService()
svc = NasiyaService()

# Payment providers (demo) — keep in sync with bot's PAY_METHODS
PAY_METHODS = {
    "payme": {"key": "payme", "label": "Payme", "url": "https://checkout.paycom.uz/", "color": "#00cccc"},
    "click": {"key": "click", "label": "Click", "url": "https://my.click.uz/", "color": "#0073ff"},
    "paynet": {"key": "paynet", "label": "Paynet", "url": "https://app.paynet.uz/", "color": "#00a651"},
}


# ── helpers ─────────────────────────────────────────────────────────────────
def _ser(obj: Any) -> Any:
    """Recursively convert date/datetime to strings for JSON."""
    if isinstance(obj, dict):
        return {k: _ser(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_ser(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.strftime("%d.%m.%Y %H:%M")
    if isinstance(obj, date):
        return obj.strftime("%d.%m.%Y")
    return obj


def _creds(auth: dict) -> tuple:
    cfg = auth["bot_config"]
    return (cfg["base_url"], cfg["one_c_login"], cfg["one_c_password"])


async def _get_user(telegram_id: int, bot_id: int) -> Optional[User]:
    async with async_session() as session:
        stmt = select(User).where(
            User.telegram_id == telegram_id,
            User.bot_id == bot_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def _save_user(telegram_id: int, bot_id: int, phone_number: str, client_id: str):
    async with async_session() as session:
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


async def _require_client(auth: dict) -> str:
    user = await _get_user(auth["telegram_id"], auth["bot_id"])
    if not user or not user.client_id:
        raise HTTPException(status_code=400, detail="Аввал рўйхатдан ўтинг")
    return user.client_id


# ── auth / session ──────────────────────────────────────────────────────────
@router.get("/user")
async def get_user(auth: dict = Depends(authenticate_webapp_user)):
    user = await _get_user(auth["telegram_id"], auth["bot_id"])
    return {
        "telegram_id": auth["telegram_id"],
        "first_name": auth["first_name"],
        "last_name": auth["last_name"],
        "username": auth["username"],
        "registered": bool(user and user.client_id),
        "phone_number": user.phone_number if user else None,
        "client_id": user.client_id if user else None,
        "company_name": auth["bot_config"]["company_name"],
        "mock": svc.is_mock(),
    }


class RegisterRequest(BaseModel):
    phone_number: str


@router.post("/register")
async def register_device(req: RegisterRequest, auth: dict = Depends(authenticate_webapp_user)):
    phone = req.phone_number.lstrip("+").replace(" ", "").replace("-", "")

    cfg = auth["bot_config"]
    result = await api_service.register_device(
        cfg["base_url"], cfg["one_c_login"], cfg["one_c_password"], phone, str(auth["telegram_id"]),
    )

    if not result or not result.get("id"):
        raise HTTPException(status_code=400, detail="Сиз топилмадингиз. Рақамни текшириб қайта уриниб кўринг.")

    client_id = str(result["id"])
    await _save_user(auth["telegram_id"], auth["bot_id"], phone, client_id)
    await svc.set_profile_basics(client_id, name=str(result.get("name") or ""), phone=phone)

    return {"success": True, "client_id": client_id, "name": result.get("name") or ""}


@router.post("/logout")
async def logout(auth: dict = Depends(authenticate_webapp_user)):
    async with async_session() as session:
        stmt = select(User).where(
            User.telegram_id == auth["telegram_id"],
            User.bot_id == auth["bot_id"],
        )
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            user.client_id = None
            user.phone_number = None
        await session.execute(
            delete(WebSession).where(
                WebSession.telegram_id == auth["telegram_id"],
                WebSession.bot_id == auth["bot_id"],
            )
        )
        await session.execute(
            delete(CartItem).where(
                CartItem.telegram_id == auth["telegram_id"],
                CartItem.bot_id == auth["bot_id"],
            )
        )
        await session.commit()
    return {"success": True}


# ── 2. cabinet ──────────────────────────────────────────────────────────────
@router.get("/cabinet")
async def get_cabinet(auth: dict = Depends(authenticate_webapp_user)):
    client_id = await _require_client(auth)
    cab = await svc.get_cabinet(*_creds(auth), client_id)
    if not cab:
        raise HTTPException(status_code=502, detail="Маълумот олинмади")
    if "next_payment" in cab:  # real 1C answer carries it
        nxt = cab.pop("next_payment")
    else:
        nxt = await svc.get_next_payment(*_creds(auth), client_id)
    # mock state is per-process: fall back to what we know from Telegram / DB
    if not cab.get("name") or cab.get("name") == "Мижоз":
        tg_name = f"{auth.get('first_name', '')} {auth.get('last_name', '')}".strip()
        cab["name"] = tg_name or cab.get("name") or "Мижоз"
    if not cab.get("phone"):
        user = await _get_user(auth["telegram_id"], auth["bot_id"])
        cab["phone"] = (user.phone_number if user else "") or ""
    return _ser({**cab, "next_payment": nxt})


class RemindersRequest(BaseModel):
    enabled: bool


@router.post("/reminders")
async def set_reminders(req: RemindersRequest, auth: dict = Depends(authenticate_webapp_user)):
    client_id = await _require_client(auth)
    await svc.set_reminders(client_id, req.enabled)
    return {"success": True, "enabled": req.enabled}


# ── 3. contracts / debt ─────────────────────────────────────────────────────
@router.get("/contracts")
async def get_contracts(auth: dict = Depends(authenticate_webapp_user)):
    client_id = await _require_client(auth)
    contracts = await svc.get_contracts(*_creds(auth), client_id)
    return _ser({
        "contracts": contracts,
        "total_debt": sum(c["remaining_debt"] for c in contracts),
        "overdue_amount": sum(c["overdue_amount"] for c in contracts),
        "active_count": sum(1 for c in contracts if c["status"] != "closed"),
    })


@router.get("/contracts/{contract_id}")
async def get_contract(contract_id: int, auth: dict = Depends(authenticate_webapp_user)):
    client_id = await _require_client(auth)
    c = await svc.get_contract(*_creds(auth), client_id, contract_id)
    if not c:
        raise HTTPException(status_code=404, detail="Шартнома топилмади")
    return _ser(c)


# ── 4. schedule ─────────────────────────────────────────────────────────────
@router.get("/schedule")
async def get_schedule(
    status: str = "all",
    contract_id: Optional[int] = None,
    auth: dict = Depends(authenticate_webapp_user),
):
    if status not in ("all", "paid", "pending", "overdue"):
        raise HTTPException(status_code=400, detail="Нотўғри статус")
    client_id = await _require_client(auth)
    rows = await svc.get_schedule(*_creds(auth), client_id, status=status, contract_id=contract_id)
    nxt = await svc.get_next_payment(*_creds(auth), client_id)
    today = date.today()
    for r in rows:
        r["days"] = (r["date"] - today).days
    return _ser({
        "rows": rows,
        "total": sum(r["amount"] for r in rows),
        "next_payment": {**nxt, "days": (nxt["date"] - today).days} if nxt else None,
    })


# ── 5. payments ─────────────────────────────────────────────────────────────
@router.get("/payment-methods")
async def get_payment_methods(auth: dict = Depends(authenticate_webapp_user)):
    return {"methods": list(PAY_METHODS.values()), "mock": svc.is_mock()}


@router.get("/payments")
async def get_payments(auth: dict = Depends(authenticate_webapp_user)):
    client_id = await _require_client(auth)
    payments = await svc.get_payments(*_creds(auth), client_id)
    cab = await svc.get_cabinet(*_creds(auth), client_id)
    return _ser({
        "payments": payments,
        "total_paid": cab["total_paid"] if cab else sum(p["amount"] for p in payments),
        "remaining_debt": cab["remaining_debt"] if cab else None,
    })


class PaymentInit(BaseModel):
    contract_id: int
    amount: float
    method: str


@router.post("/payments/init")
async def init_payment(req: PaymentInit, auth: dict = Depends(authenticate_webapp_user)):
    """Step 1: validate & return a (demo) checkout link for the chosen provider."""
    client_id = await _require_client(auth)
    if req.method not in PAY_METHODS:
        raise HTTPException(status_code=400, detail="Нотўғри тўлов усули")
    c = await svc.get_contract(*_creds(auth), client_id, req.contract_id)
    if not c or c["status"] == "closed":
        raise HTTPException(status_code=400, detail="Бу шартнома бўйича қарз йўқ")
    amount = float(req.amount)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Нотўғри сумма")
    if amount > c["remaining_debt"] + 0.5:
        amount = c["remaining_debt"]
    m = PAY_METHODS[req.method]
    checkout_url = f"{m['url']}?merchant=mxnasiya&contract={c['number']}&amount={int(amount) * 100}"
    return _ser({
        "contract_number": c["number"],
        "amount": amount,
        "after": max(0.0, c["remaining_debt"] - amount),
        "method": m,
        "checkout_url": checkout_url,
        "mock": svc.is_mock(),
    })


@router.post("/payments")
async def make_payment(req: PaymentInit, auth: dict = Depends(authenticate_webapp_user)):
    """Step 2: confirm — apply the payment and return the receipt."""
    client_id = await _require_client(auth)
    if req.method not in PAY_METHODS:
        raise HTTPException(status_code=400, detail="Нотўғри тўлов усули")
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Нотўғри сумма")
    result = await svc.make_payment(
        *_creds(auth), client_id, req.contract_id, float(req.amount),
        method=PAY_METHODS[req.method]["label"],
    )
    if not result or not result.get("success"):
        raise HTTPException(status_code=400, detail="Тўлов амалга ошмади")
    return _ser({**result, "method": PAY_METHODS[req.method]["label"], "mock": svc.is_mock()})


# ── 6. purchases ────────────────────────────────────────────────────────────
@router.get("/purchases")
async def get_purchases(auth: dict = Depends(authenticate_webapp_user)):
    client_id = await _require_client(auth)
    rows = await svc.get_purchases(*_creds(auth), client_id)
    return _ser({"purchases": rows, "total": sum(r["total"] for r in rows)})


# ── 8. support ──────────────────────────────────────────────────────────────
@router.get("/company")
async def get_company(auth: dict = Depends(authenticate_webapp_user)):
    return await svc.get_company_info(*_creds(auth))


class SupportRequest(BaseModel):
    kind: str  # request | question
    text: str


@router.post("/requests")
async def create_request(req: SupportRequest, auth: dict = Depends(authenticate_webapp_user)):
    client_id = await _require_client(auth)
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Матн киритинг")
    kind = "request" if req.kind != "question" else "question"
    res = await svc.create_request(*_creds(auth), client_id, kind, text, telegram_id=auth["telegram_id"])
    if not res or not res.get("success"):
        raise HTTPException(status_code=502, detail="Юборишда хатолик")
    return res


# ── 9. promotions ───────────────────────────────────────────────────────────
@router.get("/promotions")
async def get_promotions(auth: dict = Depends(authenticate_webapp_user)):
    return {"items": await svc.get_promotions(*_creds(auth))}
