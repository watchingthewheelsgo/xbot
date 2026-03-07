"""
IPC 通信模块
提供主进程与工作进程/容器之间的通信能力
"""

from .protocol import (
    IPCMessage,
    IPCMessageType,
    IPCResponse,
    IPCEndpoint,
    TaskIPCMessage,
    ChannelIPCMessage,
    MemoryIPCMessage,
    SystemIPCMessage,
)
from .manager import IPCManager, get_ipc_manager

__all__ = [
    # 协议
    "IPCMessage",
    "IPCMessageType",
    "IPCResponse",
    "IPCEndpoint",
    # 消息类型
    "TaskIPCMessage",
    "ChannelIPCMessage",
    "MemoryIPCMessage",
    "SystemIPCMessage",
    # 管理器
    "IPCManager",
    "get_ipc_manager",
]
