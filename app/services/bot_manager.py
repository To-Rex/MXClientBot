import asyncio
import logging
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.handlers.router import create_router
from app.models import Bot as BotModel

logger = logging.getLogger(__name__)


class BotInstance:
    __slots__ = ("bot", "dp", "task")

    def __init__(self, bot: Bot, dp: Dispatcher, task: asyncio.Task):
        self.bot = bot
        self.dp = dp
        self.task = task


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
        instance.task.cancel()
        try:
            await instance.task
        except asyncio.CancelledError:
            pass
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
                BotCommand(command="start", description="Botni boshlash"),
            ])
        except Exception as e:
            logger.warning("Failed to set commands for bot %d: %s", bot_record.id, e)

        task = asyncio.create_task(dp.start_polling(bot))

        self._instances[bot_record.id] = BotInstance(bot=bot, dp=dp, task=task)
        logger.info("Started bot %d (%s)", bot_record.id, bot_record.name)

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
