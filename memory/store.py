""" "
记忆存储接口
支持多种存储后端
"""

import json
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from pathlib import Path
from datetime import datetime

from loguru import logger

# 这里将在导入时从 .base 模块导入类型


class MemoryStore(ABC):
    """记忆存储接口"""

    @abstractmethod
    async def add(self, item: Any) -> None:
        """添加记忆项"""
        pass

    @abstractmethod
    async def get(self, item_id: str) -> Optional[Any]:
        """获取记忆项"""
        pass

    @abstractmethod
    async def update(self, item_id: str, **updates) -> bool:
        """更新记忆项"""
        pass

    @abstractmethod
    async def delete(self, item_id: str) -> bool:
        """删除记忆项"""
        pass

    @abstractmethod
    async def search(self, query: Any) -> Any:
        """搜索记忆"""
        pass

    @abstractmethod
    async def search_by_tags(self, tags: List[str], **kwargs) -> Any:
        """按标签搜索记忆"""
        pass

    @abstractmethod
    async def get_by_key(self, key: str, **kwargs) -> Optional[Any]:
        """按键获取记忆"""
        pass

    @abstractmethod
    async def get_recent(self, scope: str = "global", limit: int = 20) -> List[Any]:
        """获取最近的记忆项"""
        pass

    @abstractmethod
    async def cleanup_expired(self, **kwargs) -> None:
        """清理过期的记忆"""
        pass

    @abstractmethod
    async def cleanup_low_importance(self, **kwargs) -> None:
        """清理低重要性的记忆"""
        pass

    @abstractmethod
    def get_stats(self) -> Any:
        """获取统计信息"""
        pass

    @abstractmethod
    async def summarize_conversation(
        self, namespace: str, messages: List[Dict[str, Any]], **kwargs
    ) -> Any:
        """总结对话"""
        pass

    @abstractmethod
    async def add_conversation(self, summary: Any, **kwargs) -> None:
        """添加对话总结"""
        pass

    @abstractmethod
    async def get_conversations(
        self, namespace: str = "default", limit: int = 10
    ) -> List[Any]:
        """获取对话总结列表"""
        pass


