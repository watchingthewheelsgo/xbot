"""
XBot主入口
集成RSS数据源获取、市场数据、经济指标、关联分析、Telegram推送等功能
"""

import asyncio

from loguru import logger

from server.datastore.engine import close_db, init_db, get_session_factory
from server.settings import global_settings


async def main() -> None:
    """主函数"""
    logger.info("Starting XBot...")

    settings = global_settings
    logger.info(f"Service status: {settings.get_service_status()}")

    # 初始化服务客户端
    from server.services.client import get_service_client

    service_client = get_service_client()

    # 初始化数据源
    from server.datasource.rss.rss import RSSFetcher

    rss_fetcher = RSSFetcher()

    crypto_source = None
    if settings.is_coingecko_configured():
        from server.datasource.crypto.coingecko import CoinGeckoSource

        crypto_source = CoinGeckoSource(client=service_client)
        logger.info("CoinGecko source initialized")

    market_source = None
    finnhub_news = None
    if settings.is_finnhub_configured():
        from server.datasource.markets.finnhub import FinnhubSource
        from server.datasource.markets.finnhub_news import FinnhubNewsSource

        market_source = FinnhubSource(
            api_key=settings.finnhub_api_key, client=service_client
        )
        finnhub_news = FinnhubNewsSource(
            api_key=settings.finnhub_api_key, client=service_client
        )
        logger.info("Finnhub source initialized (quotes + news)")

    economic_source = None
    if settings.is_fred_configured():
        from server.datasource.economic.fred import FREDSource

        economic_source = FREDSource(
            api_key=settings.fred_api_key, client=service_client
        )
        logger.info("FRED source initialized")

    # 初始化关联分析引擎
    from server.analysis.correlation import CorrelationEngine

    correlation_engine = CorrelationEngine()
    logger.info("Correlation engine initialized")

    # 初始化报告生成器
    report_generator = None
    if settings.is_llm_configured():
        from server.reports.generator import ReportGenerator

        report_generator = ReportGenerator()
        logger.info("Report generator initialized")

    # 初始化统一调度器
    from server.datasource.scheduler import DataScheduler

    scheduler = DataScheduler()
    scheduler.set_sources(
        rss_fetcher=rss_fetcher,
        crypto_source=crypto_source,
        market_source=market_source,
        economic_source=economic_source,
        finnhub_news=finnhub_news,
    )

    # 初始化 Telegram Bot
    telegram_bot = None
    if settings.telegram_bot_token:
        from server.bot.telegram import TelegramBot
        from server.bot.dispatcher import CommandDispatcher, register_commands

        telegram_bot = TelegramBot(
            token=settings.telegram_bot_token,
            admin_chat_id=settings.telegram_admin_chat_id,
        )

        # 创建命令分发器并注册命令
        dispatcher = CommandDispatcher(
            scheduler=scheduler,
            correlation_engine=correlation_engine,
            report_generator=report_generator,
            rss_fetcher=rss_fetcher,
        )
        register_commands(telegram_bot, dispatcher)
        logger.info("Telegram bot initialized with commands")

    # 初始化 Feishu Bot (在同进程的后台线程中运行)
    feishu_bot = None
    if settings.is_feishu_configured():
        from server.bot.feishu_v2 import FeishuBotV2
        from server.bot.feishu_dispatcher import (
            FeishuCommandDispatcher,
            register_feishu_commands,
        )

        feishu_bot = FeishuBotV2(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret,
            admin_chat_ids=settings.get_feishu_admin_chat_ids(),
        )
        feishu_bot.set_event_loop(asyncio.get_event_loop())

        feishu_dispatcher = FeishuCommandDispatcher(
            scheduler=scheduler,
            correlation_engine=correlation_engine,
            report_generator=report_generator,
            rss_fetcher=rss_fetcher,
        )
        register_feishu_commands(feishu_bot, feishu_dispatcher)
        logger.info("Feishu bot initialized with commands")

    try:
        # 初始化数据库
        logger.info("Initializing database...")
        await init_db()
        logger.info("Database initialized successfully")

        # 从数据库加载关注列表
        from server.services.watchlist import load_watchlist

        await load_watchlist(get_session_factory())

        # 设置推送依赖（需要在数据库初始化之后）
        if telegram_bot or feishu_bot:
            scheduler.set_push_dependencies(
                telegram_bot=telegram_bot,
                feishu_bot=feishu_bot,
                correlation_engine=correlation_engine,
                report_generator=report_generator,
                db_session_factory=get_session_factory(),
            )

        # 启动 Feishu Bot WebSocket (后台线程)
        if feishu_bot:
            feishu_bot.start_in_thread()
            logger.info("Feishu bot WebSocket started")

        # 启动 Telegram Bot 轮询
        if telegram_bot:
            _tg_bot = telegram_bot
            for attempt in range(3):
                try:
                    await _tg_bot.initialize()
                    await _tg_bot.start_polling()
                    logger.info("Telegram bot polling started")
                    break
                except Exception as e:
                    logger.warning(f"Telegram init attempt {attempt + 1}/3 failed: {e}")
                    if attempt < 2:
                        await asyncio.sleep(5)
                    else:
                        logger.error(
                            "Failed to initialize Telegram bot after 3 attempts"
                        )
                        telegram_bot = None

        # 启动调度器
        logger.info("Starting data scheduler...")
        scheduler.start()

        # 执行初始数据抓取
        logger.info("Performing initial data fetch...")
        await scheduler.fetch_all_now()

        # 保持程序运行
        logger.info("XBot is running. Press Ctrl+C to stop.")
        while True:
            await asyncio.sleep(60)

    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    except Exception as e:
        logger.error(f"Error in main loop: {e}")
        raise
    finally:
        logger.info("Stopping scheduler...")
        scheduler.stop()

        if telegram_bot:
            logger.info("Stopping Telegram bot...")
            await telegram_bot.stop()

        if feishu_bot:
            logger.info("Stopping Feishu bot...")
            feishu_bot.stop()

        logger.info("Closing service client...")
        await service_client.close()

        logger.info("Closing database connections...")
        await close_db()

        logger.info("XBot stopped")


if __name__ == "__main__":
    asyncio.run(main())
