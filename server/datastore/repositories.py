"""
数据库Repository层 - 封装数据访问逻辑
"""

from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.datastore.models import (
    NewsAnalysisCacheDB,
    NewsPushLogDB,
)


class NewsPushLogRepository:
    """新闻推送日志Repository"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def has_been_pushed(self, news_hash: str, hours: int = 24) -> bool:
        """检查新闻是否在指定小时内已推送"""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        result = await self.session.execute(
            select(NewsPushLogDB).where(
                NewsPushLogDB.news_hash == news_hash,
                NewsPushLogDB.pushed_at >= cutoff,
            )
        )
        return result.scalar_one_or_none() is not None

    async def mark_pushed(self, news_hash: str, push_type: str = "digest") -> None:
        """标记新闻为已推送"""
        log = NewsPushLogDB(
            news_hash=news_hash,
            push_type=push_type,
            pushed_at=datetime.utcnow(),
        )
        self.session.add(log)

    async def cleanup_old_logs(self, days: int = 7) -> int:
        """清理旧的推送日志"""
        cutoff = datetime.utcnow() - timedelta(days=days)
        stmt = delete(NewsPushLogDB).where(NewsPushLogDB.pushed_at < cutoff)
        await self.session.execute(stmt)
        await self.session.flush()
        # In SQLAlchemy 2.0, rowcount is accessed from the session
        # after execution, but type stubs don't reflect this
        deleted = (
            getattr(self.session, "rowcount", 0)
            if hasattr(self.session, "rowcount")
            else 0
        )
        if deleted > 0:
            logger.debug(f"Cleaned up {deleted} old push log entries")
        return deleted

    async def get_recent_pushed_hashes(self, hours: int = 24) -> set[str]:
        """获取最近指定小时内已推送的新闻hash集合"""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        result = await self.session.execute(
            select(NewsPushLogDB.news_hash).where(NewsPushLogDB.pushed_at >= cutoff)
        )
        return set(result.scalars().all())

    async def get_push_count(self, hours: int = 24) -> int:
        """获取最近指定小时内的推送数量"""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        result = await self.session.execute(
            select(NewsPushLogDB).where(NewsPushLogDB.pushed_at >= cutoff)
        )
        return len(result.scalars().all())


class NewsAnalysisCacheRepository:
    """LLM分析结果缓存Repository"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, news_hash: str) -> dict | None:
        """获取缓存的LLM分析结果"""
        import json

        cache = await self.session.execute(
            select(NewsAnalysisCacheDB).where(
                NewsAnalysisCacheDB.news_hash == news_hash,
                NewsAnalysisCacheDB.expires_at > datetime.utcnow(),
            )
        )
        cached = cache.scalar_one_or_none()
        if not cached:
            return None

        # 反序列化JSON字段
        market_impact = {}
        if cached.market_impact_json:
            try:
                market_impact = json.loads(cached.market_impact_json)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse cached market_impact: {e}")

        return {
            "chinese_summary": cached.chinese_summary,
            "background": cached.background,
            "market_impact": market_impact,
            "action": cached.action,
            "importance": cached.importance,
        }

    async def set(
        self,
        news_hash: str,
        chinese_summary: str,
        background: str,
        market_impact: dict,
        action: str,
        importance: int,
        ttl_hours: int = 24,
    ) -> None:
        """缓存LLM分析结果"""
        import json

        # 检查是否已存在（更新）
        existing = await self.session.execute(
            select(NewsAnalysisCacheDB).where(
                NewsAnalysisCacheDB.news_hash == news_hash
            )
        )
        cached = existing.scalar_one_or_none()

        market_impact_json = json.dumps(market_impact, ensure_ascii=False)
        expires_at = datetime.utcnow() + timedelta(hours=ttl_hours)

        if cached:
            # 更新现有记录
            cached.chinese_summary = chinese_summary
            cached.background = background
            cached.market_impact_json = market_impact_json
            cached.action = action
            cached.importance = importance
            cached.cached_at = datetime.utcnow()
            cached.expires_at = expires_at
            logger.debug(f"Updated cache for news hash: {news_hash[:12]}...")
        else:
            # 创建新记录
            cached = NewsAnalysisCacheDB(
                news_hash=news_hash,
                chinese_summary=chinese_summary,
                background=background,
                market_impact_json=market_impact_json,
                action=action,
                importance=importance,
                cached_at=datetime.utcnow(),
                expires_at=expires_at,
            )
            self.session.add(cached)
            logger.debug(f"Created cache for news hash: {news_hash[:12]}...")

    async def cleanup_expired(self) -> int:
        """清理过期的缓存"""
        await self.session.execute(
            delete(NewsAnalysisCacheDB).where(
                NewsAnalysisCacheDB.expires_at < datetime.utcnow()
            )
        )
        await self.session.flush()
        # In SQLAlchemy 2.0, rowcount is accessed from the session
        deleted = (
            getattr(self.session, "rowcount", 0)
            if hasattr(self.session, "rowcount")
            else 0
        )
        if deleted > 0:
            logger.debug(f"Cleaned up {deleted} expired cache entries")
        return deleted

    async def get_cache_stats(self) -> dict[str, int]:
        """获取缓存统计信息"""
        total = await self.session.execute(select(NewsAnalysisCacheDB))
        total_count = len(total.scalars().all())

        expired = await self.session.execute(
            select(NewsAnalysisCacheDB).where(
                NewsAnalysisCacheDB.expires_at < datetime.utcnow()
            )
        )
        expired_count = len(expired.scalars().all())

        return {
            "total_entries": total_count,
            "expired_entries": expired_count,
            "active_entries": total_count - expired_count,
        }
