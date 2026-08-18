"""Nasiya (installment) data service — real 1C HTTP-service client.

Endpoints and payloads: docs/1C_NASIYA_API.md
Base: {base_url}/hs/client_bot/api/<endpoint>, HTTP Basic Auth (per-bot 1C login/password).

Every method returns plain dicts/lists in the shape the bot and WebApp render.
Failure model (handlers rely on it):
  * ``ServiceUnavailable`` — endpoint not implemented yet / 1C down / malformed answer.
    Bot & WebApp show "бу хизмат тез кунда ишга тушади".
  * ``NasiyaError``       — 1C answered with a business error ({"error": {code, message}}).
    Bot & WebApp show the message.
No mock data lives here anymore.
"""
import base64
import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

import httpx

from app.services.http_client import get_http_client

logger = logging.getLogger(__name__)

API_PREFIX = "/hs/client_bot/api/"
TIMEOUT = 30.0


class ServiceUnavailable(Exception):
    """1C endpoint is not ready (404/5xx/empty or malformed body/network error)."""

    def __init__(self, endpoint: str, reason: str = ""):
        self.endpoint = endpoint
        self.reason = reason
        super().__init__(f"{endpoint} unavailable: {reason}")


class NasiyaError(Exception):
    """1C returned a business error: {"error": {"code": ..., "message": ...}}."""

    def __init__(self, code: str, message: str, endpoint: str = ""):
        self.code = code
        self.message = message
        self.endpoint = endpoint
        super().__init__(f"{endpoint} {code}: {message}")


# ────────────────────────────────────────────────────────────────────────────
# low-level helpers
# ────────────────────────────────────────────────────────────────────────────
def _today() -> date:
    return datetime.now(timezone.utc).date()


def _fmt_money(v: float) -> str:
    return f"{float(v or 0):,.0f}".replace(",", " ") + " сўм"


