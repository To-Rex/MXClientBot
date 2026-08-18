# MX Nasiya — 1C HTTP-servis API spetsifikatsiyasi

Telegram bot va WebApp (mijozning nasiya bo'yicha shaxsiy kabineti) uchun 1C:Enterprise tomonida yaratilishi kerak bo'lgan HTTP-servis.

Hozir bot **mock** ma'lumotlar bilan ishlaydi (`app/services/nasiya_api.py`). Shu hujjatdagi endpointlar tayyor bo'lgach, o'sha servis metodlari real so'rovlarga almashtiriladi — bot va WebApp kodi o'zgarmaydi.

Bugungi kunda tayyor va botga ulangan: **`checkNumber`** (1-bo'lim), **`getClientInfo`** (2-bo'lim). Qolganlari — yaratilishi kerak.

> Ulash tartibi: `.env` dagi `NASIYA_REAL_ENDPOINTS` ro'yxatiga endpoint nomi qo'shiladi (masalan `getClientInfo,getContracts`). Ro'yxatdagilar real 1C dan olinadi, qolganlari mock; real API xato bersa bot avtomatik mock'ga qaytadi.

---

## 0. Umumiy qoidalar

### 0.1 Ulanish

| Narsa | Qiymat |
|---|---|
| Bazaviy URL | `{base_url}/hs/client_bot/api/` — masalan `http://nasiya.mxsoft.uz/demo_nasiya/hs/client_bot/api/`. `base_url` har bir bot uchun admin panelda saqlanadi. |
| Autentifikatsiya | **HTTP Basic Auth** — panelda kiritilgan `1C login` / `1C password`. Masalan `bot_api:123` → sarlavha `Authorization: Basic Ym90X2FwaToxMjM=` |
| Format | JSON, `Content-Type: application/json; charset=utf-8` — so'rov tanasi ham, javob ham |
| Kodlash | UTF-8 (kirill matnlar to'g'ri ko'rinishi uchun) |
| Timeout | Bot 30 soniya kutadi; javob shundan tez bo'lishi kerak |

### 0.2 Ma'lumot tiplari

| Tip | Format | Misol |
|---|---|---|
| `date` | `YYYY-MM-DD` | `"2026-08-17"` |
| `datetime` | `YYYY-MM-DDTHH:MM:SS` (Toshkent vaqti) | `"2026-08-17T14:52:10"` |
| `money` | son (float yoki int), **so'mda**, tiyinsiz, matn EMAS | `644000` yoki `644000.0` |
| `id` | butun son (1C ichki kod) | `9454` |
| `string` | UTF-8 matn | `"NS-2026-00123"` |
| `bool` | `true` / `false` | |
| bo'sh qiymat | `null` (majburiy bo'lmagan maydonlar uchun) | |
| bo'sh ro'yxat | `[]` (`null` emas) | |

### 0.3 Javob va xato formati

- Muvaffaqiyat: HTTP **200**, javob to'g'ridan-to'g'ri obyekt yoki ro'yxat (o'ramsiz).
- Xato: HTTP **4xx/5xx** + tana:

```json
{ "error": { "code": "CLIENT_NOT_FOUND", "message": "Мижоз топилмади" } }
```

| Kalit | Tip | Izoh |
|---|---|---|
| `error.code` | string | mashina o'qiydigan kod (quyidagi jadval) — bot shu bo'yicha qaror qiladi |
| `error.message` | string | inson o'qiydigan izoh (bot uni foydalanuvchiga ko'rsatishi mumkin) |

| HTTP | `error.code` | Qachon |
|---|---|---|
| 401 | `UNAUTHORIZED` | Basic Auth noto'g'ri |
| 400 | `VALIDATION_ERROR` | parametr yo'q yoki noto'g'ri (`message` da qaysi) |
| 404 | `CLIENT_NOT_FOUND` | `client_id` topilmadi |
| 404 | `CONTRACT_NOT_FOUND` | shartnoma topilmadi yoki bu mijozniki emas |
| 404 | `PAYMENT_NOT_FOUND` | `payment_id` topilmadi |
| 400 | `PAYMENT_REJECTED` | to'lov qabul qilinmadi (shartnoma yopilgan, summa ≤ 0, muddati o'tgan `payment_id`…) |
| 500 | `INTERNAL_ERROR` | 1C ichki xatosi |

