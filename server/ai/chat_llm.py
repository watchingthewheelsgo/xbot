"""
Chat LLM - 专门用于对话场景的 LLM 客户端

特性：
- 独立的系统提示词
- 对话历史管理
- 上下文摘要功能
- 可配置的对话行为
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger
from server.ai.llm import LLM
from server.ai.schema import Message


@dataclass
class ChatMessage:
    """对话消息记录"""

    role: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Optional[Dict[str, Any]] = None

    def to_message(self) -> Message:
        """转换为 Message 对象"""
        if self.role == "user":
            return Message.user_message(self.content)
        elif self.role == "assistant":
            return Message.assistant_message(self.content)
        elif self.role == "system":
            return Message.system_message(self.content)
        else:
            return Message(role=self.role, content=self.content)  # type: ignore


class ConversationMemory:
    """对话记忆管理器"""

    def __init__(
        self,
        max_messages: int = 50,
        max_context_chars: int = 8000,
        enable_summarization: bool = True,
    ):
        self.max_messages = max_messages
        self.max_context_chars = max_context_chars
        self.enable_summarization = enable_summarization
        self.messages: List[ChatMessage] = []
        self.summary: Optional[str] = None

    def add_message(
        self, role: str, content: str, metadata: Optional[Dict] = None
    ) -> None:
        """添加消息到记忆"""
        message = ChatMessage(role=role, content=content, metadata=metadata)
        self.messages.append(message)

        # 如果消息数量超过限制，可能需要摘要
        if len(self.messages) > self.max_messages:
            self._trim_messages()

    def add_user_message(self, content: str, metadata: Optional[Dict] = None) -> None:
        """添加用户消息"""
        self.add_message("user", content, metadata)

    def add_assistant_message(
        self, content: str, metadata: Optional[Dict] = None
    ) -> None:
        """添加助手消息"""
        self.add_message("assistant", content, metadata)

    def get_recent_messages(self, n: int = 20) -> List[ChatMessage]:
        """获取最近的 n 条消息"""
        return self.messages[-n:]

    def get_context_messages(self, include_summary: bool = True) -> List[Message]:
        """
        获取上下文消息用于 LLM 调用

        Returns:
            List[Message]: 适合 LLM 使用的消息列表
        """
        messages: List[Message] = []

        # 如果有摘要且需要包含
        if self.summary and include_summary:
            messages.append(Message.assistant_message(f"[对话摘要]\n{self.summary}"))

        # 添加最近的消息
        for msg in self.get_recent_messages(self.max_messages):
            messages.append(msg.to_message())

        return messages

    def get_messages_for_llm(
        self, max_history: int = 20, system_prompt: Optional[str] = None
    ) -> List[Message]:
        """
        获取适合 LLM 使用的消息列表

        Args:
            max_history: 最大历史消息数
            system_prompt: 系统提示词（会作为第一条消息）

        Returns:
            List[Message]: LLM 消息列表
        """
        messages: List[Message] = []

        # 添加系统提示词
        if system_prompt:
            messages.append(Message.system_message(system_prompt))

        # 如果有摘要，先添加摘要
        if self.summary:
            messages.append(
                Message.assistant_message(f"[历史对话摘要]\n{self.summary}")
            )

        # 添加最近的消息
        recent = self.get_recent_messages(max_history)
        for msg in recent:
            messages.append(msg.to_message())

        return messages

    async def summarize(self, llm: LLM, max_summary_chars: int = 500) -> Optional[str]:
        """
        使用 LLM 生成对话摘要

        Args:
            llm: LLM 客户端
            max_summary_chars: 最大摘要字符数

        Returns:
            Optional[str]: 生成的摘要
        """
        if not self.enable_summarization or len(self.messages) < 4:
            return None

        try:
            # 获取需要摘要的消息（保留最近 4 条不摘要）
            to_summarize = self.messages[:-4] if len(self.messages) > 4 else []
            if not to_summarize:
                return self.summary

            # 构建摘要 prompt
            chat_text = "\n".join(f"{msg.role}: {msg.content}" for msg in to_summarize)

            prompt = f"""请将以下对话内容摘要为 {max_summary_chars} 字符以内的简洁总结，保留关键信息：

