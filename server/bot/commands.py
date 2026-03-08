"""
对话模式命令处理器
实现 /chat 和 /quit 命令
"""

import time
from datetime import datetime
from typing import TYPE_CHECKING
from loguru import logger

from server.bot.chat import ChatManager

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes
    from server.bot.telegram import TelegramBot


class ChatCommandHandlers:
    """对话模式命令处理器"""

    def __init__(
        self,
        bot: "TelegramBot",
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

    async def handle_chat(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """处理 /chat 命令 - 进入对话模式"""
        if not update.effective_chat or not update.message:
            return

        chat_id = str(update.effective_chat.id)
        user = update.effective_user
        user_name = user.first_name or user.username or "User" if user else "User"

        logger.info(f"/chat command from {user_name} in {chat_id}")

        start_time = time.time()

        try:
            # 进入对话模式
            await self.chat_manager.enter_chat_mode(
                chat_id=chat_id,
                platform="telegram",
                welcome_message=True,
            )

            # 获取会话状态
            session_info = await self.chat_manager.get_session_info(chat_id)

            status_msg = f"""
✅ **对话模式已开启**

📊 会话信息：
• 状态：{session_info["state"] if session_info else "unknown"}
• 消息数：{session_info["message_count"] if session_info else 0}
• 创建时间：{session_info.get("created_at", "")[:16] if session_info else ""}

💡 使用方法：
• 直接发送消息即可开始对话
• 我会记住上下文并回答问题
• /quit 退出对话模式
• 5分钟无新消息后30秒自动退出
""".strip()

            await self.bot.send_markdown(status_msg, chat_id)

            elapsed = time.time() - start_time
            logger.info(f"/chat command completed in {elapsed:.2f}s")

        except Exception as e:
            logger.error(f"/chat command failed: {e}")
            await self.bot.send_message(f"❌ 开启对话模式失败：{str(e)[:100]}", chat_id)

    async def handle_quit(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """处理 /quit 命令 - 退出对话模式"""
        if not update.effective_chat or not update.message:
            return

        chat_id = str(update.effective_chat.id)
        user = update.effective_user
        user_name = user.first_name or user.username or "User" if user else "User"

        logger.info(f"/quit command from {user_name} in {chat_id}")

        if not self.chat_manager.is_in_chat_mode(chat_id):
            await self.bot.send_message("❌ 当前不在对话模式", chat_id)
            return

        start_time = time.time()

        try:
            # 退出对话模式
            await self.chat_manager._exit_chat_mode(chat_id, reason="user")

            # 获取最终会话状态
            session_info = await self.chat_manager.get_session_info(chat_id)

            summary_msg = f"""
👋 **对话模式已退出**

📊 会话总结：
• 消息数：{session_info["message_count"] if session_info else 0}
• 会话时长：{(datetime.now().isoformat()[:16] if session_info else "")}
• 上下文已保存到记忆

💡 再次使用 /chat 进入新的对话
""".strip()

            await self.bot.send_markdown(summary_msg, chat_id)

            elapsed = time.time() - start_time
            logger.info(f"/quit command completed in {elapsed:.2f}s")

        except Exception as e:
            logger.error(f"/quit command failed: {e}")
            await self.bot.send_message(f"❌ 退出失败：{str(e)[:100]}", chat_id)

    async def handle_chat_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """处理 /chatstatus 命令 - 查看对话状态"""
        if not update.effective_chat or not update.message:
            return

        chat_id = str(update.effective_chat.id)

        session_info = await self.chat_manager.get_session_info(chat_id)

        if not session_info:
            await self.bot.send_message("❌ 当前没有活跃的对话会话", chat_id)
            return

        is_chat_mode = self.chat_manager.is_in_chat_mode(chat_id)

        status_msg = f"""
📊 **对话状态**

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

        await self.bot.send_markdown(status_msg, chat_id)
