"""
统一的新闻处理服务 - 整合获取、过滤、分析、推送
"""

from datetime import datetime, timedelta

from loguru import logger

from server.datastore.repositories import (
    NewsAnalysisCacheRepository,
    NewsPushLogRepository,
)
from server.datasource.source_manager import SourceManager
from server.services.news_aggregator import NewsAggregator, NewsAnalyzer, NewsItem


class NewsProcessor:
    """统一的新闻处理器"""

    def __init__(
        self,
        session_factory,
        source_manager: SourceManager,
        news_aggregator: NewsAggregator,
        news_analyzer: NewsAnalyzer | None = None,
        scheduler=None,  # DataScheduler for fetching news
    ):
        self.session_factory = session_factory
        self.source_manager = source_manager
        self.news_aggregator = news_aggregator
        self.news_analyzer = news_analyzer
        self.scheduler = scheduler

    async def get_and_process_news(
        self,
        hours: float = 2,
        max_items: int = 20,
        filter_pushed: bool = True,
        push_type: str = "digest",
        use_cache: bool = True,
        platform: str = "",
        fetch_start_time: datetime | None = None,
    ) -> list[NewsItem]:
        """
        获取和处理新闻的统一入口

        Args:
            hours: 获取最近多少小时的新闻
            max_items: 最多返回多少条
            filter_pushed: 是否过滤已推送的新闻
            push_type: 推送类型（用于日志）
            use_cache: 是否使用LLM缓存
            platform: 推送平台（用于按平台去重，如 "feishu", "telegram"）
            fetch_start_time: 指定获取新闻的起始时间（用于继续推送功能）
        """
        # Step 1: 获取原始新闻
        news_items = await self._fetch_recent_news(
            hours=hours, fetch_start_time=fetch_start_time
        )

        if not news_items:
            return []

        # Step 2: 聚合去重（带源优先级排序）
        aggregated = self.news_aggregator.aggregate(
            news_items,
            time_window_minutes=int(hours * 60),
            source_manager=self.source_manager,
        )

        if not aggregated:
            return []

        # Step 3: 过滤已推送（如果需要）
        if filter_pushed and self.session_factory:
            async with self.session_factory() as session:
                push_repo = NewsPushLogRepository(session)
                recent_pushed = await push_repo.get_recent_pushed_hashes(
                    hours=24, platform=platform
                )

                filtered = [item for item in aggregated if item.id not in recent_pushed]
                logger.info(
                    f"[推送过滤] 已推送过滤 (platform={platform}): {len(aggregated)} -> {len(filtered)}"
                )
                aggregated = filtered

        if not aggregated:
            return []

        # Step 4: LLM分析（带缓存）
        if self.news_analyzer:
            aggregated = await self.news_analyzer.analyze_batch(
                aggregated, max_items=max_items
            )

        # Step 5: 按重要性或源优先级排序并限制数量
        if any(item.importance >= 2 for item in aggregated):
            # 有重要性评分，按重要性排序
            aggregated = sorted(
                [i for i in aggregated if i.importance >= 2],
                key=lambda x: x.importance,
                reverse=True,
            )
            logger.info(f"[排序] 按重要性排序，重要性>=2的新闻: {len(aggregated)} 条")
        else:
            # 没有重要性评分，按源优先级和时间排序
            aggregated = sorted(
                aggregated,
                key=lambda x: (x.source_priority, x.published),
                reverse=True,
            )
            logger.info("[排序] 按源优先级和时间排序")

        return aggregated[:max_items]

    async def mark_as_pushed(
        self, items: list[NewsItem], push_type: str = "digest", platform: str = ""
    ) -> None:
        """标记新闻为已推送（可指定平台）"""
        if not self.session_factory:
            return

        async with self.session_factory() as session:
            push_repo = NewsPushLogRepository(session)
            for item in items:
                await push_repo.mark_pushed(item.id, push_type, platform)

            await session.commit()

            # 定期清理旧日志
            deleted = await push_repo.cleanup_old_logs(days=7)
            if deleted > 0:
                logger.info(f"[推送日志] 清理旧记录 {deleted} 条")

    async def _fetch_recent_news(
        self, hours: float, fetch_start_time: datetime | None = None
    ) -> list[dict]:
        """获取最近的新闻（复用scheduler逻辑）

        Args:
            hours: 获取最近多少小时的新闻
            fetch_start_time: 指定获取新闻的起始时间（用于继续推送功能）
                           如果为 None，则获取 30 分钟前的新闻（第一次获取）
        """
        import time

        start_time = time.time()

        # Determine cutoff time
        if fetch_start_time is None:
            # First fetch: get news from 30 minutes ago
            cutoff = datetime.utcnow() - timedelta(minutes=30)
            logger.info(f"[新闻获取] 初始获取：获取 {cutoff} 之后 30 分钟内的新闻")
        else:
            # Continue fetch: get news from fetch_start_time to now
            cutoff = fetch_start_time
            hours_elapsed = (
                datetime.utcnow() - fetch_start_time
            ).total_seconds() / 3600
            logger.info(
                f"[新闻获取] 继续获取：获取 {fetch_start_time} 之后 {hours_elapsed:.1f} 小时 ({hours_elapsed * 60:.0f} 分钟) 的新闻"
            )

        logger.info("[新闻获取] 开始获取新闻...")

        news_items = []
        rss_count = 0
        finnhub_count = 0

        # Get RSS articles from database
        if self.session_factory:
            try:
                from sqlalchemy import select
                from server.datastore.models import RSSArticleDB

                rss_start = time.time()
                # Use the determined cutoff time
                async with self.session_factory() as session:
                    query = (
                        select(RSSArticleDB)
                        .where(RSSArticleDB.fetched_at >= cutoff)
                        .order_by(RSSArticleDB.fetched_at.desc())
                        .limit(200)
                    )
                    result = await session.execute(query)
                    articles = result.scalars().all()

                    for a in articles:
                        news_items.append(
                            {
                                "title": a.title,
                                "source": a.feed_name,
                                "source_type": "rss",
                                "published": a.published,
                                "summary": a.summary,
                                "link": a.link,
                                "category": a.category,
                            }
                        )
                    rss_count = len(articles)

                rss_elapsed = time.time() - rss_start
                logger.info(
                    f"[新闻获取] RSS 获取完成，耗时 {rss_elapsed:.2f}s，共 {rss_count} 条"
                )

            except Exception as e:
                logger.error(f"Failed to get RSS news: {e}")

        # Get Finnhub news from scheduler cache
        if self.scheduler and hasattr(self.scheduler, "_latest_finnhub_news"):
            finnhub_start = time.time()
            for fn in self.scheduler._latest_finnhub_news:
                if fn.published_at >= cutoff:
                    news_items.append(
                        {
                            "title": fn.headline,
                            "source": fn.source,
                            "source_type": "finnhub",
                            "published": fn.published_at,
                            "summary": fn.summary,
                            "link": fn.url,
                            "category": fn.category,
                            "related_symbols": fn.related_symbols,
                        }
                    )
            finnhub_count = len(
                [n for n in news_items if n.get("source_type") == "finnhub"]
            )

            finnhub_elapsed = time.time() - finnhub_start
            logger.info(
                f"[新闻获取] Finnhub 获取完成，耗时 {finnhub_elapsed:.2f}s，共 {finnhub_count} 条"
            )

        # Sort by published date
        news_items.sort(key=lambda x: x.get("published", datetime.min), reverse=True)

        total_elapsed = time.time() - start_time
        logger.info(
            f"[新闻获取] 完成，总耗时 {total_elapsed:.2f}s（RSS {rss_count} + Finnhub {finnhub_count} = 总共 {len(news_items)} 条）"
        )

        return news_items

    def get_status(self) -> dict:
        """获取处理器状态"""
        status = {
            "source_manager": self.source_manager.get_status()
            if self.source_manager
            else None,
            "aggregator": {
                "seen_hashes": len(self.news_aggregator._seen_hashes),
            }
            if self.news_aggregator
            else None,
        }

        if self.session_factory:
            import asyncio

            try:

                async def _get_stats():
                    async with self.session_factory() as session:
                        cache_repo = NewsAnalysisCacheRepository(session)
                        return await cache_repo.get_cache_stats()

                cache_stats = asyncio.run(_get_stats())
                status["cache"] = cache_stats
            except Exception as e:
                logger.warning(f"Failed to get cache stats: {e}")

        return status
