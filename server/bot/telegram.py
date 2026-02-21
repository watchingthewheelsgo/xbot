"""Telegram Bot with command handling and Markdown support."""

import re
from typing import Optional, Callable, Awaitable

from loguru import logger
from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from server.settings import global_settings


# Telegram message limit
MAX_MESSAGE_LENGTH = 4096


def escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2.

    Characters that need escaping: _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    special_chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)


class TelegramBot:
    """Telegram bot with command handling and push notification support."""

    def __init__(self, token: str, admin_chat_id: Optional[str] = None):
        self.token = token
        self.admin_chat_id = admin_chat_id
        self._bot = Bot(token)
        self._app: Optional[Application] = None
        self._command_handlers: dict[str, Callable] = {}

    async def initialize(self) -> None:
        """Initialize the bot application."""
        self._app = (
            Application.builder()
            .token(self.token)
            .connect_timeout(30)
            .read_timeout(30)
            .build()
        )

        # Register stored command handlers
        for cmd, handler in self._command_handlers.items():
            self._app.add_handler(CommandHandler(cmd, handler))  # type: ignore[arg-type]

        await self._app.initialize()
        logger.info("Telegram bot initialized")

    async def start_polling(self) -> None:
        """Start polling for updates."""
        if not self._app:
            await self.initialize()
        assert self._app is not None
        assert self._app.updater is not None
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot polling started")

    async def stop(self) -> None:
        """Stop the bot."""
        if self._app:
            try:
                if self._app.updater and self._app.updater.running:
                    await self._app.updater.stop()
                if self._app.running:
                    await self._app.stop()
                await self._app.shutdown()
                logger.info("Telegram bot stopped")
            except Exception as e:
                logger.warning(f"Error stopping bot: {e}")

    def add_command(
        self,
        command: str,
        handler: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]],
    ) -> None:
        """Register a command handler."""
        self._command_handlers[command] = handler
        if self._app:
            self._app.add_handler(CommandHandler(command, handler))  # type: ignore[arg-type]
        logger.debug(f"Registered command: /{command}")

    async def send_message(
        self, text: str, chat_id: Optional[str] = None, parse_mode: Optional[str] = None
    ) -> None:
        """Send a plain text message."""
        target = chat_id or self.admin_chat_id
        if not target:
            logger.error("No chat_id specified and no admin_chat_id configured")
            return

        try:
            await self._bot.send_message(
                chat_id=target, text=text, parse_mode=parse_mode
            )
        except Exception as e:
            if parse_mode and "can't parse entities" in str(e).lower():
                logger.warning(f"Markdown parse failed, retrying as plain text: {e}")
                await self._bot.send_message(chat_id=target, text=text)
            else:
                logger.error(f"Failed to send message: {e}")
                raise

    async def send_markdown(
        self, text: str, chat_id: Optional[str] = None, escape: bool = False
    ) -> None:
        """Send a Markdown formatted message.

        Args:
            text: Message text (already formatted in Markdown)
            chat_id: Target chat ID (defaults to admin_chat_id)
            escape: If True, escape special characters in text
        """
        if escape:
            text = escape_markdown_v2(text)

        await self.send_message(text, chat_id, parse_mode=ParseMode.MARKDOWN)

    async def send_long_message(
        self, text: str, chat_id: Optional[str] = None, parse_mode: Optional[str] = None
    ) -> None:
        """Send a long message, splitting if necessary.

        Splits at paragraph boundaries when possible.
        """
        target = chat_id or self.admin_chat_id
        if not target:
            logger.error("No chat_id specified and no admin_chat_id configured")
            return

        if len(text) <= MAX_MESSAGE_LENGTH:
            await self.send_message(text, target, parse_mode)
            return

        # Split into chunks
        chunks = self._split_message(text)
        for i, chunk in enumerate(chunks):
            try:
                await self._bot.send_message(
                    chat_id=target, text=chunk, parse_mode=parse_mode
                )
            except Exception as e:
                logger.error(f"Failed to send chunk {i + 1}/{len(chunks)}: {e}")
                raise

    def _split_message(self, text: str) -> list[str]:
        """Split a long message into chunks at paragraph boundaries."""
        chunks = []
        current = ""

        paragraphs = text.split("\n\n")

        for para in paragraphs:
            # If adding this paragraph exceeds limit
            if len(current) + len(para) + 2 > MAX_MESSAGE_LENGTH:
                if current:
                    chunks.append(current.strip())
                    current = ""

                # If single paragraph is too long, split by lines
                if len(para) > MAX_MESSAGE_LENGTH:
                    lines = para.split("\n")
                    for line in lines:
                        if len(current) + len(line) + 1 > MAX_MESSAGE_LENGTH:
                            if current:
                                chunks.append(current.strip())
                            current = line
                        else:
                            current = f"{current}\n{line}" if current else line
                else:
                    current = para
            else:
                current = f"{current}\n\n{para}" if current else para

        if current:
            chunks.append(current.strip())

        return chunks

    async def send_to_admin(
        self, text: str, parse_mode: Optional[str] = ParseMode.MARKDOWN
    ) -> None:
        """Send a message to the admin chat."""
        if not self.admin_chat_id:
            logger.warning("No admin_chat_id configured, cannot send admin message")
            return
        await self.send_long_message(text, self.admin_chat_id, parse_mode)


# Global bot instance
telegram_bot: Optional[TelegramBot] = None


def get_telegram_bot() -> TelegramBot:
    """Get or create the global telegram bot instance."""
    global telegram_bot
    if telegram_bot is None:
        telegram_bot = TelegramBot(
            token=global_settings.telegram_bot_token,
            admin_chat_id=global_settings.telegram_admin_chat_id,
        )
    return telegram_bot
