from telegram import Bot

from utils import safe_func_wrapper
from settings import global_settings


class TelegramBot:
    telegram_bot = Bot(global_settings.telegram_bot_token)

    @safe_func_wrapper
    async def send_message(self, message: str, chat_id: str):
        await self.telegram_bot.send_message(chat_id, message)
