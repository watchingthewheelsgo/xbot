"""
对话管理器
参考 nanoClaw 实现，支持对话模式、超时、记忆等功能
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable, Awaitable, cast
import json

from loguru import logger
from openai.types.chat import ChatCompletionMessage


# 工具相关导入
from server.ai.schema import Message, ToolChoice

# 记忆相关导入
from server.ai.memory.session_compressor import (
    SessionCompressor,
    MemoryExtractionResult,
    MemoryDeduplicator,
    ContextBuilder,
)
from memory import MemoryScope


class ChatState(Enum):
    """对话状态"""

    IDLE = "idle"  # 空闲
    CHATTING = "chatting"  # 对话中
    THINKING = "thinking"  # 思考中
    TIMEOUT = "timeout"  # 超时等待
    EXITING = "exiting"  # 正在退出


@dataclass
class ChatMessage:
    """对话消息"""

    role: str  # user, assistant, system, tool
    content: str  # 消息内容
    timestamp: datetime = field(default_factory=datetime.now)
    tool_calls: Optional[List[Dict]] = None  # 工具调用记录
    metadata: Optional[Dict[str, Any]] = None  # 元数据


@dataclass
class ChatSession:
    """对话会话"""

    chat_id: str  # 唯一标识符
    platform: str  # telegram, feishu, etc.
    state: ChatState = ChatState.IDLE
    messages: List[ChatMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_message_at: datetime = field(default_factory=datetime.now)
    last_activity_at: datetime = field(default_factory=datetime.now)

    # 超时配置
    idle_timeout_seconds: int = 300  # 5分钟无新消息后
    exit_warning_seconds: int = 30  # 5分钟后30秒退出

    def __post_init__(self):
        """初始化后设置"""
        self.last_message_at = datetime.now()
        self.last_activity_at = datetime.now()

    @property
    def is_idle(self) -> bool:
        """是否空闲"""
        return self.state == ChatState.IDLE

    @property
    def is_active(self) -> bool:
        """是否活跃（对话中）"""
        return self.state in (ChatState.CHATTING, ChatState.THINKING)

    @property
    def is_timeout(self) -> bool:
        """是否超时"""
        if self.state != ChatState.CHATTING:
            return False
        idle_time = (datetime.now() - self.last_message_at).total_seconds()
        return idle_time >= self.idle_timeout_seconds

    def add_message(
        self,
        role: str,
        content: str,
        tool_calls: Optional[List[Dict]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """添加消息"""
        message = ChatMessage(
            role=role,
            content=content,
            tool_calls=tool_calls,
            metadata=metadata or {},
        )
        self.messages.append(message)
        self.last_message_at = datetime.now()
        self.last_activity_at = datetime.now()

        # 添加消息时自动进入对话状态
        if role == "user":
            self.state = ChatState.CHATTING

    def get_messages_for_llm(
        self,
        max_history: int = 20,
        include_system: bool = True,
    ) -> List[Dict]:
        """获取适合 LLM 的消息格式"""
        messages = []

        # 系统提示
        if include_system:
            messages.append(
                {
                    "role": "system",
                    "content": "你是 XBot，一个金融信息聚合和新闻分析机器人。",
                }
            )

        # 转换历史消息为 LLM 格式
        for msg in self.messages[-max_history:]:
            msg_dict = cast(Dict[str, Any], {"role": msg.role, "content": msg.content})

            # 添加工具调用信息
            if msg.tool_calls:
                msg_dict["tool_calls"] = msg.tool_calls  # type: ignore

            # 添加元数据（如时间戳）
            if msg.metadata:
                msg_dict["metadata"] = msg.metadata  # type: ignore

            messages.append(msg_dict)

        return messages

    def get_context_summary(self, max_chars: int = 500) -> str:
        """获取上下文摘要"""
        recent_messages = [m for m in self.messages if m.role == "user"][-5:]

        if not recent_messages:
            return "新对话"

        summary = "近期对话：\n"
        for i, msg in enumerate(recent_messages, 1):
            content = (
                msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
            )
            summary += f"{i}. {content}\n"

            if len(summary) > max_chars - 50:
                summary = summary[: max_chars - 3] + "..."
                break

        return summary

    def clear(self) -> None:
        """清空会话消息但保留会话"""
        self.messages = []
        self.state = ChatState.IDLE
        logger.info(
            f"Session {self.chat_id} cleared, {len(self.messages)} messages removed"
        )


class ChatManager:
    """
    对话管理器

    特性：
    1. 管理多个对话会话（按 chat_id 隔离）
    2. 支持超时机制（5分钟无新消息后30秒退出）
    3. 集成 memory 记忆系统
    4. 集成 LLM 调用
    5. 支持工具调用（新闻、加密货币、市场、关注列表等）
    6. 持久化会话到文件
    7. 记忆提取和去重（参考 OpenViking）
    """

    def __init__(
        self,
        workspace_path: Path,
        llm_client: Optional[Any] = None,
        memory_service: Optional[Any] = None,
        enable_persistence: bool = True,
        scheduler: Optional[Any] = None,
        news_processor: Optional[Any] = None,
    ):
        self.workspace = workspace_path
        self.llm_client = llm_client
        self.memory_service = memory_service
        self.enable_persistence = enable_persistence
        self.scheduler = scheduler
        self.news_processor = news_processor

        # 会话存储
        self._sessions: Dict[str, ChatSession] = {}
        self._sessions_dir = workspace_path / ".bot" / "chat_sessions"
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

        # 超时检查任务
        self._timeout_task: Optional[asyncio.Task] = None
        self._timeout_check_interval = 10  # 每10秒检查一次超时

        # 对话模式状态
        self._chat_mode_chats: set[str] = set()  # 当前处于对话模式的 chat_id
        self._lock = asyncio.Lock()

        # 工具注册表（延迟初始化）
        self._tool_registry: Optional[Any] = None

        # 记忆系统（参考 OpenViking）
        self._session_compressor = SessionCompressor(llm_client=llm_client)
        self._memory_deduplicator = MemoryDeduplicator()
        self._context_builder: Optional[ContextBuilder] = None

        logger.info(f"ChatManager initialized, workspace: {workspace_path}")

    def _get_tool_registry(self) -> Any:
        """获取或初始化工具注册表"""
        if self._tool_registry is None:
            from server.ai.tools.chat_tools import ChatToolRegistry

            self._tool_registry = ChatToolRegistry(
                scheduler=self.scheduler,
                news_processor=self.news_processor,
            )
            logger.info(
                f"Tool registry initialized with {len(self._tool_registry.tool_names)} tools"
            )
        return self._tool_registry

    async def start_timeout_checker(self) -> None:
        """启动超时检查任务"""
        if self._timeout_task is None or self._timeout_task.done():
            self._timeout_task = asyncio.create_task(self._timeout_loop())
            logger.info("Timeout checker started")

    async def stop_timeout_checker(self) -> None:
        """停止超时检查任务"""
        if self._timeout_task and not self._timeout_task.done():
            self._timeout_task.cancel()
            try:
                await self._timeout_task
            except asyncio.CancelledError:
                pass
            logger.info("Timeout checker stopped")

    async def _timeout_loop(self) -> None:
        """超时检查循环"""
        while True:
            try:
                await asyncio.sleep(self._timeout_check_interval)
                await self._check_timeouts()
            except asyncio.CancelledError:
                logger.info("Timeout checker cancelled")
                break
            except Exception as e:
                logger.error(f"Error in timeout checker: {e}")

    async def _check_timeouts(self) -> None:
        """检查所有会话的超时状态"""
        now = datetime.now()
        sessions_to_exit: List[str] = []

        for chat_id, session in self._sessions.items():
            # 检查是否处于对话模式且超时
            if chat_id in self._chat_mode_chats and session.is_timeout:
                idle_time = (now - session.last_message_at).total_seconds()

                # 如果超过5分钟但不到5分30秒，发送警告
                if idle_time >= session.idle_timeout_seconds:
                    warning_time = (
                        session.idle_timeout_seconds - session.exit_warning_seconds
                    )
                    if warning_time <= idle_time < session.idle_timeout_seconds:
                        await self._send_timeout_warning(chat_id, session)

                    # 如果超过5分30秒，标记为退出
                    if (
                        idle_time
                        >= session.idle_timeout_seconds + session.exit_warning_seconds
                    ):
                        sessions_to_exit.append(chat_id)

        # 发送退出消息并清理会话
        for chat_id in sessions_to_exit:
            await self._exit_chat_mode(chat_id, reason="timeout")

    async def _send_timeout_warning(self, chat_id: str, session: ChatSession) -> None:
        """发送超时警告"""
        idle_time = (datetime.now() - session.last_message_at).total_seconds()
        remaining = (
            session.exit_warning_seconds - idle_time + session.idle_timeout_seconds
        )

        warning_msg = f"""
