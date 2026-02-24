"""
Unified data scheduler - manages all data source fetch jobs and push notifications.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional, TYPE_CHECKING

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


class DataScheduler:
    """
    Unified scheduler for all data sources and push notifications.
    """

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._is_running = False

        # Data source instances (injected after init)
        self._rss_fetcher: Any = None
        self._crypto_source: Any = None
        self._market_source: Any = None
        self._economic_source: Any = None
        self._finnhub_news: Any = None

        # Push notification dependencies
        self._telegram_bot: Optional["TelegramBot"] = None
        self._feishu_bot: Optional["FeishuBotV2"] = None
        self._correlation_engine: Optional["CorrelationEngine"] = None
        self._report_generator: Optional["ReportGenerator"] = None
        self._db_session_factory: Any = None

        # Latest fetched data (in-memory cache)
        self.latest_market_data: dict[str, Any] = {}
        self.latest_economic_data: dict[str, Any] = {}
        self.latest_crypto_data: list[Any] = []
        self._previous_crypto_data: list[Any] = []  # For comparison

        # News processor (unified)
        self._news_processor: Optional["NewsProcessor"] = None
        self._source_manager: Optional["SourceManager"] = None

        # Legacy components (kept for backward compatibility)
        self._news_aggregator = None
        self._news_analyzer = None
        self._latest_finnhub_news: list[Any] = []

        # Push state (legacy, maintained for compatibility)
        self._last_news_push: Optional[datetime] = None
        self._last_crypto_push: Optional[datetime] = None

        # News fetch state for pagination/continue functionality
        self._last_news_fetch_time: Optional[datetime] = (
            None  # Last fetch checkpoint time (for continue command)
        )
        self._last_news_fetch_offset: int = 0  # Offset for pagination
        self._last_news_fetch_source: str = ""  # "scheduled" or "command" or "continue"

        self._pushed_news_ids: set[str] = set()
        self._pushed_finnhub_ids: set[str] = set()
        self._alerted_insider_ids: set[str] = set()
        self._alerted_earnings: set[str] = set()
        self._previous_watchlist_prices: dict[str, float] = {}

    def set_sources(
        self,
        rss_fetcher: Any = None,
        crypto_source: Any = None,
        market_source: Any = None,
        economic_source: Any = None,
        finnhub_news: Any = None,
    ) -> None:
        """Inject data source instances."""
        self._rss_fetcher = rss_fetcher
        self._crypto_source = crypto_source
        self._market_source = market_source
        self._economic_source = economic_source
        self._finnhub_news = finnhub_news

    def set_push_dependencies(
        self,
        telegram_bot: Optional["TelegramBot"] = None,
        feishu_bot: Optional["FeishuBotV2"] = None,
        correlation_engine: Optional["CorrelationEngine"] = None,
        report_generator: Optional["ReportGenerator"] = None,
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
        news_processor: Optional["NewsProcessor"] = None,
        source_manager: Optional["SourceManager"] = None,
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

    # ── Data fetch job handlers ───────────────────────────────────────────────

    async def _rss_job(self) -> None:
        if not self._rss_fetcher:
            return
        try:
            stats = await self._rss_fetcher.fetch_all_feeds()
            total = sum(stats.values())
            logger.info(f"RSS fetch: {total} new articles")
        except Exception as e:
            logger.error(f"RSS fetch failed: {e}")

    async def _crypto_job(self) -> None:
        if not self._crypto_source:
            return
        try:
            # Save previous data for comparison
            if self.latest_crypto_data:
                self._previous_crypto_data = self.latest_crypto_data.copy()

            prices = await self._crypto_source.fetch()
            # Convert CryptoPrice objects to dicts
            self.latest_crypto_data = [
                p.model_dump() if hasattr(p, "model_dump") else p for p in prices
            ]
            logger.info(f"Crypto fetch: {len(prices)} prices updated")
        except Exception as e:
            logger.error(f"Crypto fetch failed: {e}")

    async def _market_job(self) -> None:
        if not self._market_source:
            return
        try:
            data = await self._market_source.fetch_all()
            self.latest_market_data.update(data)
            logger.info("Market data updated")
        except Exception as e:
            logger.error(f"Market fetch failed: {e}")

    async def _economic_job(self) -> None:
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

    # ── New Push notification handlers ────────────────────────────────────────

    async def _news_digest_push_job(self) -> None:
        """Push aggregated news with LLM analysis every 15 minutes."""
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
                    fetch_start = now - timedelta(minutes=15)
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

                # Push to Telegram
                if self._telegram_bot:
                    items = await self._news_processor.get_and_process_news(
                        hours=hours_elapsed,
                        max_items=10,
                        filter_pushed=False,  # Don't filter by push log, we use time-based fetch
                        push_type="scheduled",
                        use_cache=True,
                        platform="telegram",
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
                            await self._telegram_bot.send_to_admin(message)
                            await self._news_processor.mark_as_pushed(
                                items, push_type="scheduled", platform="telegram"
                            )
                            logger.info(
                                f"[Telegram] Scheduled push: {len(items)} items"
                            )
                        except Exception as e:
                            logger.error(f"Telegram digest push failed: {e}")

                # Push to Feishu
                if self._feishu_bot:
                    items = await self._news_processor.get_and_process_news(
                        hours=hours_elapsed,
                        max_items=10,
                        filter_pushed=False,
                        push_type="scheduled",
                        use_cache=True,
                        platform="feishu",
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
                            await self._feishu_bot.send_to_admin(message)
                            await self._news_processor.mark_as_pushed(
                                items, push_type="scheduled", platform="feishu"
                            )
                            logger.info(f"[Feishu] Scheduled push: {len(items)} items")
                        except Exception as e:
                            logger.error(f"Feishu digest push failed: {e}")

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
        if len(self._pushed_news_ids) > 1000:
            self._pushed_news_ids = set(list(self._pushed_news_ids)[-500:])
        if len(self._pushed_finnhub_ids) > 500:
            self._pushed_finnhub_ids = set(list(self._pushed_finnhub_ids)[-250:])

        self._last_news_push = datetime.utcnow()
        logger.info(f"News digest pushed (legacy): {len(new_items)} items")

    async def _crypto_update_push_job(self) -> None:
        """Push crypto update with comparison every 5 minutes."""
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
        """Push morning briefing at 08:00 UTC."""
        if not self._has_push_bot or not self._db_session_factory:
            return

        try:
            # Use unified processor if available
            if self._news_processor:
                items = await self._news_processor.get_and_process_news(
                    hours=12,
                    max_items=10,
                    filter_pushed=False,  # Briefing shows all important news
                    push_type="morning",
                    use_cache=True,
                    platform="telegram",  # Separate deduplication per platform
                )

                if not items:
                    return

                # Filter by importance (>=3 for briefing)
                items = [i for i in items if i.importance >= 3][:5]

                if not items:
                    return

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

                from server.bot.formatter import format_morning_briefing

                message = format_morning_briefing(
                    highlights=items,
                    market_summary=market_summary,
                    date=datetime.utcnow(),
                )

                await self._push_message(message)
                logger.info("Morning briefing pushed")

                # Push to Feishu (separate push for separate deduplication)
                if self._feishu_bot:
                    feishu_items = await self._news_processor.get_and_process_news(
                        hours=12,
                        max_items=10,
                        filter_pushed=False,
                        push_type="morning",
                        use_cache=True,
                        platform="feishu",
                    )
                    if feishu_items:
                        feishu_items = [i for i in feishu_items if i.importance >= 3][
                            :5
                        ]
                        if feishu_items:
                            message = format_morning_briefing(
                                highlights=feishu_items,
                                market_summary=market_summary,
                                date=datetime.utcnow(),
                            )
                            try:
                                await self._feishu_bot.send_to_admin(message)
                                await self._news_processor.mark_as_pushed(
                                    feishu_items, push_type="morning", platform="feishu"
                                )
                                logger.info(
                                    f"[Feishu] Morning briefing pushed: {len(feishu_items)} items"
                                )
                            except Exception as e:
                                logger.error(
                                    f"Feishu morning briefing push failed: {e}"
                                )
                # Push to Feishu (separate push for separate deduplication)
                if self._feishu_bot:
                    feishu_items = await self._news_processor.get_and_process_news(
                        hours=12,
                        max_items=10,
                        filter_pushed=False,
                        push_type="morning",
                        use_cache=True,
                        platform="feishu",
                    )
                    if feishu_items:
                        feishu_items = [i for i in feishu_items if i.importance >= 3][
                            :5
                        ]
                        if feishu_items:
                            message = format_morning_briefing(
                                highlights=feishu_items,
                                market_summary=market_summary,
                                date=datetime.utcnow(),
                            )
                            try:
                                await self._feishu_bot.send_to_admin(message)
                                await self._news_processor.mark_as_pushed(
                                    feishu_items, push_type="morning", platform="feishu"
                                )
                                logger.info(
                                    f"[Feishu] Morning briefing pushed: {len(feishu_items)} items"
                                )
                            except Exception as e:
                                logger.error(
                                    f"Feishu morning briefing push failed: {e}"
                                )

                # Push to Feishu (separate push for separate deduplication)
                if self._feishu_bot:
                    try:
                        await self._feishu_bot.send_to_admin(message)
                        await self._news_processor.mark_as_pushed(
                            items, push_type="morning", platform="feishu"
                        )
                        logger.info(
                            f"[Feishu] Morning briefing pushed: {len(items)} items"
                        )
                    except Exception as e:
                        logger.error(f"Feishu morning briefing push failed: {e}")
            else:
                # Legacy fallback
                await self._morning_briefing_job_legacy()

        except Exception as e:
            logger.error(f"Morning briefing push failed: {e}")

    async def _morning_briefing_job_legacy(self) -> None:
        """Legacy morning briefing push (fallback when NewsProcessor not available)."""
        from server.bot.formatter import format_morning_briefing

        # Get news from last 12 hours
        news_items = await self._get_recent_news(hours=12)
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
        """Push evening briefing at 20:00 UTC."""
        if not self._has_push_bot or not self._db_session_factory:
            return

        try:
            # Use unified processor if available
            if self._news_processor:
                from server.bot.formatter import format_evening_briefing

                # Push to Telegram
                if self._telegram_bot:
                    items = await self._news_processor.get_and_process_news(
                        hours=12,
                        max_items=10,
                        filter_pushed=False,  # Briefing shows all important news
                        push_type="evening",
                        use_cache=True,
                        platform="telegram",
                    )

                    if items:
                        # Filter by importance (>=3 for briefing)
                        items = [i for i in items if i.importance >= 3][:5]

                        if items:
                            message = format_evening_briefing(
                                highlights=items, date=datetime.utcnow()
                            )
                            try:
                                await self._telegram_bot.send_to_admin(message)
                                await self._news_processor.mark_as_pushed(
                                    items, push_type="evening", platform="telegram"
                                )
                                logger.info(
                                    f"[Telegram] Evening briefing pushed: {len(items)} items"
                                )
                            except Exception as e:
                                logger.error(
                                    f"Telegram evening briefing push failed: {e}"
                                )

                # Push to Feishu
                if self._feishu_bot:
                    items = await self._news_processor.get_and_process_news(
                        hours=12,
                        max_items=10,
                        filter_pushed=False,  # Briefing shows all important news
                        push_type="evening",
                        use_cache=True,
                        platform="feishu",
                    )

                    if items:
                        # Filter by importance (>=3 for briefing)
                        items = [i for i in items if i.importance >= 3][:5]

                        if items:
                            message = format_evening_briefing(
                                highlights=items, date=datetime.utcnow()
                            )
                            try:
                                await self._feishu_bot.send_to_admin(message)
                                await self._news_processor.mark_as_pushed(
                                    items, push_type="evening", platform="feishu"
                                )
                                logger.info(
                                    f"[Feishu] Evening briefing pushed: {len(items)} items"
                                )
                            except Exception as e:
                                logger.error(
                                    f"Feishu evening briefing push failed: {e}"
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
        news_items = await self._get_recent_news(hours=12)
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

    async def _finnhub_news_job(self) -> None:
        """Fetch Finnhub market news and merge into news digest."""
        if not self._finnhub_news or not self._finnhub_news.is_configured():
            return

        try:
            # Fetch general market news
            news_items = await self._finnhub_news.fetch_market_news(category="general")

            # Also fetch news for watchlist stocks
            watchlist = global_settings.watchlist_symbols or []
            for symbol in watchlist[:3]:  # Limit to top 3
                company_news = await self._finnhub_news.fetch_company_news(
                    symbol, days=1
                )
                news_items.extend(company_news[:5])

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

            for symbol in watchlist[:5]:
                transactions = await self._finnhub_news.fetch_insider_transactions(
                    symbol
                )

                for tx in transactions:
                    # Skip if already alerted
                    if tx.transaction_id in self._alerted_insider_ids:
                        continue

                    # Only alert on significant purchases (>$100k) or large sales
                    tx_value = abs(tx.change * tx.transaction_price)
                    is_purchase = tx.transaction_code == "P"

                    # Purchases are more significant signals
                    if is_purchase and tx_value >= 100000:
                        significant_transactions.append(tx)
                        self._alerted_insider_ids.add(tx.transaction_id)
                    # Large sales (>$500k) also worth noting
                    elif not is_purchase and tx_value >= 500000:
                        significant_transactions.append(tx)
                        self._alerted_insider_ids.add(tx.transaction_id)

            if significant_transactions:
                message = format_insider_alert(significant_transactions)
                await self._push_message(message)
                logger.info(
                    f"Insider alert pushed: {len(significant_transactions)} transactions"
                )

            # Limit cache size
            if len(self._alerted_insider_ids) > 500:
                self._alerted_insider_ids = set(list(self._alerted_insider_ids)[-250:])

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
            if len(self._alerted_earnings) > 200:
                self._alerted_earnings = set(list(self._alerted_earnings)[-100:])

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

            for symbol in watchlist[:8]:
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
                if abs(change_pct) >= 5:
                    is_anomaly = True
                    anomaly_type = "daily_spike" if change_pct > 0 else "daily_drop"

                # Intraday movement > 3% from last check
                if prev_price and prev_price > 0:
                    intraday_change = ((price - prev_price) / prev_price) * 100
                    if abs(intraday_change) >= 3:
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

    # ── Helper methods ────────────────────────────────────────────────────────

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

    # ── Scheduler lifecycle ──────────────────────────────────────────────────

    def start(self) -> None:
        """Start the unified scheduler."""
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
            # News digest push (every 15 min)
            self.scheduler.add_job(
                self._news_digest_push_job,
                trigger="interval",
                minutes=15,
                id="news_digest_push",
                name="News Digest Push",
                replace_existing=True,
            )
            logger.info("News digest push job: every 15 min")

            # Crypto update push (every 5 min)
            if self._crypto_source:
                self.scheduler.add_job(
                    self._crypto_update_push_job,
                    trigger="interval",
                    minutes=5,
                    id="crypto_update_push",
                    name="Crypto Update Push",
                    replace_existing=True,
                )
                logger.info("Crypto update push job: every 5 min")

            # Morning briefing (08:00 UTC)
            self.scheduler.add_job(
                self._morning_briefing_job,
                trigger=CronTrigger(hour=8, minute=0),
                id="morning_briefing",
                name="Morning Briefing Push",
                replace_existing=True,
            )
            logger.info("Morning briefing job: 08:00 UTC")

            # Evening briefing (20:00 UTC)
            self.scheduler.add_job(
                self._evening_briefing_job,
                trigger=CronTrigger(hour=20, minute=0),
                id="evening_briefing",
                name="Evening Briefing Push",
                replace_existing=True,
            )
            logger.info("Evening briefing job: 20:00 UTC")

        # ── Finnhub-based jobs ─────────────────────────────────────────────────

        if self._finnhub_news and self._finnhub_news.is_configured():
            # Finnhub news fetch (every 15 min)
            self.scheduler.add_job(
                self._finnhub_news_job,
                trigger="interval",
                minutes=15,
                id="finnhub_news_fetch",
                name="Finnhub News Fetcher",
                replace_existing=True,
            )
            logger.info("Finnhub news job: every 15 min")

            if self._has_push_bot and settings.push_enabled:
                # Insider trading alerts (every 30 min)
                self.scheduler.add_job(
                    self._insider_alert_job,
                    trigger="interval",
                    minutes=30,
                    id="insider_alert",
                    name="Insider Trading Alert",
                    replace_existing=True,
                )
                logger.info("Insider alert job: every 30 min")

                # Earnings calendar alerts (every 6 hours)
                self.scheduler.add_job(
                    self._earnings_alert_job,
                    trigger="interval",
                    hours=6,
                    id="earnings_alert",
                    name="Earnings Calendar Alert",
                    replace_existing=True,
                )
                logger.info("Earnings alert job: every 6 hours")

                # Market anomaly detection (every 5 min during market hours)
                self.scheduler.add_job(
                    self._market_anomaly_job,
                    trigger="interval",
                    minutes=5,
                    id="market_anomaly",
                    name="Market Anomaly Detection",
                    replace_existing=True,
                )
                logger.info("Market anomaly job: every 5 min")

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

    # ── Manual trigger methods ────────────────────────────────────────────────

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
