"""
会话记忆基类和类型定义
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class MemoryType(Enum):
    """记忆类型"""

    PREFERENCE = "reference"  # 参考信息（用户偏好、配置等）
    CONVERSATION = "conversation"  # 对话总结
    KNOWLEDGE = "knowledge"  # 知识库
    FACT = "fact"  # 事实（发生过的事件）
    PREFERENCE_ITEM = "reference_item"  # 参考条目


class MemoryScope(Enum):
    """记忆作用域"""

    GLOBAL = "global"  # 全局（所有会话共享）
    GROUP = "group"  # 组（特定聊天组）
    USER = "user"  # 用户（特定用户）
    TASK = "task"  # 任务上下文


@dataclass
class MemoryItem:
    """记忆项"""

    id: str
    type: MemoryType
    scope: MemoryScope
    namespace: str  # 命名空间标识
    key: str  # 记忆键
    value: str  # 记忆值
    importance: int = field(default=0)  # 重要性 0-100
    tags: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    access_count: int = field(default=0)  # 访问次数
    metadata: Dict[str, Any] = field(default_factory=dict)
    embeddings: Optional[List[float]] = None  # 向量嵌入（用于语义搜索）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "scope": self.scope.value,
            "namespace": self.namespace,
            "key": self.key,
            "value": self.value,
            "importance": self.importance,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "access_count": self.access_count,
            "metadata": self.metadata,
        }


@dataclass
class MemoryQuery:
    """记忆查询"""

    query: str  # 查询文本
    type: Optional[MemoryType] = None  # 类型过滤
    scope: Optional[MemoryScope] = None  # 作用域过滤
    namespace: Optional[str] = None  # 命名空间过滤
    tags: Optional[List[str]] = None  # 标签过滤
    min_importance: Optional[int] = None  # 最小重要性
    limit: int = 10  # 结果数量限制
    fuzzy: bool = True  # 是否模糊搜索
    include_expired: bool = False  # 是否包含已过期的


@dataclass
class MemorySearchResult:
    """记忆搜索结果"""

    total: int
    items: List[MemoryItem]
    query: str
    execution_time_ms: int


@dataclass
class ConversationSummary:
    """对话总结"""

    summary_id: str
    namespace: str
    participants: List[str]  # 参与者
    topic: str  # 对话主题
    start_time: datetime
    end_time: datetime
    key_points: List[str]  # 关键点
    sentiment: Optional[str] = None  # 情感倾向
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary_id": self.summary_id,
            "namespace": self.namespace,
            "participants": self.participants,
            "topic": self.topic,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "key_points": self.key_points,
            "sentiment": self.sentiment,
            "created_at": self.created_at.isoformat(),
        }


class MemoryStats:
    """记忆统计信息"""

    def __init__(self):
        self.total_items = 0
        self.by_type = {t.value: 0 for t in MemoryType}
        self.by_scope = {s.value: 0 for s in MemoryScope}
        self.total_searches = 0
        self.cache_hits = 0
        self.cache_misses = 0

    def add_item(self, item: MemoryItem) -> None:
        """添加记忆项"""
        self.total_items += 1
        self.by_type[item.type.value] += 1
        self.by_scope[item.scope.value] += 1

    def record_search(self, hit: bool) -> None:
        """记录搜索命中"""
        self.total_searches += 1
        if hit:
            self.cache_hits += 1
        else:
            self.cache_misses += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_items": self.total_items,
            "by_type": self.by_type,
            "by_scope": self.by_scope,
            "total_searches": self.total_searches,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
        }


def generate_memory_id() -> str:
    """生成唯一的记忆 ID"""
    return (
        f"mem_{datetime.now().timestamp()}_{str(hash(datetime.now().isoformat()))[:8]}"
    )
