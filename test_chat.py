#!/usr/bin/env python3
"""测试对话功能
验证 /chat、/quit 和对话模式的消息处理
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python path
sys.path.insert(0, str(Path(__file__).parent))


async def test_chat_commands():
    """测试对话命令"""
    print("=== 测试对话命令 ===")

    # 测试导入
    try:
        from server.bot.chat import ChatManager
        from loguru import logger

        logger.info("✓ 所有导入成功")
    except Exception as e:
        print(f"❌ 导入失败: {e}")
        return False

    # 创建测试聊天管理器
    chat_manager = ChatManager(
        workspace_path=Path("/Users/haiyuan/project/py/xbot"),
        llm_client=None,  # 暂时不需要 LLM
        memory_service=None,
    )

    print("\n=== 测试聊天管理器 ===")
    try:
        session = await chat_manager.enter_chat_mode(
            chat_id="test_chat",
            platform="test",
            welcome_message=False,
        )
        print(f"✓ 进入对话模式: {session.chat_id}")
        print(f"  状态: {session.state}")
        print(f"  消息数: {len(session.messages)}")
    except Exception as e:
        print(f"❌ 进入对话模式失败: {e}")
        return False

    # 测试发送消息
    print("\n=== 测试消息处理 ===")
    try:
        session.add_message(role="user", content="测试消息")
        print("✓ 添加了消息")
        print(f"当前消息数: {len(session.messages)}")

        # 测试会话状态检查
        print("\n=== 测试会话状态检查 ===")
        try:
            print(f"是否空闲: {session.is_idle}")
            print(f"是否活跃: {session.is_active}")
            print(f"是否超时: {session.is_timeout}")
            print(f"状态值: {session.state.value}")
        except Exception as e:
            print(f"❌ 状态检查失败: {e}")
            return False

        # 测试退出会话
        print("\n=== 测试退出对话 ===")
        try:
            await chat_manager._exit_chat_mode(chat_id="test_chat", reason="test")
            print("✅ 退出对话模式")
        except Exception as e:
            print(f"❌ 退出失败: {e}")
            return False
    except Exception as e:
        print(f"❌ 消息处理失败: {e}")
        return False

    print("\n=== 测试会话清理 ===")
    await chat_manager.cleanup_inactive_sessions(max_age_hours=0)
    print("✓ 清理完成")

    print("\n=== 所有测试通过！ ===")
    return True


async def test_telegram_bot():
    """测试 Telegram Bot 的消息发送功能"""
    print("=== 测试 Telegram Bot 消息发送 ===")

    # 模拟 Telegram Bot
    class MockBot:
        def __init__(self):
            self._messages_sent = []
            self._last_message = None

        async def send_message(self, text, chat_id, **kwargs):
            self._messages_sent.append({"text": text, "chat_id": chat_id})
            self._last_message = {"text": text, "chat_id": chat_id}
            return None

        async def send_markdown(self, text, chat_id, **kwargs):
            self._messages_sent.append(
                {"text": text, "chat_id": chat_id, "markdown": True}
            )

        async def send_chat_action(self, chat_id, action="typing"):
            pass  # 模拟发送 typing 动作

        async def get_me(self):
            return {"id": 1234567890}

    bot = MockBot()

    # 测试消息发送
    try:
        result = await bot.send_message("测试消息", chat_id="test_chat")
        print(f"发送纯文本消息: {result}")

        result = await bot.send_markdown("**测试 Markdown**", chat_id="test_chat")
        print(f"发送 Markdown 消息: {result}")

        # 测试聊天操作
        # 发送一条用户消息并检查
        test_message_count_before = len(bot._messages_sent)

        result = await bot.send_message("请帮我分析市场情况", chat_id="test_chat")
        print(f"发送分析请求: {result}")
        print(
            f"发送的纯文本消息数: {len(bot._messages_sent) - test_message_count_before}"
        )

    except Exception as e:
        print(f"❌ 消息发送失败: {e}")
        return False

    print("\n=== Telegram Bot 测试通过！ ===")
    return True


async def main():
    """主测试函数"""
    print("\n🚀 XBot 对话功能测试 🚀")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # 测试导入
    try:
        from loguru import logger

        logger.info("✓ 所有导入成功")
    except Exception as e:
        print(f"❌ 导入失败: {e}")
        return False

    # 运行测试
    test_result = await test_chat_commands()
    telegram_bot_result = await test_telegram_bot()

    if test_result and telegram_bot_result:
        print("\n✅ 所有测试通过！")
        return 0
    else:
        print("❌ 部分测试失败")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
