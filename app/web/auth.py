"""Authentication routes — login, logout, and session-based auth check."""

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.services.auth_api import AuthAPIService

router = APIRouter()
ALLOWED_TYPES = {"SUPERADMIN", "ADMIN"}


def _render_login(request: Request, error: str = "") -> HTMLResponse:
    env = request.app.state.jinja_env
    template = env.get_template("login.html")
    return HTMLResponse(template.render(request=request, error=error, username=""))


async def _check_auth(request: Request) -> bool:
    """Check if session has valid auth token and user_type."""
    token = request.session.get("access_token")
    user_type = request.session.get("user_type")
    if not token or not user_type:
        return False
    if user_type not in ALLOWED_TYPES:
        return False
    return True


class AuthMiddleware(BaseHTTPMiddleware):
    """Protect /panel routes — redirect to /login if not authenticated."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/panel"):
            if not await _check_auth(request):
                return RedirectResponse(url="/login", status_code=303)
        response = await call_next(request)
        return response


@router.get("/", response_class=HTMLResponse)
async def root_redirect(request: Request):
    if await _check_auth(request):
        return RedirectResponse(url="/panel", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if await _check_auth(request):
        return RedirectResponse(url="/panel", status_code=303)
    return _render_login(request)


@router.post("/login")
async def login_action(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    result = await AuthAPIService.login(email, password)
    if not result or not result.get("access_token"):
        return _render_login(request, error="Login yoki parol noto'g'ri")

    token = result["access_token"]
    profile = await AuthAPIService.get_profile(token)
    if not profile:
        return _render_login(request, error="Profil ma'lumotlari olinmadi")

    user_type = profile.get("user_type", "")
    if user_type not in ALLOWED_TYPES:
        return _render_login(
            request, error="Sizda ruxsat yo'q. Faqat ADMIN yoki SUPERADMIN kirishi mumkin."
        )

    response = RedirectResponse(url="/panel", status_code=303)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=86400,
        samesite="lax",
    )
    request.session["access_token"] = token
    request.session["user_type"] = user_type
    request.session["username"] = profile.get("username", "")
    return response


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("access_token")
    return response
