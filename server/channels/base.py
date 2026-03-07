"""
统一消息渠道基类
抽象不同平台的消息发送逻辑
"""

from abc import ABC, abstractmethod
from typing import Optional, List


class Channel(ABC):
    """
    统一消息渠道抽象接口
    所有渠道（Telegram、FreshBot等）必须实现此接口
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """渠道名称，如 'telegram'、'feishu'"""
        pass

    @property
    @abstractmethod
    def enabled(self) -> bool:
        """渠道是否已启用"""
        pass

    @abstractmethod
    async def initialize(self) -> None:
        """
        初始化渠道
        建立连接、加载配置等
        """
        pass

    @abstractmethod
    async def send_message(
        self, text: str, chat_id: Optional[str] = None, parse_mode: Optional[str] = None
    ) -> None:
        """
        发送纯文本消息

        Args:
            text: 消息文本
            chat_id: 目标聊天ID，如果为None则使用默认目标
            parse_mode: 解析模式（如 Markdown、HTML）
        """
        pass

    @abstractmethod
    async def send_markdown(
        self, text: str, chat_id: Optional[str] = None, escape: bool = False
    ) -> None:
        """
        发送 Markdown 格式消息

        Args:
            text: Markdown 格式的消息文本
            chat_id: 目标聊天ID
            escape: 是否自动转义特殊字符
        """
        pass

    @abstractmethod
    async def send_long_message(
        self, text: str, chat_id: Optional[str] = None, parse_mode: Optional[str] = None
    ) -> None:
        """
        发送长消息，自动分割以符合平台限制

        Args:
            text: 可能很长的消息文本
            chat_id: 目标聊天ID
            parse_mode: 解析模式
        """
        pass

    @abstractmethod
    async def send_batch(
        self, messages: List[str], chat_id: Optional[str] = None, delay: float = 0.1
    ) -> None:
        """
        批量发送多条消息

        Args:
            messages: 消息列表
            chat_id: 目标聊天ID
            delay: 每条消息之间的延迟（秒）
        """
        pass

    @abstractmethod
    def owns_chat(self, chat_id: str) -> bool:
        """
        判断此渠道是否拥有指定的聊天

        Args:
            chat_id: 要检查的聊天ID

        Returns:
            True 如果此渠道管理该聊天
        """
        pass

    @abstractmethod
    def get_admin_chat_ids(self) -> List[str]:
        """
        获取此渠道管理的所有管理员聊天ID

        Returns:
            管理员聊天ID列表
        """
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """
        优雅地关闭渠道
        断开连接、清理资源等
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        健康检查，验证渠道是否正常工作

        Returns:
            True 如果渠道运行正常
        """
        pass


class MessageLimit:
    """消息限制配置"""

    def __init__(
        self, max_length: int = 4096, chunk_size: int = 2000, chunk_delay: float = 0.1
    ):
        self.max_length = max_length
        self.chunk_size = chunk_size
        self.chunk_delay = chunk_delay

    def split_message(self, text: str) -> List[str]:
        """
        将长消息分割为符合限制的多个块

        Args:
            text: 要分割的消息文本

        Returns:
            分割后的消息块列表
        """
        if len(text) <= self.max_length:
            return [text]

        chunks = []
        current = ""

        # 按段落分割
        paragraphs = text.split("\n\n")

        for para in paragraphs:
            # 如果添加此段落会超限
            if len(current) + len(para) + 2 > self.max_length:
                if current:
                    chunks.append(current.strip())
                    current = ""
                # 如果单个段落太长，按行分割
                if len(para) > self.max_length:
                    lines = para.split("\n")
                    for line in lines:
                        if len(current) + len(line) + 1 > self.max_length:
                            if current:
                                chunks.append(current.strip())
                                current = line
                            else:
                                current = f"{current}\n{line}"
                        else:
                            current = f"{current}\n\n{para}" if current else para
                else:
                    current = para
            else:
                current = f"{current}\n\n{para}" if current else para

        if current:
            chunks.append(current.strip())

        return chunks
