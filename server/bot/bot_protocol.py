"""
Bot 协议 - 定义不同平台 Bot 的统一接口
允许 ChatCommandHandlers 等组件复用于不同平台
"""

from typing import Protocol, TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from server.bot.chat import ChatManager


class MessageBot(Protocol):
    """消息 Bot 接口 - 定义发送消息的通用方法"""

    async def send_message(self, text: str, chat_id: str) -> None:
        """发送纯文本消息"""

    async def send_markdown(self, text: str, chat_id: str) -> None:
        """发送 Markdown 格式消息"""


class ChatEnabledBot(MessageBot, Protocol):
    """支持对话模式的 Bot 接口"""

    chat_manager: "ChatManager | None"
    """聊天管理器"""

    async def handle_chat_message(
        self,
        chat_id: str,
        user_message: str,
        platform: str,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        on_tool_call: Callable[[str, list], Awaitable[None]] | None = None,
    ) -> str | None:
        """处理对话消息，返回 AI 响应"""

    async def start_timeout_checker(self) -> None:
        """启动超时检查任务"""

    async def stop_timeout_checker(self) -> None:
        """停止超时检查任务"""


class CommandHandlerFn(Protocol):
    """命令处理器函数协议"""

    async def __call__(self, event: dict[str, Any]) -> str | None:
        """处理命令事件，返回响应消息"""
        ...
