# MX Nasiya — 1C HTTP-servis API spetsifikatsiyasi

Telegram bot va WebApp (shaxsiy kabinet) uchun 1C:Enterprise tomonida yaratilishi kerak bo'lgan HTTP-servis. Hozir bot mock ma'lumotlar bilan ishlaydi (`app/services/nasiya_api.py`); shu hujjatdagi endpointlar tayyor bo'lgach, o'sha servis metodlari real so'rovlarga almashtiriladi — bot va WebApp kodi o'zgarmaydi.

Bugungi kunda tayyor: **`checkNumber`** (1-bo'lim). Qolganlari — yaratilishi kerak.

---

## 0. Umumiy qoidalar

| Narsa | Qiymat |
|---|---|
| Bazaviy URL | `{base_url}/hs/client_bot/api/` — masalan `http://nasiya.mxsoft.uz/demo_nasiya/hs/client_bot/api/` (`base_url` har bir bot uchun admin panelda saqlanadi) |
| Autentifikatsiya | **HTTP Basic Auth** — panelda kiritilgan `1C login` / `1C password` (masalan `bot_api:123` → `Authorization: Basic Ym90X2FwaToxMjM=`) |
| Format | JSON, `Content-Type: application/json; charset=utf-8` (so'rov ham, javob ham) |
| Sanalar | `YYYY-MM-DD` (masalan `2026-08-17`); vaqt kerak bo'lsa `YYYY-MM-DDTHH:MM:SS` |
| Summalar | son (float), **so'mda**, tiyinsiz: `644000` yoki `644000.0` |
| Identifikatorlar | `client_id`, `contract_id`, `payment_id` — butun son (1C ichki kod). `contract_number` — inson o'qiydigan raqam (`"NS-2026-00123"`) |
| Bo'sh ro'yxat | `[]` (null emas) |
| Muvaffaqiyat | HTTP `200`, javob to'g'ridan-to'g'ri obyekt/ro'yxat |
| Xato | HTTP `400/401/404/500` + `{"error": {"code": "CLIENT_NOT_FOUND", "message": "Мижоз топилмади"}}` |

### Xato kodlari
| HTTP | `error.code` | Qachon |
|---|---|---|
| 401 | `UNAUTHORIZED` | Basic Auth noto'g'ri |
| 404 | `CLIENT_NOT_FOUND` | `client_id` topilmadi |
| 404 | `CONTRACT_NOT_FOUND` | shartnoma topilmadi yoki bu mijozniki emas |
| 400 | `VALIDATION_ERROR` | parametr yo'q/noto'g'ri (`message` da qaysi) |
| 400 | `PAYMENT_REJECTED` | to'lov qabul qilinmadi (summa noto'g'ri, shartnoma yopilgan…) |
| 500 | `INTERNAL_ERROR` | 1C ichki xatosi |

### Enum qiymatlar
| Maydon | Qiymatlar |
|---|---|
| Shartnoma `status` | `active` — faol · `overdue` — kechikkan to'lovi bor · `closed` — to'liq yopilgan |
| Grafik qatori `status` | `paid` — to'langan · `pending` — kutilmoqda · `overdue` — muddati o'tgan |
| To'lov `method` | `payme` · `click` · `paynet` · `cash` (do'konda naqd) · `card` · `other` |
| Murojaat `kind` | `request` — murojaat/shikoyat · `question` — savol/taklif |
| Aksiya `type` | `promo` — aksiya · `new` — yangi tovar · `special` — maxsus taklif · `news` — kompaniya xabari |

---

## 1. Mijozni aniqlash — `POST checkNumber` ✅ tayyor

Telefon raqami bo'yicha mijozni topadi va Telegram `chat_id` ni bog'laydi.

**So'rov**
```http
POST /hs/client_bot/api/checkNumber
Authorization: Basic ...
Content-Type: application/json

{ "phoneNumber": 998995340313, "chatID": "66540046" }
```
| Maydon | Tip | Izoh |
|---|---|---|
| `phoneNumber` | number | `+` va bo'shliqsiz, `998…` |
| `chatID` | string | Telegram chat/user id |

**Javob 200**
```json
{ "id": 9454, "name": "XAYDAROV DILSHODJON test" }
```
Topilmasa: `404 CLIENT_NOT_FOUND` (yoki bo'sh `{}` — bot ikkalasini ham "topilmadi" deb qabul qiladi).

---

## 2. Shaxsiy kabinet — `GET getClientInfo`

Kabinet sahifasi va bosh sahifadagi umumiy ko'rsatkichlar.

```http
GET /hs/client_bot/api/getClientInfo?client_id=9454
```
**Javob 200**
```json
{
  "client_id": 9454,
  "name": "XAYDAROV DILSHODJON",
  "phone": "998995340313",
  "status": "Фаол мижоз",
  "registered_at": "2025-03-14",
  "active_contracts": 2,
  "total_contracts": 3,
  "total_nasiya": 15520000,
  "total_paid": 8300000,
  "remaining_debt": 7220000,
  "overdue_amount": 644000,
  "overdue_count": 1,
  "next_payment": { "date": "2026-08-20", "amount": 644000, "contract_number": "NS-2026-00123", "contract_id": 5012 },
  "reminders_enabled": true
}
```
| Maydon | Izoh |
|---|---|
| `status` | matn (1C dagi mijoz statusi/kategoriya) |
| `total_nasiya` | barcha shartnomalar umumiy summasi (ustama bilan) |
| `total_paid` | boshlang'ich to'lovlar + to'langan bo'lib-to'lashlar |
| `remaining_debt` | jami qolgan qarz |
| `overdue_amount` / `overdue_count` | muddati o'tgan to'lovlar summasi / soni |
| `next_payment` | eng yaqin to'lanmagan to'lov (kechikkan bo'lsa — u); yo'q bo'lsa `null` |
| `reminders_enabled` | eslatmalar yoqilganmi (8-bo'lim) |

---

## 3. Shartnomalar — `GET getContracts` va `GET getContract`

### 3.1 Ro'yxat
```http
GET /hs/client_bot/api/getContracts?client_id=9454
```
**Javob 200** — ro'yxat, har biri:
```json
[
  {
    "contract_id": 5012,
    "contract_number": "NS-2026-00123",
    "date": "2026-06-18",
    "branch": "Марказий филиал",
    "status": "active",
    "products_short": "Kir yuvish mashinasi LG 7kg, Changyutgich Samsung",
    "goods_total": 6450000,
    "total": 7417000,
    "initial_payment": 1483000,
    "months": 6,
    "monthly_payment": 989000,
    "paid": 2967000,
    "paid_count": 3,
    "remaining_debt": 2967000,
    "overdue_amount": 0,
    "overdue_count": 0,
    "next_payment_date": "2026-09-16",
    "next_payment_amount": 989000,
    "end_date": "2026-12-15"
  }
]
```
| Maydon | Izoh |
|---|---|
| `goods_total` | tovarlar summasi (ustamasiz) |
| `total` | nasiya summasi (ustama bilan) — mijoz to'laydigan jami |
| `initial_payment` | boshlang'ich to'lov |
| `months` / `monthly_payment` | muddat (oy) / oylik to'lov |
| `paid` / `paid_count` | to'langan bo'lib-to'lashlar summasi / soni (boshlang'ich to'lovsiz) |
| `remaining_debt` | qolgan qarz = to'lanmagan grafik qatorlari yig'indisi |
| `next_payment_*` | keyingi to'lanmagan qator; yopilgan bo'lsa `null` / `0` |
| `end_date` | grafikdagi oxirgi to'lov sanasi |

### 3.2 Bitta shartnoma (tovarlar + grafik bilan)
```http
GET /hs/client_bot/api/getContract?client_id=9454&contract_id=5012
```
**Javob 200** — 3.1 dagi obyekt + `products` va `schedule`:
```json
{
  "...": "3.1 dagi barcha maydonlar",
  "products": [
    { "product_id": 771, "name": "Kir yuvish mashinasi LG 7kg", "qty": 1, "price": 4800000, "sum": 4800000 },
    { "product_id": 802, "name": "Changyutgich Samsung", "qty": 1, "price": 1650000, "sum": 1650000 }
  ],
  "schedule": [
    { "n": 1, "date": "2026-07-18", "amount": 989000, "status": "paid",    "paid_date": "2026-07-16", "paid_amount": 989000 },
    { "n": 2, "date": "2026-08-17", "amount": 989000, "status": "overdue", "paid_date": null, "paid_amount": 0 },
    { "n": 3, "date": "2026-09-16", "amount": 989000, "status": "pending", "paid_date": null, "paid_amount": 0 }
  ]
}
```
Grafik qatori: `n` — tartib raqami; `amount` — **qolgan** to'lanishi kerak summa (qisman to'langan bo'lsa kamaygan); `paid_amount` — shu qator bo'yicha to'langan.

---

## 4. To'lov grafigi — `GET getSchedule`

Barcha shartnomalar (yoki bittasi) bo'yicha grafik, filtr bilan.

```http
GET /hs/client_bot/api/getSchedule?client_id=9454
GET /hs/client_bot/api/getSchedule?client_id=9454&contract_id=5012&status=overdue
```
| Parametr | Majburiy | Izoh |
|---|---|---|
| `client_id` | ha | |
| `contract_id` | yo'q | berilmasa — barcha shartnomalar |
| `status` | yo'q | `paid` / `pending` / `overdue`; berilmasa — hammasi |

**Javob 200** — sana bo'yicha o'sish tartibida:
```json
[
  { "contract_id": 5012, "contract_number": "NS-2026-00123", "n": 2, "date": "2026-08-17", "amount": 989000, "status": "overdue", "paid_date": null },
  { "contract_id": 5013, "contract_number": "NS-2026-00124", "n": 1, "date": "2026-08-20", "amount": 644000, "status": "pending", "paid_date": null }
]
```

---

## 5. To'lovlar

### 5.1 Tarix — `GET getPayments`
```http
GET /hs/client_bot/api/getPayments?client_id=9454
```
**Javob 200** — yangi → eski tartibda:
```json
[
  { "payment_id": 90011, "date": "2026-08-17", "amount": 300000, "contract_id": 5012, "contract_number": "NS-2026-00123",
    "method": "click", "receipt_no": "KV-260817-2058", "note": "Онлайн тўлов (Telegram)", "transaction_id": "clk_8f3a…" },
  { "payment_id": 88120, "date": "2026-06-18", "amount": 1483000, "contract_id": 5012, "contract_number": "NS-2026-00123",
    "method": "cash", "receipt_no": "KV-260618-1042", "note": "Бошланғич тўлов", "transaction_id": null }
]
```

### 5.2 Onlayn to'lovni boshlash — `POST createPayment`
Bot/WebApp mijoz summa va usulni tanlagach chaqiradi. 1C **kutilayotgan** to'lov hujjatini yaratadi va `payment_id` qaytaradi. (Payme/Click/Paynet checkout havolasi backend/merchant tomonida shu `payment_id` bilan hosil qilinadi.)

```http
POST /hs/client_bot/api/createPayment
{
  "client_id": 9454,
  "contract_id": 5012,
  "amount": 300000,
  "method": "click",
  "chat_id": "66540046",
  "source": "telegram_bot"          // yoki "webapp"
}
```
**Javob 200**
```json
{
  "payment_id": 90011,
  "status": "pending",
  "amount": 300000,
  "contract_number": "NS-2026-00123",
  "remaining_after": 2667000,
  "expires_at": "2026-08-17T15:30:00"
}
```
Xatolar: `PAYMENT_REJECTED` (shartnoma yopilgan, summa ≤ 0, summa qarzdan katta — 1C qarzgacha kamaytirib qaytarishi ham mumkin: javobdagi `amount` haqiqiy).

### 5.3 To'lovni tasdiqlash — `POST confirmPayment`
Provayderdan (Payme/Click/Paynet callback) muvaffaqiyat kelgach backend chaqiradi. 1C to'lovni o'tkazadi, grafikni yopadi (eng eski to'lanmagan qatordan boshlab, qisman ham bo'lishi mumkin) va kvitansiya qaytaradi.

```http
POST /hs/client_bot/api/confirmPayment
{ "payment_id": 90011, "transaction_id": "clk_8f3a…", "paid_at": "2026-08-17T14:52:10", "amount": 300000 }
```
**Javob 200 (kvitansiya)**
```json
{
  "success": true,
  "payment_id": 90011,
  "receipt_no": "KV-260817-2058",
  "date": "2026-08-17",
  "amount": 300000,
  "method": "click",
  "contract_id": 5012,
  "contract_number": "NS-2026-00123",
  "remaining_debt": 2667000,
  "next_payment_date": "2026-09-16",
  "next_payment_amount": 689000,
  "closed": false
}
```
`closed: true` bo'lsa shartnoma to'liq yopildi. Bekor qilish uchun: `POST cancelPayment { "payment_id": 90011, "reason": "user_cancel" }` → `{ "success": true }`.

> **Demo rejimda** bot `createPayment` + `confirmPayment` ni ketma-ket o'zi chaqiradi ("Тўладим — тасдиқлаш" tugmasi). Real integratsiyada tasdiqlash provayder callback'idan keladi.

---

## 6. Xaridlar tarixi — `GET getPurchases`
```http
GET /hs/client_bot/api/getPurchases?client_id=9454
```
**Javob 200** — yangi → eski:
```json
[
  { "purchase_id": 3301, "date": "2026-06-18", "contract_id": 5012, "contract_number": "NS-2026-00123", "branch": "Марказий филиал",
    "total": 6450000,
    "products": [ { "product_id": 771, "name": "Kir yuvish mashinasi LG 7kg", "qty": 1, "price": 4800000, "sum": 4800000 } ] }
]
```

---

## 7. Mijozga xizmat

### 7.1 Kompaniya ma'lumotlari — `GET getCompanyInfo`
```http
GET /hs/client_bot/api/getCompanyInfo
```
```json
{
  "name": "MX Nasiya",
  "phone": "+998 71 200 00 00",
  "operator_phone": "+998 90 000 00 00",
  "operator_username": "@mxnasiya_support",
  "email": "info@mxsoft.uz",
  "address": "Тошкент ш., Юнусобод тумани, Амир Темур кўчаси, 108",
  "working_hours": "Ду–Шб 09:00–19:00, Якшанба — дам олиш",
  "branches": [
    { "branch_id": 1, "name": "Марказий филиал", "address": "Тошкент ш., Амир Темур кўчаси, 108", "phone": "+998 71 200 00 01", "hours": "09:00–19:00", "lat": 41.3275, "lon": 69.2817 }
  ]
}
```
`lat`/`lon` ixtiyoriy (bo'lsa botda xarita tugmasi qo'shiladi).

### 7.2 Murojaat / savol — `POST createRequest`
```http
POST /hs/client_bot/api/createRequest
{ "client_id": 9454, "chat_id": "66540046", "kind": "request", "text": "Тўлов санасини кўчириб беринг", "source": "telegram_bot" }
```
**Javob 200**: `{ "request_id": 1001, "status": "new", "created_at": "2026-08-17T14:10:00" }`

---

## 8. Eslatmalar

Bot eslatmalarni **o'zi** yuboradi (grafikdan: 3 kun qolganda, to'lov kuni, kechikkanda) — bu uchun 4-bo'lim yetarli. 1C tomonidan faqat sozlama saqlash kerak:

### 8.1 `POST setReminders`
```http
POST /hs/client_bot/api/setReminders
{ "client_id": 9454, "chat_id": "66540046", "enabled": false }
```
→ `{ "success": true, "enabled": false }`  (holat `getClientInfo.reminders_enabled` da qaytadi)

### 8.2 1C → bot voqealari (ixtiyoriy, kelishiladi)
"Yangi shartnoma rasmiylashtirildi" va "to'lov qabul qilindi (do'konda/naqd)" xabarlari uchun 1C bot serveriga push yuboradi. Bot tomonida endpoint **keyingi bosqichda** yaratiladi:
```http
POST {BOT_SERVER}/api/1c/events        (Basic Auth — bot tomonidan beriladi)
{ "event": "contract_created" | "payment_received", "client_id": 9454, "chat_id": "66540046",
  "contract_number": "NS-2026-00125", "amount": 1483000, "date": "2026-08-17" }
```
→ `{ "success": true }`

---

## 9. Aksiyalar va xabarlar — `GET getPromotions`
```http
GET /hs/client_bot/api/getPromotions
GET /hs/client_bot/api/getPromotions?type=promo
```
```json
[
  { "id": 1, "type": "promo", "title": "🔥 Ёзги чегирма — 0% устама 6 ойга",
    "text": "Барча маиший техникага 6 ойгача насия 0% устама билан.",
    "valid_until": "2026-08-31", "image_url": "https://…/promo1.jpg", "url": "https://…" }
]
```
`image_url`, `url`, `valid_until` — ixtiyoriy (`null` bo'lishi mumkin).

---

## 10. Endpoint ↔ bot/WebApp mosligi

| 1C endpoint | `NasiyaService` metodi | Qayerda ishlatiladi |
|---|---|---|
| `checkNumber` | `APIService.register_device` | Login (bot kontakt, WebApp ro'yxatdan o'tish) |
| `getClientInfo` | `get_cabinet`, `get_next_payment` | 👤 Кабинет, bosh ekran, eslatmalar |
| `getContracts` | `get_contracts` | 💳 Қарзим, shartnoma tanlash (график/тўлов) |
| `getContract` | `get_contract` | Shartnoma tafsiloti |
| `getSchedule` | `get_schedule` | 📅 Графигим, eslatmalar |
| `getPayments` | `get_payments` | 🧾 Тўловлар |
| `createPayment` + `confirmPayment` | `make_payment` | 💰 Тўлов қилиш (Payme/Click/Paynet) |
| `getPurchases` | `get_purchases` | 🛍 Харидлар |
| `getCompanyInfo` | `get_company_info` | 📞 Ёрдам |
| `createRequest` | `create_request` | Мурожаат / Савол-таклиф |
| `setReminders` | `set_reminders` | Кабинет → 🔔 |
| `getPromotions` | `get_promotions` | 🎁 Акциялар |

---

## 11. 1C jamoasi uchun tekshiruv ro'yxati

- [ ] Barcha endpointlar `hs/client_bot/api/` ostida, Basic Auth bilan
- [ ] Javoblar UTF-8 JSON, sanalar `YYYY-MM-DD`, summalar son (string emas)
- [ ] `client_id` boshqa mijozning shartnomasini so'rasa — `404 CONTRACT_NOT_FOUND`
- [ ] `getContracts.remaining_debt` = shu shartnoma `schedule` dagi to'lanmagan `amount` lar yig'indisi
- [ ] `getClientInfo.remaining_debt` = barcha shartnomalar `remaining_debt` yig'indisi
- [ ] `confirmPayment` idempotent: bir xil `payment_id` ikki marta kelsa — ikkinchi marta o'sha kvitansiya, ikkilanmasin
- [ ] Qisman to'lov qatorning `amount` ini kamaytiradi, `status` `pending/overdue` da qoladi
- [ ] Bo'sh natija — `[]`, xato — `{"error": {...}}` + tegishli HTTP kod

Savollar: bot/backend jamoasi — `torex.amaki@gmail.com`.
