"""
FreshBot (Feishu/Lark) 渠道实现
适配统一 Channel 接口
"""

import asyncio
import json
import threading
import re
from typing import Optional, List

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    P2ImMessageReceiveV1,
)

from loguru import logger

from .base import Channel, MessageLimit


def markdown_to_feishu_post(text: str, title: str = "") -> dict:
    """
    将 Telegram Markdown 文本转换为 Feishu Post (富文本) JSON

    处理：*bold*, _italic_, [text](url), 纯文本，段落
    """
    paragraphs = text.split("\n")
    content = []

    for line in paragraphs:
        if not line.strip():
            continue
        elements = _parse_markdown_line(line)
        if elements:
            content.append(elements)

    # 从第一个粗体文本中提取标题（如果未提供）
    if not title and content:
        for el in content[0]:
            if el.get("tag") == "text" and "bold" in el.get("style", []):
                title = el["text"].strip()
                break

    return {"zh_cn": {"title": title, "content": content}}


def _parse_markdown_line(line: str) -> List[dict]:
    """
    解析单行 Telegram Markdown 为 Feishu Post 元素

    匹配模式：[text](url), *bold*, _italic_, 或纯文本
    """
    elements = []
    # 模式匹配：[text](url), *bold*, _italic_ 或纯文本
    pattern = r"(\[([^\]]+)\]\(([^)]+)\)|\*([^*]+)\*|_([^_]+)_)"
    last_end = 0

    for match in re.finditer(pattern, line):
        # 添加此匹配前的纯文本
        if match.start() > last_end:
            plain = line[last_end : match.start()]
            if plain:
                elements.append({"tag": "text", "text": plain})
        if match.group(2) and match.group(3):
            # [text](url) → 链接
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

    # 添加剩余的纯文本
    if last_end < len(line):
        remaining = line[last_end:]
        if remaining:
            elements.append({"tag": "text", "text": remaining})

    return elements