### 0.4 Enum qiymatlar (aynan shu matnlar, kichik harf, lotin)

| Maydon | Qiymat | Ma'nosi |
|---|---|---|
| Shartnoma `status` | `active` | faol, kechikkan to'lovi yo'q |
| | `overdue` | kamida bitta muddati o'tgan to'lovi bor |
| | `closed` | to'liq yopilgan, qarz 0 |
| Grafik qatori `status` | `paid` | to'liq to'langan |
| | `pending` | muddati hali kelmagan (yoki bugun) |
| | `overdue` | muddati o'tgan, to'lanmagan |
| To'lov `method` | `payme` · `click` · `paynet` | onlayn provayderlar |
| | `cash` | do'konda naqd |
| | `card` | terminal/karta |
| | `other` | boshqa |
| To'lov `status` | `pending` · `paid` · `cancelled` · `expired` | kutilmoqda · o'tkazildi · bekor · muddati o'tdi |
| Murojaat `kind` | `request` | murojaat / shikoyat |
| | `question` | savol / taklif |
| Aksiya `type` | `promo` · `new` · `special` · `news` | aksiya · yangi tovar · maxsus taklif · kompaniya xabari |
| `source` | `telegram_bot` · `webapp` | so'rov qayerdan kelgani |

---

## 1. Mijozni aniqlash — `POST checkNumber` ✅ tayyor

Telefon raqami bo'yicha mijozni topadi va Telegram `chat_id` ni unga bog'laydi. Bot va WebApp login qismida chaqiriladi.

### So'rov
```http
POST /hs/client_bot/api/checkNumber
Authorization: Basic Ym90X2FwaToxMjM=
Content-Type: application/json

{ "phoneNumber": 998995340313, "chatID": "66540046" }
```

| Kalit | Tip | Majburiy | Izoh |
|---|---|---|---|
| `phoneNumber` | number | ha | `+`, bo'shliq va chiziqchasiz, `998` bilan boshlanadi |
| `chatID` | string | ha | Telegram chat/user id — 1C mijoz kartochkasiga yozib qo'yadi (keyin xabar yuborish uchun) |

### Javob 200
```json
{ "id": 9454, "name": "XAYDAROV DILSHODJON test" }
```

| Kalit | Tip | Izoh |
|---|---|---|
| `id` | id | mijozning 1C dagi kodi — bot uni `client_id` sifatida saqlaydi va **keyingi barcha so'rovlarda** yuboradi |
| `name` | string | mijoz F.I.O — salomlashishda va kabinetda ko'rsatiladi |

