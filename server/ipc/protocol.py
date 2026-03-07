"""
IPC 通信协议定义
定义消息格式和数据结构
"""

from typing import Dict, Any, Optional
from enum import Enum
from datetime import datetime
from dataclasses import dataclass, field


class IPCMessageType(Enum):
    """IPC 消息类型"""

    # 通信消息
    MESSAGE = "message"

    # 任务相关
    TASK_CREATE = "task_create"
    TASK_CANCEL = "task_cancel"
    TASK_UPDATE = "task_update"
    TASK_STATUS = "task_status"
    TASK_RESULT = "task_result"

    # 系统消息
    SYSTEM = "system"
    HEALTH_CHECK = "health_check"
    SHUTDOWN = "shutdown"

    # 渠道消息
    CHANNEL_SEND = "channel_send"
    CHANNEL_BROADCAST = "channel_broadcast"

    # 数据源消息
    DATA_FETCH = "data_fetch"
    DATA_CACHE = "data_cache"
    DATA_CLEAR = "data_clear"

    # Hook 相关
    HOOK_EXECUTE = "hook_execute"
    HOOK_REGISTER = "hook_register"

    # 内存管理
    MEMORY_GET = "memory_get"
    MEMORY_SET = "memory_set"
    MEMORY_DELETE = "memory_delete"
    MEMORY_SEARCH = "memory_search"
    MEMORY_CLEAR = "memory_clear"


@dataclass
class IPCMessage:
    """IPC 消息基类"""

    type: str
    source: str  # 消息来源（channel, task, system 等）
    destination: Optional[str] = None  # 目标命名空间
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    data: Dict[str, Any] = field(default_factory=dict)
    message_id: str = field(
        default_factory=lambda: str(int(datetime.now().timestamp() * 1000))
    )
    correlation_id: Optional[str] = None  # 关联 ID，用于请求-响应匹配

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "type": self.type,
            "source": self.source,
            "destination": self.destination,
            "timestamp": self.timestamp,
            "data": self.data,
            "message_id": self.message_id,
            "correlation_id": self.correlation_id,
        }


@dataclass
class TaskIPCMessage:
    """任务相关的 IPC 消息"""

    @staticmethod
    def create_task(
        task_id: str,
        task_name: str,
        task_type: str,
        priority: int,
        data: Dict[str, Any],
        namespace: str,
    ) -> IPCMessage:
        return IPCMessage(
            type=IPCMessageType.TASK_CREATE.value,
            source="task",
            destination=namespace,
            data={
                "task_id": task_id,
                "task_name": task_name,
                "task_type": task_type,
                "priority": priority,
                "data": data,
            },
        )

    @staticmethod
    def cancel_task(
        task_id: str, reason: str = "", namespace: str = "tasks"
    ) -> IPCMessage:
        return IPCMessage(
            type=IPCMessageType.TASK_CANCEL.value,
            source="task",
            destination=namespace,
            data={
                "task_id": task_id,
                "reason": reason,
            },
        )

    @staticmethod
    def task_status(
        task_id: str,
        status: str,
        namespace: str = "tasks",
    ) -> IPCMessage:
        return IPCMessage(
            type=IPCMessageType.TASK_STATUS.value,
            source="task",
            destination=namespace,
            data={
                "task_id": task_id,
                "status": status,
            },
        )

    @staticmethod
    def task_result(
        task_id: str,
        success: bool,
        result: Any,
        error_message: str = "",
        namespace: str = "tasks",
    ) -> IPCMessage:
        return IPCMessage(
            type=IPCMessageType.TASK_RESULT.value,
            source="task",
            destination=namespace,
            data={
                "task_id": task_id,
                "success": success,
                "result": result,
                "error_message": error_message,
            },
        )


@dataclass
class ChannelIPCMessage:
    """渠道相关的 IPC 消息"""

    @staticmethod
    def send_message(
        channel: str,
        chat_id: str,
        content: str,
        message_type: str = "text",
    ) -> IPCMessage:
        return IPCMessage(
            type=IPCMessageType.CHANNEL_SEND.value,
            source="channel",
            destination=f"channel:{channel}",
            data={
                "chat_id": chat_id,
                "content": content,
                "message_type": message_type,
            },
        )

    @staticmethod
    def broadcast(
        channel: str,
        content: str,
        message_type: str = "text",
    ) -> IPCMessage:
        return IPCMessage(
            type=IPCMessageType.CHANNEL_BROADCAST.value,
            source="channel",
            destination=f"channel:{channel}",
            data={
                "content": content,
                "message_type": message_type,
            },
        )


@dataclass
class MemoryIPCMessage:
    """记忆相关的 IPC 消息"""

    @staticmethod
    def get(key: str, namespace: str = "memory") -> IPCMessage:
        return IPCMessage(
            type=IPCMessageType.MEMORY_GET.value,
            source="memory",
            destination=f"memory:{namespace}",
            data={"key": key},
        )

    @staticmethod
    def set(
        key: str,
        value: str,
        namespace: str = "memory",
    ) -> IPCMessage:
        return IPCMessage(
            type=IPCMessageType.MEMORY_SET.value,
            source="memory",
            destination=f"memory:{namespace}",
            data={"key": key, "value": value},
        )

    @staticmethod
    def delete(key: str, namespace: str = "memory") -> IPCMessage:
        return IPCMessage(
            type=IPCMessageType.MEMORY_DELETE.value,
            source="memory",
            destination=f"memory:{namespace}",
            data={"key": key},
        )

    @staticmethod
    def search(
        query: str,
        namespace: str = "memory",
    ) -> IPCMessage:
        return IPCMessage(
            type=IPCMessageType.MEMORY_SEARCH.value,
            source="memory",
            destination=f"memory:{namespace}",
            data={"query": query},
        )

    @staticmethod
    def clear(namespace: str = "memory") -> IPCMessage:
        return IPCMessage(
            type=IPCMessageType.MEMORY_CLEAR.value,
            source="memory",
            destination=f"memory:{namespace}",
            data={},
        )


@dataclass
class SystemIPCMessage:
    """系统相关的 IPC 消息"""

    @staticmethod
    def health_check(source: str = "system") -> IPCMessage:
        return IPCMessage(
            type=IPCMessageType.HEALTH_CHECK.value,
            source=source,
            data={},
        )

    @staticmethod
    def shutdown(reason: str = "") -> IPCMessage:
        return IPCMessage(
            type=IPCMessageType.SHUTDOWN.value,
            source="system",
            data={"reason": reason},
        )


class IPCResponse:
    """IPC 响应基类"""

    def __init__(
        self,
        success: bool,
        data: Optional[Any] = None,
        error_message: str = "",
        correlation_id: Optional[str] = None,
    ):
        self.success = success
        self.data = data
        self.error_message = error_message
        self.correlation_id = correlation_id


class IPCEndpoint:
    """IPC 端点"""

    # 输入端点（向容器发送）
    INPUT = "/workspace/ipc/input"
    # 输出端点（从容器接收）
    OUTPUT = "/workspace/ipc/output"
    # 任务输入
    TASKS = "/workspace/ipc/tasks"
    # 系统控制
    CONTROL = "/workspace/ipc/control"
    # 关闭标记
    CLOSE_FILE = "_close"
