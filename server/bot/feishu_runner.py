"""Feishu bot runner - runs in a separate process to avoid asyncio conflicts."""

import json
import sys
from typing import Callable

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    P2ImMessageReceiveV1,
)


class FeishuBotRunner:
    """Standalone Feishu bot that runs in its own process."""

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._command_handlers: dict[str, Callable] = {}

        # Create Lark client
        self.client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )

    def send_text(self, chat_id: str, text: str) -> None:
        """Send a text message."""
        try:
            request = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("text")
                    .content(json.dumps({"text": text}))
                    .build()
                )
                .build()
            )

            response = self.client.im.v1.message.create(request)  # type: ignore[union-attr]
            if not response.success():
                print(f"[Feishu] Failed to send: {response.code} - {response.msg}")
        except Exception as e:
            print(f"[Feishu] Error sending message: {e}")

    def _handle_message(self, data: P2ImMessageReceiveV1) -> None:
        """Handle incoming message."""
        try:
            if not data.event or not data.event.message:
                return
            message = data.event.message
            msg_type = message.message_type

            if msg_type != "text":
                return

            content = json.loads(message.content or "{}")
            text = content.get("text", "").strip()

            # Remove @mention
            if text.startswith("@"):
                parts = text.split(maxsplit=1)
                text = parts[1] if len(parts) > 1 else ""

            print(f"[Feishu] Received: {text}")

            # Handle commands
            if text.startswith("/"):
                parts = text.split(maxsplit=1)
                command = parts[0][1:]
                self._handle_command(message.chat_id or "", command)

        except Exception as e:
            print(f"[Feishu] Error handling message: {e}")

    def _handle_command(self, chat_id: str, command: str) -> None:
        """Handle a command."""
        if command == "help":
            self.send_text(
                chat_id,
                """📖 XBot 命令帮助

/help — 显示此帮助信息
/status — 查看系统状态

更多功能请使用 Telegram 机器人""",
            )
        elif command == "start":
            self.send_text(
                chat_id,
                """👋 欢迎使用 XBot

我是一个情报聚合和分析机器人。
输入 /help 查看可用命令""",
            )
        elif command == "status":
            self.send_text(chat_id, "✅ XBot 飞书机器人运行中")
        else:
            self.send_text(chat_id, f"未知命令: /{command}\n输入 /help 查看可用命令")

    def run(self) -> None:
        """Start the WebSocket connection."""
        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._handle_message)
            .build()
        )

        ws_client = lark.ws.Client(
            app_id=self.app_id,
            app_secret=self.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        print("[Feishu] Starting WebSocket connection...")
        ws_client.start()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python feishu_runner.py <app_id> <app_secret>")
        sys.exit(1)

    app_id = sys.argv[1]
    app_secret = sys.argv[2]

    bot = FeishuBotRunner(app_id, app_secret)
    bot.run()