Topilmasa: `404` + `CLIENT_NOT_FOUND` (yoki bo'sh `{}` — bot ikkalasini ham "topilmadi" deb qabul qiladi).

---

## 2. Shaxsiy kabinet — `GET getClientInfo` ✅ tayyor, ulangan

Kabinet sahifasi va bosh ekrandagi umumiy ko'rsatkichlar. Bir so'rovda mijoz haqida hamma jamlangan raqam qaytadi.

### So'rov
```http
GET /hs/client_bot/api/getClientInfo?client_id=9454
```

| Parametr | Tip | Majburiy | Izoh |
|---|---|---|---|
| `client_id` | id | ha | `checkNumber` qaytargan `id` |

### Javob 200
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
  "next_payment": {
    "date": "2026-08-20",
    "amount": 644000,
    "contract_id": 5012,
    "contract_number": "NS-2026-00123"
  },
  "reminders_enabled": true
}
```

| Kalit | Tip | Izoh |
|---|---|---|
| `client_id` | id | mijoz kodi (so'rovdagi bilan bir xil) |
| `name` | string | F.I.O — kabinetda «Ф.И.О» qatori |
| `phone` | string | telefon, `998…` — kabinetda «Телефон» qatori |
| `status` | string | mijoz statusi/kategoriyasi matni (masalan «Фаол мижоз», «VIP», «Янги мижоз») — kabinetda belgi sifatida |
| `registered_at` | date | mijoz bo'lgan sana (birinchi shartnoma yoki ro'yxatga olingan sana) |
| `active_contracts` | int | hozir yopilmagan (`active` + `overdue`) shartnomalar soni |
| `total_contracts` | int | jami shartnomalar soni (yopilganlar bilan) |
| `total_nasiya` | money | barcha shartnomalar umumiy nasiya summasi (ustama bilan) — «Умумий насия» |
| `total_paid` | money | jami to'langan: boshlang'ich to'lovlar + to'langan bo'lib-to'lashlar — «Тўланган» |
| `remaining_debt` | money | jami qolgan qarz = barcha shartnomalar `remaining_debt` yig'indisi — kabinetdagi katta raqam |
| `overdue_amount` | money | muddati o'tgan to'lovlar yig'indisi (0 bo'lsa hammasi joyida) |
| `overdue_count` | int | muddati o'tgan to'lovlar soni |
| `next_payment` | object \| null | eng yaqin to'lanmagan to'lov (kechikkani bo'lsa — birinchi kechikkan). Hech narsa qolmagan bo'lsa `null` |
| `next_payment.date` | date | to'lov sanasi |
| `next_payment.amount` | money | to'lov summasi (qisman to'langan bo'lsa qolgani) |
| `next_payment.contract_id` | id | qaysi shartnoma |
| `next_payment.contract_number` | string | shartnoma raqami (ko'rsatish uchun) |
| `reminders_enabled` | bool | eslatmalar yoqilganmi (`setReminders` bilan o'zgaradi) |

---

## 3. Shartnomalar

### 3.1 Ro'yxat — `GET getContracts`

«💳 Қарзим», grafik va to'lovda shartnoma tanlash uchun. Har bir shartnoma bo'yicha jamlangan raqamlar (tovarlar va grafiksiz — ular 3.2 da).

#### So'rov
```http
GET /hs/client_bot/api/getContracts?client_id=9454
```

| Parametr | Tip | Majburiy | Izoh |
|---|---|---|---|
| `client_id` | id | ha | |

#### Javob 200 — ro'yxat (yangi → eski)
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

| Kalit | Tip | Izoh |
|---|---|---|
| `contract_id` | id | shartnomaning 1C kodi — boshqa so'rovlarda ishlatiladi |
| `contract_number` | string | inson o'qiydigan raqam — hamma joyda ko'rsatiladi |
| `date` | date | shartnoma tuzilgan sana |
| `branch` | string | qaysi filialda rasmiylashtirilgan |
| `status` | enum | `active` / `overdue` / `closed` (0.4-bo'lim) — rang va belgi shunga qarab |
| `products_short` | string | tovarlar nomi vergul bilan — ro'yxatda bir qatorda ko'rsatish uchun |
| `goods_total` | money | tovarlar summasi (ustamasiz) |
| `total` | money | **nasiya summasi** — mijoz jami to'laydigan (ustama bilan) |
| `initial_payment` | money | boshlang'ich to'lov |
| `months` | int | muddat, oy |
| `monthly_payment` | money | oylik to'lov (grafikdagi oddiy qator summasi) |
| `paid` | money | to'langan bo'lib-to'lashlar yig'indisi (**boshlang'ich to'lovsiz**) |
| `paid_count` | int | to'liq to'langan grafik qatorlari soni (`paid_count`/`months` ko'rinishida chiqadi) |
| `remaining_debt` | money | qolgan qarz = grafikdagi to'lanmagan qatorlar `amount` yig'indisi |
| `overdue_amount` | money | shu shartnomadagi muddati o'tgan summa |
| `overdue_count` | int | muddati o'tgan qatorlar soni |
| `next_payment_date` | date \| null | keyingi to'lanmagan qator sanasi (`closed` bo'lsa `null`) |
| `next_payment_amount` | money | keyingi to'lov summasi (`closed` bo'lsa `0`) |
| `end_date` | date | grafikdagi oxirgi to'lov sanasi — «Якуний сана» |

> Tekshiruv: `total - initial_payment = paid + remaining_debt` bo'lishi kerak.

### 3.2 Bitta shartnoma — `GET getContract`

Shartnoma tafsiloti ekrani: tovarlar ro'yxati va to'liq grafik.

#### So'rov
```http
GET /hs/client_bot/api/getContract?client_id=9454&contract_id=5012
```

| Parametr | Tip | Majburiy | Izoh |
|---|---|---|---|
| `client_id` | id | ha | |
| `contract_id` | id | ha | boshqa mijozniki bo'lsa → `404 CONTRACT_NOT_FOUND` |

#### Javob 200
3.1 dagi **barcha** maydonlar + `products` va `schedule`:
```json
{
  "contract_id": 5012,
  "contract_number": "NS-2026-00123",
  "...": "3.1 dagi qolgan maydonlar",
  "products": [
    { "product_id": 771, "name": "Kir yuvish mashinasi LG 7kg", "qty": 1, "price": 4800000, "sum": 4800000 },
    { "product_id": 802, "name": "Changyutgich Samsung",       "qty": 1, "price": 1650000, "sum": 1650000 }
  ],
  "schedule": [
    { "n": 1, "date": "2026-07-18", "amount": 989000, "status": "paid",    "paid_date": "2026-07-16", "paid_amount": 989000 },
    { "n": 2, "date": "2026-08-17", "amount": 989000, "status": "overdue", "paid_date": null,         "paid_amount": 0 },
    { "n": 3, "date": "2026-09-16", "amount": 689000, "status": "pending", "paid_date": null,         "paid_amount": 300000 }
  ]
}
```

`products[]` — har bir element:

| Kalit | Tip | Izoh |
|---|---|---|
| `product_id` | id | tovar kodi |
| `name` | string | tovar nomi |
| `qty` | number | miqdor |
| `price` | money | birlik narxi |
| `sum` | money | `price × qty` |

`schedule[]` — har bir element (sana bo'yicha o'sish tartibida):

| Kalit | Tip | Izoh |
|---|---|---|
| `n` | int | qator tartib raqami (1, 2, 3…) |
| `date` | date | to'lov muddati |
| `amount` | money | **hali to'lanishi kerak** summa. To'liq to'langan bo'lsa — asl summa; qisman to'langan bo'lsa — qolgani (misolda 3-qator: 989000 − 300000 = 689000) |
| `status` | enum | `paid` / `pending` / `overdue` |
| `paid_date` | date \| null | to'liq to'langan sana; to'lanmagan bo'lsa `null` |
| `paid_amount` | money | shu qator bo'yicha to'langan summa (qisman bo'lsa 0 dan katta, `status` esa hali `pending/overdue`) |

---

## 4. To'lov grafigi — `GET getSchedule`

«📅 Графигим» — barcha shartnomalar yoki bittasi bo'yicha, statuslar bo'yicha filtr bilan. Bot eslatmalarni ham shu ma'lumotdan hisoblaydi.

### So'rov
```http
GET /hs/client_bot/api/getSchedule?client_id=9454
GET /hs/client_bot/api/getSchedule?client_id=9454&contract_id=5012&status=overdue
```

| Parametr | Tip | Majburiy | Izoh |
|---|---|---|---|
| `client_id` | id | ha | |
| `contract_id` | id | yo'q | berilmasa — mijozning **barcha** shartnomalari |
| `status` | enum | yo'q | `paid` / `pending` / `overdue`; berilmasa — hammasi |

### Javob 200 — ro'yxat, `date` bo'yicha o'sish tartibida
```json
[
  { "contract_id": 5012, "contract_number": "NS-2026-00123", "n": 2, "date": "2026-08-17", "amount": 989000, "status": "overdue", "paid_date": null,         "paid_amount": 0 },
  { "contract_id": 5013, "contract_number": "NS-2026-00124", "n": 1, "date": "2026-08-20", "amount": 644000, "status": "pending", "paid_date": null,         "paid_amount": 0 },
  { "contract_id": 5012, "contract_number": "NS-2026-00123", "n": 1, "date": "2026-07-18", "amount": 989000, "status": "paid",    "paid_date": "2026-07-16", "paid_amount": 989000 }
]
```

| Kalit | Tip | Izoh |
|---|---|---|
| `contract_id` | id | qaysi shartnoma |
| `contract_number` | string | shartnoma raqami (barcha shartnomalar ko'rinishida qator yonida chiqadi) |
| `n` | int | qator raqami shartnoma ichida |
| `date` | date | to'lov muddati |
| `amount` | money | to'lanishi kerak (qolgan) summa — 3.2 dagi bilan bir xil ma'no |
| `status` | enum | `paid` / `pending` / `overdue` |
| `paid_date` | date \| null | to'langan sana |
| `paid_amount` | money | to'langan qismi |

---

## 5. To'lovlar

### 5.1 To'lovlar tarixi — `GET getPayments`

«🧾 Тўловлар» — mijozning barcha to'lovlari (boshlang'ich to'lovlar, do'konda, onlayn).

#### So'rov
```http
GET /hs/client_bot/api/getPayments?client_id=9454
```

| Parametr | Tip | Majburiy | Izoh |
|---|---|---|---|
| `client_id` | id | ha | |
| `contract_id` | id | yo'q | faqat bitta shartnoma to'lovlari |
| `limit` | int | yo'q | oxirgi N ta (berilmasa — hammasi) |

#### Javob 200 — ro'yxat (yangi → eski)
```json
[
  {
    "payment_id": 90011,
    "date": "2026-08-17",
    "amount": 300000,
    "contract_id": 5012,
    "contract_number": "NS-2026-00123",
    "method": "click",
    "receipt_no": "KV-260817-2058",
    "note": "Онлайн тўлов (Telegram)",
    "transaction_id": "clk_8f3a91"
  },
  {
    "payment_id": 88120,
    "date": "2026-06-18",
    "amount": 1483000,
    "contract_id": 5012,
    "contract_number": "NS-2026-00123",
    "method": "cash",
    "receipt_no": "KV-260618-1042",
    "note": "Бошланғич тўлов",
    "transaction_id": null
  }
]
```

| Kalit | Tip | Izoh |
|---|---|---|
| `payment_id` | id | to'lov hujjati kodi |
| `date` | date | to'lov sanasi |
| `amount` | money | to'langan summa |
| `contract_id` | id | qaysi shartnoma bo'yicha |
| `contract_number` | string | shartnoma raqami |
| `method` | enum | `payme` / `click` / `paynet` / `cash` / `card` / `other` — tarixda usul nomi ko'rsatiladi |
| `receipt_no` | string | kvitansiya raqami — mijozga ko'rsatiladi |
| `note` | string | izoh («Бошланғич тўлов», «3-тўлов», «Онлайн тўлов»…) |
| `transaction_id` | string \| null | provayder tranzaksiya raqami (onlayn bo'lsa), naqd bo'lsa `null` |

### 5.2 Onlayn to'lovni boshlash — `POST createPayment`

Mijoz summa va usulni (Payme/Click/Paynet) tanlagach chaqiriladi. 1C **kutilayotgan** to'lov hujjatini yaratadi va `payment_id` qaytaradi. Provayder checkout havolasi backend/merchant tomonida shu `payment_id` bilan hosil qilinadi.

#### So'rov
```http
POST /hs/client_bot/api/createPayment
{
  "client_id": 9454,
  "contract_id": 5012,
  "amount": 300000,
  "method": "click",
  "chat_id": "66540046",
  "source": "telegram_bot"
}
```

| Kalit | Tip | Majburiy | Izoh |
|---|---|---|---|
| `client_id` | id | ha | |
| `contract_id` | id | ha | qaysi shartnoma bo'yicha to'lov |
| `amount` | money | ha | mijoz tanlagan summa (> 0). Qarzdan katta bo'lsa 1C qarzgacha kamaytirishi mumkin — javobdagi `amount` haqiqiy |
| `method` | enum | ha | `payme` / `click` / `paynet` |
| `chat_id` | string | yo'q | Telegram chat id (kim to'layapti) |
| `source` | enum | yo'q | `telegram_bot` / `webapp` |

#### Javob 200
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

| Kalit | Tip | Izoh |
|---|---|---|
| `payment_id` | id | yaratilgan kutilayotgan to'lov kodi — `confirmPayment`/`cancelPayment` da ishlatiladi, provayderga `order_id` sifatida beriladi |
| `status` | enum | `pending` |
| `amount` | money | 1C qabul qilgan summa (kamaytirilgan bo'lishi mumkin) |
| `contract_number` | string | shartnoma raqami |
| `remaining_after` | money | to'lov o'tgach qoladigan qarz (mijozga oldindan ko'rsatiladi) |
| `expires_at` | datetime | shu vaqtgacha tasdiqlanmasa to'lov `expired` bo'ladi |

Xato: `400 PAYMENT_REJECTED` (shartnoma yopilgan, summa ≤ 0 va h.k.).

### 5.3 To'lovni tasdiqlash — `POST confirmPayment`

Provayderdan (Payme/Click/Paynet callback) muvaffaqiyat kelgach backend chaqiradi. 1C to'lovni o'tkazadi, grafikni **eng eski to'lanmagan qatordan boshlab** yopadi (qisman ham bo'lishi mumkin) va kvitansiya qaytaradi.

#### So'rov
```http
POST /hs/client_bot/api/confirmPayment
{
  "payment_id": 90011,
  "transaction_id": "clk_8f3a91",
  "paid_at": "2026-08-17T14:52:10",
  "amount": 300000
}
```

| Kalit | Tip | Majburiy | Izoh |
|---|---|---|---|
| `payment_id` | id | ha | `createPayment` qaytargan kod |
| `transaction_id` | string | ha | provayder tranzaksiya raqami (kvitansiya va tekshiruv uchun) |
| `paid_at` | datetime | yo'q | provayder tasdiqlagan vaqt (berilmasa — hozir) |
| `amount` | money | yo'q | provayder haqiqatda yechgan summa (berilsa `createPayment` dagi bilan solishtiriladi) |

#### Javob 200 — kvitansiya
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

| Kalit | Tip | Izoh |
|---|---|---|
| `success` | bool | `true` — o'tkazildi |
| `payment_id` | id | to'lov kodi |
| `receipt_no` | string | kvitansiya raqami — mijozga ko'rsatiladi |
| `date` | date | to'lov sanasi |
| `amount` | money | o'tkazilgan summa |
| `method` | enum | usul |
| `contract_id` / `contract_number` | id / string | shartnoma |
| `remaining_debt` | money | to'lovdan **keyin** shu shartnomada qolgan qarz — botda «Қолган қарз автоматик янгиланади» |
| `next_payment_date` | date \| null | keyingi to'lov sanasi (yopilgan bo'lsa `null`) |
| `next_payment_amount` | money | keyingi to'lov summasi (yopilgan bo'lsa `0`) |
| `closed` | bool | `true` — shartnoma to'liq yopildi (bot 🎉 ko'rsatadi) |

**Idempotentlik:** bir xil `payment_id` ikkinchi marta kelsa — qayta o'tkazilmasin, o'sha kvitansiya qaytsin.

### 5.4 To'lovni bekor qilish — `POST cancelPayment`
```http
POST /hs/client_bot/api/cancelPayment
{ "payment_id": 90011, "reason": "user_cancel" }
```

| Kalit | Tip | Majburiy | Izoh |
|---|---|---|---|
| `payment_id` | id | ha | |
| `reason` | string | yo'q | `user_cancel` / `provider_error` / `expired` |

Javob 200: `{ "success": true, "payment_id": 90011, "status": "cancelled" }`

> **Demo rejimda** bot `createPayment` + `confirmPayment` ni ketma-ket o'zi chaqiradi («Тўладим — тасдиқлаш» tugmasi). Real integratsiyada tasdiqlash provayder callback'idan keladi.

---

## 6. Xaridlar tarixi — `GET getPurchases`

«🛍 Харидлар» — mijoz nimani, qachon, qancha summaga, qaysi shartnoma bilan olgan.

### So'rov
```http
GET /hs/client_bot/api/getPurchases?client_id=9454
```

| Parametr | Tip | Majburiy | Izoh |
|---|---|---|---|
| `client_id` | id | ha | |

### Javob 200 — ro'yxat (yangi → eski)
```json
[
  {
    "purchase_id": 3301,
    "date": "2026-06-18",
    "contract_id": 5012,
    "contract_number": "NS-2026-00123",
    "branch": "Марказий филиал",
    "total": 6450000,
    "products": [
      { "product_id": 771, "name": "Kir yuvish mashinasi LG 7kg", "qty": 1, "price": 4800000, "sum": 4800000 },
      { "product_id": 802, "name": "Changyutgich Samsung",       "qty": 1, "price": 1650000, "sum": 1650000 }
    ]
  }
]
```

| Kalit | Tip | Izoh |
|---|---|---|
| `purchase_id` | id | xarid (sotuv hujjati) kodi |
| `date` | date | xarid sanasi |
| `contract_id` | id | bog'liq nasiya shartnomasi (bosilsa shartnoma ochiladi) |
| `contract_number` | string | shartnoma raqami |
| `branch` | string | filial |
| `total` | money | xarid summasi (tovarlar, ustamasiz) |
| `products[]` | list | 3.2 dagi `products` bilan bir xil tuzilma: `product_id`, `name`, `qty`, `price`, `sum` |

---

## 7. Mijozga xizmat

### 7.1 Kompaniya ma'lumotlari — `GET getCompanyInfo`

«📞 Ёрдам» — kontaktlar va filiallar. Parametrsiz.

```http
GET /hs/client_bot/api/getCompanyInfo
```

#### Javob 200
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
    {
      "branch_id": 1,
      "name": "Марказий филиал",
      "address": "Тошкент ш., Амир Темур кўчаси, 108",
      "phone": "+998 71 200 00 01",
      "hours": "09:00–19:00",
      "lat": 41.3275,
      "lon": 69.2817
    }
  ]
}
```

