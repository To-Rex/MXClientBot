import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader
from starlette.middleware.sessions import SessionMiddleware

from app.config import HOST, LOG_LEVEL, PORT, SESSION_SECRET_KEY
from app.database import async_session, engine
from app.models import Base
from app.services.bot_manager import BotManager
from app.services.http_client import close_http_client
from app.services.nasiya_api import NasiyaError, ServiceUnavailable
from app.web.auth import AuthMiddleware, router as auth_router
from app.web.events_api import router as events_router
from app.web.routes import router as web_router
from app.web.web_app_api import router as webapp_api_router

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all skips indexes on pre-existing tables — add them explicitly
        for table in Base.metadata.tables.values():
            for index in table.indexes:
                await conn.run_sync(lambda sync_conn, idx=index: idx.create(sync_conn, checkfirst=True))

    bot_manager = BotManager(async_session)
    app.state.bot_manager = bot_manager
    app.state.jinja_env = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=True,
        auto_reload=False,  # templates are static in production — skip stat() per render
    )

    await bot_manager.start_all()
    logger.info("Application started")

    yield

    await bot_manager.stop_all()
    await close_http_client()
    await engine.dispose()
    logger.info("Application stopped")


app = FastAPI(title="Telegram Multi Bot Manager", lifespan=lifespan)

app.add_middleware(AuthMiddleware)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY)

SOON_MESSAGE = "Бу хизмат тез кунда ишга тушади. Ноқулайлик учун узр — бироздан сўнг қайта уриниб кўринг."


@app.exception_handler(ServiceUnavailable)
async def _service_unavailable_handler(request: Request, exc: ServiceUnavailable):
    logger.warning("1C service unavailable: %s (%s)", exc.endpoint, exc.reason)
    return JSONResponse(status_code=503, content={"detail": SOON_MESSAGE, "code": "SERVICE_UNAVAILABLE", "endpoint": exc.endpoint})


@app.exception_handler(NasiyaError)
async def _nasiya_error_handler(request: Request, exc: NasiyaError):
    logger.warning("1C error %s: %s (%s)", exc.code, exc.message, exc.endpoint)
    return JSONResponse(status_code=400, content={"detail": exc.message, "code": exc.code})


app.include_router(auth_router)
app.include_router(events_router)
app.include_router(web_router)
app.include_router(webapp_api_router)


@app.get("/webapp", response_class=HTMLResponse)
async def webapp_page(request: Request):
    env = request.app.state.jinja_env
    template = env.get_template("webapp.html")
    return HTMLResponse(template.render())


@app.get("/webapp/", response_class=HTMLResponse)
async def webapp_slash(request: Request):
    return await webapp_page(request)


def main():
    import uvicorn

    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level=LOG_LEVEL.lower())


if __name__ == "__main__":
    main()
