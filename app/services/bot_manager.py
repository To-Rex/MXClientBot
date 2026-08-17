import asyncio
import logging
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.config import WEBAPP_URL
from app.handlers.router import create_router
from app.models import Bot as BotModel
from app.services.reminders import reminder_loop

logger = logging.getLogger(__name__)


class BotInstance:
    __slots__ = ("bot", "dp", "task", "reminder_task")

    def __init__(self, bot: Bot, dp: Dispatcher, task: asyncio.Task, reminder_task: Optional[asyncio.Task] = None):
        self.bot = bot
        self.dp = dp
        self.task = task
        self.reminder_task = reminder_task


class BotManager:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory
        self._instances: dict[int, BotInstance] = {}

    async def start_all(self):
        async with self._session_factory() as session:
            result = await session.execute(
                select(BotModel).where(BotModel.is_active == True)
            )
            bots = result.scalars().all()

        for bot_record in bots:
            await self._start_bot(bot_record)

        logger.info("Started %d bots", len(bots))

    async def add_bot(self, bot_record: BotModel):
        await self._start_bot(bot_record)

    async def stop_bot(self, bot_id: int):
        instance = self._instances.pop(bot_id, None)
        if instance is None:
            return
        for t in (instance.reminder_task, instance.task):
            if t is None:
                continue
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug("task finished with error for bot %d: %s", bot_id, e)
        await instance.bot.session.close()
        logger.info("Stopped bot %d", bot_id)

    async def restart_bot(self, bot_record: BotModel):
        await self.stop_bot(bot_record.id)
        await self._start_bot(bot_record)
        logger.info("Restarted bot %d", bot_record.id)

    async def _start_bot(self, bot_record: BotModel):
        if bot_record.id in self._instances:
            await self.stop_bot(bot_record.id)

        bot = Bot(
            token=bot_record.token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )

        dp = Dispatcher()

        bot_config = {
            "id": bot_record.id,
            "company_name": bot_record.company_name or "",
            "base_url": bot_record.base_url or "",
            "one_c_login": bot_record.one_c_login or "",
            "one_c_password": bot_record.one_c_password or "",
        }

        router = create_router(bot_config, self._session_factory)
        dp.include_router(router)

        try:
            await bot.set_my_commands([
                BotCommand(command="start", description="Ботни бошлаш / асосий меню"),
                BotCommand(command="getsession", description="Браузер учун ҳавола олиш"),
                BotCommand(command="logout", description="Тизимдан чиқиш"),
            ])
        except Exception as e:
            logger.warning("Failed to set commands for bot %d: %s", bot_record.id, e)

        if WEBAPP_URL:
            try:
                webapp_full_url = f"{WEBAPP_URL.rstrip('/')}/webapp?bot_id={bot_record.id}"
                await bot.set_chat_menu_button(
                    menu_button=MenuButtonWebApp(
                        text="Web App",
                        web_app=WebAppInfo(url=webapp_full_url),
                    )
                )
                logger.info("Set WebApp menu button for bot %d: %s", bot_record.id, webapp_full_url)
            except Exception as e:
                logger.warning("Failed to set WebApp menu button for bot %d: %s", bot_record.id, e)

        task = asyncio.create_task(
            self._supervised_polling(bot, dp, bot_record.id, bot_record.name),
            name=f"polling-bot-{bot_record.id}",
        )

        creds = (bot_config["base_url"], bot_config["one_c_login"], bot_config["one_c_password"])
        reminder_task = asyncio.create_task(
            reminder_loop(bot, bot_record.id, creds, self._session_factory),
            name=f"reminders-bot-{bot_record.id}",
        )

        self._instances[bot_record.id] = BotInstance(bot=bot, dp=dp, task=task, reminder_task=reminder_task)
        logger.info("Started bot %d (%s)", bot_record.id, bot_record.name)

    @staticmethod
    async def _supervised_polling(bot: Bot, dp: Dispatcher, bot_id: int, name: str):
        """Keep polling alive forever.

        aiogram's polling already retries network errors, but if
        ``start_polling`` itself raises (e.g. ``getMe`` fails while the network is
        down at startup, or an unexpected internal error), the task would die
        silently and the bot would stop responding.  This loop restarts it with
        exponential backoff until the bot is stopped explicitly (cancel).
        """
        delay = 2
        while True:
            try:
                await dp.start_polling(
                    bot,
                    allowed_updates=dp.resolve_used_update_types(),
                    handle_signals=False,
                    close_bot_session=False,
                )
                logger.info("Polling finished for bot %d (%s)", bot_id, name)
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(
                    "Polling crashed for bot %d (%s): %s: %s — restarting in %ss",
                    bot_id, name, type(e).__name__, e, delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    async def stop_all(self):
        for bot_id in list(self._instances.keys()):
            await self.stop_bot(bot_id)

    def is_running(self, bot_id: int) -> bool:
        return bot_id in self._instances

    def get_instance(self, bot_id: int) -> Optional[BotInstance]:
        return self._instances.get(bot_id)

    @property
    def running_count(self) -> int:
        return len(self._instances)
