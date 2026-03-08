"""
Feishu Bot 适配器 - 将 Feishu 特定类型适配到通用接口
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.bot.feishu_v2 import FeishuBotV2


class FeishuMessageAdapter:
    """Feishu 消息适配器"""

    @staticmethod
    def to_event(event: dict) -> dict:
        """将 Feishu 事件转换为标准事件格式（已经是字典）"""
        # Feishu 事件已经是字典格式，只需确保必要字段
        return {
            "chat_id": event.get("chat_id", ""),
            "user_name": "User",  # Feishu 没有直接的用户名获取方式
            "platform": "feishu",
            "args": event.get("args", "").split() if event.get("args") else [],
            "event": event,
        }


class FeishuBotAdapter:
    """Feishu Bot 适配器 - 实现 MessageBot 协议"""

    def __init__(self, bot: "FeishuBotV2"):
        self._bot = bot

    async def send_message(self, text: str, chat_id: str) -> None:
        """发送纯文本消息"""
        self._bot.send_text(chat_id, text)

    async def send_markdown(self, text: str, chat_id: str) -> None:
        """发送 Markdown 格式消息（Feishu 使用 post 格式）"""
        self._bot.send_post(chat_id, text)


class FeishuChatAdapter(FeishuBotAdapter):
    """Feishu Chat 适配器 - 实现 ChatEnabledBot 协议"""

    def __init__(self, bot: "FeishuBotV2"):
        super().__init__(bot)

    @property
    def chat_manager(self):
        """聊天管理器"""
        return self._bot.chat_manager

    async def handle_chat_message(
        self,
        chat_id: str,
        user_message: str,
        platform: str = "feishu",
        on_progress=None,
        on_tool_call=None,
    ) -> str | None:
        """处理对话消息，返回 AI 响应"""

        # 复用 ChatManager 的处理逻辑
        async def _on_progress(msg: str):
            """进度回调 - 飞书不支持 typing，只能记录"""
            pass

        async def _on_tool_call(tool_id: str, tool_calls: list) -> None:
            """工具调用回调"""
            try:
                from server.bot.chat import format_tool_call_message

                tool_msg = format_tool_call_message(tool_calls)
                self._bot.send_post(chat_id, tool_msg)
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
