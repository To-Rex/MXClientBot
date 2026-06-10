import logging
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from app.database import async_session
from app.models import User
from app.services.api import APIService
from app.web.web_app_auth import authenticate_webapp_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webapp/api")

api_service = APIService()


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
        cfg["base_url"], cfg["one_c_login"], cfg["one_c_password"], phone,
    )

    if not result or not result.get("id"):
        raise HTTPException(status_code=400, detail="Ro'yxatdan o'tishda xatolik")

    client_id = str(result["id"])
    await _save_user(auth["telegram_id"], auth["bot_id"], phone, client_id)

    return {"success": True, "client_id": client_id}


@router.get("/profile")
async def get_profile(auth: dict = Depends(authenticate_webapp_user)):
    user = await _get_user(auth["telegram_id"], auth["bot_id"])
    if not user or not user.client_id:
        raise HTTPException(status_code=400, detail="Avval ro'yxatdan o'ting")

    cfg = auth["bot_config"]
    profile = await api_service.get_client_info(
        cfg["base_url"], cfg["one_c_login"], cfg["one_c_password"], user.client_id,
    )

    if profile is None:
        raise HTTPException(status_code=502, detail="Ma'lumotlarni olishda xatolik")

    if not profile:
        return {"fields": [], "images": []}

    IMAGE_FIELD_NAMES = ("images", "photos", "rasmlar", "photos_list")
    PROFILE_FIELD_LABELS = {
        "name": "Ism", "group": "Guruh", "branch": "Filial",
        "address": "Manzil", "category": "Kategoriya", "phone": "Telefon",
        "agent": "Agent", "status": "Status", "visit_days": "Tashrif kunlari",
        "activity_types": "Faoliyat turlari",
    }

    fields = []
    shown_labels = set()

    for field, label in PROFILE_FIELD_LABELS.items():
        value = profile.get(field)
        if value is not None and value != "":
            fields.append({"label": label, "value": str(value)})
            shown_labels.add(label)

    for field, value in profile.items():
        if field in PROFILE_FIELD_LABELS or field in IMAGE_FIELD_NAMES:
            continue
        if field in ("client_id", "id"):
            continue
        if value is not None and value != "" and isinstance(value, (str, int, float)):
            label = field.replace("_", " ").title()
            if label not in shown_labels:
                fields.append({"label": label, "value": str(value)})
                shown_labels.add(label)

    images = []
    for field in IMAGE_FIELD_NAMES:
        value = profile.get(field)
        if isinstance(value, list) and value:
            images = [str(img) for img in value if img]
            break
        if isinstance(value, str) and value.strip():
            images = [value.strip()]
            break

    return {"fields": fields, "images": images}


@router.get("/info")
async def get_info(auth: dict = Depends(authenticate_webapp_user)):
    user = await _get_user(auth["telegram_id"], auth["bot_id"])
    if not user or not user.client_id:
        raise HTTPException(status_code=400, detail="Avval ro'yxatdan o'ting")

    cfg = auth["bot_config"]
    profile = await api_service.get_client_info(
        cfg["base_url"], cfg["one_c_login"], cfg["one_c_password"], user.client_id,
    )

    company = cfg["company_name"]
    info = {"company": company, "details": []}

    if profile:
        branch = profile.get("filial_name") or profile.get("branch", "")
        group_name = profile.get("group_name") or profile.get("group", "")
        agent_data = profile.get("agent", {})
        agent_name = agent_data.get("agent_name", "") if isinstance(agent_data, dict) else ""
        status_name = profile.get("status_name") or profile.get("status", "")

        if branch:
            info["details"].append({"label": "Filial", "value": branch})
        if group_name:
            info["details"].append({"label": "Guruh", "value": group_name})
        if agent_name:
            info["details"].append({"label": "Agent", "value": agent_name})
        if status_name:
            info["details"].append({"label": "Status", "value": status_name})
        if user.client_id:
            info["details"].append({"label": "Client ID", "value": user.client_id})
        if user.phone_number:
            info["details"].append({"label": "Telefon", "value": f"+{user.phone_number}"})

    return info


@router.get("/products")
async def get_products(auth: dict = Depends(authenticate_webapp_user)):
    user = await _get_user(auth["telegram_id"], auth["bot_id"])
    if not user or not user.client_id:
        raise HTTPException(status_code=400, detail="Avval ro'yxatdan o'ting")

    cfg = auth["bot_config"]
    data = await api_service.get_products(
        cfg["base_url"], cfg["one_c_login"], cfg["one_c_password"],
    )

    if not data or not data.get("data"):
        return {"groups": []}

    groups = []
    for g in data["data"]:
        groups.append({
            "group_id": g["group_id"],
            "group_name": g["group_name"],
            "product_count": len(g.get("products", [])),
        })

    return {"groups": groups}


