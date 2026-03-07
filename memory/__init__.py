"""
会话记忆模块
提供 AI 上下文记忆、对话总结和知识库功能
"""

from .base import (
    MemoryItem,
    MemoryQuery,
    MemorySearchResult,
    ConversationSummary,
    MemoryStats,
    MemoryScope,
    MemoryType,
    generate_memory_id,
)
from .store import MemoryStore, FileMemoryStore, get_memory_store

__all__ = [
    # 基础类
    "MemoryStore",
    "FileMemoryStore",
    "MemoryItem",
    "MemoryQuery",
    "MemorySearchResult",
    "ConversationSummary",
    "MemoryStats",
    "MemoryScope",
    "MemoryType",
    "generate_memory_id",
    # 接口
    "get_memory_store",
]
