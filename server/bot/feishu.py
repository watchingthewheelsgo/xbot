"""Feishu (Lark) Bot with command handling and message support."""

import hashlib
import hmac
import json
from typing import Optional, Callable, Awaitable

import httpx
from loguru import logger

from server.settings import global_settings


class FeishuBot:
    """Feishu bot with command handling and push notification support."""

    def __init__(
        self, app_id: str, app_secret: str, verification_token: Optional[str] = None
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.verification_token = verification_token
        self._access_token: Optional[str] = None
        self._command_handlers: dict[str, Callable] = {}
        self._client = httpx.AsyncClient(timeout=30.0)

    async def get_access_token(self) -> str:
        """Get tenant access token."""
        if self._access_token:
            return self._access_token

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret,
        }

        try:
            resp = await self._client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") == 0:
                self._access_token = data["tenant_access_token"]
                logger.info("Feishu access token obtained")
                return self._access_token  # type: ignore[return-value]
            else:
                logger.error(f"Failed to get access token: {data}")
                raise Exception(f"Failed to get access token: {data.get('msg')}")
        except Exception as e:
            logger.error(f"Error getting access token: {e}")
            raise

    async def send_message(
        self,
        chat_id: str,
        content: dict,
        msg_type: str = "text",
    ) -> None:
        """Send a message to a chat.

        Args:
            chat_id: Chat ID (open_chat_id)
            content: Message content (format depends on msg_type)
            msg_type: Message type (text, post, interactive, etc.)
        """
        token = await self.get_access_token()
        url = "https://open.feishu.cn/open-apis/im/v1/messages"

        params = {"receive_id_type": "chat_id"}
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "receive_id": chat_id,
            "msg_type": msg_type,
            "content": json.dumps(content),
        }

        try:
            resp = await self._client.post(
                url, params=params, headers=headers, json=payload
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                logger.error(f"Failed to send message: {data}")
                raise Exception(f"Failed to send message: {data.get('msg')}")

            logger.debug(f"Message sent to {chat_id}")
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            raise

    async def send_text(self, chat_id: str, text: str) -> None:
        """Send a plain text message."""
        content = {"text": text}
        await self.send_message(chat_id, content, msg_type="text")

    async def send_markdown(self, chat_id: str, title: str, content: str) -> None:
        """Send a markdown message (post format).

        Args:
            chat_id: Chat ID
            title: Message title
            content: Markdown content
        """
        post_content = {
            "zh_cn": {
                "title": title,
                "content": [[{"tag": "text", "text": content}]],
            }
        }
        await self.send_message(chat_id, post_content, msg_type="post")

    async def send_rich_text(self, chat_id: str, title: str, elements: list) -> None:
        """Send a rich text message with formatted elements.

        Args:
            chat_id: Chat ID
            title: Message title
            elements: List of content elements (text, links, etc.)
        """
        post_content = {"zh_cn": {"title": title, "content": [elements]}}
        await self.send_message(chat_id, post_content, msg_type="post")

    def add_command(
        self,
        command: str,
        handler: Callable[[dict], Awaitable[str]],
    ) -> None:
        """Register a command handler.

        Args:
            command: Command name (without /)
            handler: Async function that takes event dict and returns response text
        """
        self._command_handlers[command] = handler
        logger.debug(f"Registered Feishu command: /{command}")

    async def handle_event(self, event: dict) -> dict:
        """Handle incoming event from Feishu.

        Args:
            event: Event data from Feishu

        Returns:
            Response dict
        """
        # URL verification challenge
        if event.get("type") == "url_verification":
            return {"challenge": event.get("challenge")}

        # Event callback
        if event.get("header", {}).get("event_type") == "im.message.receive_v1":
            return await self._handle_message(event)

        return {}

    async def _handle_message(self, event: dict) -> dict:
        """Handle incoming message event."""
        try:
            event_data = event.get("event", {})
            message = event_data.get("message", {})
            sender = event_data.get("sender", {})
            chat_id = message.get("chat_id")
            content_str = message.get("content", "{}")

            # Parse message content
            content = json.loads(content_str)
            text = content.get("text", "").strip()

            logger.info(
                f"Received message from {sender.get('sender_id', {}).get('user_id')}: {text}"
            )

            # Check if it's a command
            if text.startswith("/"):
                parts = text.split(maxsplit=1)
                command = parts[0][1:]  # Remove leading /
                args = parts[1] if len(parts) > 1 else ""

                if command in self._command_handlers:
                    handler = self._command_handlers[command]
                    response = await handler(
                        {"chat_id": chat_id, "args": args, "event": event_data}
                    )

                    if response:
                        await self.send_text(chat_id, response)
                else:
                    await self.send_text(
                        chat_id, f"未知命令: /{command}\n输入 /help 查看可用命令"
                    )

            return {}

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            return {}

    def verify_signature(
        self, timestamp: str, nonce: str, encrypt: str, signature: str
    ) -> bool:
        """Verify request signature from Feishu.

        Args:
            timestamp: Request timestamp
            nonce: Request nonce
            encrypt: Encrypted body (empty string if not encrypted)
            signature: Signature to verify

        Returns:
            True if signature is valid
        """
        if not self.verification_token:
            return True  # Skip verification if no token configured

        # Concatenate timestamp + nonce + encrypt + token
        content = f"{timestamp}{nonce}{encrypt}{self.verification_token}"
        computed = hashlib.sha256(content.encode()).hexdigest()

        return hmac.compare_digest(computed, signature)

    async def close(self) -> None:
        """Close HTTP client."""
        await self._client.aclose()


# Global bot instance
feishu_bot: Optional[FeishuBot] = None


def get_feishu_bot() -> Optional[FeishuBot]:
    """Get or create the global Feishu bot instance."""
    global feishu_bot
    if feishu_bot is None and global_settings.feishu_app_id:
        feishu_bot = FeishuBot(
            app_id=global_settings.feishu_app_id,
            app_secret=global_settings.feishu_app_secret,
            verification_token=global_settings.feishu_verification_token,
        )
    return feishu_bot