@router.get("/products/{group_id}")
async def get_products_by_group(group_id: int, auth: dict = Depends(authenticate_webapp_user)):
    user = await _get_user(auth["telegram_id"], auth["bot_id"])
    if not user or not user.client_id:
        raise HTTPException(status_code=400, detail="Avval ro'yxatdan o'ting")

    cfg = auth["bot_config"]
    data = await api_service.get_products(
        cfg["base_url"], cfg["one_c_login"], cfg["one_c_password"],
    )

    if not data or not data.get("data"):
        raise HTTPException(status_code=404, detail="Mahsulotlar topilmadi")

    group = next((g for g in data["data"] if g["group_id"] == group_id), None)
    if not group:
        raise HTTPException(status_code=404, detail="Guruh topilmadi")

    products = []
    for product in group.get("products", []):
        price_val = 0.0
        cry = ""
        prices = product.get("typePrice", [])
        if prices:
            p = prices[0]
            price_val = float(p["price"])
            cry = p.get("cry", "")

        qty = ""
        sklads = product.get("sklad", [])
        if sklads:
            qty = str(sklads[0].get("qty", ""))

        images = []
        imgs = product.get("img", [])
        if imgs:
            for img in imgs:
                url = img.get("URL", "")
                if url:
                    images.append(f"/webapp/api/image-proxy?url={quote(url, safe='')}")

        status = product.get("status", "")

        products.append({
            "id": product.get("id"),
            "name": product.get("name", "Nomsiz"),
            "price": price_val,
            "currency": cry,
            "qty": qty,
            "status": status,
            "images": images,
        })

    return {
        "group_id": group_id,
        "group_name": group.get("group_name", "Guruh"),
        "products": products,
    }


