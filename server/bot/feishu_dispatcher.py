"""Feishu command handlers (dispatcher)."""

from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from server.bot.formatter import (
    format_status,
    format_help,
    format_news_digest_with_analysis,
    format_news_digest_simple,
    format_crypto_update,
    format_market_with_watchlist,
)
from server.settings import global_settings
from server.bot.chat_handlers import ChatCommandHandlers

if TYPE_CHECKING:
    from server.datasource.scheduler import DataScheduler
    from server.analysis.correlation import CorrelationEngine
    from server.reports.generator import ReportGenerator
    from server.services.news_processor import NewsProcessor


class FeishuCommandDispatcher:
    """Handles Feishu bot commands."""

    def __init__(
        self,
        scheduler: "DataScheduler",
        correlation_engine: "CorrelationEngine | None" = None,
        report_generator: "ReportGenerator | None" = None,
        rss_fetcher=None,
        news_processor: "NewsProcessor | None" = None,
        chat_command_handlers: "ChatCommandHandlers | None" = None,
    ):
        self.scheduler = scheduler
        self.correlation_engine = correlation_engine
        self.report_generator = report_generator
        self.rss_fetcher = rss_fetcher
        self.news_processor = news_processor
        self.chat_command_handlers = chat_command_handlers

    async def handle_news(self, event: dict) -> str:
        """Handle /news command - show recent news with analysis."""
        chat_id = event.get("chat_id")
        logger.info(f"/news command from Feishu chat {chat_id}")

        try:
            # Use unified news processor if available
            if self.news_processor:
                from datetime import datetime, timedelta

                # Calculate fetch start time
                now = datetime.utcnow()
                if self.scheduler and hasattr(self.scheduler, "_last_news_fetch_time"):
                    last_fetch_time = self.scheduler._last_news_fetch_time
                    if last_fetch_time:
                        # Fetch from last scheduled/command fetch to now
                        fetch_start = last_fetch_time
                        elapsed = (now - fetch_start).total_seconds() / 60
                        logger.info(
                            f"[/news Feishu] Fetching from last fetch {elapsed:.1f} min ago"
                        )
                    else:
                        # First /news: fetch from 15 minutes ago
                        fetch_start = now - timedelta(minutes=15)
                        logger.info(
                            "[/news Feishu] First fetch, getting news from 15 min ago"
                        )
                else:
                    # No scheduler: fallback to 15 minutes ago
                    fetch_start = now - timedelta(minutes=15)
                    logger.info(
                        "[/news Feishu] No scheduler, getting news from 15 min ago"
                    )

                # Update scheduler checkpoint for /continue to work
                if self.scheduler and hasattr(self.scheduler, "_last_news_fetch_time"):
                    self.scheduler._last_news_fetch_time = now
                    self.scheduler._last_news_fetch_offset = 0
                    self.scheduler._last_news_fetch_source = "command"

                # Calculate hours for fetch
                hours_elapsed = max(0.25, (now - fetch_start).total_seconds() / 3600)

                items = await self.news_processor.get_and_process_news(
                    hours=hours_elapsed,
                    max_items=10,
                    filter_pushed=False,
                    push_type="command",
                    use_cache=True,
                    platform="feishu",
                    fetch_start_time=fetch_start,
                )

                if not items:
                    return "📰 暂无最新新闻"

                # Format and return
                if any(item.chinese_summary for item in items):
                    message = format_news_digest_with_analysis(items, max_items=10)
                else:
                    message = format_news_digest_simple(items, max_items=10)

                logger.info(f"News sent to Feishu chat {chat_id}")
                return message
            else:
                # Legacy fallback
                return await self._handle_news_legacy(event)

        except Exception as e:
            logger.error(f"News command failed: {e}")
            return f"❌ 获取失败: {str(e)[:100]}"

    async def _handle_news_legacy(self, event: dict) -> str:
        """Legacy /news handler (fallback when NewsProcessor not available)."""
        chat_id = event.get("chat_id")
        logger.info(f"/news command (legacy) from Feishu chat {chat_id}")

        try:
            # Get recent news (last 2 hours)
            news_items = await self.scheduler._get_recent_news(hours=2)

            if not news_items:
                return "📰 暂无最新新闻"

            # Aggregate and deduplicate
            from server.services.news_aggregator import NewsAggregator, NewsAnalyzer

            aggregator = NewsAggregator(similarity_threshold=0.5)
            aggregated = aggregator.aggregate(news_items, time_window_minutes=120)

            if not aggregated:
                return "📰 暂无最新新闻"

            # Analyze with LLM if available
            if self.report_generator:
                try:
                    analyzer = NewsAnalyzer(llm=self.report_generator.llm)
                    aggregated = await analyzer.analyze_batch(aggregated, max_items=8)
                except Exception as e:
                    logger.warning(f"News analysis failed: {e}")

            # Format and return
            if any(item.chinese_summary for item in aggregated):
                message = format_news_digest_with_analysis(aggregated, max_items=8)
            else:
                message = format_news_digest_simple(aggregated, max_items=8)

            logger.info(f"News sent (legacy) to Feishu chat {chat_id}")
            return message

        except Exception as e:
            logger.error(f"News command (legacy) failed: {e}")
            return f"❌ 获取失败: {str(e)[:100]}"

    async def handle_crypto(self, event: dict) -> str:
        """Handle /crypto command - show cryptocurrency prices."""
        chat_id = event.get("chat_id")
        logger.info(f"/crypto command from Feishu chat {chat_id}")

        try:
            if not self.scheduler.latest_crypto_data:
                return "💰 暂无加密货币数据，请稍后再试"

            message = format_crypto_update(
                crypto_data=self.scheduler.latest_crypto_data,
                previous_data=self.scheduler._previous_crypto_data,
                timestamp=datetime.utcnow(),
            )

            logger.info(f"Crypto sent to Feishu chat {chat_id}")
            return message

        except Exception as e:
            logger.error(f"Crypto command failed: {e}")
            return f"❌ 获取失败: {str(e)[:100]}"

    async def handle_market(self, event: dict) -> str:
        """Handle /market command - show market data with watchlist stocks."""
        chat_id = event.get("chat_id")
        logger.info(f"/market command from Feishu chat {chat_id}")

        try:
            indices = self.scheduler.latest_market_data.get("indices", [])
            commodities = self.scheduler.latest_market_data.get("commodities", [])

            # Get watchlist quotes
            watchlist_quotes = []
            watchlist_news = []

            if (
                hasattr(self.scheduler, "_finnhub_news")
                and self.scheduler._finnhub_news
            ):
                # Get watchlist from settings or default
                watchlist = global_settings.watchlist_symbols or [
                    "NVDA",
                    "AAPL",
                    "MSFT",
                    "GOOGL",
                    "TSLA",
                ]

                for symbol in watchlist[:5]:
                    quote = await self.scheduler._finnhub_news.fetch_quote(symbol)
                    if quote:
                        watchlist_quotes.append(quote)

                    # Get recent news for top 2 stocks
                    if len(watchlist_news) < 3:
                        news = await self.scheduler._finnhub_news.fetch_company_news(
                            symbol, days=1
                        )
                        for n in news[:2]:
                            watchlist_news.append(
                                {
                                    "symbol": symbol,
                                    "headline": n.headline,
                                    "source": n.source,
                                    "url": n.url,
                                }
                            )

            message = format_market_with_watchlist(
                indices=indices,
                commodities=commodities,
                watchlist_quotes=watchlist_quotes,
                watchlist_news=watchlist_news[:5],
                timestamp=datetime.utcnow(),
            )

            return message

        except Exception as e:
            logger.error(f"Market command failed: {e}")
            return f"❌ 获取失败: {str(e)[:100]}"

    async def handle_watch(self, event: dict) -> str:
        """Handle /watch command - manage watchlist.

        Usage:
            /watch - show current watchlist
            /watch add NVDA - add symbol
            /watch add topic:AI监管 - add topic
            /watch add sector:半导体 - add sector
            /watch remove NVDA - remove item
        """
        chat_id = event.get("chat_id")
        args = event.get("args", "").strip()
        logger.info(f"/watch command from Feishu chat {chat_id}")

        try:
            from server.services.watchlist import add_watch, remove_watch, list_watches
            from server.datastore.engine import get_session_factory

            sf = get_session_factory()

            if not args:
                items = await list_watches(sf)
                if not items:
                    return "📋 *关注列表为空*\n\n使用 /watch add NVDA 添加股票\n使用 /watch add topic:AI监管 添加话题"

                lines = ["📋 *当前关注列表*\n"]
                type_labels = {
                    "stock": "📈 股票",
                    "topic": "🏷️ 话题",
                    "sector": "🏭 行业",
                    "region": "🌍 地区",
                }
                grouped: dict[str, list] = {}
                for item in items:
                    grouped.setdefault(item["watch_type"], []).append(item["symbol"])
                for wt, symbols in grouped.items():
                    label = type_labels.get(wt, wt)
                    lines.append(f"{label}: {', '.join(symbols)}")

                lines.append("\n/watch add NVDA — 添加股票")
                lines.append("/watch add topic:AI监管 — 添加话题")
                lines.append("/watch remove NVDA — 移除")
                return "\n".join(lines)

            parts = args.split(maxsplit=1)
            action = parts[0].lower()
            target = parts[1] if len(parts) > 1 else None

            if action == "add" and target:
                watch_type = "stock"
                symbol = target
                for prefix in ("topic:", "sector:", "region:"):
                    if target.lower().startswith(prefix):
                        watch_type = prefix[:-1]
                        symbol = target[len(prefix) :]
                        break
                if watch_type == "stock":
                    symbol = symbol.upper()

                ok = await add_watch(sf, symbol, watch_type=watch_type)
                if ok:
                    return f"✅ 已添加 {symbol} ({watch_type}) 到关注列表"
                else:
                    return f"ℹ️ {symbol} 已在关注列表中"

            elif action == "remove" and target:
                symbol = target
                if not any(
                    target.lower().startswith(p)
                    for p in ("topic:", "sector:", "region:")
                ):
                    symbol = target.upper()
                ok = await remove_watch(sf, symbol)
                if ok:
                    return f"✅ 已从关注列表移除 {symbol}"
                else:
                    return f"ℹ️ {symbol} 不在关注列表中"

            else:
                return (
                    "用法:\n"
                    "/watch — 查看关注列表\n"
                    "/watch add NVDA — 添加股票\n"
                    "/watch add topic:AI监管 — 添加话题\n"
                    "/watch add sector:半导体 — 添加行业\n"
                    "/watch remove NVDA — 移除"
                )

        except Exception as e:
            logger.error(f"Watch command failed: {e}")
            return f"❌ 操作失败: {str(e)[:100]}"

    async def handle_feed(self, event: dict) -> str:
        """Handle /feed command - manage RSS feeds.

        Usage:
            /feed list - list all feeds
            /feed add <url> [name] - add new feed (validates first)
            /feed remove <name> - remove feed
        """
        args = event.get("args", "").strip()
        logger.info("/feed command from Feishu")

        if not self.rss_fetcher:
            return "❌ RSS模块未初始化"

        try:
            if not args or args.lower() == "list":
                feeds = self.rss_fetcher.feeds
                if not feeds:
                    return "📡 *RSS源列表为空*\n\n使用 /feed add <url> 添加"

                lines = [f"📡 *RSS源列表* ({len(feeds)}个)\n"]
                by_cat: dict[str, list] = {}
                for f in feeds:
                    by_cat.setdefault(f.category or "other", []).append(f.name)
                for cat, names in sorted(by_cat.items()):
                    lines.append(f"*{cat}*: {', '.join(names)}")
                lines.append("\n/feed add <url> — 添加\n/feed remove <name> — 删除")
                return "\n".join(lines)

            parts = args.split(maxsplit=2)
            action = parts[0].lower()

            if action == "add" and len(parts) >= 2:
                url = parts[1]
                custom_name = parts[2] if len(parts) > 2 else None

                # Validate
                ok, feed_title, entries = await self.rss_fetcher.validate_feed(url)
                if not ok:
                    return f"❌ 无法解析该RSS源: {url}\n请检查URL是否正确"

                name = custom_name or feed_title
                added = self.rss_fetcher.add_feed(name=name, url=url)
                if not added:
                    return f"ℹ️ 该源已存在: {name}"

                lines = [f"✅ 已添加RSS源: *{name}*\n", "最新5条内容:"]
                for i, entry in enumerate(entries, 1):
                    lines.append(f"{i}. {entry['title']}")
                    lines.append(f"   _{entry['published']}_")
                return "\n".join(lines)

            elif action == "remove" and len(parts) >= 2:
                name = " ".join(parts[1:])
                removed = self.rss_fetcher.remove_feed(name)
                if removed:
                    return f"✅ 已删除RSS源: {name}"
                else:
                    return f"ℹ️ 未找到RSS源: {name}"

            else:
                return (
                    "用法:\n"
                    "/feed list — 列出所有RSS源\n"
                    "/feed add <url> [名称] — 添加新源\n"
                    "/feed remove <名称> — 删除源"
                )

        except Exception as e:
            logger.error(f"Feed command failed: {e}")
            return f"❌ 操作失败: {str(e)[:100]}"

    async def handle_status(self, event: dict) -> str:
        """Handle /status command - show system status."""
        chat_id = event.get("chat_id")
        logger.info(f"/status command from Feishu chat {chat_id}")

        try:
            scheduler_status = self.scheduler.get_status()
            service_status = global_settings.get_service_status()

            data_stats = {
                "crypto_prices": len(self.scheduler.latest_crypto_data),
            }

            message = format_status(scheduler_status, service_status, data_stats)
            return message

        except Exception as e:
            logger.error(f"Status command failed: {e}")
            return f"❌ 获取状态失败: {str(e)[:100]}"

    async def handle_help(self, event: dict) -> str:
        """Handle /help command - show help message."""
        return format_help()

    async def handle_start(self, event: dict) -> str:
        """Handle /start command - welcome message."""
        return """👋 *欢迎使用 XBot*

我是一个情报聚合和分析机器人，可以帮你：
• 追踪全球新闻动态（带市场影响分析）
• 监控加密货币价格变动
• 查看股市和大宗商品数据
• 关注特定股票并获取相关新闻
• 每日早晚简报推送

输入 /help 查看所有命令"""

    async def handle_continue(self, event: dict) -> str:
        """Handle /continue command - fetch more news from the same time window."""
        chat_id = event.get("chat_id")
        logger.info(f"/continue command from Feishu chat {chat_id}")

        try:
            if not self.scheduler or not self.news_processor:
                return "❌ 功能未配置"

            # Get scheduler state
            if not hasattr(self.scheduler, "_last_news_fetch_time"):
                return "❌ 未找到上次获取记录，请先使用 /news"

            fetch_start = self.scheduler._last_news_fetch_time
            if not fetch_start:
                return "❌ 未找到上次获取记录，请先使用 /news"

            # Increment offset for pagination
            if hasattr(self.scheduler, "_last_news_fetch_offset"):
                self.scheduler._last_news_fetch_offset += 10
                offset = self.scheduler._last_news_fetch_offset
            else:
                offset = 10
                self.scheduler._last_news_fetch_offset = offset

            # Calculate time window
            from datetime import datetime

            now = datetime.utcnow()
            hours_elapsed = max(0.25, (now - fetch_start).total_seconds() / 3600)

            # Fetch news with offset
            items = await self.news_processor.get_and_process_news(
                hours=hours_elapsed,
                max_items=10,
                filter_pushed=False,
                push_type="command",
                use_cache=True,
                platform="feishu",
                fetch_start_time=fetch_start,
                offset=offset,
            )

            if not items:
                # Reset offset
                self.scheduler._last_news_fetch_offset = 0
                return "📰 没有更多新闻了"

            # Format and return
            if any(item.chinese_summary for item in items):
                message = format_news_digest_with_analysis(items, max_items=10)
            else:
                message = format_news_digest_simple(items, max_items=10)

            # Add pagination hint
            if len(items) >= 10:
                message += (
                    f"\n\n📌 *第 {offset // 10 + 1} 页* — 输入 /continue 继续翻页"
                )

            logger.info(
                f"[/continue Feishu] Fetched {len(items)} items with offset {offset}"
            )
            return message

        except Exception as e:
            logger.error(f"/continue command failed: {e}")
            return f"❌ 操作失败: {str(e)[:100]}"