{chat_text}

请用中文回复，只输出摘要内容。"""

            summary = await llm.ask(
                messages=[Message.user_message(prompt)],
                system_msgs=[Message.system_message("你是一个对话摘要专家。")],
                stream=False,
                temperature=0.5,
            )

            self.summary = summary[:max_summary_chars]
            logger.info(f"Generated conversation summary: {len(self.summary)} chars")

            return self.summary

        except Exception as e:
            logger.error(f"Failed to summarize conversation: {e}")
            return None

    def _trim_messages(self) -> None:
        """修剪消息列表"""
        if len(self.messages) > self.max_messages:
            # 先尝试生成摘要
            if self.enable_summarization:
                to_keep = 6  # 保留最近 6 条
                self.messages = self.messages[-to_keep:]
                logger.info(
                    f"Trimmed messages, keeping {len(self.messages)} recent messages"
                )
            else:
                self.messages = self.messages[-self.max_messages :]

    def clear(self) -> None:
        """清空记忆"""
        self.messages.clear()
        self.summary = None

    def get_message_count(self) -> int:
        """获取消息数量"""
        return len(self.messages)

    def get_context_size(self) -> int:
        """获取上下文字符数（估算）"""
        return sum(len(msg.content) for msg in self.messages)

    def to_dict(self) -> Dict[str, Any]:
        """导出为字典（用于持久化）"""
        return {
            "messages": [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat(),
                    "metadata": msg.metadata,
                }
                for msg in self.messages
            ],
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationMemory":
        """从字典加载（用于持久化）"""
        memory = cls()
        for msg_data in data.get("messages", []):
            try:
                timestamp = datetime.fromisoformat(msg_data["timestamp"])
                message = ChatMessage(
                    role=msg_data["role"],
                    content=msg_data["content"],
                    timestamp=timestamp,
                    metadata=msg_data.get("metadata"),
                )
                memory.messages.append(message)
            except Exception as e:
                logger.warning(f"Failed to load message: {e}")
        memory.summary = data.get("summary")
        return memory


class ChatLLM:
    """
    专门用于对话场景的 LLM 客户端

    特点：
    - 预设的系统提示词
    - 独立的对话记忆
    - 自动摘要长对话
    - 可配置的对话行为
    """

    DEFAULT_SYSTEM_PROMPT = """你是 XBot，一个专业的金融信息聚合和分析助手。

你的特点：
- 专业、准确、乐于助人
- 可以回答金融、市场、经济相关的问题
- 支持多轮对话，会记住上下文
- 对于不确定的信息会诚实说明

