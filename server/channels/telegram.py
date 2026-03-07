"""
Telegram 渠道实现
适配统一 Channel 接口
"""

import re
from typing import Optional, List

from loguru import logger
from telegram import Bot
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler

from .base import Channel, MessageLimit


# Telegram 消息限制
MAX_MESSAGE_LENGTH = 4096


def escape_markdown_v2(text: str) -> str:
    """转义 Telegram MarkdownV2 特殊字符"""
    special_chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)


class TelegramChannel(Channel):
    """Telegram 渠道实现"""

    def __init__(
        self,
        token: str,
        admin_chat_id: Optional[str] = None,
        bot_name: str = "telegram",
    ):
        self._name = bot_name
        self._token = token
        self._admin_chat_id = admin_chat_id
        self._bot = Bot(token)
        self._app: Optional[Application] = None
        self._command_handlers = {}
        self._enabled = bool(token)

        # 消息限制器
        self._limit = MessageLimit(
            max_length=MAX_MESSAGE_LENGTH, chunk_size=2000, chunk_delay=0.1
        )

        # Telegram 长消息分割策略
        # 按段落优先分割，避免截断句子
        self._split_strategy = "paragraph"  # paragraph, line, aggressive

    @property
    def name(self) -> str:
        return self._name

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def initialize(self) -> None:
        """初始化 Telegram bot"""
        if not self._enabled:
            logger.warning("Telegram bot not enabled (no token)")
            return

        self._app = (
            Application.builder()
            .token(self._token)
            .connect_timeout(30)
            .read_timeout(30)
            .build()
        )

        # 注册命令处理器（动态添加）
        for cmd, handler in self._command_handlers.items():
            self._app.add_handler(CommandHandler(cmd, handler))

        await self._app.initialize()
        logger.info("Telegram bot initialized")

    async def send_message(
        self, text: str, chat_id: Optional[str] = None, parse_mode: Optional[str] = None
    ) -> None:
        """发送纯文本消息"""
        target = chat_id or self._admin_chat_id
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
        """发送 Markdown 格式消息"""
        if escape:
            text = escape_markdown_v2(text)
        await self.send_message(text, chat_id, ParseMode.MARKDOWN)

    async def send_long_message(
        self, text: str, chat_id: Optional[str] = None, parse_mode: Optional[str] = None
    ) -> None:
        """发送长消息，自动分割"""
        target = chat_id or self._admin_chat_id
        if not target:
            logger.error("No chat_id specified and no admin_chat_id configured")
            return

        chunks = self._limit.split_message(text)

        for i, chunk in enumerate(chunks):
            try:
                await self._bot.send_message(
                    chat_id=target, text=chunk, parse_mode=parse_mode
                )
                # 批量发送时添加延迟，避免被限流
                if i < len(chunks) - 1:
                    import asyncio

                    await asyncio.sleep(self._limit.chunk_delay)
            except Exception as e:
                logger.error(f"Failed to send chunk {i + 1}/{len(chunks)}: {e}")
                raise

    async def send_batch(
        self, messages: List[str], chat_id: Optional[str] = None, delay: float = 0.1
    ) -> None:
        """批量发送多条消息"""
        target = chat_id or self._admin_chat_id
        if not target:
            logger.error("No chat_id specified and no admin_chat_id configured")
            return

        for i, msg in enumerate(messages):
            await self.send_message(msg, chat_id=target)
            if i < len(messages) - 1:
                import asyncio

                await asyncio.sleep(delay)

    def owns_chat(self, chat_id: str) -> bool:
        """判断是否拥有指定的聊天（Telegram 没有聊天ID概念，返回 False）"""
        # Telegram 使用 chat_id 直接，不像 FreshBot 有 username
        # 可以通过检查消息来源来判断
        return False

    def get_admin_chat_ids(self) -> List[str]:
        """获取管理员聊天 ID"""
        if not self._admin_chat_id:
            return []
        return [self._admin_chat_id]

    async def shutdown(self) -> None:
        """优雅地关闭 bot"""
        if self._app:
            try:
                if self._app.updater and self._app.updater.running:
                    await self._app.updater.stop()  # type: ignore
                if self._app.running:
                    await self._app.stop()
                await self._app.shutdown()
                logger.info("Telegram bot stopped")
            except Exception as e:
                logger.warning(f"Error stopping Telegram bot: {e}")

    async def health_check(self) -> bool:
        """健康检查"""
        if not self._enabled or not self._app:
            return False
        try:
            # 获取 bot 信息验证连接
            await self._bot.get_me()
            return True
        except Exception as e:
            logger.warning(f"Telegram health check failed: {e}")
            return False

    def add_command_handler(self, command: str, handler) -> None:
        """添加命令处理器（用于向后兼容）"""
        self._command_handlers[command] = handler

    async def start_polling(self) -> None:
        """开始轮询接收消息"""
        if not self._app:
            await self.initialize()
        await self._app.run_polling(drop_pending_updates=True)  # type: ignore
        logger.info("Telegram bot polling started")


# 全局实例（向后兼容）
_telegram_instance: Optional[TelegramChannel] = None


def get_telegram_channel(
    token: str, admin_chat_id: Optional[str] = None
) -> TelegramChannel:
    """获取或创建全局 Telegram 渠道实例"""
    global _telegram_instance
    if _telegram_instance is None:
        _telegram_instance = TelegramChannel(
            token=token, admin_chat_id=admin_chat_id, bot_name="telegram"
        )
    return _telegram_instance