class FileMemoryStore(MemoryStore):
    """基于文件的记忆存储"""

    DEFAULT_NAMESPACE = "default"
    MAX_FILE_SIZE = 10000
    CACHE_TTL = 300

    def __init__(self, base_dir: str = "."):
        self.base_dir = Path(base_dir).resolve()
        self.memory_dir = self.base_dir / "memory"
        self.conversations_dir = self.base_dir / "conversations"
        self.metadata_dir = self.base_dir / ".metadata"
        self._stats = {}

        # 创建目录
        for dir_path in [self.memory_dir, self.conversations_dir, self.metadata_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"File memory store initialized at {self.base_dir}")

    def _get_item_path(self, item: Any) -> str:
        """获取记忆项的文件路径"""
        scope = getattr(item, "scope", None) or "global"
        namespace = getattr(item, "namespace", "default")
        namespace_dir = self.memory_dir / scope / namespace
        namespace_dir.mkdir(parents=True, exist_ok=True)

        return str(namespace_dir / f"{getattr(item, 'id', 'unknown')}.json")

    def _get_conversation_path(self, namespace: str, summary_id: str) -> str:
        """获取对话总结文件路径"""
        scope_dir = self.conversations_dir / namespace
        scope_dir.mkdir(parents=True, exist_ok=True)

        return str(scope_dir / f"{summary_id}.json")

    async def add(self, item: Any) -> None:
        """添加记忆项"""
        item_path = self._get_item_path(item)

        # 保存
        with open(item_path, "w", encoding="utf-8") as f:
            json.dump(item, f)

        # 添加到统计
        self._stats["total"] = self._stats.get("total", 0) + 1

        logger.debug(f"Memory added: {getattr(item, 'id', 'unknown')}")

    async def get(self, item_id: str) -> Optional[Any]:
        """获取记忆项"""
        for scope_dir in self.memory_dir.iterdir():
            if not scope_dir.is_dir():
                continue

            for item_file in scope_dir.glob("*.json"):
                try:
                    with open(item_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("id") == item_id:
                        return data
                except (json.JSONDecodeError, KeyError):
                    logger.warning(f"Failed to parse memory file: {item_file}")

        return None

    async def update(self, item_id: str, **updates) -> bool:
        """更新记忆项"""
        item = await self.get(item_id)
        if not item:
            return False

        # 更新字段
        for key, value in updates.items():
            if hasattr(item, key):
                setattr(item, key, value)

        # 保存
        item_path = self._get_item_path(item)
        with open(item_path, "w", encoding="utf-8") as f:
            json.dump(item, f)

        logger.debug(f"Memory updated: {item_id}")
        return True

    async def delete(self, item_id: str) -> bool:
        """删除记忆项"""
        item = await self.get(item_id)
        if not item:
            return False

        item_path = self._get_item_path(item)
        if Path(item_path).exists():
            Path(item_path).unlink()

        logger.debug(f"Memory deleted: {item_id}")
        return True

    async def search(self, query: Any) -> Any:
        """搜索记忆"""
        start_time = datetime.now()
        results = []

        for scope_dir in self.memory_dir.iterdir():
            if not scope_dir.is_dir():
                continue

            for namespace_dir in scope_dir.iterdir():
                if not namespace_dir.is_dir():
                    continue

                for item_file in namespace_dir.glob("*.json"):
                    try:
                        with open(item_file, "r", encoding="utf-8") as f:
                            item_obj = json.load(f)

                            # 过滤
                            query_text = getattr(query, "query", "").lower()
                            item_value = getattr(item_obj, "value", "").lower()

                            if query_text in item_value:
                                results.append(item_obj)
                    except (json.JSONDecodeError, KeyError):
                        continue

        results.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        limit = getattr(query, "limit", 10)
        final_results = results[:limit]

        execution_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        result = {
            "total": len(results),
            "items": final_results,
            "query": query_text,
            "execution_time_ms": execution_time_ms,
        }

        logger.info(
            f"Memory search: query='{query_text}', found={len(final_results)}, took={execution_time_ms}ms"
        )

        return result

    async def search_by_tags(self, tags: List[str], **kwargs) -> List[Any]:
        """按标签搜索记忆"""
        results = []

        for scope_dir in self.memory_dir.iterdir():
            if not scope_dir.is_dir():
                continue

            for namespace_dir in scope_dir.iterdir():
                if not namespace_dir.is_dir():
                    continue

                for item_file in namespace_dir.glob("*.json"):
                    try:
                        with open(item_file, "r", encoding="utf-8") as f:
                            item_obj = json.load(f)
                            item_tags = item_obj.get("tags", [])

                            if any(tag in item_tags for tag in tags):
                                results.append(item_obj)

                    except (json.JSONDecodeError, KeyError):
                        continue

        return results[: getattr(kwargs, "limit", 10)]

    async def get_by_key(self, key: str, **kwargs) -> Optional[Any]:
        """按键获取记忆"""
        namespace = kwargs.get("namespace", "default")

        for scope_dir in self.memory_dir.iterdir():
            if not scope_dir.is_dir():
                continue

            namespace_dir = scope_dir / namespace
            if namespace_dir.exists():
                for item_file in namespace_dir.glob("*.json"):
                    try:
                        with open(item_file, "r", encoding="utf-8") as f:
                            item_obj = json.load(f)
                            if item_obj.get("key") == key:
                                return item_obj
                    except (json.JSONDecodeError, KeyError):
                        continue

        return None

    async def get_recent(self, scope: str = "global", limit: int = 20) -> List[Any]:
        """获取最近的记忆项"""
        results = []

        scope_dir = self.memory_dir / scope
        if not scope_dir.exists():
            return results

        item_files = sorted(scope_dir.glob("*.json"), reverse=True)
        limit = min(limit, len(item_files))

        for item_file in item_files[:limit]:
            try:
                with open(item_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    results.append(data)
            except (json.JSONDecodeError, KeyError):
                continue

        return results

    async def cleanup_expired(self, **kwargs) -> None:
        """清理过期的记忆"""
        now = datetime.now()

        cleaned = 0
        for scope_dir in self.memory_dir.iterdir():
            if not scope_dir.is_dir():
                continue

            for namespace_dir in scope_dir.iterdir():
                if not namespace_dir.is_dir():
                    continue

                for item_file in namespace_dir.glob("*.json"):
                    try:
                        with open(item_file, "r", encoding="utf-8") as f:
                            data = json.load(f)

                            # 过期检查
                            expires_at = data.get("expires_at")
                            if expires_at and datetime.fromisoformat(expires_at) < now:
                                Path(item_file).unlink()
                                cleaned += 1
                    except (json.JSONDecodeError, KeyError):
                        pass

        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} expired memory items")

    async def cleanup_low_importance(self, **kwargs) -> None:
        """清理低重要性的记忆"""
        threshold = kwargs.get("threshold", 20)

        for scope_dir in self.memory_dir.iterdir():
            if not scope_dir.is_dir():
                continue

            for namespace_dir in scope_dir.iterdir():
                if not namespace_dir.is_dir():
                    continue

                for item_file in namespace_dir.glob("*.json"):
                    try:
                        with open(item_file, "r", encoding="utf-8") as f:
                            data = json.load(f)

                            # 检查重要性
                            if data.get("importance", 0) < threshold:
                                Path(item_file).unlink()
                    except (json.JSONDecodeError, KeyError):
                        pass

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self._stats

    async def summarize_conversation(
        self, namespace: str, messages: List[Dict[str, Any]], **kwargs
    ) -> Any:
        """简单实现：返回基本总结"""
        participants = [
            msg.get("sender", "unknown") for msg in messages if msg.get("sender")
        ]
        topic = "conversation"
        now = datetime.now()

        summary = {
            "summary_id": str(int(datetime.now().timestamp())),
            "namespace": namespace,
            "participants": participants,
            "topic": topic,
            "start_time": now.isoformat(),
            "end_time": now.isoformat(),
            "key_points": [f"Messages: {len(messages)}"],
        }

        return summary

    async def add_conversation(self, summary: Any, **kwargs) -> None:
        """添加对话总结"""
        summary_id = summary.get("summary_id")
        namespace = summary.get("namespace", "default")

        scope_dir = self.conversations_dir / namespace
        scope_dir.mkdir(exist_ok=True, parents=True)

        summary_path = str(scope_dir / f"{summary_id}.json")

        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f)

        logger.debug(f"Conversation summary added: {summary_id}")

    async def get_conversations(
        self, namespace: str = "default", limit: int = 10
    ) -> List[Any]:
        """获取对话总结列表"""
        scope_dir = self.conversations_dir / namespace
        if not scope_dir.exists():
            return []

        results = []

        for summary_file in sorted(scope_dir.glob("*.json"), reverse=True):
            try:
                with open(summary_file, "r", encoding="utf-8") as f:
                    results.append(json.load(f))
            except (json.JSONDecodeError, KeyError):
                continue

        return results[:limit]


# 全局内存存储实例
_global_memory_store: Optional[MemoryStore] = None


def get_memory_store(base_dir: str = ".") -> MemoryStore:
    """获取或创建全局内存存储实例"""
    global _global_memory_store
    if _global_memory_store is None:
        _global_memory_store = FileMemoryStore(base_dir=base_dir)
    return _global_memory_store
