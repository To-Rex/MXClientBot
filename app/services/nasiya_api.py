"""Nasiya (installment) data service.

Every public method has the same shape the real 1C service will have:
    (base_url, login, password, client_id, ...) -> dict | list

Right now the data source is an in-memory MOCK (deterministic per client_id) so
the whole bot flow can be exercised end-to-end.  When the 1C endpoints are
ready, replace the bodies (or set NASIYA_MOCK=0 and fill the real branches) —
handlers do not need to change.
"""
import base64
import hashlib
import logging
import random
from datetime import date, datetime, timezone, timedelta
from typing import Any, Optional

import httpx

from app.config import NASIYA_MOCK, NASIYA_REAL_ENDPOINTS
from app.services.http_client import get_http_client

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────────
# Real 1C HTTP-service helpers  ({base_url}/hs/client_bot/api/<endpoint>)
# Only endpoints listed in NASIYA_REAL_ENDPOINTS are called; on any failure the
# caller falls back to the mock so the bot keeps working.
# ────────────────────────────────────────────────────────────────────────────
API_PREFIX = "/hs/client_bot/api/"


def _use_real(endpoint: str, base_url: str) -> bool:
    return bool(base_url) and endpoint in NASIYA_REAL_ENDPOINTS


async def _real_get(base_url: str, login: str, password: str, endpoint: str, params: dict) -> Optional[Any]:
    """GET {base_url}/hs/client_bot/api/{endpoint}?... with Basic Auth. Returns parsed JSON or None."""
    url = f"{base_url.rstrip('/')}{API_PREFIX}{endpoint}"
    creds = base64.b64encode(f"{login}:{password}".encode()).decode()
    headers = {"Authorization": f"Basic {creds}", "Accept": "application/json"}
    logger.info("📡 1C %s REQUEST %s params=%s", endpoint, url, params)
    try:
        resp = await get_http_client().get(url, params=params, headers=headers)
        logger.info("📡 1C %s RESPONSE %s: %s", endpoint, resp.status_code, resp.text[:500])
        if resp.status_code != 200:
            return None
        return resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.error("❌ 1C %s EXCEPTION %s: %s", endpoint, url, e)
        return None


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
    """Accepts 'YYYY-MM-DD', 'YYYY-MM-DDTHH:MM:SS', 'DD.MM.YYYY', 'YYYYMMDD'."""
    if not v:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%d.%m.%Y", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:len(fmt) + 6] if "%z" in fmt else s, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None

# ────────────────────────────────────────────────────────────────────────────
# Mock state (per process).  client_id -> {"contracts": [...], "payments": [...],
# "requests": [...], "profile": {...}}
# ────────────────────────────────────────────────────────────────────────────
_STATE: dict[str, dict] = {}

_PRODUCT_POOL = [
    ("Samsung Galaxy A55 128GB", 4_200_000),
    ("iPhone 15 128GB", 11_500_000),
    ("Artel 55\" Smart TV", 5_600_000),
    ("Muzlatgich Samsung RB37", 7_900_000),
    ("Kir yuvish mashinasi LG 7kg", 4_800_000),
    ("Konditsioner Midea 12", 4_300_000),
    ("Noutbuk Acer Aspire 5", 6_700_000),
    ("Gaz plita Artel Apetito", 2_900_000),
    ("Changyutgich Samsung", 1_650_000),
    ("Mikroto'lqinli pech Midea", 1_150_000),
]

_STATUSES = ["Фаол мижоз", "VIP мижоз", "Янги мижоз"]

_COMPANY = {
    "name": "MX Nasiya",
    "phone": "+998 71 200 00 00",
    "operator_phone": "+998 90 000 00 00",
    "operator_username": "@mxnasiya_support",
    "email": "info@mxsoft.uz",
    "address": "Тошкент ш., Юнусобод тумани, Амир Темур кўчаси, 108",
    "working_hours": "Ду–Шб 09:00–19:00, Якшанба — дам олиш",
    "branches": [
        {"name": "Марказий филиал", "address": "Тошкент ш., Амир Темур кўчаси, 108", "phone": "+998 71 200 00 01", "hours": "09:00–19:00"},
        {"name": "Чилонзор филиали", "address": "Тошкент ш., Чилонзор, Бунёдкор кўчаси, 12", "phone": "+998 71 200 00 02", "hours": "09:00–20:00"},
        {"name": "Самарқанд филиали", "address": "Самарқанд ш., Регистон кўчаси, 5", "phone": "+998 66 200 00 03", "hours": "09:00–18:00"},
    ],
}