@router.get("/image-proxy")
async def image_proxy(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Yaroqsiz URL")

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            upstream = await client.get(url)
            upstream.raise_for_status()
    except Exception as e:
        logger.error("❌ image_proxy FAILED for %s: %s", url, e)
        raise HTTPException(status_code=502, detail="Rasm yuklanmadi")

    content_type = upstream.headers.get("content-type", "image/jpeg")
    return Response(
        content=upstream.content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/orders")
async def get_orders(auth: dict = Depends(authenticate_webapp_user)):
    user = await _get_user(auth["telegram_id"], auth["bot_id"])
    if not user or not user.client_id:
        raise HTTPException(status_code=400, detail="Avval ro'yxatdan o'ting")

    cfg = auth["bot_config"]
    data = await api_service.get_orders(
        cfg["base_url"], cfg["one_c_login"], cfg["one_c_password"], user.client_id,
    )

    if not data or not data.get("data"):
        return {"orders": []}

    orders = []
    for order in data["data"]:
        goods = order.get("list_goods", [])
        first_item = goods[0] if goods else {}
        item_price = first_item.get("summa", 0) / max(first_item.get("qty", 1), 1)
        item_product_id = first_item.get("id", 0)

        items = []
        for item in goods:
            items.append({
                "name": item.get("name", "-"),
                "qty": item.get("qty", 0),
                "summa": item.get("summa", 0),
            })

        orders.append({
            "id": order.get("id", "?"),
            "name": order.get("name", ""),
            "total_qty": order.get("qty", 0),
            "total_sum": order.get("summa", 0),
            "first_product_id": item_product_id,
            "first_price": item_price,
            "items": items,
        })

    return {"orders": orders}


class CreateOrderRequest(BaseModel):
    product_id: int
    price: float
    qty: float = 1.0


@router.post("/orders")
async def create_order(req: CreateOrderRequest, auth: dict = Depends(authenticate_webapp_user)):
    if req.qty <= 0:
        raise HTTPException(status_code=400, detail="Miqdor musbat bo'lishi kerak")

    user = await _get_user(auth["telegram_id"], auth["bot_id"])
    if not user or not user.client_id:
        raise HTTPException(status_code=400, detail="Avval ro'yxatdan o'ting")

    cfg = auth["bot_config"]
    result = await api_service.create_order(
        cfg["base_url"], cfg["one_c_login"], cfg["one_c_password"],
        client_id=int(user.client_id),
        product_id=req.product_id,
        price=req.price,
        qty=req.qty,
    )

    if not result or result.get("error"):
        error = (result or {}).get("message") or (result or {}).get("error", "Noma'lum xatolik")
        raise HTTPException(status_code=400, detail=str(error))

    return {
        "success": True,
        "order_id": result.get("id", "?"),
        "total": req.price * req.qty,
    }


class EditOrderRequest(BaseModel):
    product_id: int
    price: float
    qty: float


@router.patch("/orders/{order_id}")
async def edit_order(order_id: int, req: EditOrderRequest, auth: dict = Depends(authenticate_webapp_user)):
    if req.qty <= 0:
        raise HTTPException(status_code=400, detail="Miqdor musbat bo'lishi kerak")

    cfg = auth["bot_config"]
    result = await api_service.edit_order(
        cfg["base_url"], cfg["one_c_login"], cfg["one_c_password"],
        order_id=order_id,
        products=[{
            "product_id": req.product_id,
            "price": req.price,
            "qty": req.qty,
            "sum": req.price * req.qty,
        }],
    )

    if not result or result.get("error"):
        error = (result or {}).get("message") or (result or {}).get("error", "Noma'lum xatolik")
        raise HTTPException(status_code=400, detail=str(error))

    return {"success": True, "total": req.price * req.qty}


@router.delete("/orders/{order_id}")
async def delete_order(order_id: int, auth: dict = Depends(authenticate_webapp_user)):
    cfg = auth["bot_config"]
    result = await api_service.delete_order(
        cfg["base_url"], cfg["one_c_login"], cfg["one_c_password"], order_id,
    )

    if not result or result.get("error"):
        error = (result or {}).get("message") or (result or {}).get("error", "Noma'lum xatolik")
        raise HTTPException(status_code=400, detail=str(error))

    return {"success": True}


@router.get("/akt-sverka")
async def get_akt_sverka(months: int = 1, auth: dict = Depends(authenticate_webapp_user)):
    if months not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="months 1, 2 yoki 3 bo'lishi kerak")

    user = await _get_user(auth["telegram_id"], auth["bot_id"])
    if not user or not user.client_id:
        raise HTTPException(status_code=400, detail="Avval ro'yxatdan o'ting")

    end = datetime.now()
    start = end - timedelta(days=months * 30)
    date_begin = start.strftime("%Y%m%d")
    date_end = end.strftime("%Y%m%d")

    cfg = auth["bot_config"]
    data = await api_service.get_akt_sverka(
        cfg["base_url"], cfg["one_c_login"], cfg["one_c_password"],
        user.client_id,
        date_begin=date_begin,
        date_end=date_end,
    )

    if not data or not data.get("data"):
        return {"documents": [], "months": months}

    documents = []
    for doc in data["data"]:
        doc_debt = doc.get("debt", 0)
        doc_credit = doc.get("credit", 0)

        if doc_debt > 0:
            direction = "Buyurtma"
        elif doc_credit > 0:
            direction = "To'lov"
        else:
            direction = doc.get("type_doc", "")

        details = []
        for d in doc.get("detals", []):
            d_debt = d.get("debt", 0)
            d_credit = d.get("credit", 0)
            details.append({
                "name": str(d.get("osnova", "-")),
                "qty": str(d.get("qty", "0")),
                "summa": d_debt or d_credit,
            })

        documents.append({
            "id": str(doc.get("id_doc", "?")),
            "date": str(doc.get("date_doc", "")),
            "type": str(doc.get("type_doc", "")),
            "direction": direction,
            "debt": doc_debt,
            "credit": doc_credit,
            "balance": doc.get("balance", 0),
            "details": details,
        })

    return {"documents": documents, "months": months}


@router.get("/balance")
async def get_balance(auth: dict = Depends(authenticate_webapp_user)):
    user = await _get_user(auth["telegram_id"], auth["bot_id"])
    if not user or not user.client_id:
        raise HTTPException(status_code=400, detail="Avval ro'yxatdan o'ting")

    cfg = auth["bot_config"]
    data = await api_service.get_balance(
        cfg["base_url"], cfg["one_c_login"], cfg["one_c_password"],
        user.client_id,
    )

    if not data:
        raise HTTPException(status_code=502, detail="Balansni olishda xatolik")

    return {
        "balance": data.get("balance", "0 UZS"),
        "client_id": user.client_id,
    }