⏰ 会话即将结束（{remaining}秒后自动退出）

发送任何消息继续对话，或使用 /quit 主动退出。
""".strip()

        await self._send_message(chat_id, warning_msg)
        session.state = ChatState.TIMEOUT

    async def _exit_chat_mode(self, chat_id: str, reason: str = "user") -> None:
        """退出对话模式"""
        if chat_id not in self._chat_mode_chats:
            return

        self._chat_mode_chats.discard(chat_id)

        session = self._sessions.get(chat_id)
        if session:
            session.state = ChatState.EXITING
            exit_msg = f"👋 对话模式已退出（{reason}）"

            await self._send_message(chat_id, exit_msg)

            # 保存会话到记忆
            if self.memory_service:
                await self._save_session_to_memory(chat_id, session)

        logger.info(f"Chat mode exited for {chat_id}, reason: {reason}")

    async def _send_message(self, chat_id: str, content: str) -> None:
        """发送消息（由渠道实现）"""
        # 这里需要通过回调注入实际的消息发送逻辑
        # 暂时使用日志记录
        logger.info(f"[Chat] To {chat_id}: {content[:100]}")

    async def _save_session_to_memory(self, chat_id: str, session: ChatSession) -> None:
        """
        将会话保存到记忆（参考 OpenViking）

        处理流程：
        1. 使用 SessionCompressor 提取记忆
        2. 使用 MemoryDeduplicator 去重
        3. 保存去重后的记忆
        """
        if not self.memory_service:
            return

        # 消息数量不足时不提取
        if len(session.messages) < 5:
            logger.debug(
                f"Not enough messages for memory extraction: {len(session.messages)}"
            )
            return

        try:
            # 构建消息列表用于提取
            messages_list = [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat(),
                }
                for msg in session.messages
            ]

            # 使用会话压缩器提取记忆
            extraction_result: MemoryExtractionResult = (
                await self._session_compressor.compress_session(
                    messages=messages_list, chat_id=chat_id, namespace="chat"
                )
            )

            # 保存会话摘要
            await self.memory_service.remember(
                key=f"chat_summary_{chat_id}",
                value=extraction_result.session_summary,
                scope=MemoryScope.USER,
                namespace="chat",
                importance=30,
                tags=["session_summary", chat_id],
            )

            # 保存用户最后活动时间
            await self.memory_service.remember(
                key=f"last_active_{chat_id}",
                value=datetime.now().isoformat(),
                scope=MemoryScope.USER,
                namespace="chat",
                importance=20,
            )

            # 保存提取的记忆
            saved_count = 0
            for extracted_mem in extraction_result.memories:
                # 去重决策
                # 先获取现有记忆
                existing_memories = []
                if self.memory_service:
                    existing_memories = await self.memory_service.search(
                        query=extracted_mem.summary[:50],
                        scope=MemoryScope.USER,
                        namespace="chat",
                        limit=5,
                    )

                # 执行去重
                action, merge_id = await self._memory_deduplicator.deduplicate(
                    new_memory=extracted_mem,
                    existing_memories=existing_memories,
                    llm_client=self.llm_client,
                )

                # 根据决策处理
                if action == "SKIP":
                    logger.debug(
                        f"Skipping duplicate memory: {extracted_mem.summary[:30]}"
                    )
                    continue
                elif action == "MERGE":
                    if merge_id:
                        # 合并到现有记忆
                        await self.memory_service.remember(
                            key=f"{extracted_mem.category}_{merge_id}",
                            value=f"{extracted_mem.content}\n\n{extracted_mem.overview}",
                            scope=MemoryScope.USER,
                            namespace="chat",
                            importance=extracted_mem.importance,
                            tags=extracted_mem.tags,
                        )
                        saved_count += 1
                        logger.debug(f"Merged memory into {merge_id}")
                elif action == "DELETE":
                    if merge_id:
                        # 删除旧记忆
                        await self.memory_service.delete(merge_id)
                        saved_count += 1
                        logger.debug(f"Deleted old memory {merge_id}")
                elif action == "CREATE":
                    # 创建新记忆
                    mem_key = f"{extracted_mem.category}_{extracted_mem.summary[:30].replace(' ', '_')}"
                    await self.memory_service.remember(
                        key=mem_key,
                        value=f"{extracted_mem.overview}\n\n{extracted_mem.content}",
                        scope=MemoryScope.USER,
                        namespace="chat",
                        importance=extracted_mem.importance,
                        tags=extracted_mem.tags,
                    )
                    saved_count += 1
                    logger.debug(f"Created new memory: {mem_key}")

            logger.info(
                f"Session saved to memory for {chat_id}, saved {saved_count} memories"
            )

        except Exception as e:
            logger.error(f"Failed to save session to memory: {e}")

    async def _build_memory_context(self, chat_id: str) -> str:
        """
        构建记忆上下文（参考 OpenViking）

        包括：
        1. 用户偏好
        2. 相关历史记忆（带热度排序）
        3. 用户画像
        """
        if not self.memory_service:
            return ""

        try:
            # 初始化上下文构建器
            if self._context_builder is None and self.llm_client:
                from memory import get_memory_store

                self._context_builder = ContextBuilder(
                    memory_store=get_memory_store(),
                    llm_client=self.llm_client,
                )

            if self._context_builder is None:
                return ""

            # 构建上下文
            context = await self._context_builder.build_context(
                chat_id=chat_id, namespace="chat", max_recent_messages=5, max_memories=3
            )

            # 格式化为系统提示
            lines = ["用户上下文信息：", ""]

            # 添加偏好
            if context["preferences"]:
                lines.append("用户偏好:")
                for item in context["preferences"][:3]:
                    lines.append(f"- {item.value[:80]}")
                lines.append("")

            # 添加用户画像
            if context["user_profile"]:
                lines.append(f"用户画像: {context['user_profile'].value[:150]}")
                lines.append("")

            # 添加上下文摘要
            if context["context_summary"]:
                lines.append(context["context_summary"])
                lines.append("")

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Failed to build memory context: {e}")
            return ""

    async def delete(self, item_id: str) -> bool:
        """删除记忆（委托给 memory_service）"""
        if not self.memory_service:
            return False
        return await self.memory_service.delete(item_id)

    async def enter_chat_mode(
        self,
        chat_id: str,
        platform: str,
        welcome_message: bool = True,
    ) -> ChatSession:
        """进入对话模式"""
        # 如果已经在对话模式，直接返回现有会话
        if chat_id in self._chat_mode_chats:
            session = self._sessions.get(chat_id)
            if session:
                session.last_activity_at = datetime.now()
                logger.info(f"Already in chat mode: {chat_id}")
                return session

        # 创建新会话
        session = ChatSession(
            chat_id=chat_id,
            platform=platform,
        )

        # 尝试从记忆加载历史
        if self.memory_service:
            try:
                # 加载之前的对话摘要
                _summary_key = f"chat_summary_{chat_id}"
                # 这里需要根据实际的 memory 模式来加载
                # 暂时跳过，使用空历史开始
                pass
            except Exception as e:
                logger.debug(f"Failed to load session history from memory: {e}")

        self._chat_mode_chats.add(chat_id)
        self._sessions[chat_id] = session

        # 发送欢迎消息
        if welcome_message:
            welcome = """
