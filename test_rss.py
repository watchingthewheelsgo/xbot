"""
测试RSS功能的简单脚本
"""

import asyncio

from loguru import logger

from server.datasource.rss import RSSFetcher
from server.datastore.engine import close_db, init_db


async def test_rss() -> None:
    """测试RSS获取功能"""
    try:
        # 初始化数据库
        logger.info("Initializing database...")
        await init_db()

        # 创建RSS获取器
        fetcher = RSSFetcher()
        logger.info(f"Loaded {len(fetcher.feeds)} RSS feeds")

        # 获取所有RSS
        logger.info("Fetching all RSS feeds...")
        stats = await fetcher.fetch_all_feeds()

        # 输出结果
        logger.info("\n" + "=" * 50)
        logger.info("RSS Fetch Results:")
        logger.info("=" * 50)

        total = 0
        for feed_name, count in stats.items():
            logger.info(f"  {feed_name}: {count} new articles")
            total += count

        logger.info("=" * 50)
        logger.info(f"Total: {total} new articles")
        logger.info("=" * 50)

    except Exception as e:
        logger.error(f"Error during test: {e}")
        raise
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(test_rss())
