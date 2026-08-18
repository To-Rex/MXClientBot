"""WebApp JSON API — MX Nasiya personal cabinet (mirrors the Telegram bot).

Auth: Telegram initData (X-Telegram-Init-Data) or ?session=<token> from /getsession.
Data: ``NasiyaService`` (real 1C HTTP-service) — same service the bot uses.
1C endpoints that are not ready → 503 {"code": "SERVICE_UNAVAILABLE"} (handled in app/main.py).
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
    nxt = cab.pop("next_payment", None)
    if not cab.get("phone"):
        user = await _get_user(auth["telegram_id"], auth["bot_id"])
        cab["phone"] = (user.phone_number if user else "") or ""
    return _ser({**cab, "next_payment": nxt})


class RemindersRequest(BaseModel):
    enabled: bool


@router.post("/reminders")
async def set_reminders(req: RemindersRequest, auth: dict = Depends(authenticate_webapp_user)):
    client_id = await _require_client(auth)
    enabled = await svc.set_reminders(*_creds(auth), client_id, req.enabled, chat_id=str(auth["telegram_id"]))
    return {"success": True, "enabled": enabled}


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
    return {"methods": list(PAY_METHODS.values())}


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
    payment_id: Optional[int] = None


@router.post("/payments/init")
async def init_payment(req: PaymentInit, auth: dict = Depends(authenticate_webapp_user)):
    """Step 1: 1C createPayment → pending payment + (demo) checkout link for the provider."""
    client_id = await _require_client(auth)
    if req.method not in PAY_METHODS:
        raise HTTPException(status_code=400, detail="Нотўғри тўлов усули")
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Нотўғри сумма")
    created = await svc.create_payment(*_creds(auth), client_id, req.contract_id, float(req.amount),
                                       req.method, chat_id=str(auth["telegram_id"]), source="webapp")
    m = PAY_METHODS[req.method]
    checkout_url = f"{m['url']}?merchant=mxnasiya&order={created['payment_id']}&amount={int(created['amount']) * 100}"
    return _ser({
        "payment_id": created["payment_id"],
        "contract_number": created["contract_number"],
        "amount": created["amount"],
        "after": created["remaining_after"],
        "expires_at": created["expires_at"],
        "method": m,
        "checkout_url": checkout_url,
    })


@router.post("/payments")
async def confirm_payment(req: PaymentInit, auth: dict = Depends(authenticate_webapp_user)):
    """Step 2: confirm — 1C confirmPayment (creates the pending payment first if init was skipped)."""
    client_id = await _require_client(auth)
    if req.method not in PAY_METHODS:
        raise HTTPException(status_code=400, detail="Нотўғри тўлов усули")
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Нотўғри сумма")
    result = await svc.make_payment(
        *_creds(auth), client_id, req.contract_id, float(req.amount), method=req.method,
        chat_id=str(auth["telegram_id"]), source="webapp", payment_id=req.payment_id,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail="Тўлов амалга ошмади")
    return _ser({**result, "method": result.get("method") or PAY_METHODS[req.method]["label"]})


class PaymentCancel(BaseModel):
    payment_id: int


@router.post("/payments/cancel")
async def cancel_payment(req: PaymentCancel, auth: dict = Depends(authenticate_webapp_user)):
    await _require_client(auth)
    ok = await svc.cancel_payment(*_creds(auth), req.payment_id, "user_cancel")
    return {"success": ok}


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
    res = await svc.create_request(*_creds(auth), client_id, kind, text, telegram_id=auth["telegram_id"], source="webapp")
    if not res or not res.get("success"):
        raise HTTPException(status_code=502, detail="Юборишда хатолик")
    return res


# ── 9. promotions ───────────────────────────────────────────────────────────
@router.get("/promotions")
async def get_promotions(type: Optional[str] = None, auth: dict = Depends(authenticate_webapp_user)):
    return {"items": await svc.get_promotions(*_creds(auth), type)}
