"""
数据库引擎配置和管理
使用SQLAlchemy异步引擎连接SQLite数据库
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.datastore.models import Base
from server.settings import global_settings

# 全局数据库引擎实例
engine = None
AsyncSessionLocal = None


async def init_db() -> None:
    """初始化数据库连接和表结构"""
    global engine, AsyncSessionLocal

    # 创建异步引擎
    engine = create_async_engine(
        global_settings.database_url,
        echo=global_settings.database_echo,
        future=True,
    )

    # 创建会话工厂
    AsyncSessionLocal = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # 创建所有表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话（生成器函数，用于依赖注入）"""
    if AsyncSessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def close_db() -> None:
    """关闭数据库连接"""
    global engine
    if engine:
        await engine.dispose()


def get_session_factory():
    """获取会话工厂（用于调度器等需要直接创建会话的场景）"""
    if AsyncSessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return AsyncSessionLocal
