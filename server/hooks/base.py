"""
Hook 系统基类
支持在关键事件前后插入自定义逻辑
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List, Callable


class Hook(ABC):
    """Hook 基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Hook 名称"""
        pass

    @property
    @abstractmethod
    def enabled(self) -> bool:
        """Hook 是否启用"""
        pass

    @abstractmethod
    async def execute(self, *args, **kwargs) -> Any:
        """
        执行 Hook

        Returns:
            修改后的数据或 None
        """
        pass


class HookResult:
    """Hook 执行结果"""

    def __init__(
        self,
        success: bool = True,
        modified_data: Optional[Any] = None,
        should_skip: bool = False,
        error_message: str = "",
    ):
        self.success = success
        self.modified_data = modified_data
        self.should_skip = should_skip
        self.error_message = error_message

    def __repr__(self) -> str:
        return (
            f"HookResult(success={self.success}, "
            f"skip={self.should_skip}, "
            f"error='{self.error_message}')"
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "modified_data": self.modified_data,
            "should_skip": self.should_skip,
            "error_message": self.error_message,
        }


class PreToolUseHookInput:
    """工具使用前的 Hook 输入"""

    def __init__(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ):
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.context = context or {}


class PreToolUseHookOutput:
    """工具使用前的 Hook 输出"""

    def __init__(
        self,
        modified_input: Optional[Dict[str, Any]] = None,
        should_skip: bool = False,
        environment_vars: Optional[Dict[str, str]] = None,
    ):
        self.modified_input = modified_input
        self.should_skip = should_skip
        self.environment_vars = environment_vars


class PreCompactHookInput:
    """会话压缩前的 Hook 输入"""

    def __init__(
        self,
        transcript_path: str,
        session_id: str,
        messages: List[Dict[str, Any]],
    ):
        self.transcript_path = transcript_path
        self.session_id = session_id
        self.messages = messages


class PreCompactHookOutput:
    """会话压缩前的 Hook 输出"""

    def __init__(
        self,
        should_archive: bool = True,
        archive_path: Optional[str] = None,
        custom_summary: Optional[str] = None,
    ):
        self.should_archive = should_archive
        self.archive_path = archive_path
        self.custom_summary = custom_summary


class PreSendMessageHookInput:
    """发送消息前的 Hook 输入"""

    def __init__(
        self,
        channel: str,
        chat_id: str,
        content: str,
        message_type: str = "text",
    ):
        self.channel = channel
        self.chat_id = chat_id
        self.content = content
        self.message_type = message_type


class PreSendMessageHookOutput:
    """发送消息前的 Hook 输出"""

    def __init__(
        self,
        modified_content: Optional[str] = None,
        should_skip: bool = False,
        alternative_channel: Optional[str] = None,
    ):
        self.modified_content = modified_content
        self.should_skip = should_skip
        self.alternative_channel = alternative_channel


class PostSendMessageHookInput:
    """发送消息后的 Hook 输入"""

    def __init__(
        self,
        channel: str,
        chat_id: str,
        content: str,
        success: bool,
        error_message: str = "",
    ):
        self.channel = channel
        self.chat_id = chat_id
        self.content = content
        self.success = success
        self.error_message = error_message


class TaskStartHookInput:
    """任务开始前的 Hook 输入"""

    def __init__(
        self,
        task_id: str,
        task_name: str,
        task_data: Dict[str, Any],
    ):
        self.task_id = task_id
        self.task_name = task_name
        self.task_data = task_data


class TaskCompleteHookInput:
    """任务完成后的 Hook 输入"""

    def __init__(
        self,
        task_id: str,
        task_name: str,
        success: bool,
        result: Any,
        duration_ms: int,
        error_message: str = "",
    ):
        self.task_id = task_id
        self.task_name = task_name
        self.success = success
        self.result = result
        self.duration_ms = duration_ms
        self.error_message = error_message


class DataFetchHookInput:
    """数据获取 Hook 输入"""

    def __init__(
        self,
        source_type: str,
        source_name: str,
        url: str,
        data: Optional[Any],
        error_message: str = "",
    ):
        self.source_type = source_type
        self.source_name = source_name
        self.url = url
        self.data = data
        self.error_message = error_message


class DataFetchHookOutput:
    """数据获取 Hook 输出"""

    def __init__(
        self,
        should_skip: bool = False,
        transform_data: Optional[Callable[[Any], Any]] = None,
        cache_ttl: Optional[int] = None,
    ):
        self.should_skip = should_skip
        self.transform_data = transform_data
        self.cache_ttl = cache_ttl
