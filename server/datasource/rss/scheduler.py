"""
RSS定时任务调度器
使用APScheduler实现定期抓取RSS feed
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from server.datasource.rss.rss import RSSFetcher
from server.settings import global_settings
from server.utils import safe_func_wrapper


class RSSScheduler:
    """RSS定时任务调度器"""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.fetcher: RSSFetcher | None = None
        self._is_running = False

    def _ensure_fetcher(self) -> RSSFetcher:
        """确保fetcher已初始化"""
        if self.fetcher is None:
            self.fetcher = RSSFetcher()
        return self.fetcher

    @safe_func_wrapper
    async def fetch_rss_job(self) -> None:
        """RSS抓取任务"""
        logger.info("Starting scheduled RSS fetch...")
        try:
            fetcher = self._ensure_fetcher()
            stats = await fetcher.fetch_all_feeds()
            total = sum(stats.values())
            logger.info(f"Scheduled RSS fetch completed: {total} new articles")

            # 记录每个源的详细信息
            for feed_name, count in stats.items():
                if count > 0:
                    logger.info(f"  - {feed_name}: {count} new articles")

        except Exception as e:
            logger.error(f"Error in scheduled RSS fetch: {e}")

    def start(self) -> None:
        """启动调度器"""
        if self._is_running:
            logger.warning("RSS scheduler is already running")
            return

        interval_minutes = global_settings.rss_update_interval_minutes

        # 添加定时任务
        self.scheduler.add_job(
            self.fetch_rss_job,
            trigger="interval",
            minutes=interval_minutes,
            id="rss_fetch_job",
            name="RSS Feed Fetcher",
            replace_existing=True,
        )

        # 启动调度器
        self.scheduler.start()
        self._is_running = True

        logger.info(f"RSS scheduler started: fetching every {interval_minutes} minutes")

    def stop(self) -> None:
        """停止调度器"""
        if not self._is_running:
            logger.warning("RSS scheduler is not running")
            return

        self.scheduler.shutdown(wait=False)
        self._is_running = False
        logger.info("RSS scheduler stopped")

    def is_running(self) -> bool:
        """检查调度器是否运行中"""
        return self._is_running

    async def fetch_now(self) -> dict[str, int]:
        """立即执行一次抓取（手动触发）"""
        logger.info("Manual RSS fetch triggered")
        fetcher = self._ensure_fetcher()
        stats = await fetcher.fetch_all_feeds()
        total = sum(stats.values())
        logger.info(f"Manual RSS fetch completed: {total} new articles")
        return stats


# 全局调度器实例
rss_scheduler = RSSScheduler()
