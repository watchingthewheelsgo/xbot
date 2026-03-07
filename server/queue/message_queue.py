"""
统一消息队列系统
支持按组隔离、全局并发限制、优先级处理和重试机制
"""

import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Optional, Callable, Dict, Any
from enum import Enum

from loguru import logger


class MessageType(Enum):
    """消息类型枚举"""

    NORMAL = "normal"
    URGENT = "urgent"
    SYSTEM = "system"
    BURST = "burst"
    TASK = "task"


class QueueItem:
    """队列项"""

    def __init__(
        self,
        message_type: MessageType,
        channel: str,
        chat_id: str,
        content: str,
        priority: int = 0,
        retry_count: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.message_type = message_type
        self.channel = channel
        self.chat_id = chat_id
        self.content = content
        self.priority = priority
        self.retry_count = retry_count
        self.metadata = metadata or {}
        self.created_at = datetime.now()
        self.queued_at = self.created_at
        self.processing_started_at: Optional[datetime] = None
        self.processing_ended_at: Optional[datetime] = None

    def __lt__(self, other: "QueueItem") -> bool:
        """优先级比较（优先级高的在前面）"""
        return self.priority > other.priority

    def __repr__(self) -> str:
        return (
            f"QueueItem(type={self.message_type.value}, "
            f"priority={self.priority}, "
            f"channel={self.channel}, "
            f"chat_id={self.chat_id})"
        )


class QueueStats:
    """队列统计信息"""

    def __init__(self):
        self.enqueued = 0
        self.processed = 0
        self.failed = 0
        self.retried = 0
        self.dropped = 0

    def increment(self, field: str) -> None:
        """递增统计字段"""
        if hasattr(self, field):
            setattr(self, field, getattr(self, field) + 1)

    def to_dict(self) -> Dict[str, int]:
        """转换为字典"""
        return {
            "enqueued": self.enqueued,
            "processed": self.processed,
            "failed": self.failed,
            "retried": self.retried,
            "dropped": self.dropped,
        }


class MessageQueue:
    """
    统一消息队列

    特性：
    - 按组隔离（每组独立队列）
    - 全局并发限制
    - 优先级支持
    - 指数退避重试
    - 任务优先于普通消息
    """

    # 配置常量
    MAX_RETRIES = 5
    BASE_RETRY_DELAY_MS = 5000  # 5秒
    MAX_RETRY_DELAY_MS = 300000  # 5分钟
    QUEUE_DROP_THRESHOLD = 10000  # 队列满时丢弃阈值

    def __init__(
        self,
        max_concurrent: int = 5,
        max_queue_size: int = 1000,
        max_age_minutes: int = 60,
    ):
        """
        Args:
            max_concurrent: 最大并发处理数
            max_queue_size: 每个队列最大大小
            max_age_minutes: 队列中消息最大存活时间（分钟）
        """
        self.max_concurrent = max_concurrent
        self.max_queue_size = max_queue_size
        self.max_age_minutes = max_age_minutes

        # 每组的队列
        self.queues: Dict[str, asyncio.Queue] = defaultdict(
            lambda: asyncio.Queue(maxsize=max_queue_size)
        )

        # 处理器注册
        self.processors: Dict[str, Callable[[QueueItem], Any]] = {}

        # 活跃任务追踪
        self.active_tasks: Dict[str, asyncio.Task] = {}

        # 并发控制
        self.semaphore = asyncio.Semaphore(max_concurrent)

        # 统计
        self.stats: Dict[str, QueueStats] = defaultdict(QueueStats)

        self._running = False

    def register_processor(
        self, queue_key: str, processor: Callable[[QueueItem], Any]
    ) -> None:
        """
        注册消息处理器

        Args:
            queue_key: 队列标识（通常是 channel 或 channel:chat_id）
            processor: 处理函数，接收 QueueItem
        """
        self.processors[queue_key] = processor
        logger.debug(f"Registered processor for queue: {queue_key}")

    async def enqueue(
        self,
        channel: str,
        chat_id: str,
        content: str,
        message_type: MessageType = MessageType.NORMAL,
        priority: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        将消息入队

        Args:
            channel: 渠道名称
            chat_id: 聊天ID
            content: 消息内容
            message_type: 消息类型
            priority: 优先级（数值越大优先级越高）
            metadata: 附加元数据

        Returns:
            True 如果成功入队，False 如果队列已满
        """
        queue_key = self._get_queue_key(channel, chat_id)

        # 检查队列是否已满
        queue = self.queues[queue_key]
        if queue.full():
            logger.warning(
                f"Queue {queue_key} is full, dropping message. "
                f"Queue size: {queue.qsize()}, Max: {self.max_queue_size}"
            )
            self.stats[queue_key].increment("dropped")
            return False

        # 创建队列项
        item = QueueItem(
            message_type=message_type,
            channel=channel,
            chat_id=chat_id,
            content=content,
            priority=priority,
            metadata=metadata,
        )

        try:
            # 尝试入队，带超时防止永久阻塞
            await asyncio.wait_for(queue.put(item), timeout=1.0)
            self.stats[queue_key].increment("enqueued")
            logger.debug(
                f"Enqueued message to {queue_key}, queue size: {queue.qsize()}"
            )
            return True
        except asyncio.TimeoutError:
            logger.error(f"Timeout putting message into queue {queue_key}")
            self.stats[queue_key].increment("dropped")
            return False

    async def enqueue_task(
        self,
        channel: str,
        task_name: str,
        task_data: Dict[str, Any],
        priority: int = 10,  # 任务默认高优先级
    ) -> bool:
        """
        将任务入队（任务优先级高于普通消息）

        Args:
            channel: 渠道名称
            task_name: 任务名称
            task_data: 任务数据
            priority: 优先级

        Returns:
            True 如果成功入队
        """
        queue_key = self._get_queue_key(channel, "tasks")

        if self.queues[queue_key].full():
            logger.warning(f"Task queue {queue_key} is full")
            self.stats[queue_key].increment("dropped")
            return False

        content = f"[TASK] {task_name}"
        metadata = {"task": True, "task_data": task_data}

        return await self.enqueue(
            channel=channel,
            chat_id="tasks",
            content=content,
            message_type=MessageType.TASK,
            priority=priority,
            metadata=metadata,
        )

    async def process_queue(
        self,
        queue_key: str,
        max_workers: Optional[int] = None,
    ) -> None:
        """
        处理指定队列中的消息

        Args:
            queue_key: 队列标识
            max_workers: 最大工作协程数（None 表示使用全局限制）
        """
        processor = self.processors.get(queue_key)
        if not processor:
            logger.warning(f"No processor registered for queue: {queue_key}")
            return

        queue = self.queues[queue_key]

        # 使用独立信号量控制此队列的并发
        if max_workers:
            local_semaphore = asyncio.Semaphore(max_workers)
        else:
            local_semaphore = self.semaphore

        logger.info(f"Starting queue processor for {queue_key}")

        while self._running:
            try:
                async with local_semaphore:
                    item = await queue.get()

                    # 跳过过期的消息
                    age_minutes = (
                        datetime.now() - item.created_at
                    ).total_seconds() / 60
                    if age_minutes > self.max_age_minutes:
                        logger.debug(
                            f"Dropping expired message from {queue_key}, age: {age_minutes:.1f}min"
                        )
                        self.stats[queue_key].increment("dropped")
                        continue

                    item.processing_started_at = datetime.now()

                    try:
                        # 执行处理器
                        result = await processor(item)

                        if result is False:
                            # 处理器返回 False 表示失败，重试
                            if item.retry_count < self.MAX_RETRIES:
                                delay = self._calculate_retry_delay(item.retry_count)
                                logger.info(
                                    f"Retrying message from {queue_key}, "
                                    f"attempt {item.retry_count + 1}, delay: {delay / 1000}s"
                                )
                                await asyncio.sleep(delay / 1000)

                                # 重新入队
                                item.retry_count += 1
                                await queue.put(item)
                                self.stats[queue_key].increment("retried")
                            else:
                                logger.error(
                                    f"Message failed after {self.MAX_RETRIES} retries, dropping"
                                )
                                self.stats[queue_key].increment("failed")
                        else:
                            self.stats[queue_key].increment("processed")

                        item.processing_ended_at = datetime.now()

                    except asyncio.CancelledError:
                        logger.debug(f"Message processing cancelled for {queue_key}")
                        # 重新入队以便后续处理
                        await queue.put(item)

                    except Exception as e:
                        logger.error(
                            f"Error processing message from {queue_key}: {e}",
                            exc_info=True,
                        )
                        self.stats[queue_key].increment("failed")

            except asyncio.CancelledError:
                logger.info(f"Queue processor {queue_key} cancelled")
                break

    async def process_all_queues(self) -> None:
        """处理所有队列"""
        logger.info("Starting all queue processors")
        for queue_key in list(self.queues.keys()):
            asyncio.create_task(self.process_queue(queue_key))

    async def drain_queue(self, queue_key: str) -> int:
        """
        清空指定队列（用于关闭前）

        Args:
            queue_key: 队列标识

        Returns:
            已处理的消息数量
        """
        queue = self.queues[queue_key]
        count = 0

        while not queue.empty():
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.1)
                if item.message_type != MessageType.TASK:
                    count += 1
            except asyncio.TimeoutError:
                break

        return count

    async def shutdown(self) -> None:
        """优雅关闭队列系统"""
        logger.info("Shutting down message queue...")
        self._running = False

        # 取消所有活跃任务
        for task_id, task in self.active_tasks.items():
            if not task.done():
                task.cancel()
                logger.debug(f"Cancelled task {task_id}")

        # 等待所有任务完成
        if self.active_tasks:
            await asyncio.gather(
                *[
                    asyncio.wait_for(task, timeout=5.0)
                    for task in self.active_tasks.values()
                ],
                return_exceptions=True,
            )

        logger.info("Message queue shutdown complete")

    def _get_queue_key(self, channel: str, chat_id: str) -> str:
        """生成队列键"""
        return f"{channel}:{chat_id}"

    def _calculate_retry_delay(self, retry_count: int) -> int:
        """计算重试延迟（指教退避）"""
        delay = self.BASE_RETRY_DELAY_MS * (2**retry_count)
        return min(delay, self.MAX_RETRY_DELAY_MS)

    def get_queue_stats(self) -> Dict[str, Dict[str, int]]:
        """获取所有队列的统计信息"""
        result = {}
        for queue_key, stats in self.stats.items():
            result[queue_key] = {
                "queue_size": self.queues[queue_key].qsize(),
                **stats.to_dict(),
            }
        return result

    def get_global_stats(self) -> Dict[str, int]:
        """获取全局统计"""
        total = {
            "active_tasks": len(self.active_tasks),
            "total_queues": len(self.queues),
            "max_concurrent": self.max_concurrent,
            "current_concurrent": self.max_concurrent - self.semaphore._value,
            "total_queued": sum(s.enqueued for s in self.stats.values()),
            "total_processed": sum(s.processed for s in self.stats.values()),
            "total_failed": sum(s.failed for s in self.stats.values()),
            "total_retried": sum(s.retried for s in self.stats.values()),
            "total_dropped": sum(s.dropped for s in self.stats.values()),
        }
        return total

    def get_queue_info(self) -> Dict[str, Any]:
        """获取队列系统信息"""
        return {
            "running": self._running,
            "max_concurrent": self.max_concurrent,
            "max_queue_size": self.max_queue_size,
            "max_age_minutes": self.max_age_minutes,
            "queues": list(self.queues.keys()),
            "processors": list(self.processors.keys()),
        }


# 全局队列实例
_global_queue: Optional[MessageQueue] = None


def get_global_queue() -> MessageQueue:
    """获取或创建全局队列实例"""
    global _global_queue
    if _global_queue is None:
        _global_queue = MessageQueue()
    return _global_queue


def init_global_queue(
    max_concurrent: int = 5,
    max_queue_size: int = 1000,
    max_age_minutes: int = 60,
) -> MessageQueue:
    """初始化全局队列"""
    global _global_queue
    _global_queue = MessageQueue(
        max_concurrent=max_concurrent,
        max_queue_size=max_queue_size,
        max_age_minutes=max_age_minutes,
    )
    return _global_queue