def register_feishu_commands(bot, dispatcher: FeishuCommandDispatcher) -> None:
    """Register all command handlers with the Feishu bot."""
    bot.add_command("start", dispatcher.handle_start)
    bot.add_command("help", dispatcher.handle_help)
    bot.add_command("news", dispatcher.handle_news)
    bot.add_command("crypto", dispatcher.handle_crypto)
    bot.add_command("market", dispatcher.handle_market)
    bot.add_command("watch", dispatcher.handle_watch)
    bot.add_command("feed", dispatcher.handle_feed)
    bot.add_command("status", dispatcher.handle_status)
    bot.add_command("continue", dispatcher.handle_continue)

    logger.info("Registered 9 Feishu bot commands")


def register_feishu_chat_commands(bot, dispatcher: FeishuCommandDispatcher) -> None:
    """Register chat mode commands after chat_command_handlers is initialized."""
    if dispatcher.chat_command_handlers:
        bot.add_command("chat", dispatcher.chat_command_handlers.handle_chat)
        bot.add_command("quit", dispatcher.chat_command_handlers.handle_quit)
        bot.add_command(
            "chatstatus", dispatcher.chat_command_handlers.handle_chat_status
        )
        logger.info("Registered 3 Feishu chat mode commands")
    else:
        logger.info("Chat mode commands not registered (no chat_command_handlers)")
