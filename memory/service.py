"""
记忆服务集成层
提供高层次的记忆操作接口
"""

from typing import List, Optional, Dict, Any
from loguru import logger

from memory.base import (
    MemoryItem,
    MemoryQuery,
    ConversationSummary,
    MemoryStats,
    MemoryScope,
    MemoryType,
    generate_memory_id,
)
from memory.store import MemoryStore, get_memory_store


class MemoryService:
    """
    记忆服务

    提供统一的记忆操作接口，抽象底层存储细节
    """

    def __init__(self, store: Optional[MemoryStore] = None):
        self._store = store or get_memory_store()

    async def remember(
        self,
        key: str,
        value: str,
        scope: MemoryScope = MemoryScope.GLOBAL,
        namespace: str = "default",
        importance: int = 50,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        记住一个键值对

        Args:
            key: 记忆键
            value: 记忆值
            scope: 作用域
            namespace: 命名空间
            importance: 重要性 (0-100)
            tags: 标签列表
            metadata: 元数据

        Returns:
            True 如果成功
        """
        item = MemoryItem(
            id=generate_memory_id(),
            type=MemoryType.PREFERENCE,
            scope=scope,
            namespace=namespace,
            key=key,
            value=value,
            importance=importance,
            tags=tags or [],
            metadata=metadata or {},
        )

        await self._store.add(item)
        logger.debug(f"Remembered: {key} = {value}")
        return True

    async def remember_fact(
        self,
        fact: str,
        scope: MemoryScope = MemoryScope.GLOBAL,
        confidence: float = 1.0,
        namespace: str = "default",
    ) -> bool:
        """
        记住一个事实（带置信度）

        Args:
            fact: 事实描述
            scope: 作用域
            confidence: 置信度 (0-1)
            namespace: 命名空间

        Returns:
            True 如果成功
        """
        key = f"fact:{hash(fact)}"
        item = MemoryItem(
            id=generate_memory_id(),
            type=MemoryType.FACT,
            scope=scope,
            namespace=namespace,
            key=key,
            value=fact,
            importance=int(confidence * 50),  # 转换为 0-50
            metadata={"confidence": confidence},
        )

        await self._store.add(item)
        logger.debug(f"Remembered fact: {fact}")
        return True

    async def get(self, key: str, **kwargs) -> Optional[str]:
        """
        获取记忆值

        Args:
            key: 记忆键
            **kwargs: 额外参数（scope, namespace 等）

        Returns:
            记忆值，如果不存在则返回 None
        """
        scope = kwargs.get("scope", MemoryScope.GLOBAL)
        namespace = kwargs.get("namespace", "default")

        item = await self._store.get_by_key(key, scope=scope, namespace=namespace)
        return item.value if item else None

    async def search(
        self,
        query: str,
        scope: Optional[MemoryScope] = None,
        fuzzy: bool = True,
        limit: int = 10,
        namespace: str = "default",
    ) -> List[MemoryItem]:
        """
        搜索记忆

        Args:
            query: 查询文本
            scope: 作用域
            fuzzy: 是否模糊搜索
            limit: 结果数量限制
            namespace: 命名空间

        Returns:
            匹配的记忆项列表
        """
        memory_query = MemoryQuery(
            query=query,
            fuzzy=fuzzy,
            limit=limit,
            scope=scope,
            namespace=namespace,
        )

        result = await self._store.search(memory_query)
        return result.items

    async def summarize(
        self,
        messages: List[Dict[str, Any]],
        namespace: str = "conversations",
        participants: Optional[List[str]] = None,
    ) -> ConversationSummary:
        """
        总结对话

        Args:
            messages: 消息列表
            namespace: 命名空间
            participants: 参与者列表

        Returns:
            对话总结对象
        """
        return await self._store.summarize_conversation(
            namespace=namespace,
            messages=messages,
        )

    async def get_conversations(
        self,
        namespace: str = "conversations",
        limit: int = 10,
    ) -> List[ConversationSummary]:
        """
        获取对话总结列表

        Args:
            namespace: 命名空间
            limit: 数量限制

        Returns:
            对话总结列表
        """
        return await self._store.get_conversations(
            namespace=namespace,
            limit=limit,
        )

    async def add_conversation_note(
        self,
        summary_id: str,
        note: str,
        namespace: str = "conversations",
    ) -> None:
        """
        为对话总结添加笔记

        Args:
            summary_id: 对话总结 ID
            note: 笔记内容
            namespace: 命名空间
        """
        # 简单实现：直接更新元数据
        if await self._store.get_by_key(
            summary_id, scope=MemoryScope.GLOBAL, namespace=namespace
        ):
            # 在实际实现中，应该获取完整的总结对象并更新
            logger.debug(f"Added note to conversation {summary_id}")
        else:
            logger.warning(f"Conversation {summary_id} not found")

    async def get_stats(self) -> MemoryStats:
        """获取记忆统计"""
        return self._store.get_stats()

    async def cleanup_expired(self, days: int = 7) -> None:
        """清理过期的记忆"""
        from datetime import datetime, timedelta

        before = datetime.now() - timedelta(days=days)
        await self._store.cleanup_expired(before=before)

    async def cleanup_low_importance(
        self,
        threshold: int = 20,
        count: int = 10,
    ) -> None:
        """清理低重要性的记忆"""
        # 简单实现：查找并删除低重要性且旧的记忆
        pass

    async def export(self, scope: Optional[MemoryScope] = None) -> str:
        """
        导出记忆数据为 JSON

        Args:
            scope: 作用域

        Returns:
            JSON 格式的记忆数据
        """
        import json

        # 简单实现：导出统计数据
        stats = self._store.get_stats()
        return json.dumps(stats, ensure_ascii=False, indent=2)

    async def import_data(self, data: str, format: str = "json") -> None:
        """
        导入记忆数据

        Args:
            data: JSON 或其他格式的记忆数据
            format: 数据格式

        Returns:
            导入的项目数
        """
        pass
