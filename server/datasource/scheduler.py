"""
Unified data scheduler - manages all data source fetch jobs and push notifications.

This scheduler coordinates all data fetching jobs and push notifications,
with support for multiple platforms (Telegram, Feishu) and atomic
task claiming to prevent duplicate executions.
"""

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from server.settings import global_settings

if TYPE_CHECKING:
    from server.bot.telegram import TelegramBot
    from server.bot.feishu_v2 import FeishuBotV2
    from server.analysis.correlation import CorrelationEngine
    from server.reports.generator import ReportGenerator
    from server.services.news_processor import NewsProcessor
    from server.datasource.source_manager import SourceManager
    from server.datasource.rss.rss import RSSFetcher
    from server.datasource.crypto.coingecko import CoinGeckoSource
    from server.datasource.markets.finnhub import FinnhubSource
    from server.datasource.markets.finnhub_news import FinnhubNewsSource
    from server.datasource.economic.fred import FREDSource


# ============================================================================
# Constants
# ============================================================================

# Scheduler intervals (in minutes)
NEWS_DIGEST_INTERVAL_MINUTES = 15
CRYPTO_UPDATE_INTERVAL_MINUTES = 5
FINNHUB_NEWS_INTERVAL_MINUTES = 15
INSIDER_ALERT_INTERVAL_MINUTES = 30
EARNINGS_ALERT_INTERVAL_HOURS = 6
MARKET_ANOMALY_INTERVAL_MINUTES = 5

# Time windows for briefings (in hours)
MORNING_BRIEFING_HOUR = 8
EVENING_BRIEFING_HOUR = 20
BRIEFING_TIME_WINDOW_HOURS = 12

# Import thresholds for alerts
INSIDER_PURCHASE_THRESHOLD_USD = 100000
INSIDER_SALE_THRESHOLD_USD = 500000
MARKET_ANOMALY_DAILY_THRESHOLD_PCT = 5.0
MARKET_ANOMALY_INTRADAY_THRESHOLD_PCT = 3.0

# Cache limits
PUSHED_NEWS_CACHE_LIMIT = 1000
PUSHED_NEWS_CACHE_RETAIN = 500
PUSHED_FINNHUB_CACHE_LIMIT = 500
PUSHED_FINNHUB_CACHE_RETAIN = 250
ALERTED_INSIDER_CACHE_LIMIT = 500
ALERTED_INSIDER_CACHE_RETAIN = 250
ALERTED_EARNINGS_CACHE_LIMIT = 200
ALERTED_EARNINGS_CACHE_RETAIN = 100

# Fetch limits
WATCHLIST_SYMBOLS_FETCH_LIMIT = 8
WATCHLIST_COMPANY_NEWS_LIMIT = 3
WATCHLIST_COMPANY_NEWS_ITEMS = 5


# ============================================================================
# Helper Functions
# ============================================================================


def _calculate_next_interval_time(
    scheduled_time: datetime, interval_minutes: int
) -> datetime:
    """
    Calculate the next run time for interval-based tasks, anchored
    to the scheduled time rather than now to prevent cumulative drift.

    Args:
        scheduled_time: The originally scheduled time
        interval_minutes: Interval between runs in minutes

    Returns:
        The next run time as a datetime object
    """
    now = datetime.utcnow()
    interval_ms = interval_minutes * 60 * 1000

    # Start from scheduled time and add intervals until we land in the future
    next_time = scheduled_time
    while next_time <= now:
        next_time += timedelta(milliseconds=interval_ms)

    return next_time


# ============================================================================
# Data Scheduler
# ============================================================================


