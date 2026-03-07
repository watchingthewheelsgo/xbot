"""
数据库连接池管理
优化 SQLAlchemy 连接，提供更好的并发性能和资源管理
"""

import asyncio
from typing import Optional
from contextlib import asynccontextmanager

from loguru import logger


class DatabasePool:
    """
    数据库连接池

    特性：
    - 连接池大小控制
    - 连接生命周期管理
    - 自动重连机制
    - 健康检查
    - 统计信息收集
    """

    # 默认配置
    DEFAULT_POOL_SIZE = 5
    DEFAULT_MAX_OVERFLOW = 10
    DEFAULT_POOL_RECYCLE = 3600  # 1小时
    DEFAULT_POOL_PRE_PING = True

    def __init__(
        self,
        url: str,
        pool_size: int = DEFAULT_POOL_SIZE,
        max_overflow: int = DEFAULT_MAX_OVERFLOW,
        recycle: int = DEFAULT_POOL_RECYCLE,
        pool_pre_ping: bool = DEFAULT_POOL_PRE_PING,
        echo: bool = False,
    ):
        self.url = url
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.recycle = recycle
        self.pool_pre_ping = pool_pre_ping
        self.echo = echo

        self._engine = None
        self._session_factory = None

        # 统计信息
        self._stats = {
            "total_connections": 0,
            "active_connections": 0,
            "idle_connections": 0,
            "failed_connections": 0,
            "checkout_count": 0,
            "checkin_count": 0,
            "checkin_failed_count": 0,
            "total_acquired": 0,
            "total_released": 0,
            "total_errors": 0,
            "created_at": None,
            "last_checkout": None,
            "last_checkin": None,
            "last_checkin_failed": None,
            "last_error": None,
        }

        self._running = False

        logger.info(
            f"DatabasePool initialized: {url}, "
            f"size={pool_size}, "
            f"max_overflow={max_overflow}, "
            f"recycle={recycle}s"
        )

    async def initialize(self) -> None:
        """初始化连接池"""
        from sqlalchemy.ext.asyncio import (
            create_async_engine,
            async_sessionmaker,
            AsyncSession,
            # NullPool removed - not in sqlalchemy.ext.asyncio
        )

        self._engine = create_async_engine(
            self.url,
            echo=self.echo,
            pool_size=self.pool_size,
            max_overflow=self.max_overflow,
            pool_recycle=self.recycle,
            pool_pre_ping=self.pool_pre_ping,
            # 连接池配置
            poolclass=None,
        )

        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        self._stats["created_at"] = asyncio.get_event_loop().time()

        try:
            # 预热连接池（创建初始连接）
            async with self._session_factory() as session:
                # 执行简单查询来预热
                from sqlalchemy import text

                await session.execute(text("SELECT 1"))
                pass

            logger.info("Database pool initialized and warmed up")

        except Exception as e:
            logger.error(f"Database pool initialization failed: {e}")

    @asynccontextmanager
    async def get_session(self):
        """
        获取数据库会话的上下文管理器

        自动处理事务和异常
        """
        if not self._session_factory:
            raise RuntimeError("Database pool not initialized")

        self._stats["total_acquired"] += 1
        self._stats["active_connections"] += 1

        try:
            async with self._session_factory() as session:
                try:
                    yield session
                    # 提交事务
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
                finally:
                    self._stats["active_connections"] -= 1
                    self._stats["total_released"] += 1

        except Exception as e:
            logger.error(f"Session error: {e}")
            raise

    async def close(self) -> None:
        """关闭连接池"""
        if not self._running:
            return

        self._running = False

        if self._engine:
            try:
                logger.info("Closing database pool...")

                # 调用连接池关闭
                if hasattr(self._engine, "dispose"):
                    await self._engine.dispose()
                elif hasattr(self._engine, "close"):
                    self._engine.close()  # type: ignore

                logger.info("Database pool closed")

            except Exception as e:
                logger.error(f"Error closing database pool: {e}")

    async def health_check(self) -> bool:
        """健康检查"""
        if not self._session_factory:
            return False

        try:
            async with self._session_factory() as session:
                from sqlalchemy import text

                await session.execute(text("SELECT 1"))

            self._stats["last_checkin"] = asyncio.get_event_loop().time()
            return True

        except Exception as e:
            self._stats["last_checkin_failed"] = asyncio.get_event_loop().time()
            logger.error(f"Database health check failed: {e}")
            return False

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "url": self.url,
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
            "recycle": self.recycle,
            "running": self._running,
            **self._stats,
        }


# 全局连接池实例
_global_pool: Optional[DatabasePool] = None


def get_global_pool(url: str, **kwargs) -> DatabasePool:
    """获取或创建全局连接池实例"""
    global _global_pool
    if _global_pool is None:
        _global_pool = DatabasePool(url=url, **kwargs)
    return _global_pool


async def close_global_pool() -> None:
    """关闭全局连接池"""
    global _global_pool
    if _global_pool:
        await _global_pool.close()
        _global_pool = None