回复时请：
- 使用简洁清晰的语言
- 适当使用表情符号增加亲和力
- 对重要信息进行强调
- 必要时提供相关数据或建议
"""

    def __init__(
        self,
        llm: Optional[LLM] = None,
        system_prompt: Optional[str] = None,
        max_history: int = 20,
        max_context_chars: int = 12000,
        enable_summarization: bool = True,
    ):
        """
        初始化 ChatLLM

        Args:
            llm: 底层 LLM 客户端
            system_prompt: 系统提示词
            max_history: 最大历史消息数
            max_context_chars: 最大上下文字符数
            enable_summarization: 是否启用自动摘要
        """
        self.llm = llm or LLM()
        self.system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT
        self.memory = ConversationMemory(
            max_messages=max_history * 2,  # 存储更多消息用于摘要
            max_context_chars=max_context_chars,
            enable_summarization=enable_summarization,
        )
        self.max_history = max_history

        # 统计信息
        self.total_calls = 0
        self.total_tokens = 0

    async def chat(
        self,
        user_message: str,
        metadata: Optional[Dict[str, Any]] = None,
        stream: bool = False,
        temperature: Optional[float] = None,
    ) -> str:
        """
        发送用户消息并获取回复

        Args:
            user_message: 用户消息
            metadata: 消息元数据
            stream: 是否流式输出
            temperature: 温度参数

        Returns:
            str: 助手回复
        """
        # 添加用户消息到记忆
        self.memory.add_user_message(user_message, metadata)

        # 获取上下文消息
        messages = self.memory.get_messages_for_llm(
            max_history=self.max_history,
            system_prompt=self.system_prompt,
        )

        try:
            # 调用 LLM
            response = await self.llm.ask(
                messages=messages,  # type: ignore
                stream=stream,
                temperature=temperature,
            )

            # 添加助手回复到记忆
            self.memory.add_assistant_message(response)

            # 更新统计
            self.total_calls += 1
            self.total_tokens += self.llm.count_tokens(user_message + response)

            # 检查是否需要摘要
            if self.memory.get_message_count() > self.max_history * 1.5:
                await self.memory.summarize(self.llm)

            return response

        except Exception as e:
            logger.error(f"Chat failed: {e}")
            raise

    async def chat_with_context(
        self,
        user_message: str,
        context: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        带额外上下文的对话

        Args:
            user_message: 用户消息
            context: 上下文信息（如市场数据、新闻等）
            metadata: 消息元数据

        Returns:
            str: 助手回复
        """
        # 构建增强的提示词
        context_prompt = self.system_prompt

        # 添加上下文信息
        if context:
            context_text = self._format_context(context)
            context_prompt += f"\n\n[当前上下文]\n{context_text}\n"

        # 临时替换系统提示词
        original_prompt = self.system_prompt
        self.system_prompt = context_prompt

        try:
            response = await self.chat(user_message, metadata=metadata)
            return response
        finally:
            # 恢复原始系统提示词
            self.system_prompt = original_prompt

    def _format_context(self, context: Dict[str, Any]) -> str:
        """格式化上下文信息"""
        lines = []
        for key, value in context.items():
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False, indent=2)
            lines.append(f"{key}: {value}")
        return "\n".join(lines)

    async def chat_stream(
        self,
        user_message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        流式对话

        Args:
            user_message: 用户消息
            metadata: 消息元数据

        Yields:
            str: 回复片段
        """
        # 添加用户消息到记忆
        self.memory.add_user_message(user_message, metadata)

        # 获取上下文消息
        messages = self.memory.get_messages_for_llm(
            max_history=self.max_history,
            system_prompt=self.system_prompt,
        )

        try:
            full_response = ""
            async for chunk in self.llm.ask_stream(messages=messages):  # type: ignore
                full_response += chunk
                yield chunk

            # 添加完整回复到记忆
            self.memory.add_assistant_message(full_response)

            # 更新统计
            self.total_calls += 1
            self.total_tokens += self.llm.count_tokens(user_message + full_response)

        except Exception as e:
            logger.error(f"Chat stream failed: {e}")
            raise

    def clear_memory(self) -> None:
        """清空对话记忆"""
        self.memory.clear()

    def get_memory_summary(self) -> Dict[str, Any]:
        """获取记忆摘要"""
        return {
            "message_count": self.memory.get_message_count(),
            "context_size": self.memory.get_context_size(),
            "has_summary": self.memory.summary is not None,
            "total_calls": self.total_calls,
            "total_tokens": self.total_tokens,
        }

    def export_memory(self) -> Dict[str, Any]:
        """导出记忆数据"""
        return self.memory.to_dict()

    def import_memory(self, data: Dict[str, Any]) -> None:
        """导入记忆数据"""
        self.memory = ConversationMemory.from_dict(data)
        logger.info(f"Imported memory with {self.memory.get_message_count()} messages")

    def update_system_prompt(self, prompt: str) -> None:
        """更新系统提示词"""
        self.system_prompt = prompt

    def get_system_prompt(self) -> str:
        """获取当前系统提示词"""
        return self.system_prompt