class DataScheduler:
    """
    Unified scheduler for all data sources and push notifications.

    This class manages:
    - Scheduled data fetching (RSS, crypto, markets, economic)
    - Push notifications (news digests, briefings, alerts)
    - Task deduplication and state management
    """

    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler()
        self._is_running = False

        # Data source instances (injected after init)
        self._rss_fetcher: "RSSFetcher | None" = None
        self._crypto_source: "CoinGeckoSource | None" = None
        self._market_source: "FinnhubSource | None" = None
        self._economic_source: "FREDSource | None" = None
        self._finnhub_news: "FinnhubNewsSource | None" = None

        # Push notification dependencies
        self._telegram_bot: "TelegramBot | None" = None
        self._feishu_bot: "FeishuBotV2 | None" = None
        self._correlation_engine: "CorrelationEngine | None" = None
        self._report_generator: "ReportGenerator | None" = None
        self._db_session_factory: Any = None

        # Latest fetched data (in-memory cache)
        self.latest_market_data: dict[str, dict | list] = {}
        self.latest_economic_data: dict[str, dict | None] = {}
        self.latest_crypto_data: list[dict] = []
        self._previous_crypto_data: list[dict] = []  # For comparison

        # Track crypto data before conversion for type checking
        self._raw_crypto_data: list[Any] = []  # Raw data from source

        # News processor (unified)
        self._news_processor: "NewsProcessor | None" = None
        self._source_manager: "SourceManager | None" = None

        # Legacy components (kept for backward compatibility)
        self._news_aggregator: Any = None
        self._news_analyzer: Any = None
        self._latest_finnhub_news: list[Any] = []

        # Push state (legacy, maintained for compatibility)
        self._last_news_push: datetime | None = None
        self._last_crypto_push: datetime | None = None

        # News fetch state for pagination/continue functionality
        self._last_news_fetch_time: datetime | None = None  # Last fetch checkpoint
        self._last_news_fetch_offset: int = 0  # Offset for pagination
        self._last_news_fetch_source: str = ""  # "scheduled" or "command" or "continue"

        # Pushed news and alerts tracking (for deduplication)
        self._pushed_news_ids: set[str] = set()
        self._pushed_finnhub_ids: set[str] = set()
        self._alerted_insider_ids: set[str] = set()
        self._alerted_earnings: set[str] = set()
        self._previous_watchlist_prices: dict[str, float] = {}

    # -------------------------------------------------------------------------
    # Dependency Injection
    # -------------------------------------------------------------------------

    def set_sources(
        self,
        rss_fetcher: "RSSFetcher | None" = None,
        crypto_source: "CoinGeckoSource | None" = None,
        market_source: "FinnhubSource | None" = None,
        economic_source: "FREDSource | None" = None,
        finnhub_news: "FinnhubNewsSource | None" = None,
    ) -> None:
        """Inject data source instances."""
        self._rss_fetcher = rss_fetcher
        self._crypto_source = crypto_source
        self._market_source = market_source
        self._economic_source = economic_source
        self._finnhub_news = finnhub_news

    def set_push_dependencies(
        self,
        telegram_bot: "TelegramBot | None" = None,
        feishu_bot: "FeishuBotV2 | None" = None,
        correlation_engine: "CorrelationEngine | None" = None,
        report_generator: "ReportGenerator | None" = None,
        db_session_factory: Any = None,
    ) -> None:
        """Inject push notification dependencies."""
        self._telegram_bot = telegram_bot
        self._feishu_bot = feishu_bot
        self._correlation_engine = correlation_engine
        self._report_generator = report_generator
        self._db_session_factory = db_session_factory

        # Initialize news aggregator and analyzer
        from server.services.news_aggregator import NewsAggregator, NewsAnalyzer

        self._news_aggregator = NewsAggregator(similarity_threshold=0.5)
        if report_generator:
            self._news_analyzer = NewsAnalyzer(llm=report_generator.llm)

    def set_news_processor(
        self,
        news_processor: "NewsProcessor | None" = None,
        source_manager: "SourceManager | None" = None,
    ) -> None:
        """Inject the unified news processor and source manager."""
        self._news_processor = news_processor
        self._source_manager = source_manager

    @property
    def _has_push_bot(self) -> bool:
        """Check if any push bot is configured."""
        return self._telegram_bot is not None or self._feishu_bot is not None

    async def _push_message(self, message: str) -> None:
        """Send a push notification to all configured bots."""
        if self._telegram_bot:
            try:
                await self._telegram_bot.send_to_admin(message)
            except Exception as e:
                logger.error(f"Telegram push failed: {e}")
        if self._feishu_bot:
            try:
                await self._feishu_bot.send_to_admin(message)
            except Exception as e:
                logger.error(f"Feishu push failed: {e}")

    async def _push_to_platform(self, platform: str, message: str) -> bool:
        """Send a push notification to a specific platform."""
        if platform == "telegram" and self._telegram_bot:
            try:
                await self._telegram_bot.send_to_admin(message)
                return True
            except Exception as e:
                logger.error(f"Telegram push failed: {e}")
                return False
        elif platform == "feishu" and self._feishu_bot:
            try:
                await self._feishu_bot.send_to_admin(message)
                return True
            except Exception as e:
                logger.error(f"Feishu push failed: {e}")
                return False
        return False

    # -------------------------------------------------------------------------
    # Data Fetch Jobs
    # -------------------------------------------------------------------------

    async def _rss_job(self) -> None:
        """Fetch RSS feeds."""
        if not self._rss_fetcher:
            return
        try:
            stats = await self._rss_fetcher.fetch_all_feeds()
            total = sum(stats.values())
            logger.info(f"RSS fetch: {total} new articles")
        except Exception as e:
            logger.error(f"RSS fetch failed: {e}")

    async def _crypto_job(self) -> None:
        """Fetch cryptocurrency prices."""
        if not self._crypto_source:
            return
        try:
            # Save previous data for comparison
            if self.latest_crypto_data:
                self._previous_crypto_data = self.latest_crypto_data.copy()

            prices = await self._crypto_source.fetch()
            # Store raw data and convert to dicts
            self._raw_crypto_data = prices
            self.latest_crypto_data = []
            for p in prices:
                if hasattr(p, "model_dump"):
                    self.latest_crypto_data.append(p.model_dump())
                else:
                    # Handle both dict-like objects and raw dicts
                    p_dict: dict[str, Any] = (
                        dict(p) if hasattr(p, "items") else p  # type: ignore[arg-type]
                    )
                    self.latest_crypto_data.append(p_dict)
            logger.info(f"Crypto fetch: {len(prices)} prices updated")
        except Exception as e:
            logger.error(f"Crypto fetch failed: {e}")

    async def _market_job(self) -> None:
        """Fetch market data."""
        if not self._market_source:
            return
        try:
            data = await self._market_source.fetch_all()
            self.latest_market_data.update(data)
            logger.info("Market data updated")
        except Exception as e:
            logger.error(f"Market fetch failed: {e}")

    async def _economic_job(self) -> None:
        """Fetch economic indicators."""
        if not self._economic_source:
            return
        try:
            indicators = await self._economic_source.fetch_all()
            self.latest_economic_data = {
                k: v.model_dump() if v else None for k, v in indicators.items()
            }
            logger.info("Economic indicators updated")
        except Exception as e:
            logger.error(f"Economic fetch failed: {e}")

    # -------------------------------------------------------------------------
    # Push Notification Jobs
    # -------------------------------------------------------------------------

    async def _news_digest_push_job(self) -> None:
        """Push aggregated news with LLM analysis every NEWS_DIGEST_INTERVAL_MINUTES minutes."""
        if not self._has_push_bot or not self._db_session_factory:
            return

        try:
            # Use unified news processor if available
            if self._news_processor:
                from server.bot.formatter import (
                    format_news_digest_with_analysis,
                    format_news_digest_simple,
                )

                # Calculate fetch start time
                now = datetime.utcnow()
                if self._last_news_fetch_time is None:
                    # First push: fetch news from 15 minutes ago
                    fetch_start = now - timedelta(minutes=NEWS_DIGEST_INTERVAL_MINUTES)
                    logger.info(
                        f"[Scheduled Push] First push, fetching from 15 min ago: {fetch_start}"
                    )
                else:
                    # Subsequent pushes: fetch from last checkpoint
                    fetch_start = self._last_news_fetch_time
                    elapsed = (now - fetch_start).total_seconds() / 60
                    logger.info(
                        f"[Scheduled Push] Fetching from last checkpoint {elapsed:.1f} min ago"
                    )

                # Update checkpoint to current time for next iteration
                self._last_news_fetch_time = now
                self._last_news_fetch_offset = 0  # Reset offset for pagination
                self._last_news_fetch_source = "scheduled"

                # Calculate hours for _fetch_recent_news (unused but needed for interface)
                hours_elapsed = max(0.25, (now - fetch_start).total_seconds() / 3600)

                # Push to each platform with separate deduplication
                for platform in ("telegram", "feishu"):
                    bot = (
                        self._telegram_bot
                        if platform == "telegram"
                        else self._feishu_bot
                    )
                    if not bot:
                        continue

                    items = await self._news_processor.get_and_process_news(
                        hours=hours_elapsed,
                        max_items=10,
                        filter_pushed=False,  # Don't filter by push log, we use time-based fetch
                        push_type="scheduled",
                        use_cache=True,
                        platform=platform,
                        fetch_start_time=fetch_start,
                    )

                    if items:
                        if any(item.chinese_summary for item in items):
                            message = format_news_digest_with_analysis(
                                items, max_items=10
                            )
                        else:
                            message = format_news_digest_simple(items, max_items=10)

                        try:
                            await self._push_to_platform(platform, message)
                            await self._news_processor.mark_as_pushed(
                                items, push_type="scheduled", platform=platform
                            )
                            logger.info(
                                f"[{platform.title()}] Scheduled push: {len(items)} items"
                            )
                        except Exception as e:
                            logger.error(f"{platform.title()} digest push failed: {e}")

                self._last_news_push = now
            else:
                # Legacy fallback
                await self._news_digest_push_job_legacy()

        except Exception as e:
            logger.error(f"News digest push failed: {e}")

    async def _news_digest_push_job_legacy(self) -> None:
        """Legacy news digest push (fallback when NewsProcessor not available)."""
        from server.bot.formatter import (
            format_news_digest_with_analysis,
            format_news_digest_simple,
        )

        # Get recent news (last 10 minutes to catch new items)
        news_items = await self._get_recent_news(hours=0.17)  # ~10 min

        # Merge Finnhub news into the mix
        if self._latest_finnhub_news:
            for fn in self._latest_finnhub_news:
                if fn.news_id not in self._pushed_finnhub_ids:
                    news_items.append(
                        {
                            "title": fn.headline,
                            "source": fn.source,
                            "published": fn.published_at,
                            "summary": fn.summary,
                            "link": fn.url,
                            "category": fn.category,
                            "finnhub_id": fn.news_id,
                        }
                    )

        # Aggregate and deduplicate
        aggregated = []
        if self._news_aggregator and news_items:
            aggregated = self._news_aggregator.aggregate(
                news_items, time_window_minutes=10
            )

        # Filter out already pushed news
        new_items = [
            item for item in aggregated if item.id not in self._pushed_news_ids
        ]

        # If no new items, skip silently
        if not new_items:
            return

        # Analyze with LLM if available
        if self._news_analyzer and self._report_generator:
            try:
                new_items = await self._news_analyzer.analyze_batch(
                    new_items, max_items=5
                )
            except Exception as e:
                logger.warning(f"News analysis failed: {e}")

        # Format and send
        if any(item.chinese_summary for item in new_items):
            message = format_news_digest_with_analysis(new_items, max_items=5)
        else:
            message = format_news_digest_simple(new_items, max_items=5)

        await self._push_message(message)

        # Mark as pushed
        for item in new_items:
            self._pushed_news_ids.add(item.id)
            # Also mark Finnhub IDs
            for src in item.sources:
                if "finnhub_id" in src:
                    self._pushed_finnhub_ids.add(src["finnhub_id"])

        # Limit cache size
        self._trim_cache(
            self._pushed_news_ids,
            PUSHED_NEWS_CACHE_LIMIT,
            PUSHED_NEWS_CACHE_RETAIN,
        )
        self._trim_cache(
            self._pushed_finnhub_ids,
            PUSHED_FINNHUB_CACHE_LIMIT,
            PUSHED_FINNHUB_CACHE_RETAIN,
        )

        self._last_news_push = datetime.utcnow()
        logger.info(f"News digest pushed (legacy): {len(new_items)} items")

    async def _crypto_update_push_job(self) -> None:
        """Push crypto update with comparison every CRYPTO_UPDATE_INTERVAL_MINUTES minutes."""
        if not self._has_push_bot or not self.latest_crypto_data:
            return

        try:
            from server.bot.formatter import format_crypto_update

            message = format_crypto_update(
                crypto_data=self.latest_crypto_data,
                previous_data=self._previous_crypto_data,
                timestamp=datetime.utcnow(),
            )

            await self._push_message(message)
            self._last_crypto_push = datetime.utcnow()
            logger.info("Crypto update pushed")

        except Exception as e:
            logger.error(f"Crypto update push failed: {e}")

    async def _morning_briefing_job(self) -> None:
        """Push morning briefing at MORNING_BRIEFING_HOUR UTC."""
        if not self._has_push_bot or not self._db_session_factory:
            return

        try:
            # Use unified processor if available
            if self._news_processor:
                from server.bot.formatter import format_morning_briefing

                # Build market summary
                market_summary = ""
                if self.latest_market_data.get("indices"):
                    indices = self.latest_market_data["indices"]
                    parts = []
                    for idx in indices[:3]:
                        if isinstance(idx, dict):
                            name = idx.get("name", "")
                            change = idx.get("change_percent", 0) or 0
                            sign = "+" if change >= 0 else ""
                            parts.append(f"{name} {sign}{change:.1f}%")
                    if parts:
                        market_summary = " | ".join(parts)

                # Push to each platform with separate deduplication
                for platform in ("telegram", "feishu"):
                    bot = (
                        self._telegram_bot
                        if platform == "telegram"
                        else self._feishu_bot
                    )
                    if not bot:
                        continue

                    items = await self._news_processor.get_and_process_news(
                        hours=BRIEFING_TIME_WINDOW_HOURS,
                        max_items=10,
                        filter_pushed=False,  # Briefing shows all important news
                        push_type="morning",
                        use_cache=True,
                        platform=platform,
                    )

                    if not items:
                        continue

                    # Filter by importance (>=3 for briefing)
                    items = [i for i in items if i.importance >= 3][:5]

                    if not items:
                        continue

                    message = format_morning_briefing(
                        highlights=items,
                        market_summary=market_summary,
                        date=datetime.utcnow(),
                    )

                    try:
                        await self._push_to_platform(platform, message)
                        await self._news_processor.mark_as_pushed(
                            items, push_type="morning", platform=platform
                        )
                        logger.info(
                            f"[{platform.title()}] Morning briefing pushed: {len(items)} items"
                        )
                    except Exception as e:
                        logger.error(
                            f"{platform.title()} morning briefing push failed: {e}"
                        )
            else:
                # Legacy fallback
                await self._morning_briefing_job_legacy()

        except Exception as e:
            logger.error(f"Morning briefing push failed: {e}")

    async def _morning_briefing_job_legacy(self) -> None:
        """Legacy morning briefing push (fallback when NewsProcessor not available)."""
        from server.bot.formatter import format_morning_briefing

        # Get news from last 12 hours
        news_items = await self._get_recent_news(hours=BRIEFING_TIME_WINDOW_HOURS)
        if not news_items:
            return

        # Aggregate
        if self._news_aggregator:
            aggregated = self._news_aggregator.aggregate(
                news_items, time_window_minutes=720
            )
        else:
            return

        # Analyze top items
        if self._news_analyzer and aggregated:
            aggregated = await self._news_analyzer.analyze_batch(
                aggregated, max_items=10
            )

        # Build market summary
        market_summary = ""
        if self.latest_market_data.get("indices"):
            indices = self.latest_market_data["indices"]
            parts = []
            for idx in indices[:3]:
                if isinstance(idx, dict):
                    name = idx.get("name", "")
                    change = idx.get("change_percent", 0) or 0
                    sign = "+" if change >= 0 else ""
                    parts.append(f"{name} {sign}{change:.1f}%")
            if parts:
                market_summary = " | ".join(parts)

        message = format_morning_briefing(
            highlights=aggregated,
            market_summary=market_summary,
            date=datetime.utcnow(),
        )

        await self._push_message(message)
        logger.info("Morning briefing pushed (legacy)")

    async def _evening_briefing_job(self) -> None:
        """Push evening briefing at EVENING_BRIEFING_HOUR UTC."""
        if not self._has_push_bot or not self._db_session_factory:
            return

        try:
            # Use unified processor if available
            if self._news_processor:
                from server.bot.formatter import format_evening_briefing

                # Push to each platform with separate deduplication
                for platform in ("telegram", "feishu"):
                    bot = (
                        self._telegram_bot
                        if platform == "telegram"
                        else self._feishu_bot
                    )
                    if not bot:
                        continue

                    items = await self._news_processor.get_and_process_news(
                        hours=BRIEFING_TIME_WINDOW_HOURS,
                        max_items=10,
                        filter_pushed=False,  # Briefing shows all important news
                        push_type="evening",
                        use_cache=True,
                        platform=platform,
                    )

                    if not items:
                        continue

                    # Filter by importance (>=3 for briefing)
                    items = [i for i in items if i.importance >= 3][:5]

                    if not items:
                        continue

                    message = format_evening_briefing(
                        highlights=items, date=datetime.utcnow()
                    )
                    try:
                        await self._push_to_platform(platform, message)
                        await self._news_processor.mark_as_pushed(
                            items, push_type="evening", platform=platform
                        )
                        logger.info(
                            f"[{platform.title()}] Evening briefing pushed: {len(items)} items"
                        )
                    except Exception as e:
                        logger.error(
                            f"{platform.title()} evening briefing push failed: {e}"
                        )
            else:
                # Legacy fallback
                await self._evening_briefing_job_legacy()

        except Exception as e:
            logger.error(f"Evening briefing push failed: {e}")

    async def _evening_briefing_job_legacy(self) -> None:
        """Legacy evening briefing push (fallback when NewsProcessor not available)."""
        from server.bot.formatter import format_evening_briefing

        # Get news from last 12 hours
        news_items = await self._get_recent_news(hours=BRIEFING_TIME_WINDOW_HOURS)
        if not news_items:
            return

        # Aggregate
        if self._news_aggregator:
            aggregated = self._news_aggregator.aggregate(
                news_items, time_window_minutes=720
            )
        else:
            return

        # Analyze top items
        if self._news_analyzer and aggregated:
            aggregated = await self._news_analyzer.analyze_batch(
                aggregated, max_items=10
            )

        message = format_evening_briefing(highlights=aggregated, date=datetime.utcnow())

        await self._push_message(message)
        logger.info("Evening briefing pushed (legacy)")

    # -------------------------------------------------------------------------
    # Finnhub-based Jobs
    # -------------------------------------------------------------------------

    async def _finnhub_news_job(self) -> None:
        """Fetch Finnhub market news and merge into news digest."""
        if not self._finnhub_news or not self._finnhub_news.is_configured():
            return

        try:
            # Fetch general market news
            news_items = await self._finnhub_news.fetch_market_news(category="general")

            # Also fetch news for watchlist stocks
            watchlist = global_settings.watchlist_symbols or []
            for symbol in watchlist[:WATCHLIST_SYMBOLS_FETCH_LIMIT]:
                company_news = await self._finnhub_news.fetch_company_news(
                    symbol, days=1
                )
                news_items.extend(company_news[:WATCHLIST_COMPANY_NEWS_ITEMS])

            logger.info(f"Finnhub news fetch: {len(news_items)} items")

            # Store in memory for news digest integration
            self._latest_finnhub_news = news_items

        except Exception as e:
            logger.error(f"Finnhub news fetch failed: {e}")

    async def _insider_alert_job(self) -> None:
        """Check for significant insider transactions on watchlist stocks."""
        if not self._has_push_bot or not self._finnhub_news:
            return
        if not self._finnhub_news.is_configured():
            return

        try:
            from server.bot.formatter import format_insider_alert

            watchlist = global_settings.watchlist_symbols or []
            significant_transactions = []

            for symbol in watchlist[:WATCHLIST_SYMBOLS_FETCH_LIMIT]:
                transactions = await self._finnhub_news.fetch_insider_transactions(
                    symbol
                )

                for tx in transactions:
                    # Skip if already alerted
                    if tx.transaction_id in self._alerted_insider_ids:
                        continue

                    # Only alert on significant transactions
                    tx_value = abs(tx.change * tx.transaction_price)
                    is_purchase = tx.transaction_code == "P"

                    # Purchases are more significant signals
                    if is_purchase and tx_value >= INSIDER_PURCHASE_THRESHOLD_USD:
                        significant_transactions.append(tx)
                        self._alerted_insider_ids.add(tx.transaction_id)
                    # Large sales are also worth noting
                    elif not is_purchase and tx_value >= INSIDER_SALE_THRESHOLD_USD:
                        significant_transactions.append(tx)
                        self._alerted_insider_ids.add(tx.transaction_id)

            if significant_transactions:
                message = format_insider_alert(significant_transactions)
                await self._push_message(message)
                logger.info(
                    f"Insider alert pushed: {len(significant_transactions)} transactions"
                )

            # Limit cache size
            self._trim_cache(
                self._alerted_insider_ids,
                ALERTED_INSIDER_CACHE_LIMIT,
                ALERTED_INSIDER_CACHE_RETAIN,
            )

        except Exception as e:
            logger.error(f"Insider alert job failed: {e}")

    async def _earnings_alert_job(self) -> None:
        """Alert on upcoming earnings for watchlist stocks."""
        if not self._has_push_bot or not self._finnhub_news:
            return
        if not self._finnhub_news.is_configured():
            return

        try:
            from server.bot.formatter import format_earnings_alert

            watchlist = set(global_settings.watchlist_symbols or [])
            earnings = await self._finnhub_news.fetch_earnings_calendar(days=3)

            # Filter for watchlist stocks
            watchlist_earnings = []
            for event in earnings:
                alert_key = f"{event.symbol}_{event.report_date.date()}"
                if (
                    event.symbol in watchlist
                    and alert_key not in self._alerted_earnings
                ):
                    watchlist_earnings.append(event)
                    self._alerted_earnings.add(alert_key)

            if watchlist_earnings:
                message = format_earnings_alert(watchlist_earnings)
                await self._push_message(message)
                logger.info(f"Earnings alert pushed: {len(watchlist_earnings)} events")

            # Limit cache size
            self._trim_cache(
                self._alerted_earnings,
                ALERTED_EARNINGS_CACHE_LIMIT,
                ALERTED_EARNINGS_CACHE_RETAIN,
            )

        except Exception as e:
            logger.error(f"Earnings alert job failed: {e}")

    async def _market_anomaly_job(self) -> None:
        """Detect significant price movements in watchlist stocks."""
        if not self._has_push_bot or not self._finnhub_news:
            return
        if not self._finnhub_news.is_configured():
            return

        try:
            from server.bot.formatter import format_market_anomaly_alert

            watchlist = global_settings.watchlist_symbols or []
            anomalies = []

            for symbol in watchlist[:WATCHLIST_SYMBOLS_FETCH_LIMIT]:
                quote = await self._finnhub_news.fetch_quote(symbol)
                if not quote:
                    continue

                price = quote.get("price", 0)
                change_pct = quote.get("change_percent", 0) or 0
                prev_price = self._previous_watchlist_prices.get(symbol)

                # Detect anomalies
                is_anomaly = False
                anomaly_type = ""

                # Daily change > 5%
                if abs(change_pct) >= MARKET_ANOMALY_DAILY_THRESHOLD_PCT:
                    is_anomaly = True
                    anomaly_type = "daily_spike" if change_pct > 0 else "daily_drop"

                # Intraday movement > 3% from last check
                if prev_price and prev_price > 0:
                    intraday_change = ((price - prev_price) / prev_price) * 100
                    if abs(intraday_change) >= MARKET_ANOMALY_INTRADAY_THRESHOLD_PCT:
                        is_anomaly = True
                        anomaly_type = (
                            "intraday_spike" if intraday_change > 0 else "intraday_drop"
                        )

                if is_anomaly:
                    anomalies.append(
                        {
                            "symbol": symbol,
                            "price": price,
                            "change_percent": change_pct,
                            "anomaly_type": anomaly_type,
                            "prev_price": prev_price,
                        }
                    )

                # Update price cache
                self._previous_watchlist_prices[symbol] = price

            if anomalies:
                message = format_market_anomaly_alert(anomalies)
                await self._push_message(message)
                logger.info(f"Market anomaly alert pushed: {len(anomalies)} stocks")

        except Exception as e:
            logger.error(f"Market anomaly job failed: {e}")

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _trim_cache(self, cache: set, limit: int, retain: int) -> None:
        """Trim cache to limit, retaining the most recent items."""
        if len(cache) > limit:
            # Convert to list, keep last 'retain' items (most recent)
            cache_list = list(cache)
            cache.clear()
            cache.update(cache_list[-retain:])
            logger.debug(f"Trimmed cache from {len(cache_list)} to {len(cache)} items")

    def _format_crypto_for_summary(self) -> dict:
        """Convert crypto list to dict format for formatter."""
        result = {}
        for item in self.latest_crypto_data:
            if isinstance(item, dict) and "id" in item:
                coin_id = item["id"]
                result[coin_id] = {
                    "usd": item.get("current_price", 0),
                    "usd_24h_change": item.get("price_change_percentage_24h", 0),
                }
        return result

    async def _get_recent_news(self, hours: float = 1) -> list[dict]:
        """Get recent news articles from database and Finnhub."""
        import time

        start_time = time.time()
        logger.info(f"[新闻获取] 开始获取最近 {hours} 小时的新闻...")

        news_items = []
        rss_count = 0
        finnhub_count = 0

        # Get RSS articles from database
        if self._db_session_factory:
            try:
                rss_start = time.time()
                from sqlalchemy import select
                from server.datastore.models import RSSArticleDB

                cutoff = datetime.utcnow() - timedelta(hours=hours)

                async with self._db_session_factory() as session:
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
                                "category": getattr(a, "category", ""),
                            }
                        )
                    rss_count = len(articles)

                rss_elapsed = time.time() - rss_start
                logger.info(
                    f"[新闻获取] RSS 获取完成，耗时 {rss_elapsed:.2f}s，共 {rss_count} 条"
                )

            except Exception as e:
                logger.error(f"Failed to get RSS news: {e}")

        # Get Finnhub news from memory cache
        finnhub_start = time.time()
        if self._latest_finnhub_news:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            for fn in self._latest_finnhub_news:
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

    async def _build_report_context(self, hours: int = 24) -> Any:
        """Build report context from available data."""
        from server.reports.generator import ReportDataContext

        news_items = await self._get_recent_news(hours=hours)

        correlation_results = None
        if self._correlation_engine and news_items:
            correlation_results = self._correlation_engine.analyze(news_items)

        return ReportDataContext(
            news_items=news_items,
            market_data=self.latest_market_data,
            economic_data=self.latest_economic_data,
            correlation_results=correlation_results,
        )

    # -------------------------------------------------------------------------
    # Scheduler Lifecycle
    # -------------------------------------------------------------------------

    def start(self) -> None:
        """Start unified scheduler."""
        if self._is_running:
            logger.warning("DataScheduler is already running")
            return

        settings = global_settings

        # ── Data fetch jobs ───────────────────────────────────────────────────

        if self._rss_fetcher:
            self.scheduler.add_job(
                self._rss_job,
                trigger="interval",
                minutes=settings.fetch_interval_rss,
                id="rss_fetch",
                name="RSS Feed Fetcher",
                replace_existing=True,
            )
            logger.info(f"RSS job: every {settings.fetch_interval_rss} min")

        if self._crypto_source:
            self.scheduler.add_job(
                self._crypto_job,
                trigger="interval",
                minutes=settings.fetch_interval_crypto,
                id="crypto_fetch",
                name="Crypto Price Fetcher",
                replace_existing=True,
            )
            logger.info(f"Crypto job: every {settings.fetch_interval_crypto} min")

        if self._market_source:
            self.scheduler.add_job(
                self._market_job,
                trigger="interval",
                minutes=settings.fetch_interval_markets,
                id="market_fetch",
                name="Market Data Fetcher",
                replace_existing=True,
            )
            logger.info(f"Market job: every {settings.fetch_interval_markets} min")

        if self._economic_source:
            self.scheduler.add_job(
                self._economic_job,
                trigger="interval",
                minutes=settings.fetch_interval_economic,
                id="economic_fetch",
                name="Economic Indicator Fetcher",
                replace_existing=True,
            )
            logger.info(f"Economic job: every {settings.fetch_interval_economic} min")

        # ── Push notification jobs ────────────────────────────────────────────

        if self._has_push_bot and settings.push_enabled:
            # News digest push
            self.scheduler.add_job(
                self._news_digest_push_job,
                trigger="interval",
                minutes=NEWS_DIGEST_INTERVAL_MINUTES,
                id="news_digest_push",
                name="News Digest Push",
                replace_existing=True,
            )
            logger.info(
                f"News digest push job: every {NEWS_DIGEST_INTERVAL_MINUTES} min"
            )

            # Crypto update push
            if self._crypto_source:
                self.scheduler.add_job(
                    self._crypto_update_push_job,
                    trigger="interval",
                    minutes=CRYPTO_UPDATE_INTERVAL_MINUTES,
                    id="crypto_update_push",
                    name="Crypto Update Push",
                    replace_existing=True,
                )
                logger.info(
                    f"Crypto update push job: every {CRYPTO_UPDATE_INTERVAL_MINUTES} min"
                )

            # Morning briefing
            self.scheduler.add_job(
                self._morning_briefing_job,
                trigger=CronTrigger(hour=MORNING_BRIEFING_HOUR, minute=0),
                id="morning_briefing",
                name="Morning Briefing Push",
                replace_existing=True,
            )
            logger.info(f"Morning briefing job: {MORNING_BRIEFING_HOUR}:00 UTC")

            # Evening briefing
            self.scheduler.add_job(
                self._evening_briefing_job,
                trigger=CronTrigger(hour=EVENING_BRIEFING_HOUR, minute=0),
                id="evening_briefing",
                name="Evening Briefing Push",
                replace_existing=True,
            )
            logger.info(f"Evening briefing job: {EVENING_BRIEFING_HOUR}:00 UTC")

        # ── Finnhub-based jobs ─────────────────────────────────────────────────

        if self._finnhub_news and self._finnhub_news.is_configured():
            # Finnhub news fetch
            self.scheduler.add_job(
                self._finnhub_news_job,
                trigger="interval",
                minutes=FINNHUB_NEWS_INTERVAL_MINUTES,
                id="finnhub_news_fetch",
                name="Finnhub News Fetcher",
                replace_existing=True,
            )
            logger.info(f"Finnhub news job: every {FINNHUB_NEWS_INTERVAL_MINUTES} min")

            if self._has_push_bot and settings.push_enabled:
                # Insider trading alerts
                self.scheduler.add_job(
                    self._insider_alert_job,
                    trigger="interval",
                    minutes=INSIDER_ALERT_INTERVAL_MINUTES,
                    id="insider_alert",
                    name="Insider Trading Alert",
                    replace_existing=True,
                )
                logger.info(
                    f"Insider alert job: every {INSIDER_ALERT_INTERVAL_MINUTES} min"
                )

                # Earnings calendar alerts
                self.scheduler.add_job(
                    self._earnings_alert_job,
                    trigger="interval",
                    hours=EARNINGS_ALERT_INTERVAL_HOURS,
                    id="earnings_alert",
                    name="Earnings Calendar Alert",
                    replace_existing=True,
                )
                logger.info(
                    f"Earnings alert job: every {EARNINGS_ALERT_INTERVAL_HOURS} hours"
                )

                # Market anomaly detection
                self.scheduler.add_job(
                    self._market_anomaly_job,
                    trigger="interval",
                    minutes=MARKET_ANOMALY_INTERVAL_MINUTES,
                    id="market_anomaly",
                    name="Market Anomaly Detection",
                    replace_existing=True,
                )
                logger.info(
                    f"Market anomaly job: every {MARKET_ANOMALY_INTERVAL_MINUTES} min"
                )

        self.scheduler.start()
        self._is_running = True
        logger.info("DataScheduler started")

    def stop(self) -> None:
        """Stop the scheduler."""
        if not self._is_running:
            return
        self.scheduler.shutdown(wait=False)
        self._is_running = False
        logger.info("DataScheduler stopped")

    # -------------------------------------------------------------------------
    # Manual Trigger Methods
    # -------------------------------------------------------------------------

    async def fetch_all_now(self) -> None:
        """Trigger all data fetches immediately."""
        logger.info("Running initial data fetch for all sources...")
        tasks = []
        if self._rss_fetcher:
            tasks.append(self._rss_job())
        if self._crypto_source:
            tasks.append(self._crypto_job())
        if self._market_source:
            tasks.append(self._market_job())
        if self._economic_source:
            tasks.append(self._economic_job())
        if self._finnhub_news and self._finnhub_news.is_configured():
            tasks.append(self._finnhub_news_job())

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Initial data fetch complete")

    async def trigger_news_digest(self) -> None:
        """Manually trigger news digest push."""
        await self._news_digest_push_job()

    async def trigger_crypto_update(self) -> None:
        """Manually trigger crypto update push."""
        await self._crypto_update_push_job()

    async def trigger_morning_briefing(self) -> None:
        """Manually trigger morning briefing."""
        await self._morning_briefing_job()

    async def trigger_evening_briefing(self) -> None:
        """Manually trigger evening briefing."""
        await self._evening_briefing_job()

    async def trigger_insider_alert(self) -> None:
        """Manually trigger insider trading alert."""
        await self._insider_alert_job()

    async def trigger_earnings_alert(self) -> None:
        """Manually trigger earnings calendar alert."""
        await self._earnings_alert_job()

    async def trigger_market_anomaly(self) -> None:
        """Manually trigger market anomaly detection."""
        await self._market_anomaly_job()

    async def trigger_finnhub_news(self) -> None:
        """Manually trigger Finnhub news fetch."""
        await self._finnhub_news_job()

    # -------------------------------------------------------------------------
    # Status Methods
    # -------------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """Get scheduler status."""
        jobs = []
        if self._is_running:
            for job in self.scheduler.get_jobs():
                next_run = job.next_run_time
                jobs.append(
                    {
                        "id": job.id,
                        "name": job.name,
                        "next_run": next_run.isoformat() if next_run else None,
                    }
                )
        return {
            "running": self._is_running,
            "jobs": jobs,
            "sources": {
                "rss": self._rss_fetcher is not None,
                "crypto": self._crypto_source is not None,
                "markets": self._market_source is not None,
                "economic": self._economic_source is not None,
                "finnhub_news": self._finnhub_news is not None
                and self._finnhub_news.is_configured(),
            },
            "push": {
                "telegram": self._telegram_bot is not None,
                "feishu": self._feishu_bot is not None,
                "news_aggregator": self._news_aggregator is not None,
                "news_analyzer": self._news_analyzer is not None,
            },
            "alerts": {
                "insider": len(self._alerted_insider_ids),
                "earnings": len(self._alerted_earnings),
                "watchlist_prices": len(self._previous_watchlist_prices),
            },
        }

    async def get_news_status(self) -> dict:
        """Get news status including last fetch time."""
        return {
            "last_news_fetch_time": self._last_news_fetch_time.isoformat()
            if self._last_news_fetch_time
            else None,
            "last_news_push_time": self._last_news_push.isoformat()
            if self._last_news_push
            else None,
            "fetch_offset": self._last_news_fetch_offset,
            "fetch_source": self._last_news_fetch_source,
        }
