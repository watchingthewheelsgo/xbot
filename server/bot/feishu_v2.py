"""Feishu (Lark) Bot using official SDK with WebSocket long connection."""

import asyncio
import json
import re
import threading
from typing import Optional, Callable, Awaitable

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    P2ImMessageReceiveV1,
)
from loguru import logger

from server.settings import global_settings


def markdown_to_feishu_post(text: str, title: str = "") -> dict:
    """Convert Telegram Markdown text to Feishu post (rich text) JSON.

    Handles: *bold*, _italic_, [text](url), plain text, paragraphs.
    """
    paragraphs = text.split("\n")
    content = []

    for line in paragraphs:
        if not line.strip():
            continue
        elements = _parse_markdown_line(line)
        if elements:
            content.append(elements)

    # Extract title from first bold text if not provided
    if not title and content:
        for el in content[0]:
            if el.get("tag") == "text" and "bold" in el.get("style", []):
                title = el["text"].strip()
                break

    return {"zh_cn": {"title": title, "content": content}}


def _parse_markdown_line(line: str) -> list[dict]:
    """Parse a single line of Telegram Markdown into Feishu post elements."""
    elements = []
    # Pattern matches: [text](url), *bold*, _italic_, or plain text
    pattern = r"(\[([^\]]+)\]\(([^)]+)\)|\*([^*]+)\*|_([^_]+)_)"
    last_end = 0

    for match in re.finditer(pattern, line):
        # Add plain text before this match
        if match.start() > last_end:
            plain = line[last_end : match.start()]
            if plain:
                elements.append({"tag": "text", "text": plain})

        if match.group(2) and match.group(3):
            # [text](url) → link
            elements.append(
                {"tag": "a", "text": match.group(2), "href": match.group(3)}
            )
        elif match.group(4):
            # *bold*
            elements.append({"tag": "text", "text": match.group(4), "style": ["bold"]})
        elif match.group(5):
            # _italic_
            elements.append(
                {"tag": "text", "text": match.group(5), "style": ["italic"]}
            )

        last_end = match.end()

    # Add remaining plain text
    if last_end < len(line):
        remaining = line[last_end:]
        if remaining:
            elements.append({"tag": "text", "text": remaining})

    return elements