_PROMOTIONS = [
    {
        "id": 1, "type": "promo", "title": "🔥 Ёзги чегирма — 0% устама 6 ойга",
        "text": "Барча маиший техникага 6 ойгача насия 0% устама билан. Акция 31.08 гача амал қилади.",
        "valid_until": "31.08.2026",
    },
    {
        "id": 2, "type": "new", "title": "🆕 Янги товар — iPhone 16 серияси",
        "text": "iPhone 16 / 16 Pro энди насияга. Бошланғич тўлов 20% дан.",
        "valid_until": "",
    },
    {
        "id": 3, "type": "special", "title": "🎁 Махсус таклиф — доимий мижозларга",
        "text": "Иккинчи шартнома учун бошланғич тўлов 10% гача камайтирилади. Батафсил операторлардан сўранг.",
        "valid_until": "30.09.2026",
    },
    {
        "id": 4, "type": "news", "title": "📢 Компания хабари",
        "text": "Чилонзор филиалимиз энди якшанба кунлари ҳам ишлайди: 10:00–18:00.",
        "valid_until": "",
    },
]


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _fmt_money(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ") + " сўм"


def _fmt_date(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def _seed(client_id: str) -> random.Random:
    h = hashlib.md5(str(client_id).encode()).hexdigest()
    return random.Random(int(h[:8], 16))


def _build_client(client_id: str, name: str = "", phone: str = "") -> dict:
    rnd = _seed(client_id)
    today = _today()
    contracts = []
    payments = []
    n_contracts = rnd.choice([1, 2, 2, 3])
    for ci in range(n_contracts):
        months = rnd.choice([3, 6, 6, 9, 12])
        started_months_ago = rnd.randint(0, months - 1) if ci < n_contracts - 1 else rnd.randint(0, 2)
        start = today.replace(day=min(today.day, 28)) - timedelta(days=30 * started_months_ago)
        n_products = rnd.choice([1, 1, 2, 3])
        products = []
        for _ in range(n_products):
            pname, pprice = rnd.choice(_PRODUCT_POOL)
            qty = 1
            products.append({"name": pname, "qty": qty, "price": pprice, "sum": pprice * qty})
        goods_total = sum(p["sum"] for p in products)
        markup = 0.0 if months <= 6 and rnd.random() < 0.4 else 0.15
        total = round(goods_total * (1 + markup), -3)
        initial = round(total * rnd.choice([0.1, 0.2, 0.3]), -3)
        monthly = round((total - initial) / months, -3)
        number = f"NS-{start.year}-{int(str(client_id)[-4:] or 0) * 7 + ci + 11:05d}"
        schedule = []
        for k in range(1, months + 1):
            due = start + timedelta(days=30 * k)
            amount = monthly if k < months else (total - initial - monthly * (months - 1))
            status = "pending"
            paid_date = None
            if due < today:
                if due < today - timedelta(days=45) or rnd.random() < 0.7:
                    status = "paid"
                    paid_date = due - timedelta(days=rnd.randint(0, 5))
                else:
                    status = "overdue"
            schedule.append({
                "n": k, "date": due, "amount": float(amount), "status": status, "paid_date": paid_date,
            })
        contract = {
            "contract_id": int(f"{int(hashlib.md5(number.encode()).hexdigest()[:6], 16)}"),
            "number": number,
            "date": start,
            "products": products,
            "goods_total": float(goods_total),
            "total": float(total),
            "initial_payment": float(initial),
            "months": months,
            "monthly_payment": float(monthly),
            "schedule": schedule,
            "branch": rnd.choice(_COMPANY["branches"])["name"],
        }
        contracts.append(contract)
        payments.append({
            "date": start, "amount": float(initial), "contract_number": number,
            "method": "Нақд (дўконда)", "receipt_no": f"KV-{start.strftime('%y%m%d')}-{rnd.randint(1000, 9999)}",
            "note": "Бошланғич тўлов",
        })
        for s in schedule:
            if s["status"] == "paid":
                payments.append({
                    "date": s["paid_date"], "amount": s["amount"], "contract_number": number,
                    "method": rnd.choice(["Payme", "Click", "Нақд (дўконда)", "Uzum Bank"]),
                    "receipt_no": f"KV-{s['paid_date'].strftime('%y%m%d')}-{rnd.randint(1000, 9999)}",
                    "note": f"{s['n']}-тўлов",
                })
    payments.sort(key=lambda p: p["date"], reverse=True)
    profile = {
        "client_id": str(client_id),
        "name": name or "Мижоз",
        "phone": phone or "",
        "status": rnd.choice(_STATUSES),
        "registered_at": _fmt_date(min(c["date"] for c in contracts)),
        "reminders_enabled": True,
    }
    return {"contracts": contracts, "payments": payments, "requests": [], "profile": profile}


def _client(client_id: str) -> dict:
    cid = str(client_id)
    if cid not in _STATE:
        _STATE[cid] = _build_client(cid)
    return _STATE[cid]


def _contract_view(c: dict) -> dict:
    """Derived numbers for one contract (schedule dicts are not mutated)."""
    today = _today()
    # remaining = what is still unpaid on the schedule (partial payments shrink an
    # installment's amount, so this stays correct after partial online payments)
    remaining = max(0.0, sum(s["amount"] for s in c["schedule"] if s["status"] != "paid"))
    paid = max(0.0, c["total"] - c["initial_payment"] - remaining)
    overdue = [s for s in c["schedule"] if s["status"] == "overdue"]
    pending = [s for s in c["schedule"] if s["status"] != "paid"]
    next_p = pending[0] if pending else None
    if remaining <= 0.5:
        status = "closed"
    elif overdue:
        status = "overdue"
    else:
        status = "active"
    return {
        **{k: v for k, v in c.items() if k != "schedule"},
        "paid": float(paid),
        "remaining_debt": float(remaining),
        "overdue_amount": float(sum(s["amount"] for s in overdue)),
        "overdue_count": len(overdue),
        "paid_count": sum(1 for s in c["schedule"] if s["status"] == "paid"),
        "status": status,
        "next_payment_date": next_p["date"] if next_p else None,
        "next_payment_amount": float(next_p["amount"]) if next_p else 0.0,
        "days_to_next": (next_p["date"] - today).days if next_p else None,
        "end_date": c["schedule"][-1]["date"],
    }


class NasiyaService:
    """Facade used by handlers.  All methods are async to match the real client."""

    fmt_money = staticmethod(_fmt_money)
    fmt_date = staticmethod(_fmt_date)

    @staticmethod
    def is_mock() -> bool:
        return NASIYA_MOCK

    # ── profile / cabinet ────────────────────────────────────────────────
    @staticmethod
    async def set_profile_basics(client_id: str, name: str = "", phone: str = "") -> None:
        """Called after checkNumber so the mock cabinet shows the real name/phone."""
        st = _client(client_id)
        if name:
            st["profile"]["name"] = name
        if phone:
            st["profile"]["phone"] = phone

    @staticmethod
    async def get_cabinet(base_url: str, login: str, password: str, client_id: str) -> Optional[dict]:
        if _use_real("getClientInfo", base_url):
            data = await _real_get(base_url, login, password, "getClientInfo", {"client_id": client_id})
            if isinstance(data, dict) and (data.get("client_id") is not None or data.get("name")):
                return NasiyaService._map_client_info(data, client_id)
            # Connected endpoint must never silently show mock numbers:
            # return None → bot/webapp show "маълумот олинмади", user retries later.
            logger.error("getClientInfo: real 1C javob bermadi (client_id=%s)", client_id)
            return None
        return NasiyaService._mock_cabinet(client_id)

    @staticmethod
    def _map_client_info(d: dict, client_id: str) -> dict:
        """Map 1C getClientInfo JSON → cabinet dict used by bot & webapp (see docs/1C_NASIYA_API.md §2)."""
        nxt_raw = d.get("next_payment")
        nxt = None
        if isinstance(nxt_raw, dict) and nxt_raw.get("date"):
            nd = _parse_date(nxt_raw.get("date"))
            if nd:
                nxt = {
                    "date": nd,
                    "amount": _to_float(nxt_raw.get("amount")),
                    "contract_id": _to_int(nxt_raw.get("contract_id")),
                    "contract_number": str(nxt_raw.get("contract_number") or ""),
                    "status": "overdue" if nd < _today() else "pending",
                }
        reg = _parse_date(d.get("registered_at"))
        local = _client(client_id)["profile"]  # keeps locally toggled reminders until setReminders is wired
        # remember real name/phone so other (still-mock) screens show them too
        if d.get("name"):
            local["name"] = str(d["name"])
        if d.get("phone"):
            local["phone"] = str(d["phone"])
        return {
            "client_id": str(d.get("client_id") or client_id),
            "name": str(d.get("name") or local.get("name") or "Мижоз"),
            "phone": str(d.get("phone") or local.get("phone") or ""),
            "status": str(d.get("status") or "Мижоз"),
            "registered_at": _fmt_date(reg) if reg else str(d.get("registered_at") or ""),
            "reminders_enabled": bool(local.get("reminders_enabled", True)),
            "active_contracts": _to_int(d.get("active_contracts")),
            "total_contracts": _to_int(d.get("total_contracts")),
            "total_nasiya": _to_float(d.get("total_nasiya")),
            "total_paid": _to_float(d.get("total_paid")),
            "remaining_debt": _to_float(d.get("remaining_debt")),
            "overdue_amount": _to_float(d.get("overdue_amount")),
            "overdue_count": _to_int(d.get("overdue_count")),
            "next_payment": nxt,
            "source": "1c",
        }

    @staticmethod
    def _mock_cabinet(client_id: str) -> dict:
        st = _client(client_id)
        views = [_contract_view(c) for c in st["contracts"]]
        active = [v for v in views if v["status"] != "closed"]
        return {
            **st["profile"],
            "active_contracts": len(active),
            "total_contracts": len(views),
            "total_nasiya": sum(v["total"] for v in views),
            "total_paid": sum(v["paid"] + v["initial_payment"] for v in views),
            "remaining_debt": sum(v["remaining_debt"] for v in views),
            "overdue_amount": sum(v["overdue_amount"] for v in views),
            "overdue_count": sum(v["overdue_count"] for v in views),
            "source": "mock",
        }

    @staticmethod
    async def set_reminders(client_id: str, enabled: bool) -> None:
        _client(client_id)["profile"]["reminders_enabled"] = enabled

    # ── contracts ────────────────────────────────────────────────────────
    @staticmethod
    async def get_contracts(base_url: str, login: str, password: str, client_id: str) -> list[dict]:
        return [_contract_view(c) for c in _client(client_id)["contracts"]]

    @staticmethod
    async def get_contract(base_url: str, login: str, password: str, client_id: str, contract_id: int) -> Optional[dict]:
        for c in _client(client_id)["contracts"]:
            if c["contract_id"] == contract_id:
                v = _contract_view(c)
                v["schedule"] = [dict(s) for s in c["schedule"]]
                return v
        return None

    # ── schedule ─────────────────────────────────────────────────────────
    @staticmethod
    async def get_schedule(
        base_url: str, login: str, password: str, client_id: str,
        status: str = "all", contract_id: Optional[int] = None,
    ) -> list[dict]:
        rows = []
        for c in _client(client_id)["contracts"]:
            if contract_id and c["contract_id"] != contract_id:
                continue
            for s in c["schedule"]:
                if status != "all" and s["status"] != status:
                    continue
                rows.append({**s, "contract_number": c["number"], "contract_id": c["contract_id"]})
        rows.sort(key=lambda r: r["date"])
        return rows

    @staticmethod
    async def get_next_payment(base_url: str, login: str, password: str, client_id: str) -> Optional[dict]:
        rows = await NasiyaService.get_schedule(base_url, login, password, client_id, status="all")
        pending = [r for r in rows if r["status"] != "paid"]
        if not pending:
            return None
        pending.sort(key=lambda r: (r["status"] != "overdue", r["date"]))
        return pending[0]

    # ── payments ─────────────────────────────────────────────────────────
    @staticmethod
    async def get_payments(base_url: str, login: str, password: str, client_id: str) -> list[dict]:
        return list(_client(client_id)["payments"])

    @staticmethod
    async def make_payment(
        base_url: str, login: str, password: str, client_id: str,
        contract_id: int, amount: float, method: str = "Онлайн (бот)",
    ) -> Optional[dict]:
        """Apply a payment: closes oldest unpaid installments first (partial allowed).

        The mock mutates state so remaining debt updates immediately
        (TZ 5: "Қолган қарзни автоматик янгилаш").
        """
        st = _client(client_id)
        contract = next((c for c in st["contracts"] if c["contract_id"] == contract_id), None)
        if not contract or amount <= 0:
            return None
        view = _contract_view(contract)
        if amount > view["remaining_debt"] + 0.5:
            amount = view["remaining_debt"]
        left = amount
        today = _today()
        for s in contract["schedule"]:
            if left <= 0.5:
                break
            if s["status"] == "paid":
                continue
            if left + 0.5 >= s["amount"]:
                left -= s["amount"]
                s["status"] = "paid"
                s["paid_date"] = today
            else:
                s["amount"] = round(s["amount"] - left, 2)
                left = 0
        receipt_no = f"KV-{today.strftime('%y%m%d')}-{random.randint(1000, 9999)}"
        payment = {
            "date": today, "amount": float(amount), "contract_number": contract["number"],
            "method": method, "receipt_no": receipt_no, "note": f"Онлайн тўлов ({method}, Telegram)",
        }
        st["payments"].insert(0, payment)
        after = _contract_view(contract)
        logger.info("💳 mock payment client=%s contract=%s amount=%s", client_id, contract["number"], amount)
        return {
            "success": True,
            "receipt_no": receipt_no,
            "amount": float(amount),
            "date": today,
            "contract_number": contract["number"],
            "remaining_debt": after["remaining_debt"],
            "next_payment_date": after["next_payment_date"],
            "next_payment_amount": after["next_payment_amount"],
            "closed": after["status"] == "closed",
        }

    # ── purchases ────────────────────────────────────────────────────────
    @staticmethod
    async def get_purchases(base_url: str, login: str, password: str, client_id: str) -> list[dict]:
        rows = []
        for c in _client(client_id)["contracts"]:
            rows.append({
                "date": c["date"], "contract_number": c["number"], "contract_id": c["contract_id"],
                "products": c["products"], "total": c["goods_total"], "branch": c["branch"],
            })
        rows.sort(key=lambda r: r["date"], reverse=True)
        return rows

    # ── support ──────────────────────────────────────────────────────────
    @staticmethod
    async def get_company_info(base_url: str = "", login: str = "", password: str = "") -> dict:
        return _COMPANY

    @staticmethod
    async def create_request(
        base_url: str, login: str, password: str, client_id: str,
        kind: str, text: str, telegram_id: int = 0,
    ) -> Optional[dict]:
        st = _client(client_id)
        req_id = 1000 + len(st["requests"]) + 1
        st["requests"].append({
            "id": req_id, "kind": kind, "text": text, "telegram_id": telegram_id,
            "created_at": datetime.now(timezone.utc),
        })
        logger.info("📨 mock request client=%s kind=%s text=%r", client_id, kind, text[:80])
        return {"success": True, "id": req_id}

    # ── promotions / news ────────────────────────────────────────────────
    @staticmethod
    async def get_promotions(base_url: str = "", login: str = "", password: str = "") -> list[dict]:
        return list(_PROMOTIONS)


nasiya_service = NasiyaService()
