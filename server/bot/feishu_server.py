"""FastAPI server for Feishu bot event callbacks."""

from typing import Optional

from fastapi import FastAPI, Request, Header
from loguru import logger

from server.bot.feishu import FeishuBot


class FeishuServer:
    """HTTP server for handling Feishu bot events."""

    def __init__(self, bot: FeishuBot):
        self.bot = bot
        self.app = FastAPI(title="XBot Feishu Server")

        # Register routes
        self.app.post("/feishu/event")(self.handle_event)
        self.app.get("/health")(self.health_check)

    async def handle_event(
        self,
        request: Request,
        x_lark_request_timestamp: Optional[str] = Header(None),
        x_lark_request_nonce: Optional[str] = Header(None),
        x_lark_signature: Optional[str] = Header(None),
    ):
        """Handle incoming event from Feishu.

        Args:
            request: FastAPI request object
            x_lark_request_timestamp: Request timestamp header
            x_lark_request_nonce: Request nonce header
            x_lark_signature: Request signature header

        Returns:
            Response dict
        """
        try:
            body = await request.json()
            logger.debug(
                f"Received Feishu event: {body.get('header', {}).get('event_type')}"
            )

            # Verify signature if configured
            if self.bot.verification_token and x_lark_signature:
                if not self.bot.verify_signature(
                    x_lark_request_timestamp or "",
                    x_lark_request_nonce or "",
                    "",  # encrypt (empty if not encrypted)
                    x_lark_signature,
                ):
                    logger.warning("Invalid signature from Feishu")
                    return {"error": "Invalid signature"}

            # Handle event
            response = await self.bot.handle_event(body)
            return response

        except Exception as e:
            logger.error(f"Error handling Feishu event: {e}")
            return {"error": str(e)}

    async def health_check(self):
        """Health check endpoint."""
        return {"status": "ok", "service": "xbot-feishu"}


def create_feishu_server(bot: FeishuBot) -> FastAPI:
    """Create FastAPI app for Feishu bot.

    Args:
        bot: FeishuBot instance

    Returns:
        FastAPI app
    """
    server = FeishuServer(bot)
    return server.app