class FeishuBotV2:
    """Feishu bot using official SDK with WebSocket long connection (no public URL needed)."""

    def __init__(
        self, app_id: str, app_secret: str, admin_chat_ids: list[str] | None = None
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.admin_chat_ids = admin_chat_ids or []
        self._command_handlers: dict[str, Callable] = {}
        self._ws_client = None
        self._own_loop: asyncio.AbstractEventLoop | None = None
        self._ws_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._processed_message_ids: set[str] = set()  # Dedup reconnect replays

        # Create Lark client for sending messages
        self.client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )

        logger.info("Feishu bot initialized with official SDK")

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Store reference to the main asyncio event loop for cross-thread calls."""
        self._loop = loop

    def add_command(
        self,
        command: str,
        handler: Callable[[dict], Awaitable[str]],
    ) -> None:
        """Register a command handler."""
        self._command_handlers[command] = handler
        logger.debug(f"Registered Feishu command: /{command}")

    def send_text(self, chat_id: str, text: str) -> None:
        """Send a text message to a chat (synchronous)."""
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
                logger.error(
                    f"Failed to send message: {response.code} - {response.msg}"
                )
            else:
                logger.debug(f"Message sent to {chat_id}")

        except Exception as e:
            logger.error(f"Error sending message: {e}")

    def send_post(self, chat_id: str, text: str, title: str = "") -> None:
        """Send a rich text (post) message, converting Telegram Markdown to Feishu format."""
        try:
            post_content = markdown_to_feishu_post(text, title=title)

            request = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("post")
                    .content(json.dumps(post_content))
                    .build()
                )
                .build()
            )

            response = self.client.im.v1.message.create(request)  # type: ignore[union-attr]

            if not response.success():
                logger.error(f"Failed to send post: {response.code} - {response.msg}")
                # Fallback to plain text
                self.send_text(chat_id, text)
            else:
                logger.debug(f"Post message sent to {chat_id}")

        except Exception as e:
            logger.error(f"Error sending post message: {e}")
            # Fallback to plain text
            self.send_text(chat_id, text)

    async def send_to_admin(self, text: str, parse_mode: Optional[str] = None) -> None:
        """Send a push notification to all admin chats (async, for scheduler use)."""
        if not self.admin_chat_ids:
            logger.warning(
                "No feishu_admin_chat_id configured, cannot send admin message"
            )
            return
        loop = asyncio.get_event_loop()
        for chat_id in self.admin_chat_ids:
            await loop.run_in_executor(None, self.send_post, chat_id, text, "")

    def _handle_message(self, data: P2ImMessageReceiveV1) -> None:
        """Handle incoming message event (synchronous callback from SDK)."""
        try:
            if not data.event or not data.event.message:
                return
            message = data.event.message

            # Dedup: skip messages already processed (replayed after reconnect)
            msg_id = message.message_id
            if msg_id and msg_id in self._processed_message_ids:
                logger.debug(f"Skipping duplicate message: {msg_id}")
                return
            if msg_id:
                self._processed_message_ids.add(msg_id)
                # Limit cache size
                if len(self._processed_message_ids) > 5000:
                    self._processed_message_ids = set(
                        list(self._processed_message_ids)[-2500:]
                    )

            chat_id = message.chat_id
            msg_type = message.message_type

            # Only handle text messages
            if msg_type != "text":
                return

            # Parse message content
            content = json.loads(message.content or "{}")
            text = content.get("text", "").strip()

            # Remove @mention if present
            if text.startswith("@"):
                parts = text.split(maxsplit=1)
                text = parts[1] if len(parts) > 1 else ""

            logger.info(f"Received Feishu message from chat_id={chat_id}: {text}")

            # Built-in /chatid command — returns current chat_id
            if text == "/chatid":
                self.send_text(chat_id or "", f"当前会话 chat_id:\n{chat_id}")
                return

            # Check if it's a command
            if text.startswith("/"):
                parts = text.split(maxsplit=1)
                command = parts[0][1:]  # Remove leading /
                args = parts[1] if len(parts) > 1 else ""

                if command in self._command_handlers:
                    handler = self._command_handlers[command]
                    self._run_async_handler(handler, chat_id or "", args)
                else:
                    self.send_text(
                        chat_id or "", f"未知命令: /{command}\n输入 /help 查看可用命令"
                    )

        except Exception as e:
            logger.error(f"Error handling Feishu message: {e}")

    def _run_async_handler(self, handler: Callable, chat_id: str, args: str) -> None:
        """Run an async command handler from the sync SDK callback thread."""
        if self._loop is None or self._loop.is_closed():
            logger.error("No event loop available for async handler")
            self.send_text(chat_id, "❌ 内部错误：事件循环不可用")
            return

        future = asyncio.run_coroutine_threadsafe(
            handler({"chat_id": chat_id, "args": args}),
            self._loop,
        )

        try:
            response = future.result(timeout=120)
            if response:
                self.send_post(chat_id, response)
        except TimeoutError:
            logger.error(f"Async handler timed out: {handler.__name__}")
            self.send_text(chat_id, "❌ 请求超时，请稍后再试")
        except Exception as e:
            logger.error(f"Async handler failed ({handler.__name__}): {e}")
            self.send_text(chat_id, f"❌ 处理失败: {str(e)[:100]}")

    def start_in_thread(self) -> None:
        """Start WebSocket connection in a background daemon thread."""
        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._handle_message)
            .build()
        )

        self._ws_client = lark.ws.Client(
            app_id=self.app_id,
            app_secret=self.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        def _run_ws():
            # The lark SDK uses a module-level `loop` variable grabbed at import time,
            # which is the main thread's event loop. We must replace it with a fresh
            # loop owned by this thread, otherwise run_until_complete() fails with
            # "This event loop is already running".
            import lark_oapi.ws.client as ws_mod

            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            ws_mod.loop = new_loop
            self._own_loop = new_loop
            if self._ws_client:
                try:
                    self._ws_client.start()
                except Exception as e:
                    logger.error(f"Feishu WebSocket error: {e}")

        self._ws_thread = threading.Thread(
            target=_run_ws,
            name="feishu-ws",
            daemon=True,
        )
        self._ws_thread.start()
        logger.info("Feishu WebSocket started in background thread")

    def stop(self) -> None:
        """Stop the WebSocket connection."""
        if self._ws_client:
            try:
                loop = getattr(self, "_own_loop", None)
                if loop and loop.is_running():
                    loop.call_soon_threadsafe(loop.stop)
                logger.info("Feishu WebSocket connection stopped")
            except Exception as e:
                logger.warning(f"Error stopping Feishu WebSocket: {e}")


# Global bot instance
feishu_bot_v2: Optional[FeishuBotV2] = None


def get_feishu_bot_v2() -> Optional[FeishuBotV2]:
    """Get or create the global Feishu bot instance."""
    global feishu_bot_v2
    if feishu_bot_v2 is None and global_settings.feishu_app_id:
        feishu_bot_v2 = FeishuBotV2(
            app_id=global_settings.feishu_app_id,
            app_secret=global_settings.feishu_app_secret,
            admin_chat_ids=global_settings.get_feishu_admin_chat_ids(),
        )
    return feishu_bot_v2
