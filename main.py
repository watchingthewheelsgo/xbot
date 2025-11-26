"""
XBot主入口
集成RSS数据源获取、Telegram Bot等功能
"""

import asyncio

from loguru import logger

from server.datasource.rss import rss_scheduler
from server.datastore.engine import close_db, init_db


async def main() -> None:
    """主函数"""
    logger.info("Starting XBot...")

    try:
        # 初始化数据库
        logger.info("Initializing database...")
        await init_db()
        logger.info("Database initialized successfully")

        # 启动RSS调度器
        logger.info("Starting RSS scheduler...")
        rss_scheduler.start()

        # 执行第一次RSS抓取
        logger.info("Performing initial RSS fetch...")
        await rss_scheduler.fetch_now()

        # 保持程序运行
        logger.info("XBot is running. Press Ctrl+C to stop.")
        while True:
            await asyncio.sleep(60)

    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    except Exception as e:
        logger.error(f"Error in main loop: {e}")
    finally:
        # 清理资源
        logger.info("Stopping RSS scheduler...")
        rss_scheduler.stop()

        logger.info("Closing database connections...")
        await close_db()

        logger.info("XBot stopped")


if __name__ == "__main__":
    asyncio.run(main())