💬 **对话模式已开启**

我会记住我们的对话，可以回答问题、调用工具等。

• 发送 /quit 直接退出
• 5分钟无新消息后30秒自动退出
• 对话结束后会保存到记忆
""".strip()
            await self._send_message(chat_id, welcome)

        logger.info(f"Chat mode entered for {chat_id}")

        return session

    async def process_message(
        self,
        chat_id: str,
        user_message: str,
        platform: str = "unknown",
        on_progress: Optional[Callable[[str], Awaitable[None]]] = None,
        on_tool_call: Optional[Callable[[str, List[Dict]], Awaitable[None]]] = None,
    ) -> Optional[str]:
        """处理用户消息并生成回复"""
        # 如果不在对话模式中，自动进入对话模式
        if chat_id not in self._chat_mode_chats:
            logger.debug(f"Auto-entering chat mode for {chat_id}")
            # 创建新会话
            session = ChatSession(
                chat_id=chat_id,
                platform=platform,
            )
            self._chat_mode_chats.add(chat_id)
            self._sessions[chat_id] = session
        else:
            # 获取现有会话
            session = self._sessions.get(chat_id)

        if not session:
            logger.warning(f"No session found for {chat_id}")
            return None

        # 更新活动时间
        session.last_activity_at = datetime.now()
        session.add_message(role="user", content=user_message)

        try:
            # 获取 LLM 输入
            messages = session.get_messages_for_llm(max_history=20)

            # 发送思考进度
            session.state = ChatState.THINKING
            if on_progress:
                await on_progress("思考中...")

            # 调用 LLM
            if not self.llm_client:
                # 没有 LLM 时返回提示消息
                error_msg = "AI 服务未配置，无法生成回复。\n\n请先配置 LLM 客户端（如 OpenAI API）来启用对话功能。"
                session.state = ChatState.CHATTING
                return error_msg

            response_content = await self._call_llm(messages, chat_id)

            # 检查是否有工具调用需要执行
            if response_content.get("tool_calls"):
                tool_calls: list[Dict[str, Any]] = response_content["tool_calls"]  # type: ignore[assignment]

                session.state = ChatState.THINKING
                if on_tool_call:
                    await on_tool_call(chat_id, tool_calls)

                # 执行工具
                tool_results = await self._execute_tools(tool_calls, chat_id)

                # 将工具结果添加到历史
                for tool_call in tool_calls:
                    call_id = tool_call.get("id", "")
                    result = tool_results.get(call_id, "工具执行失败")

                    # 将工具结果格式化为消息
                    function = tool_call.get("function", {})
                    tool_name = function.get("name", "")

                    # 使用 OpenAI 格式的 tool 消息
                    session.add_message(
                        role="tool",
                        content=result,
                        tool_calls=[
                            {"id": call_id, "tool_name": tool_name, "result": result}
                        ],
                    )

                # 再次调用 LLM
                messages = session.get_messages_for_llm(max_history=40)

                if on_progress:
                    await on_progress("生成最终回复...")

                response_content = await self._call_llm(messages, chat_id)

            # 添加助手回复
            assistant_message = response_content.get("content", "")
            session.add_message(role="assistant", content=assistant_message)

            session.state = ChatState.CHATTING

            # 持久化会话
            await self._save_session(chat_id, session)

            return assistant_message

        except Exception as e:
            logger.error(f"Error processing message for {chat_id}: {e}")
            session.state = ChatState.CHATTING
            return f"抱歉，处理消息时出错：{str(e)[:100]}"

    async def _call_llm(
        self, messages: List[Dict[str, Any]], chat_id: str
    ) -> Dict[str, Any]:
        """调用 LLM，支持工具调用和记忆上下文"""
        if not self.llm_client:
            return {"content": "LLM 客户端未配置"}

        try:
            # 获取工具注册表
            tool_registry = self._get_tool_registry()
            tools = tool_registry.definitions if tool_registry else None

            # 构建记忆上下文
            memory_context = await self._build_memory_context(chat_id)

            # 分离 system 消息和普通消息
            system_messages = []
            conversation_messages = []

            # 添加记忆上下文到系统消息
            if memory_context:
                system_messages.append(Message.system_message(memory_context))

            # 添加工具说明到系统消息
            system_messages.append(
                Message.system_message(
                    "你可以使用工具来获取最新数据，包括新闻、加密货币价格、市场数据等。"
                    "当用户需要这类信息时，请主动调用相应的工具。"
                )
            )

            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")

                if role == "system":
                    system_messages.append(Message.system_message(content))
                elif role == "user":
                    conversation_messages.append(Message.user_message(content))
                elif role == "assistant":
                    conversation_messages.append(Message.assistant_message(content))
                elif role == "tool":
                    # 处理工具消息
                    conversation_messages.append(Message.user_message(content))
                else:
                    conversation_messages.append(Message(role=role, content=content))  # type: ignore

            # 获取底层 LLM 实例
            llm_instance = (
                self.llm_client.llm
                if hasattr(self.llm_client, "llm")
                else self.llm_client
            )

            # 使用 LLM.ask_tool() 方法支持工具调用
            response_message: Optional[
                ChatCompletionMessage
            ] = await llm_instance.ask_tool(
                messages=conversation_messages,
                system_msgs=system_messages if system_messages else None,
                tools=tools,
                tool_choice=ToolChoice.AUTO,
            )

            if response_message is None:
                return {"content": "AI 返回了空响应"}

            # 检查是否有工具调用
            tool_calls = getattr(response_message, "tool_calls", None)
            content = response_message.content or ""

            # 提取工具调用信息
            formatted_tool_calls = []
            if tool_calls:
                for tc in tool_calls:
                    formatted_tool_calls.append(
                        {
                            "id": tc.id,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                    )

            return {
                "content": content,
                "tool_calls": formatted_tool_calls if formatted_tool_calls else None,
            }

        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"content": f"调用 AI 时出错：{str(e)[:100]}"}

    async def _execute_tools(
        self, tool_calls: List[Dict[str, Any]], chat_id: str
    ) -> Dict[str, str]:
        """执行工具调用"""
        tool_registry = self._get_tool_registry()
        results = {}

        for tool_call in tool_calls:
            call_id = tool_call.get("id", "")
            function = tool_call.get("function", {})
            tool_name = function.get("name", "")
            arguments_str = function.get("arguments", "{}")

            try:
                # 解析参数
                import json

                if isinstance(arguments_str, str):
                    arguments = json.loads(arguments_str)
                else:
                    arguments = arguments_str

                # 执行工具
                tool_result = await tool_registry.execute_tool(tool_name, arguments)

                if tool_result.success:
                    results[call_id] = tool_result.content
                    logger.info(
                        f"Tool {tool_name} executed successfully for chat {chat_id}"
                    )
                else:
                    results[call_id] = f"工具执行失败: {tool_result.content}"
                    logger.warning(f"Tool {tool_name} failed: {tool_result.content}")

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse tool arguments: {e}")
                results[call_id] = f"参数解析失败: {str(e)[:50]}"
            except Exception as e:
                logger.error(f"Tool execution failed for {tool_name}: {e}")
                results[call_id] = f"工具执行失败: {str(e)[:50]}"

        return results

    async def _save_session(self, chat_id: str, session: ChatSession) -> None:
        """保存会话到文件"""
        if not self.enable_persistence:
            return

        session_path = self._sessions_dir / f"{safe_chat_id(chat_id)}.json"

        session_data = {
            "chat_id": session.chat_id,
            "platform": session.platform,
            "state": session.state.value,
            "created_at": session.created_at.isoformat(),
            "last_message_at": session.last_message_at.isoformat(),
            "last_activity_at": session.last_activity_at.isoformat(),
            "idle_timeout_seconds": session.idle_timeout_seconds,
            "exit_warning_seconds": session.exit_warning_seconds,
            "message_count": len(session.messages),
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.timestamp.isoformat(),
                }
                for m in session.messages
            ],
        }

        try:
            with open(session_path, "w", encoding="utf-8") as f:
                json.dump(session_data, f, ensure_ascii=False, indent=2)

            logger.debug(f"Session saved: {chat_id}")

        except Exception as e:
            logger.error(f"Failed to save session {chat_id}: {e}")

    async def load_session(self, chat_id: str) -> Optional[ChatSession]:
        """加载会话"""
        session_path = self._sessions_dir / f"{safe_chat_id(chat_id)}.json"

        if not session_path.exists():
            return None

        try:
            with open(session_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            session = ChatSession(
                chat_id=data["chat_id"],
                platform=data.get("platform", "unknown"),
                state=ChatState(data.get("state", "idle")),
                created_at=datetime.fromisoformat(data["created_at"]),
            )

            # 加载消息
            for msg_data in data.get("messages", []):
                msg = ChatMessage(
                    role=msg_data["role"],
                    content=msg_data["content"],
                    timestamp=datetime.fromisoformat(
                        msg_data.get("timestamp", datetime.now().isoformat())
                    ),
                )
                session.messages.append(msg)

            logger.debug(f"Session loaded: {chat_id}, {len(session.messages)} messages")

            return session

        except Exception as e:
            logger.error(f"Failed to load session {chat_id}: {e}")
            return None

    async def get_session_info(self, chat_id: str) -> Optional[Dict]:
        """获取会话信息"""
        session = self._sessions.get(chat_id)
        if not session:
            return None

        return {
            "chat_id": chat_id,
            "state": session.state.value,
            "message_count": len(session.messages),
            "created_at": session.created_at.isoformat(),
            "last_activity_at": session.last_activity_at.isoformat(),
            "is_chat_mode": chat_id in self._chat_mode_chats,
        }

    async def cleanup_inactive_sessions(self, max_age_hours: int = 24) -> int:
        """清理不活跃的会话"""
        now = datetime.now()
        cleaned = 0

        for chat_id, session in list(self._sessions.items()):
            age = (now - session.last_activity_at).total_seconds() / 3600

            if age > max_age_hours and chat_id not in self._chat_mode_chats:
                # 删除持久化文件
                session_path = self._sessions_dir / f"{safe_chat_id(chat_id)}.json"
                try:
                    session_path.unlink()
                except Exception:
                    pass

                del self._sessions[chat_id]
                cleaned += 1

        if cleaned > 0:
            logger.info(f"Cleaned {cleaned} inactive sessions")

        return cleaned

    def get_active_chat_count(self) -> int:
        """获取活跃对话数量"""
        return len(self._chat_mode_chats)

    def is_in_chat_mode(self, chat_id: str) -> bool:
        """检查是否在对话模式"""
        return chat_id in self._chat_mode_chats


def safe_chat_id(chat_id: str) -> str:
    """安全的 chat_id（用于文件名）"""
    return chat_id.replace(":", "_").replace("/", "_")


def format_tool_call_message(tool_calls: List[Dict]) -> str:
    """格式化工具调用消息"""
    if not tool_calls:
        return ""

    lines = ["🔧 工具调用:"]
    for tc in tool_calls:
        tool_id = tc.get("id", "unknown")
        args = tc.get("arguments", {})
        _result = tc.get("result", "")
        lines.append(f"  • {tool_id}")
        if args:
            args_str = ", ".join(f"{k}={v}" for k, v in args.items() if k != "input")
            if args_str:
                lines.append(f"    {args_str}")

    return "\n".join(lines) + "\n"
