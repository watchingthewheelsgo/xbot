"""Telegram command handlers (dispatcher)."""

from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from server.bot.formatter import (
    format_status,
    format_help,
    format_news_digest_with_analysis,
    format_news_digest_simple,
    format_crypto_update,
    format_market_with_watchlist,
)
from server.settings import global_settings

if TYPE_CHECKING:
    from server.bot.telegram import TelegramBot
    from server.datasource.scheduler import DataScheduler
    from server.analysis.correlation import CorrelationEngine
    from server.reports.generator import ReportGenerator


class CommandDispatcher:
    """Handles Telegram bot commands."""

    def __init__(
        self,
        scheduler: "DataScheduler",
        correlation_engine: "CorrelationEngine | None" = None,
        report_generator: "ReportGenerator | None" = None,
        rss_fetcher=None,
    ):
        self.scheduler = scheduler
        self.correlation_engine = correlation_engine
        self.report_generator = report_generator
        self.rss_fetcher = rss_fetcher

    async def handle_news(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /news command - show recent news with analysis."""
        assert update.effective_chat is not None
        assert update.message is not None
        chat_id = update.effective_chat.id
        logger.info(f"/news command from chat {chat_id}")

        await update.message.reply_text("⏳ 正在获取最新新闻...")

        try:
            # Get recent news (last 2 hours)
            news_items = await self.scheduler._get_recent_news(hours=2)

            if not news_items:
                await update.message.reply_text("📰 暂无最新新闻")
                return

            # Aggregate and deduplicate
            from server.services.news_aggregator import NewsAggregator, NewsAnalyzer

            aggregator = NewsAggregator(similarity_threshold=0.5)
            aggregated = aggregator.aggregate(news_items, time_window_minutes=120)

            if not aggregated:
                await update.message.reply_text("📰 暂无最新新闻")
                return

            # Analyze with LLM if available
            if self.report_generator:
                try:
                    analyzer = NewsAnalyzer(llm=self.report_generator.llm)
                    aggregated = await analyzer.analyze_batch(aggregated, max_items=8)
                except Exception as e:
                    logger.warning(f"News analysis failed: {e}")

            # Format and send
            if any(item.chinese_summary for item in aggregated):
                message = format_news_digest_with_analysis(aggregated, max_items=8)
            else:
                message = format_news_digest_simple(aggregated, max_items=8)

            await update.message.reply_text(
                message, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
            )
            logger.info(f"News sent to chat {chat_id}")

        except Exception as e:
            logger.error(f"News command failed: {e}")
            await update.message.reply_text(f"❌ 获取失败: {str(e)[:100]}")

    async def handle_crypto(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /crypto command - show cryptocurrency prices."""
        assert update.effective_chat is not None
        assert update.message is not None
        chat_id = update.effective_chat.id
        logger.info(f"/crypto command from chat {chat_id}")

        try:
            if not self.scheduler.latest_crypto_data:
                await update.message.reply_text("💰 暂无加密货币数据，请稍后再试")
                return

            message = format_crypto_update(
                crypto_data=self.scheduler.latest_crypto_data,
                previous_data=self.scheduler._previous_crypto_data,
                timestamp=datetime.utcnow(),
            )

            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
            logger.info(f"Crypto sent to chat {chat_id}")

        except Exception as e:
            logger.error(f"Crypto command failed: {e}")
            await update.message.reply_text(f"❌ 获取失败: {str(e)[:100]}")

    async def handle_market(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /market command - show market data with watchlist stocks."""
        assert update.effective_chat is not None
        assert update.message is not None
        chat_id = update.effective_chat.id
        logger.info(f"/market command from chat {chat_id}")

        await update.message.reply_text("⏳ 正在获取市场数据...")

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

            await update.message.reply_text(
                message, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
            )

        except Exception as e:
            logger.error(f"Market command failed: {e}")
            await update.message.reply_text(f"❌ 获取失败: {str(e)[:100]}")

    async def handle_watch(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /watch command - manage watchlist.

        Usage:
            /watch - show current watchlist
            /watch add NVDA - add symbol
            /watch add topic:AI监管 - add topic
            /watch remove NVDA - remove item
        """
        assert update.effective_chat is not None
        assert update.message is not None
        chat_id = update.effective_chat.id
        logger.info(f"/watch command from chat {chat_id}")

        args = context.args or []

        try:
            from server.services.watchlist import add_watch, remove_watch, list_watches
            from server.datastore.engine import get_session_factory

            sf = get_session_factory()

            if not args:
                items = await list_watches(sf)
                if not items:
                    await update.message.reply_text(
                        "📋 *关注列表为空*\n\n"
                        "使用 `/watch add NVDA` 添加股票\n"
                        "使用 `/watch add topic:AI监管` 添加话题",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                else:
                    lines = ["📋 *当前关注列表*\n"]
                    type_labels = {
                        "stock": "📈 股票",
                        "topic": "🏷️ 话题",
                        "sector": "🏭 行业",
                        "region": "🌍 地区",
                    }
                    grouped: dict[str, list] = {}
                    for item in items:
                        grouped.setdefault(item["watch_type"], []).append(
                            item["symbol"]
                        )
                    for wt, symbols in grouped.items():
                        label = type_labels.get(wt, wt)
                        lines.append(f"{label}: {', '.join(symbols)}")
                    lines.append("\n`/watch add NVDA` — 添加股票")
                    lines.append("`/watch add topic:AI监管` — 添加话题")
                    lines.append("`/watch remove NVDA` — 移除")
                    await update.message.reply_text(
                        "\n".join(lines),
                        parse_mode=ParseMode.MARKDOWN,
                    )
                return

            action = args[0].lower()
            target = " ".join(args[1:]) if len(args) > 1 else None

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
                    await update.message.reply_text(
                        f"✅ 已添加 {symbol} ({watch_type}) 到关注列表"
                    )
                else:
                    await update.message.reply_text(f"ℹ️ {symbol} 已在关注列表中")

            elif action == "remove" and target:
                symbol = target
                if not any(
                    target.lower().startswith(p)
                    for p in ("topic:", "sector:", "region:")
                ):
                    symbol = target.upper()
                ok = await remove_watch(sf, symbol)
                if ok:
                    await update.message.reply_text(f"✅ 已从关注列表移除 {symbol}")
                else:
                    await update.message.reply_text(f"ℹ️ {symbol} 不在关注列表中")

            else:
                await update.message.reply_text(
                    "用法:\n"
                    "/watch — 查看关注列表\n"
                    "/watch add NVDA — 添加股票\n"
                    "/watch add topic:AI监管 — 添加话题\n"
                    "/watch add sector:半导体 — 添加行业\n"
                    "/watch remove NVDA — 移除"
                )

        except Exception as e:
            logger.error(f"Watch command failed: {e}")
            await update.message.reply_text(f"❌ 操作失败: {str(e)[:100]}")

    async def handle_feed(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /feed command - manage RSS feeds."""
        assert update.effective_chat is not None
        assert update.message is not None
        chat_id = update.effective_chat.id
        logger.info(f"/feed command from chat {chat_id}")

        if not self.rss_fetcher:
            await update.message.reply_text("❌ RSS模块未初始化")
            return

        args = context.args or []

        try:
            if not args or args[0].lower() == "list":
                feeds = self.rss_fetcher.feeds
                if not feeds:
                    await update.message.reply_text(
                        "📡 *RSS源列表为空*\n\n使用 `/feed add <url>` 添加",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                    return

                lines = [f"📡 *RSS源列表* ({len(feeds)}个)\n"]
                by_cat: dict[str, list] = {}
                for f in feeds:
                    by_cat.setdefault(f.category or "other", []).append(f.name)
                for cat, names in sorted(by_cat.items()):
                    lines.append(f"*{cat}*: {', '.join(names)}")
                lines.append("\n`/feed add <url>` — 添加\n`/feed remove <name>` — 删除")
                await update.message.reply_text(
                    "\n".join(lines), parse_mode=ParseMode.MARKDOWN
                )
                return

            action = args[0].lower()

            if action == "add" and len(args) >= 2:
                url = args[1]
                custom_name = " ".join(args[2:]) if len(args) > 2 else None

                await update.message.reply_text("⏳ 正在验证RSS源...")

                ok, feed_title, entries = await self.rss_fetcher.validate_feed(url)
                if not ok:
                    await update.message.reply_text(
                        f"❌ 无法解析该RSS源: {url}\n请检查URL是否正确"
                    )
                    return

                name = custom_name or feed_title
                added = self.rss_fetcher.add_feed(name=name, url=url)
                if not added:
                    await update.message.reply_text(f"ℹ️ 该源已存在: {name}")
                    return

                lines = [f"✅ 已添加RSS源: *{name}*\n", "最新5条内容:"]
                for i, entry in enumerate(entries, 1):
                    lines.append(f"{i}\\. {entry['title']}")
                    lines.append(f"   _{entry['published']}_")
                await update.message.reply_text(
                    "\n".join(lines), parse_mode=ParseMode.MARKDOWN
                )

            elif action == "remove" and len(args) >= 2:
                name = " ".join(args[1:])
                removed = self.rss_fetcher.remove_feed(name)
                if removed:
                    await update.message.reply_text(f"✅ 已删除RSS源: {name}")
                else:
                    await update.message.reply_text(f"ℹ️ 未找到RSS源: {name}")

            else:
                await update.message.reply_text(
                    "用法:\n"
                    "/feed list — 列出所有RSS源\n"
                    "/feed add <url> [名称] — 添加新源\n"
                    "/feed remove <名称> — 删除源"
                )

        except Exception as e:
            logger.error(f"Feed command failed: {e}")
            await update.message.reply_text(f"❌ 操作失败: {str(e)[:100]}")

    async def handle_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /status command - show system status."""
        assert update.effective_chat is not None
        assert update.message is not None
        chat_id = update.effective_chat.id
        logger.info(f"/status command from chat {chat_id}")

        try:
            scheduler_status = self.scheduler.get_status()
            service_status = global_settings.get_service_status()

            data_stats = {
                "crypto_prices": len(self.scheduler.latest_crypto_data),
            }

            message = format_status(scheduler_status, service_status, data_stats)
            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Status command failed: {e}")
            await update.message.reply_text(f"❌ 获取状态失败: {str(e)[:100]}")

    async def handle_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /help command - show help message."""
        assert update.message is not None
        message = format_help()
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def handle_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /start command - welcome message."""
        assert update.message is not None
        welcome = """👋 *欢迎使用 XBot*

我是一个情报聚合和分析机器人，可以帮你：
• 追踪全球新闻动态（带市场影响分析）
• 监控加密货币价格变动
• 查看股市和大宗商品数据
• 关注特定股票并获取相关新闻
• 每日早晚简报推送

输入 /help 查看所有命令"""
        await update.message.reply_text(welcome, parse_mode=ParseMode.MARKDOWN)


def register_commands(bot: "TelegramBot", dispatcher: CommandDispatcher) -> None:
    """Register all command handlers with the bot."""

    bot.add_command("start", dispatcher.handle_start)
    bot.add_command("help", dispatcher.handle_help)
    bot.add_command("news", dispatcher.handle_news)
    bot.add_command("crypto", dispatcher.handle_crypto)
    bot.add_command("market", dispatcher.handle_market)
    bot.add_command("watch", dispatcher.handle_watch)
    bot.add_command("feed", dispatcher.handle_feed)
    bot.add_command("status", dispatcher.handle_status)

    logger.info("Registered 8 bot commands")
