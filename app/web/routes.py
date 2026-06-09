from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from sqlalchemy import func, select

from app.database import async_session
from app.models import Bot, User
from app.services.auth_api import AuthAPIService

router = APIRouter(prefix="/panel")


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots():
    return "User-agent: *\nDisallow: /\n"


@router.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


def _render(request: Request, template_name: str, context: dict | None = None) -> HTMLResponse:
    env = request.app.state.jinja_env
    ctx = {
        "request": request,
        "username": request.session.get("username", ""),
    }
    if context:
        ctx.update(context)
    template = env.get_template(template_name)
    return HTMLResponse(template.render(ctx))


def _bot_manager(request: Request):
    return request.app.state.bot_manager


async def _get_bot_or_404(bot_id: int):
    async with async_session() as session:
        result = await session.execute(select(Bot).where(Bot.id == bot_id))
        bot = result.scalar_one_or_none()
        if bot is None:
            raise HTTPException(status_code=404, detail="Bot topilmadi")
        return bot


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    async with async_session() as session:
        result = await session.execute(select(Bot).order_by(Bot.created_at.desc()))
        bots = result.scalars().all()

        user_counts = {}
        for bot in bots:
            count_result = await session.execute(
                select(func.count(User.id)).where(User.bot_id == bot.id)
            )
            user_counts[bot.id] = count_result.scalar()

    bm = _bot_manager(request)
    return _render(request, "index.html", {
        "bots": bots,
        "user_counts": user_counts,
        "bot_manager": bm,
    })


@router.get("/bots/create", response_class=HTMLResponse)
async def create_form(request: Request):
    return _render(request, "create.html")


@router.post("/bots/create")
async def create_bot(
    request: Request,
    name: str = Form(...),
    token: str = Form(...),
    company_name: str = Form(""),
    base_url: str = Form(""),
    one_c_login: str = Form(""),
    one_c_password: str = Form(""),
    is_active: bool = Form(False),
):
    bot = Bot(
        name=name,
        token=token,
        company_name=company_name,
        base_url=base_url,
        one_c_login=one_c_login,
        one_c_password=one_c_password,
        is_active=is_active,
    )

    async with async_session() as session:
        session.add(bot)
        await session.commit()
        await session.refresh(bot)

        if bot.is_active:
            await _bot_manager(request).add_bot(bot)

    return RedirectResponse(url="/panel", status_code=303)


@router.get("/bots/{bot_id}/edit", response_class=HTMLResponse)
async def edit_form(request: Request, bot_id: int):
    bot = await _get_bot_or_404(bot_id)
    return _render(request, "edit.html", {"bot": bot})


@router.post("/bots/{bot_id}/edit")
async def edit_bot(
    request: Request,
    bot_id: int,
    name: str = Form(...),
    token: str = Form(...),
    company_name: str = Form(""),
    base_url: str = Form(""),
    one_c_login: str = Form(""),
    one_c_password: str = Form(""),
    is_active: bool = Form(False),
):
    bot = await _get_bot_or_404(bot_id)
    bm = _bot_manager(request)
    token_changed = bot.token != token

    async with async_session() as session:
        bot = await session.merge(bot)
        bot.name = name
        bot.token = token
        bot.company_name = company_name
        bot.base_url = base_url
        bot.one_c_login = one_c_login
        bot.one_c_password = one_c_password
        bot.is_active = is_active
        await session.commit()
        await session.refresh(bot)

        if token_changed or not bm.is_running(bot.id):
            if bot.is_active:
                await bm.restart_bot(bot)
            else:
                await bm.stop_bot(bot.id)
        elif not bot.is_active:
            await bm.stop_bot(bot.id)
        elif bot.is_active and not bm.is_running(bot.id):
            await bm.add_bot(bot)

    return RedirectResponse(url="/panel", status_code=303)


@router.post("/bots/{bot_id}/toggle")
async def toggle_bot(request: Request, bot_id: int):
    bot = await _get_bot_or_404(bot_id)
    bm = _bot_manager(request)

    async with async_session() as session:
        bot = await session.merge(bot)
        bot.is_active = not bot.is_active
        await session.commit()

    if bot.is_active:
        await bm.add_bot(bot)
    else:
        await bm.stop_bot(bot.id)

    return RedirectResponse(url="/panel", status_code=303)


@router.post("/bots/{bot_id}/delete")
async def delete_bot(request: Request, bot_id: int):
    bot = await _get_bot_or_404(bot_id)
    bm = _bot_manager(request)
    await bm.stop_bot(bot.id)

    async with async_session() as session:
        bot = await session.merge(bot)
        await session.delete(bot)
        await session.commit()

    return RedirectResponse(url="/panel", status_code=303)


@router.get("/bots/{bot_id}/stats", response_class=HTMLResponse)
async def bot_stats(request: Request, bot_id: int):
    bot = await _get_bot_or_404(bot_id)

    async with async_session() as session:
        total = await session.execute(
            select(func.count(User.id)).where(User.bot_id == bot_id)
        )
        total_users = total.scalar()

        recent_result = await session.execute(
            select(User)
            .where(User.bot_id == bot_id)
            .order_by(User.created_at.desc())
            .limit(50)
        )
        recent_users = recent_result.scalars().all()

    bm = _bot_manager(request)
    return _render(request, "stats.html", {
        "bot": bot,
        "total_users": total_users,
        "recent_users": recent_users,
        "is_running": bm.is_running(bot_id),
    })


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    token = request.session.get("access_token", "")
    profile = await AuthAPIService.get_profile(token) if token else None
    return _render(request, "profile.html", {"profile": profile or {}})
