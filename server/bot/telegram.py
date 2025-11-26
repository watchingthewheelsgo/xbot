from telegram import Bot

from utils import safe_func_wrapper
from settings import global_settings


class TelegramBot:
    telegram_bot = Bot(global_settings.telegram_bot_token)

    @safe_func_wrapper
    async def send_message(self, message: str, chat_id: str):
        await self.telegram_bot.send_message(chat_id, message)

    @safe_func_wrapper
    async def send_photo(self, photo: str, chat_id: str):
        await self.telegram_bot.send_photo(chat_id, photo)

    @safe_func_wrapper
    async def send_audio(self, audio: str, chat_id: str):
        await self.telegram_bot.send_audio(chat_id, audio)

    @safe_func_wrapper
    async def send_video(self, video: str, chat_id: str):
        await self.telegram_bot.send_video(chat_id, video)

    @safe_func_wrapper
    async def send_document(self, document: str, chat_id: str):
        await self.telegram_bot.send_document(chat_id, document)

    @safe_func_wrapper
    async def send_sticker(self, sticker: str, chat_id: str):
        await self.telegram_bot.send_sticker(chat_id, sticker)