class FeishuChannel(Channel):
    """FreshBot (Feishu/Lark) 渠道实现"""

    # Feishu 消息限制
    MAX_MESSAGE_LENGTH = 20000  # Feishu post 消息限制

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        admin_chat_ids: Optional[List[str]] = None,
        bot_name: str = "feishu",
    ):
        self._name = bot_name
        self._app_id = app_id
        self._app_secret = app_secret
        self._admin_chat_ids = admin_chat_ids or []
        self._command_handlers = {}
        self._ws_client = None
        self._own_loop = None
        self._ws_thread = None
        self._loop = None
        self._processed_message_ids = set()  # 去重重连消息
        self._enabled = bool(app_id) and bool(app_secret)

        # 创建 Lark 客户端（用于发送消息）
        self._client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )

        # 消息限制器
        self._limit = MessageLimit(
            max_length=self.MAX_MESSAGE_LENGTH, chunk_size=5000, chunk_delay=0.2
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def initialize(self) -> None:
        """初始化 Feishu WebSocket 连接"""
        if not self._enabled:
            logger.warning("Feishu bot not enabled (no credentials)")
            return

        await self._start_websocket()
        logger.info("Feishu bot initialized")

    async def _start_websocket(self) -> None:
        """启动 WebSocket 连接（在后台线程中）"""
        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._handle_message)
            .build()
        )

        self._ws_client = lark.ws.Client(
            app_id=self._app_id,
            app_secret=self._app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        def _run_ws():
            # Lark SDK 使用导入时获取的模块级 loop 变量
            # 主线程的 event loop。我们必须替换为新的 loop
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

    async def send_message(
        self, text: str, chat_id: Optional[str] = None, parse_mode: Optional[str] = None
    ) -> None:
        """发送纯文本消息（同步）"""
        target = chat_id or self._admin_chat_ids[0] if self._admin_chat_ids else None
        if not target:
            logger.error("No chat_id specified and no admin_chat_id configured")
            return

        try:
            request = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(target)
                    .msg_type("text")
                    .content(json.dumps({"text": text}))
                    .build()
                )
                .build()
            )

            response = self._client.im.v1.message.create(request)  # type: ignore
            if not response.success():
                logger.error(
                    f"Failed to send message: {response.code} - {response.msg}"
                )
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            raise

    async def send_markdown(
        self, text: str, chat_id: Optional[str] = None, escape: bool = False
    ) -> None:
        """发送 Markdown 格式消息（转换为富文本 post）"""
        target = chat_id or self._admin_chat_ids[0] if self._admin_chat_ids else None
        if not target:
            logger.error("No chat_id specified and no admin_chat_id configured")
            return

        try:
            post_content = markdown_to_feishu_post(text)
            request = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(target)
                    .msg_type("post")
                    .content(json.dumps(post_content))
                    .build()
                )
                .build()
            )

            response = self._client.im.v1.message.create(request)  # type: ignore
            if not response.success():
                logger.error(f"Failed to send post: {response.code} - {response.msg}")
        except Exception as e:
            logger.error(f"Error sending post: {e}")
            raise

    async def send_long_message(
        self, text: str, chat_id: Optional[str] = None, parse_mode: Optional[str] = None
    ) -> None:
        """发送长消息（Feishu post 限制较高，通常不需要分割）"""
        # Feishu post 消息限制很高，通常不需要分割
        # 如果消息特别长，可以拆分成多个 post
        MAX_POST_CHARS = 18000

        if len(text) <= MAX_POST_CHARS:
            await self.send_markdown(text, chat_id)
            return

        # 分割消息
        chunks = self._limit.split_message(text)
        for i, chunk in enumerate(chunks):
            await self.send_markdown(chunk, chat_id)
            if i < len(chunks) - 1:
                await asyncio.sleep(self._limit.chunk_delay)

    async def send_batch(
        self, messages: List[str], chat_id: Optional[str] = None, delay: float = 0.2
    ) -> None:
        """批量发送多条消息"""
        target = chat_id or self._admin_chat_ids[0] if self._admin_chat_ids else None
        if not target:
            logger.error("No chat_id specified and no admin_chat_id configured")
            return

        for i, msg in enumerate(messages):
            await self.send_markdown(msg, chat_id)
            if i < len(messages) - 1:
                await asyncio.sleep(delay)

    def owns_chat(self, chat_id: str) -> bool:
        """判断是否拥有指定的聊天"""
        # Feishu 使用 chat_id，类似 Telegram
        # 可以通过检查消息来源来判断
        return False

    def get_admin_chat_ids(self) -> List[str]:
        """获取管理员聊天 ID"""
        return self._admin_chat_ids.copy()

    async def shutdown(self) -> None:
        """优雅地关闭 WebSocket 连接"""
        if self._ws_client:
            try:
                loop = getattr(self, "_own_loop", None)
                if loop and not loop.is_closed():
                    loop.call_soon_threadsafe(loop.stop)
                logger.info("Feishu WebSocket connection stopped")
            except Exception as e:
                logger.warning(f"Error stopping Feishu WebSocket: {e}")

        # 停止线程
        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=5)

    async def health_check(self) -> bool:
        """健康检查"""
        if not self._enabled:
            return False
        try:
            # 检查 WebSocket 线程状态
            return bool(self._ws_thread and self._ws_thread.is_alive())
        except Exception as e:
            logger.warning(f"Feishu health check failed: {e}")
            return False

    def add_command_handler(self, command: str, handler) -> None:
        """添加命令处理器（向后兼容）"""
        self._command_handlers[command] = handler

    def _handle_message(self, data: P2ImMessageReceiveV1) -> None:
        """处理收到的消息事件（同步回调）"""
        try:
            if not data.event or not data.event.message:
                return

            message = data.event.message
            msg_id = message.message_id

            # 去重：跳过已处理的消息（重连时）
            if msg_id and msg_id in self._processed_message_ids:
                logger.debug(f"Skipping duplicate message: {msg_id}")
                return

            if msg_id:
                self._processed_message_ids.add(msg_id)
                # 限制缓存大小
                if len(self._processed_message_ids) > 5000:
                    self._processed_message_ids = set(
                        list(self._processed_message_ids)[-2500:]
                    )

            chat_id = message.chat_id
            msg_type = message.message_type

            # 只处理文本消息
            if msg_type != "text":
                return

            # 解析消息内容
            content = json.loads(message.content or "{}")
            text = content.get("text", "").strip()

            # 移除 @提及
            if text.startswith("@"):
                parts = text.split(maxsplit=1)
                text = parts[1] if len(parts) > 1 else ""

            logger.info(f"Received Feishu message from chat_id={chat_id}: {text}")

            # 内置 /chatid 命令
            if text == "/chatid":
                self._send_text_sync(chat_id or "", f"当前会话 chat_id:\n{chat_id}")
                return

            # 检查是否为命令
            if text.startswith("/"):
                parts = text.split(maxsplit=1)
                command = parts[0][1:]  # 移除 /
                args = parts[1] if len(parts) > 1 else ""

                if command in self._command_handlers:
                    handler = self._command_handlers[command]
                    # 在事件循环中运行异步处理器
                    self._run_async_handler(handler, chat_id or "", args)
                else:
                    self._send_text_sync(
                        chat_id or "", f"未知命令: /{command}\n输入 /help 查看可用命令"
                    )

        except Exception as e:
            logger.error(f"Error handling Feishu message: {e}")

    def _send_text_sync(self, chat_id: str, text: str) -> None:
        """同步发送文本消息（用于 WebSocket 回调）"""
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

            response = self._client.im.v1.message.create(request)  # type: ignore
            if not response.success():
                logger.error(
                    f"Failed to send message: {response.code} - {response.msg}"
                )
        except Exception as e:
            logger.error(f"Error sending message: {e}")

    def _run_async_handler(self, handler, chat_id: str, args: str) -> None:
        """在事件循环中运行异步命令处理器"""
        loop = getattr(self, "_own_loop", None)
        if loop is None or loop.is_closed():
            logger.error("No event loop available for async handler")
            self._send_text_sync(chat_id, "❌ 内部错误：事件循环不可用")
            return

        try:
            future = asyncio.run_coroutine_threadsafe(
                handler({"chat_id": chat_id, "args": args}),
                loop,
            )
            # 设置超时
            loop.run_until_complete(asyncio.wait_for(future, timeout=120))  # type: ignore
        except asyncio.TimeoutError:
            logger.error(f"Async handler timed out: {handler.__name__}")
            self._send_text_sync(chat_id, "❌ 请求超时，请稍后再试")
        except Exception as e:
            logger.error(f"Async handler failed ({handler.__name__}): {e}")
            self._send_text_sync(chat_id, f"❌ 处理失败: {str(e)[:100]}")


# 全局实例（向后兼容）
_feishu_instance: Optional[FeishuChannel] = None


def get_feishu_channel(
    app_id: str, app_secret: str, admin_chat_ids: Optional[List[str]] = None
) -> FeishuChannel:
    """获取或创建全局 Feishu 渠道实例"""
    global _feishu_instance
    if _feishu_instance is None:
        _feishu_instance = FeishuChannel(
            app_id=app_id,
            app_secret=app_secret,
            admin_chat_ids=admin_chat_ids,
            bot_name="feishu",
        )
    return _feishu_instance
