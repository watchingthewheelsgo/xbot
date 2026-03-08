"""
Telegram Bot 适配器 - 将 Telegram 特定类型适配到通用接口
"""

from telegram import Update
from telegram.ext import ContextTypes
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.bot.telegram import TelegramBot


class TelegramMessageAdapter:
    """Telegram 消息适配器"""

    @staticmethod
    def to_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict:
        """将 Telegram Update 转换为通用事件格式"""
        user = update.effective_user
        chat = update.effective_chat

        user_name = "User"
        if user:
            user_name = user.first_name or user.username or "User"

        return {
            "chat_id": str(chat.id) if chat else "",
            "user_name": user_name,
            "platform": "telegram",
            "args": context.args if context and hasattr(context, "args") else [],
            "user_id": str(user.id) if user else None,
            "message_id": update.message.message_id if update.message else None,
            "update": update,
            "context": context,
        }


class TelegramBotAdapter:
    """Telegram Bot 适配器 - 实现 MessageBot 协议"""

    def __init__(self, bot: "TelegramBot"):
        self._bot = bot

    async def send_message(self, text: str, chat_id: str) -> None:
        """发送纯文本消息"""
        await self._bot.send_message(text, chat_id)

    async def send_markdown(self, text: str, chat_id: str) -> None:
        """发送 Markdown 格式消息"""
        await self._bot.send_markdown(text, chat_id)


class TelegramChatAdapter(TelegramBotAdapter):
    """Telegram Chat 适配器 - 实现 ChatEnabledBot 协议"""

    def __init__(self, bot: "TelegramBot"):
        super().__init__(bot)

    @property
    def chat_manager(self):
        """聊天管理器"""
        return self._bot.chat_manager

    async def handle_chat_message(
        self,
        chat_id: str,
        user_message: str,
        platform: str = "telegram",
        on_progress=None,
        on_tool_call=None,
    ) -> str | None:
        """处理对话消息，返回 AI 响应"""

        # 复用 TelegramBot 的内部处理逻辑
        async def _on_progress(msg: str):
            """进度回调"""
            if msg:
                try:
                    await self._bot.send_chat_action(chat_id=chat_id, action="typing")
                except Exception:
                    pass

        async def _on_tool_call(tool_id: str, tool_calls: list) -> None:
            """工具调用回调"""
            try:
                from server.bot.chat import format_tool_call_message

                tool_msg = format_tool_call_message(tool_calls)
                await self._bot.send_message(tool_msg, chat_id)
            except Exception:
                pass

        chat_mgr = self._bot.chat_manager
        if chat_mgr is None:
            return None

        response = await chat_mgr.process_message(
            chat_id=chat_id,
            user_message=user_message,
            platform=platform,
            on_progress=on_progress or _on_progress,
            on_tool_call=on_tool_call or _on_tool_call,
        )
        return response

    async def start_timeout_checker(self) -> None:
        """启动超时检查任务"""
        chat_mgr = self._bot.chat_manager
        if chat_mgr:
            await chat_mgr.start_timeout_checker()

    async def stop_timeout_checker(self) -> None:
        """停止超时检查任务"""
        chat_mgr = self._bot.chat_manager
        if chat_mgr:
            await chat_mgr.stop_timeout_checker()