| Kalit | Tip | Izoh |
|---|---|---|
| `name` | string | kompaniya nomi |
| `phone` | string | asosiy telefon (bosilsa qo'ng'iroq) |
| `operator_phone` | string | operator/qo'llab-quvvatlash telefoni |
| `operator_username` | string | operator Telegram username (`@` bilan) — «Оператор билан боғланиш» tugmasi |
| `email` | string | elektron pochta |
| `address` | string | bosh ofis manzili |
| `working_hours` | string | ish vaqti matni |
| `branches[]` | list | filiallar |
| `branches[].branch_id` | id | filial kodi |
| `branches[].name` | string | filial nomi |
| `branches[].address` | string | manzil |
| `branches[].phone` | string | telefon |
| `branches[].hours` | string | ish vaqti |
| `branches[].lat` / `lon` | number \| null | koordinatalar (ixtiyoriy; bo'lsa botda xarita tugmasi chiqadi) |

### 7.2 Murojaat / savol — `POST createRequest`

«✍️ Мурожаат қолдириш» va «💡 Савол/таклиф» — 1C da murojaat hujjati yaratiladi, operatorlar ko'radi.

```http
POST /hs/client_bot/api/createRequest
{
  "client_id": 9454,
  "chat_id": "66540046",
  "kind": "request",
  "text": "Тўлов санасини кўчириб беринг",
  "source": "telegram_bot"
}
```

| Kalit | Tip | Majburiy | Izoh |
|---|---|---|---|
| `client_id` | id | ha | |
| `chat_id` | string | ha | operator javobini Telegram orqali yuborish uchun |
| `kind` | enum | ha | `request` (murojaat/shikoyat) / `question` (savol/taklif) |
| `text` | string | ha | mijoz matni (1000 belgigacha) |
| `source` | enum | yo'q | `telegram_bot` / `webapp` |

#### Javob 200
```json
{ "request_id": 1001, "status": "new", "created_at": "2026-08-17T14:10:00" }
```

| Kalit | Tip | Izoh |
|---|---|---|
| `request_id` | id | murojaat raqami — mijozga «№ 1001» deb ko'rsatiladi |
| `status` | string | `new` (keyin 1C da `in_progress` / `done` bo'lishi mumkin) |
| `created_at` | datetime | qabul qilingan vaqt |

---

## 8. Eslatmalar

Bot eslatmalarni **o'zi** yuboradi — grafikdan (4-bo'lim) hisoblab: to'lovga 3 kun qolganda, to'lov kuni, kechikkanda. 1C tomonidan faqat mijoz sozlamasi saqlanadi.

### 8.1 Sozlama — `POST setReminders`
```http
POST /hs/client_bot/api/setReminders
{ "client_id": 9454, "chat_id": "66540046", "enabled": false }
```

| Kalit | Tip | Majburiy | Izoh |
|---|---|---|---|
| `client_id` | id | ha | |
| `chat_id` | string | yo'q | |
| `enabled` | bool | ha | `true` — eslatmalar yoqilgan, `false` — o'chirilgan |

Javob 200: `{ "success": true, "enabled": false }` — holat keyin `getClientInfo.reminders_enabled` da qaytadi.

### 8.2 1C → bot voqealari (ixtiyoriy, kelishiladi)

«Янги шартнома расмийлаштирилди» va «тўлов қабул қилинди (дўконда/нақд)» xabarlari uchun 1C bot serveriga push yuboradi. Bot tomonidagi endpoint **keyingi bosqichda** yaratiladi:

```http
POST {BOT_SERVER}/api/1c/events
Authorization: Basic ...   (bot tomonidan beriladi)
{
  "event": "contract_created",
  "client_id": 9454,
  "chat_id": "66540046",
  "contract_id": 5020,
  "contract_number": "NS-2026-00125",
  "amount": 1483000,
  "date": "2026-08-17"
}
```

| Kalit | Tip | Izoh |
|---|---|---|
| `event` | enum | `contract_created` — yangi shartnoma; `payment_received` — to'lov qabul qilindi (offlayn) |
| `client_id` / `chat_id` | id / string | kimga yuborish |
| `contract_id` / `contract_number` | id / string | qaysi shartnoma |
| `amount` | money | shartnoma summasi yoki to'lov summasi |
| `date` | date | voqea sanasi |

Javob: `{ "success": true }`

---

## 9. Aksiyalar va xabarlar — `GET getPromotions`

«🎁 Акциялар» — aksiyalar, yangi tovarlar, maxsus takliflar, kompaniya xabarlari.

```http
GET /hs/client_bot/api/getPromotions
GET /hs/client_bot/api/getPromotions?type=promo
```

| Parametr | Tip | Majburiy | Izoh |
|---|---|---|---|
| `type` | enum | yo'q | `promo` / `new` / `special` / `news`; berilmasa — hammasi (faqat amaldagilari) |

#### Javob 200 — ro'yxat (yangi → eski)
```json
[
  {
    "id": 1,
    "type": "promo",
    "title": "🔥 Ёзги чегирма — 0% устама 6 ойга",
    "text": "Барча маиший техникага 6 ойгача насия 0% устама билан.",
    "valid_until": "2026-08-31",
    "image_url": "https://nasiya.mxsoft.uz/img/promo1.jpg",
    "url": "https://nasiya.mxsoft.uz/promo/1"
  }
]
```

| Kalit | Tip | Izoh |
|---|---|---|
| `id` | id | xabar kodi |
| `type` | enum | `promo` / `new` / `special` / `news` — filtr va rang |
| `title` | string | sarlavha |
| `text` | string | matn (qisqa, 500 belgigacha) |
| `valid_until` | date \| null | amal qilish muddati (yo'q bo'lsa `null`) |
| `image_url` | string \| null | rasm havolasi (bo'lsa bot rasm bilan yuboradi) |
| `url` | string \| null | «Батафсил» havolasi |

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
| `createPayment` → `confirmPayment` / `cancelPayment` | `make_payment` | 💰 Тўлов қилиш (Payme/Click/Paynet), kvitansiya |
| `getPurchases` | `get_purchases` | 🛍 Харидлар |
| `getCompanyInfo` | `get_company_info` | 📞 Ёрдам |
| `createRequest` | `create_request` | Мурожаат / Савол-таклиф |
| `setReminders` | `set_reminders` | Кабинет → 🔔 |
| `getPromotions` | `get_promotions` | 🎁 Акциялар |

---

## 11. 1C jamoasi uchun tekshiruv ro'yxati

- [ ] Barcha endpointlar `hs/client_bot/api/` ostida, Basic Auth bilan; noto'g'ri parol → `401`
- [ ] Javoblar UTF-8 JSON; sanalar `YYYY-MM-DD`; summalar **son** (string emas); bo'sh ro'yxat `[]`
- [ ] Har bir so'rovda `client_id` tekshiriladi: boshqa mijoz shartnomasi/to'lovi so'ralsa → `404`
- [ ] `getContracts[].remaining_debt` = shu shartnoma `schedule` dagi to'lanmagan `amount` yig'indisi; `total − initial_payment = paid + remaining_debt`
- [ ] `getClientInfo.remaining_debt` = barcha shartnomalar `remaining_debt` yig'indisi
- [ ] Qisman to'lov qatorning `amount` ini kamaytiradi, `paid_amount` ni oshiradi, `status` `pending/overdue` da qoladi
- [ ] `confirmPayment` idempotent: bir xil `payment_id` ikki marta kelsa — ikkilanmaydi, o'sha kvitansiya qaytadi
- [ ] `createPayment` dan keyin `expires_at` gacha tasdiqlanmasa to'lov `expired`
- [ ] Enum qiymatlar aynan hujjatdagidek (kichik harf, lotin)

Savollar: bot/backend jamoasi — `torex.amaki@gmail.com`.
