"""Telegram Bot with command handling and Markdown support."""

import asyncio
from pathlib import Path
import re
from typing import Optional, Callable, TYPE_CHECKING, Any

from loguru import logger
from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

if TYPE_CHECKING:
    from server.bot.chat import ChatManager
else:
    # Import at runtime for type hints outside TYPE_CHECKING
    from server.bot.chat import ChatManager


# Telegram message limit
MAX_MESSAGE_LENGTH = 4096


def escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2.

    Characters that need escaping: _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    special_chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(special_chars)}])", r"\\1", text)


class TelegramBot:
    """Telegram bot with command handling, push notification and chat mode support."""

    def __init__(
        self,
        token: str,
        admin_chat_id: Optional[str] = None,
        chat_manager: Optional[ChatManager] = None,
        llm_client: Optional[Any] = None,
        memory_service: Optional[Any] = None,
        workspace: Path = Path.home() / ".xbot",
    ):
        self.token = token
        self.admin_chat_id = admin_chat_id
        self.chat_manager = chat_manager
        self.workspace = workspace

        # 初始化聊天管理器（如果提供了 LLM 和记忆服务）
        if llm_client and memory_service and chat_manager is not None:
            chat_manager.llm_client = llm_client
            chat_manager.memory_service = memory_service

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

        # Register command handlers
        for cmd, handler in self._command_handlers.items():
            self._app.add_handler(CommandHandler(cmd, handler))

        # Register message handler for chat mode
        if self.chat_manager:
            self._app.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
            )

        await self._app.initialize()
        logger.info("Telegram bot initialized")

        # Start chat timeout checker
        if self.chat_manager:
            await self.chat_manager.start_timeout_checker()

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

                if self.chat_manager:
                    await self.chat_manager.stop_timeout_checker()

                if self._app.running:
                    await self._app.stop()

                await self._app.shutdown()
                logger.info("Telegram bot stopped")

            except Exception as e:
                logger.warning(f"Error stopping bot: {e}")

    async def _handle_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        处理非命令消息（用于对话模式）

        只有在对话模式下才处理消息
        """
        if not update.message or not update.effective_chat:
            return

        chat_id = str(update.effective_chat.id)
        message_text = update.message.text or ""

        # 不在对话模式，不处理
        if not self.chat_manager or not self.chat_manager.is_in_chat_mode(chat_id):
            logger.debug(f"Message ignored (not in chat mode): {chat_id}")
            return

        # 处理消息
        async def on_progress(msg: str):
            """进度回调"""
            if msg:
                try:
                    await self._bot.send_chat_action(chat_id=chat_id, action="typing")
                    await asyncio.sleep(0.5)
                    await self._bot.send_chat_action(chat_id=chat_id, action="typing")
                except Exception:
                    pass  # 忽略进度发送错误

        async def on_tool_call(tool_id: str, tool_calls: list) -> None:
            """工具调用回调"""
            try:
                from server.bot.chat import format_tool_call_message

                tool_msg = format_tool_call_message(tool_calls)
                await self._bot.send_message(tool_msg, chat_id)
            except Exception:
                pass  # 忽略工具调用发送错误

        response = await self.chat_manager.process_message(
            chat_id=chat_id,
            user_message=message_text,
            platform="telegram",
            on_progress=on_progress,
            on_tool_call=on_tool_call,
        )

        if response:
            await self.send_long_message(response, chat_id)

    async def _start_timeout_checker(self) -> None:
        """启动超时检查任务"""
        if self.chat_manager:
            asyncio.create_task(self.chat_manager.start_timeout_checker())

    def add_command(
        self,
        command: str,
        handler: Callable[[Update, ContextTypes.DEFAULT_TYPE], Any],
    ) -> None:
        """Register a command handler."""
        self._command_handlers[command] = handler
        if self._app:
            self._app.add_handler(CommandHandler(command, handler))
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

    async def send_chat_action(self, chat_id: str, action: str = "typing") -> None:
        """Send a chat action (typing, etc.)."""
        try:
            await self._bot.send_chat_action(chat_id=chat_id, action=action)
        except Exception as e:
            logger.debug(f"Failed to send chat action {action}: {e}")

    async def health_check(self) -> bool:
        """Health check."""
        try:
            await self._bot.get_me()
            return True
        except Exception:
            return False


# Global bot instance
telegram_bot: Optional[TelegramBot] = None


def get_telegram_bot(
    token: str,
    admin_chat_id: Optional[str] = None,
    chat_manager: Optional[ChatManager] = None,
) -> TelegramBot:
    """Get or create the global Telegram bot instance."""
    global telegram_bot

    if telegram_bot is None:
        telegram_bot = TelegramBot(
            token=token,
            admin_chat_id=admin_chat_id,
            chat_manager=chat_manager,
        )

    return telegram_bot
