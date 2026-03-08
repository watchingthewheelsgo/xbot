"""
对话模式命令处理器 - 平台无关实现
复用于 Telegram、飞书等所有平台
"""

import time
from typing import TYPE_CHECKING, Any
from loguru import logger

from server.bot.chat import ChatManager

if TYPE_CHECKING:
    from server.bot.bot_protocol import MessageBot


class ChatCommandHandlers:
    """对话模式命令处理器 - 平台无关"""

    def __init__(
        self,
        bot: "MessageBot",
        chat_manager: ChatManager,
        llm_client=None,
        memory_service=None,
    ):
        self.bot = bot
        self.chat_manager = chat_manager

        # 如果提供了 LLM 和记忆服务，设置到 chat_manager
        if llm_client:
            self.chat_manager.llm_client = llm_client
        if memory_service:
            self.chat_manager.memory_service = memory_service

        logger.info("ChatCommandHandlers initialized")

    async def handle_chat(self, event: dict[str, Any]) -> str | None:
        """处理 /chat 命令 - 进入对话模式"""
        chat_id = event.get("chat_id", "")
        platform = event.get("platform", "unknown")
        user_name = event.get("user_name", "User")

        logger.info(f"/chat command from {user_name} in {chat_id} ({platform})")

        start_time = time.time()

        try:
            # 进入对话模式
            await self.chat_manager.enter_chat_mode(
                chat_id=chat_id,
                platform=platform,
                welcome_message=False,  # 我们自己发送欢迎消息
            )

            # 获取会话状态
            session_info = await self.chat_manager.get_session_info(chat_id)

            status_msg = f"""✅ 对话模式已开启

📊 会话信息：
• 状态：{session_info["state"] if session_info else "unknown"}
• 消息数：{session_info["message_count"] if session_info else 0}
• 创建时间：{session_info.get("created_at", "")[:16] if session_info else ""}

💡 使用方法：
• 直接发送消息即可开始对话
• 我会记住上下文并回答问题
• /quit 退出对话模式
• /chatstatus 查看对话状态
• 5分钟无新消息后30秒自动退出
""".strip()

            elapsed = time.time() - start_time
            logger.info(f"/chat command completed in {elapsed:.2f}s")
            return status_msg

        except Exception as e:
            logger.error(f"/chat command failed: {e}")
            return f"❌ 开启对话模式失败：{str(e)[:100]}"

    async def handle_quit(self, event: dict[str, Any]) -> str | None:
        """处理 /quit 命令 - 退出对话模式"""
        chat_id = event.get("chat_id", "")
        user_name = event.get("user_name", "User")

        logger.info(f"/quit command from {user_name} in {chat_id}")

        if not self.chat_manager.is_in_chat_mode(chat_id):
            return "❌ 当前不在对话模式"

        start_time = time.time()

        try:
            # 退出对话模式
            await self.chat_manager._exit_chat_mode(chat_id, reason="user")

            # 获取最终会话状态
            session_info = await self.chat_manager.get_session_info(chat_id)

            summary_msg = f"""👋 对话模式已退出

📊 会话总结：
• 消息数：{session_info["message_count"] if session_info else 0}
• 上下文已保存到记忆

💡 再次使用 /chat 进入新的对话
""".strip()

            elapsed = time.time() - start_time
            logger.info(f"/quit command completed in {elapsed:.2f}s")
            return summary_msg

        except Exception as e:
            logger.error(f"/quit command failed: {e}")
            return f"❌ 退出失败：{str(e)[:100]}"

    async def handle_chat_status(self, event: dict[str, Any]) -> str | None:
        """处理 /chatstatus 命令 - 查看对话状态"""
        chat_id = event.get("chat_id", "")

        session_info = await self.chat_manager.get_session_info(chat_id)

        if not session_info:
            return "❌ 当前没有活跃的对话会话"

        is_chat_mode = self.chat_manager.is_in_chat_mode(chat_id)

        status_msg = f"""📊 对话状态

{"✅ 在对话模式" if is_chat_mode else "⭕ 不在对话模式"}

📋 会话信息：
• Chat ID：{session_info.get("chat_id", chat_id[:20])}
• 平台：{session_info.get("platform", "unknown")}
• 状态：{session_info["state"]}
• 消息数：{session_info["message_count"]}
• 创建时间：{session_info.get("created_at", "")[:19] if session_info else ""}
• 最后活动：{session_info.get("last_activity_at", "")[:19] if session_info else ""}

{"💡 5分钟后30秒自动退出" if is_chat_mode else "使用 /chat 进入对话模式"}
""".strip()

        return status_msg