def _fmt_date(d: Any) -> str:
    if isinstance(d, (date, datetime)):
        return d.strftime("%d.%m.%Y")
    p = _parse_date(d)
    return p.strftime("%d.%m.%Y") if p else (str(d) if d else "")


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _to_int(v: Any, default: int = 0) -> int:
    try:
        return int(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _parse_date(v: Any) -> Optional[date]:
    """Accepts 'YYYY-MM-DD', ISO datetime, 'DD.MM.YYYY', 'YYYYMMDD'."""
    if not v:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt, n in (("%Y-%m-%d", 10), ("%d.%m.%Y", 10), ("%Y%m%d", 8)):
        try:
            return datetime.strptime(s[:n], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def _parse_dt(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).strip())
    except ValueError:
        d = _parse_date(v)
        return datetime(d.year, d.month, d.day) if d else None


def _raise_if_error(endpoint: str, data: Any) -> None:
    if isinstance(data, dict) and isinstance(data.get("error"), dict):
        err = data["error"]
        raise NasiyaError(str(err.get("code") or "ERROR"), str(err.get("message") or "Хатолик"), endpoint)


async def _request(
    method: str, base_url: str, login: str, password: str, endpoint: str,
    params: Optional[dict] = None, body: Optional[dict] = None,
) -> Any:
    """Perform request; return parsed JSON. Raises ServiceUnavailable / NasiyaError."""
    if not base_url:
        raise ServiceUnavailable(endpoint, "base_url is empty (bot settings)")
    url = f"{base_url.rstrip('/')}{API_PREFIX}{endpoint}"
    creds = base64.b64encode(f"{login}:{password}".encode()).decode()
    headers = {"Authorization": f"Basic {creds}", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    logger.info("📡 1C %s %s params=%s body=%s", method, url, params, body)
    try:
        resp = await get_http_client().request(method, url, params=params, json=body, headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError as e:
        logger.error("❌ 1C %s network error: %s", endpoint, e)
        raise ServiceUnavailable(endpoint, f"network: {e}")
    text = resp.text or ""
    logger.info("📡 1C %s RESPONSE %s: %s", endpoint, resp.status_code, text[:400])

    if resp.status_code == 401:
        raise NasiyaError("UNAUTHORIZED", "1C логин/парол нотўғри (панелдан текширинг)", endpoint)
    if resp.status_code in (404, 405, 501) or resp.status_code >= 500:
        raise ServiceUnavailable(endpoint, f"http {resp.status_code}")
    if not text.strip():
        # 1C answers 200 with an empty body for handlers that are not implemented yet
        raise ServiceUnavailable(endpoint, "empty body")
    try:
        data = resp.json()
    except ValueError:
        raise ServiceUnavailable(endpoint, "non-JSON body")
    _raise_if_error(endpoint, data)
    if resp.status_code >= 400:
        raise NasiyaError(f"HTTP_{resp.status_code}", str(data)[:200], endpoint)
    return data


async def _get(base_url, login, password, endpoint, **params) -> Any:
    return await _request("GET", base_url, login, password, endpoint,
                          params={k: v for k, v in params.items() if v is not None})


async def _post(base_url, login, password, endpoint, body: dict) -> Any:
    return await _request("POST", base_url, login, password, endpoint, body=body)


def _expect_list(endpoint: str, data: Any) -> list:
    """1C's catch-all handler may answer 200 with someone else's JSON — validate shape."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "data", "list", "rows", endpoint):
            if isinstance(data.get(key), list):
                return data[key]
    raise ServiceUnavailable(endpoint, "unexpected shape (not a list)")


def _expect_dict(endpoint: str, data: Any, must_have: tuple = ()) -> dict:
    if not isinstance(data, dict):
        raise ServiceUnavailable(endpoint, "unexpected shape (not an object)")
    if must_have and not any(k in data for k in must_have):
        raise ServiceUnavailable(endpoint, f"unexpected shape (missing {must_have})")
    return data


# ────────────────────────────────────────────────────────────────────────────
# mappers: 1C JSON → bot/webapp dicts
# ────────────────────────────────────────────────────────────────────────────
METHOD_LABELS = {
    "payme": "Payme", "click": "Click", "paynet": "Paynet",
    "cash": "Нақд (дўконда)", "card": "Карта / терминал", "other": "Бошқа",
}


def _map_next_payment(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict) or not raw.get("date"):
        return None
    d = _parse_date(raw.get("date"))
    if not d:
        return None
    return {
        "date": d,
        "amount": _to_float(raw.get("amount")),
        "contract_id": _to_int(raw.get("contract_id")),
        "contract_number": str(raw.get("contract_number") or ""),
        "status": "overdue" if d < _today() else "pending",
    }


def _map_client_info(d: dict, client_id: str) -> dict:
    reg = _parse_date(d.get("registered_at"))
    return {
        "client_id": str(d.get("client_id") or client_id),
        "name": str(d.get("name") or "Мижоз"),
        "phone": str(d.get("phone") or ""),
        "status": str(d.get("status") or "Мижоз"),
        "registered_at": _fmt_date(reg) if reg else str(d.get("registered_at") or "—"),
        "reminders_enabled": bool(d.get("reminders_enabled", True)),
        "active_contracts": _to_int(d.get("active_contracts")),
        "total_contracts": _to_int(d.get("total_contracts")),
        "total_nasiya": _to_float(d.get("total_nasiya")),
        "total_paid": _to_float(d.get("total_paid")),
        "remaining_debt": _to_float(d.get("remaining_debt")),
        "overdue_amount": _to_float(d.get("overdue_amount")),
        "overdue_count": _to_int(d.get("overdue_count")),
        "next_payment": _map_next_payment(d.get("next_payment")),
    }


def _map_product(p: dict) -> dict:
    qty = _to_float(p.get("qty"), 1.0)
    price = _to_float(p.get("price"))
    return {
        "product_id": _to_int(p.get("product_id")),
        "name": str(p.get("name") or "Товар"),
        "qty": int(qty) if qty == int(qty) else qty,
        "price": price,
        "sum": _to_float(p.get("sum"), price * qty),
    }


def _map_schedule_row(r: dict, contract_id: int = 0, contract_number: str = "") -> dict:
    d = _parse_date(r.get("date")) or _today()
    status = str(r.get("status") or "").lower()
    if status not in ("paid", "pending", "overdue"):
        status = "paid" if r.get("paid_date") else ("overdue" if d < _today() else "pending")
    return {
        "n": _to_int(r.get("n")),
        "date": d,
        "amount": _to_float(r.get("amount")),
        "status": status,
        "paid_date": _parse_date(r.get("paid_date")),
        "paid_amount": _to_float(r.get("paid_amount")),
        "contract_id": _to_int(r.get("contract_id"), contract_id),
        "contract_number": str(r.get("contract_number") or contract_number),
    }


def _map_contract(c: dict) -> dict:
    """1C contract → dict used by handlers (keys: number, date, products, remaining_debt, ...)."""
    today = _today()
    status = str(c.get("status") or "").lower()
    remaining = _to_float(c.get("remaining_debt"))
    if status not in ("active", "overdue", "closed"):
        status = "closed" if remaining <= 0.5 else ("overdue" if _to_float(c.get("overdue_amount")) > 0 else "active")
    products_raw = c.get("products")
    products = [_map_product(p) for p in products_raw if isinstance(p, dict)] if isinstance(products_raw, list) else []
    if not products and c.get("products_short"):
        products = [{"product_id": 0, "name": n.strip(), "qty": 1, "price": 0.0, "sum": 0.0}
                    for n in str(c["products_short"]).split(",") if n.strip()]
    nxt_date = _parse_date(c.get("next_payment_date"))
    number = str(c.get("contract_number") or c.get("number") or c.get("contract_id") or "")
    cid = _to_int(c.get("contract_id"))
    out = {
        "contract_id": cid,
        "number": number,
        "date": _parse_date(c.get("date")) or today,
        "branch": str(c.get("branch") or ""),
        "status": status,
        "products": products,
        "products_short": str(c.get("products_short") or ", ".join(p["name"] for p in products)),
        "goods_total": _to_float(c.get("goods_total")),
        "total": _to_float(c.get("total")),
        "initial_payment": _to_float(c.get("initial_payment")),
        "months": _to_int(c.get("months")),
        "monthly_payment": _to_float(c.get("monthly_payment")),
        "paid": _to_float(c.get("paid")),
        "paid_count": _to_int(c.get("paid_count")),
        "remaining_debt": remaining,
        "overdue_amount": _to_float(c.get("overdue_amount")),
        "overdue_count": _to_int(c.get("overdue_count")),
        "next_payment_date": nxt_date,
        "next_payment_amount": _to_float(c.get("next_payment_amount")),
        "days_to_next": (nxt_date - today).days if nxt_date else None,
        "end_date": _parse_date(c.get("end_date")) or nxt_date or today,
    }
    sched_raw = c.get("schedule")
    if isinstance(sched_raw, list):
        out["schedule"] = [_map_schedule_row(r, cid, number) for r in sched_raw if isinstance(r, dict)]
    return out


def _map_payment(p: dict) -> dict:
    method = str(p.get("method") or "other")
    return {
        "payment_id": _to_int(p.get("payment_id")),
        "date": _parse_date(p.get("date")) or _today(),
        "amount": _to_float(p.get("amount")),
        "contract_id": _to_int(p.get("contract_id")),
        "contract_number": str(p.get("contract_number") or ""),
        "method": METHOD_LABELS.get(method.lower(), method),
        "method_code": method.lower(),
        "receipt_no": str(p.get("receipt_no") or ""),
        "note": str(p.get("note") or ""),
        "transaction_id": p.get("transaction_id"),
    }


def _map_receipt(r: dict) -> dict:
    method = str(r.get("method") or "")
    return {
        "success": bool(r.get("success", True)),
        "payment_id": _to_int(r.get("payment_id")),
        "receipt_no": str(r.get("receipt_no") or ""),
        "date": _parse_date(r.get("date")) or _today(),
        "amount": _to_float(r.get("amount")),
        "method": METHOD_LABELS.get(method.lower(), method),
        "contract_id": _to_int(r.get("contract_id")),
        "contract_number": str(r.get("contract_number") or ""),
        "remaining_debt": _to_float(r.get("remaining_debt")),
        "next_payment_date": _parse_date(r.get("next_payment_date")),
        "next_payment_amount": _to_float(r.get("next_payment_amount")),
        "closed": bool(r.get("closed", False)),
    }


# ────────────────────────────────────────────────────────────────────────────
# service facade
# ────────────────────────────────────────────────────────────────────────────
class NasiyaService:
    fmt_money = staticmethod(_fmt_money)
    fmt_date = staticmethod(_fmt_date)

    # ── 2. cabinet ──────────────────────────────────────────────────────
    @staticmethod
    async def get_cabinet(base_url: str, login: str, password: str, client_id: str) -> dict:
        data = await _get(base_url, login, password, "getClientInfo", client_id=client_id)
        d = _expect_dict("getClientInfo", data, ("client_id", "name"))
        return _map_client_info(d, client_id)

    @staticmethod
    async def get_next_payment(base_url: str, login: str, password: str, client_id: str) -> Optional[dict]:
        cab = await NasiyaService.get_cabinet(base_url, login, password, client_id)
        return cab.get("next_payment")

    @staticmethod
    async def set_reminders(base_url: str, login: str, password: str, client_id: str,
                            enabled: bool, chat_id: str = "") -> bool:
        data = await _post(base_url, login, password, "setReminders",
                           {"client_id": _to_int(client_id), "chat_id": str(chat_id or ""), "enabled": bool(enabled)})
        d = _expect_dict("setReminders", data)
        return bool(d.get("enabled", enabled))

    # ── 3. contracts ────────────────────────────────────────────────────
    @staticmethod
    async def get_contracts(base_url: str, login: str, password: str, client_id: str) -> list[dict]:
        data = await _get(base_url, login, password, "getContracts", client_id=client_id)
        rows = _expect_list("getContracts", data)
        out = [_map_contract(c) for c in rows if isinstance(c, dict)]
        out.sort(key=lambda c: c["date"], reverse=True)
        return out

    @staticmethod
    async def get_contract(base_url: str, login: str, password: str, client_id: str, contract_id: int) -> Optional[dict]:
        try:
            data = await _get(base_url, login, password, "getContract", client_id=client_id, contract_id=contract_id)
        except NasiyaError as e:
            if e.code == "CONTRACT_NOT_FOUND":
                return None
            raise
        d = _expect_dict("getContract", data, ("contract_id", "contract_number", "number"))
        c = _map_contract(d)
        c.setdefault("schedule", [])
        return c

    # ── 4. schedule ─────────────────────────────────────────────────────
    @staticmethod
    async def get_schedule(
        base_url: str, login: str, password: str, client_id: str,
        status: str = "all", contract_id: Optional[int] = None,
    ) -> list[dict]:
        data = await _get(base_url, login, password, "getSchedule",
                          client_id=client_id, contract_id=contract_id,
                          status=None if status in (None, "", "all") else status)
        rows = [_map_schedule_row(r) for r in _expect_list("getSchedule", data) if isinstance(r, dict)]
        if status not in (None, "", "all"):
            rows = [r for r in rows if r["status"] == status]  # in case 1C ignored the filter
        rows.sort(key=lambda r: r["date"])
        return rows

    # ── 5. payments ─────────────────────────────────────────────────────
    @staticmethod
    async def get_payments(base_url: str, login: str, password: str, client_id: str,
                           contract_id: Optional[int] = None, limit: Optional[int] = None) -> list[dict]:
        data = await _get(base_url, login, password, "getPayments",
                          client_id=client_id, contract_id=contract_id, limit=limit)
        rows = [_map_payment(p) for p in _expect_list("getPayments", data) if isinstance(p, dict)]
        rows.sort(key=lambda p: p["date"], reverse=True)
        return rows

    @staticmethod
    async def create_payment(base_url: str, login: str, password: str, client_id: str,
                             contract_id: int, amount: float, method: str,
                             chat_id: str = "", source: str = "telegram_bot") -> dict:
        data = await _post(base_url, login, password, "createPayment", {
            "client_id": _to_int(client_id), "contract_id": int(contract_id),
            "amount": float(amount), "method": method, "chat_id": str(chat_id or ""), "source": source,
        })
        d = _expect_dict("createPayment", data, ("payment_id",))
        return {
            "payment_id": _to_int(d.get("payment_id")),
            "status": str(d.get("status") or "pending"),
            "amount": _to_float(d.get("amount"), float(amount)),
            "contract_number": str(d.get("contract_number") or ""),
            "remaining_after": _to_float(d.get("remaining_after")),
            "expires_at": _parse_dt(d.get("expires_at")),
        }

    @staticmethod
    async def confirm_payment(base_url: str, login: str, password: str, payment_id: int,
                              transaction_id: str, amount: Optional[float] = None,
                              paid_at: Optional[datetime] = None) -> dict:
        body: dict[str, Any] = {"payment_id": int(payment_id), "transaction_id": str(transaction_id)}
        if amount is not None:
            body["amount"] = float(amount)
        if paid_at is not None:
            body["paid_at"] = paid_at.strftime("%Y-%m-%dT%H:%M:%S")
        data = await _post(base_url, login, password, "confirmPayment", body)
        d = _expect_dict("confirmPayment", data, ("success", "receipt_no", "payment_id"))
        return _map_receipt(d)

    @staticmethod
    async def cancel_payment(base_url: str, login: str, password: str, payment_id: int,
                             reason: str = "user_cancel") -> bool:
        try:
            data = await _post(base_url, login, password, "cancelPayment",
                               {"payment_id": int(payment_id), "reason": reason})
        except (ServiceUnavailable, NasiyaError):
            return False
        return bool(isinstance(data, dict) and data.get("success", True))

    @staticmethod
    async def make_payment(base_url: str, login: str, password: str, client_id: str,
                           contract_id: int, amount: float, method: str = "other",
                           chat_id: str = "", source: str = "telegram_bot",
                           payment_id: Optional[int] = None, transaction_id: str = "") -> dict:
        """create + confirm in one go (used while provider callbacks are not wired)."""
        if payment_id is None:
            created = await NasiyaService.create_payment(base_url, login, password, client_id,
                                                         contract_id, amount, method, chat_id, source)
            payment_id, amount = created["payment_id"], created["amount"]
        return await NasiyaService.confirm_payment(
            base_url, login, password, payment_id,
            transaction_id or f"{source}-{payment_id}", amount, datetime.now(),
        )

    # ── 6. purchases ────────────────────────────────────────────────────
    @staticmethod
    async def get_purchases(base_url: str, login: str, password: str, client_id: str) -> list[dict]:
        data = await _get(base_url, login, password, "getPurchases", client_id=client_id)
        out = []
        for r in _expect_list("getPurchases", data):
            if not isinstance(r, dict):
                continue
            products = [_map_product(p) for p in (r.get("products") or []) if isinstance(p, dict)]
            out.append({
                "purchase_id": _to_int(r.get("purchase_id")),
                "date": _parse_date(r.get("date")) or _today(),
                "contract_id": _to_int(r.get("contract_id")),
                "contract_number": str(r.get("contract_number") or ""),
                "branch": str(r.get("branch") or ""),
                "products": products,
                "total": _to_float(r.get("total"), sum(p["sum"] for p in products)),
            })
        out.sort(key=lambda r: r["date"], reverse=True)
        return out

    # ── 7. support ──────────────────────────────────────────────────────
    @staticmethod
    async def get_company_info(base_url: str, login: str, password: str) -> dict:
        data = await _get(base_url, login, password, "getCompanyInfo")
        d = _expect_dict("getCompanyInfo", data, ("name", "phone", "branches"))
        branches = []
        for b in d.get("branches") or []:
            if isinstance(b, dict):
                branches.append({
                    "branch_id": _to_int(b.get("branch_id")),
                    "name": str(b.get("name") or ""),
                    "address": str(b.get("address") or ""),
                    "phone": str(b.get("phone") or ""),
                    "hours": str(b.get("hours") or ""),
                    "lat": b.get("lat"), "lon": b.get("lon"),
                })
        return {
            "name": str(d.get("name") or ""),
            "phone": str(d.get("phone") or ""),
            "operator_phone": str(d.get("operator_phone") or d.get("phone") or ""),
            "operator_username": str(d.get("operator_username") or ""),
            "email": str(d.get("email") or ""),
            "address": str(d.get("address") or ""),
            "working_hours": str(d.get("working_hours") or ""),
            "branches": branches,
        }

    @staticmethod
    async def create_request(base_url: str, login: str, password: str, client_id: str,
                             kind: str, text: str, telegram_id: int = 0, source: str = "telegram_bot") -> dict:
        data = await _post(base_url, login, password, "createRequest", {
            "client_id": _to_int(client_id), "chat_id": str(telegram_id or ""),
            "kind": "question" if kind == "question" else "request", "text": text, "source": source,
        })
        d = _expect_dict("createRequest", data, ("request_id", "id"))
        return {"success": True, "id": _to_int(d.get("request_id") or d.get("id")),
                "status": str(d.get("status") or "new")}

    # ── 9. promotions ───────────────────────────────────────────────────
    @staticmethod
    async def get_promotions(base_url: str, login: str, password: str, kind: Optional[str] = None) -> list[dict]:
        data = await _get(base_url, login, password, "getPromotions",
                          type=None if kind in (None, "all") else kind)
        out = []
        for i in _expect_list("getPromotions", data):
            if not isinstance(i, dict):
                continue
            t = str(i.get("type") or "news").lower()
            vu = i.get("valid_until")
            out.append({
                "id": _to_int(i.get("id")),
                "type": t if t in ("promo", "new", "special", "news") else "news",
                "title": str(i.get("title") or ""),
                "text": str(i.get("text") or ""),
                "valid_until": _fmt_date(vu) if vu else "",
                "image_url": i.get("image_url") or None,
                "url": i.get("url") or None,
            })
        if kind not in (None, "all"):
            out = [i for i in out if i["type"] == kind]
        return out


nasiya_service = NasiyaService()
