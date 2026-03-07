"""
统一消息队列模块
"""

from .message_queue import (
    MessageQueue,
    MessageType,
    QueueItem,
    QueueStats,
    get_global_queue,
    init_global_queue,
)

__all__ = [
    "MessageQueue",
    "MessageType",
    "QueueItem",
    "QueueStats",
    "get_global_queue",
    "init_global_queue",
]
