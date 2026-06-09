# Telegram Multi Bot Management System

**Production-ready multi-bot management platform** — web admin panel with authentication for managing multiple Telegram bots with 1C integration.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.13+ |
| Web Framework | FastAPI |
| Telegram SDK | Aiogram 3 |
| ORM | SQLAlchemy (async) |
| Database | SQLite (via aiosqlite) |
| Migrations | Alembic |
| Templates | Jinja2 |
| HTTP Client | httpx |
| Session | Starlette SessionMiddleware (itsdangerous) |
| Server | Uvicorn |

## Architecture

```
├── run.py                          # Entry point
├── requirements.txt
├── alembic.ini                     # Migration config
├── alembic/
│   ├── env.py                      # Async SQLAlchemy env
│   ├── script.py.mako
│   └── versions/                   # Migration files
└── app/
    ├── main.py                     # FastAPI app, lifespan, middleware
    ├── config.py                   # Environment settings
    ├── database.py                 # Async engine & session
    ├── models.py                   # Bot, User ORM models
    ├── services/
    │   ├── api.py                  # 1C API client (8 endpoints)
    │   ├── auth_api.py             # External auth API (login, profile)
    │   └── bot_manager.py          # Dynamic bot lifecycle manager
    ├── handlers/
    │   └── router.py               # Telegram handlers (commands, callbacks, FSM)
    ├── web/
    │   ├── auth.py                 # Auth middleware, login/logout routes
    │   └── routes.py               # Admin panel CRUD routes (/panel)
    └── templates/
        ├── base.html               # Base layout + nav
        ├── login.html              # Login form
        ├── index.html              # Bot list
        ├── create.html             # Add bot form
        ├── edit.html               # Edit bot form
        ├── stats.html              # Bot statistics
        └── profile.html            # Admin profile
```

## Key Design Decisions

### Dynamic Bot Management
- Each bot runs in its own `asyncio.Task` with a dedicated `aiogram.Dispatcher`
- `BotManager` handles lifecycle: `start` / `stop` / `restart`
- Bots auto-start on app launch based on `is_active` flag
- Adding, removing, or updating a bot requires **zero downtime**

### Authentication
- External auth API (`POST /api/v1/authentication/login`) for JWT token
- `GET /api/v1/authentication/profile` to verify `user_type`
- Only `SUPERADMIN` and `ADMIN` roles can access `/panel`
- Server-side session via `SessionMiddleware` (itsdangerous-signed cookies)
- `AuthMiddleware` protects all `/panel/*` routes

### 1C Integration
All 1C API calls go through `APIService` with:
- HTTP Basic Authentication
- Structured logging for every request/response
- Proper error handling with `httpx`

## Database Schema

### `bots`
| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key |
| name | String | Bot display name |
| token | String | Telegram Bot API token (unique) |
| company_name | String | Company name |
| base_url | String | 1C server base URL |
| one_c_login | String | 1C Basic Auth login |
| one_c_password | String | 1C Basic Auth password |
| is_active | Boolean | Bot enabled/disabled |
| created_at | DateTime | Creation timestamp |
| updated_at | DateTime | Last update timestamp |

### `users`
| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key |
| telegram_id | BigInteger | Telegram user ID |
| phone_number | String | Phone number |
| client_id | String | 1C client ID |
| bot_id | Integer | FK → bots.id |
| created_at | DateTime | Registration timestamp |
| updated_at | DateTime | Last update timestamp |

## Admin Panel

Access at `http://localhost:8000/panel` (login required)

| Screen | Route | Description |
|--------|-------|-------------|
| **Login** | `/login` | Email + password → JWT token |
| **Bot list** | `/panel` | All bots with status, user counts, actions |
| **Create bot** | `/panel/bots/create` | Add new bot with 1C credentials |
| **Edit bot** | `/panel/bots/{id}/edit` | Update config, token, toggle active |
| **Statistics** | `/panel/bots/{id}/stats` | User count, recent registrations |
| **Profile** | `/panel/profile` | Admin user info from external API |
| **Logout** | `/logout` | Clear session, redirect to login |

### Navigation Bar
- **Bot Boshqaruv Paneli** — link to bot list
- **Profil** — admin profile page
- **👤 username** — current user
- **Chiqish** — logout

## Telegram Bot Features

### Main Menu (2×2 grid + footer)
```
👤 Profil        ℹ️ Info
📦 Mahsulotlar    📋 Buyurtmalar
    📊 Akt sverka
```

### User Flow
1. **`/start`** → Send phone number (contact button)
2. **Registration** → Calls `POST /hs/client/api/device` with phone
3. **Profile** → Calls `GET /hs/agent/api/get_client_info` — client details with images
4. **Info** → Company info, branch, group, agent, status
5. **Products** → Browse by category, image + price + stock per product
   - Categories as inline keyboard, switching clears previous messages
   - Each product has **🛒 Buyurtma berish** button
6. **Orders** → Place orders with quantity input + cancel button
   - **✏️ Tahrirlash** — edit order quantity
   - **🗑 O'chirish** — delete order with confirmation
7. **Akt sverka** → Reconciliation report with 1/2/3 month period selector
   - Switching periods clears previous report, keeps selector in place
   - **🛒 Buyurtma** (debit) / **💰 To'lov** (credit) labels

### Cancellation
- Quantity input shows **❌ Bekor qilish** button
- `/start` clears any active FSM state

### APIs Integrated

#### 1C Endpoints (per-bot credentials)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/hs/client/api/device` | POST | Register client by phone |
| `/hs/agent/api/get_client_info` | GET | Get client details |
| `/hs/client/api/Getproductsbygroup` | GET | Product catalog by groups |
| `/hs/client/api/CreateOrder` | POST | Create new order |
| `/hs/client/api/Getlistorders` | GET | List client orders |
| `/hs/client/api/EditOrder` | PATCH | Edit order quantity |
| `/hs/client/api/delete_order` | POST | Delete an order |
| `/hs/client/api/akt_sverka` | GET | Reconciliation report (date range) |

#### Auth Endpoints (external)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/authentication/login` | POST | Get JWT access token |
| `/api/v1/authentication/profile` | GET | Get admin profile info |

## Getting Started

### Prerequisites
- Python 3.13+

### Installation
```bash
git clone <repo-url>
cd MX-Client-Bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Run
```bash
python app.py
# Login page: http://localhost:8000/login
# Admin panel: http://localhost:8000/panel
```

### Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///app.db` | Database connection string |
| `HOST` | `0.0.0.0` | Server host |
| `PORT` | `8000` | Server port |
| `LOG_LEVEL` | `INFO` | Logging level |

### Database Migrations
```bash
# Generate migration after model changes
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head
```

## Extending the System

### Adding a New 1C API Endpoint

1. Add method to `app/services/api.py`:
```python
@staticmethod
async def new_endpoint(base_url, login, password, ...) -> Optional[dict]:
    ...
```

2. Add handler in `app/handlers/router.py`:
```python
@router.message(F.text == "🎯 New Feature")
async def new_handler(message: Message):
    ...
```

3. Add button to main menu keyboard (3 locations: start handler, contact success)

### Adding a New Admin Page

1. Create template in `app/templates/`
2. Add route in `app/web/routes.py` under `/panel` prefix
3. Auto-protected by `AuthMiddleware`

## License

Proprietary. All rights reserved.
