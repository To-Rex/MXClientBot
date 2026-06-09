import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from jinja2 import Environment, FileSystemLoader
from starlette.middleware.sessions import SessionMiddleware

from app.config import HOST, LOG_LEVEL, PORT
from app.database import async_session, engine
from app.models import Base
from app.services.bot_manager import BotManager
from app.web.auth import AuthMiddleware, router as auth_router
from app.web.routes import router as web_router

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    bot_manager = BotManager(async_session)
    app.state.bot_manager = bot_manager
    app.state.jinja_env = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=True,
    )

    await bot_manager.start_all()
    logger.info("Application started")

    yield

    await bot_manager.stop_all()
    await engine.dispose()
    logger.info("Application stopped")


app = FastAPI(title="Telegram Multi Bot Manager", lifespan=lifespan)

app.add_middleware(AuthMiddleware)
app.add_middleware(SessionMiddleware, secret_key="mx-bot-secret-key-change-in-production")

app.include_router(auth_router)
app.include_router(web_router)


def main():
    import uvicorn

    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level=LOG_LEVEL.lower())


if __name__ == "__main__":
    main()
