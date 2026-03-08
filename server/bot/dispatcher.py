"""Telegram command handlers (dispatcher)."""

import time
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
from server.bot.chat_handlers import ChatCommandHandlers
from server.bot.telegram_adapter import (
    TelegramMessageAdapter,
    TelegramBotAdapter,
)

if TYPE_CHECKING:
    from server.bot.telegram import TelegramBot
    from server.datasource.scheduler import DataScheduler
    from server.analysis.correlation import CorrelationEngine
    from server.reports.generator import ReportGenerator
    from server.services.news_processor import NewsProcessor
    from server.ai.llm import LLM
    from memory.service import MemoryService


class CommandDispatcher:
    """Handles Telegram bot commands."""

    def __init__(
        self,
        scheduler: "DataScheduler",
        correlation_engine: "CorrelationEngine | None" = None,
        report_generator: "ReportGenerator | None" = None,
        rss_fetcher=None,
        news_processor: "NewsProcessor | None" = None,
        bot: "TelegramBot | None" = None,
        chat_command_handlers: "ChatCommandHandlers | None" = None,
        llm_client: "LLM | None" = None,
        memory_service: "MemoryService | None" = None,
    ):
        self.scheduler = scheduler
        self.correlation_engine = correlation_engine
        self.report_generator = report_generator
        self.rss_fetcher = rss_fetcher
        self.news_processor = news_processor
        self.bot = bot
        self.llm_client = llm_client
        self.memory_service = memory_service

        # 初始化聊天命令处理器（使用适配器）
        if bot and bot.chat_manager:
            bot_adapter = TelegramBotAdapter(bot)
            self.chat_command_handlers = ChatCommandHandlers(
                bot=bot_adapter,
                chat_manager=bot.chat_manager,
                llm_client=llm_client,
                memory_service=memory_service,
            )
        else:
            self.chat_command_handlers = chat_command_handlers

    async def handle_news(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /news command - show recent news with analysis."""
        import time

        assert update.effective_chat is not None
        assert update.message is not None
        chat_id = update.effective_chat.id
        logger.info(f"/news command from chat {chat_id}")

        start_time = time.time()

        await update.message.reply_text("⏳ 正在获取最新新闻...")

        try:
            # Use unified news processor if available
            if self.news_processor:
                # Calculate fetch start time
                from datetime import datetime, timedelta

                now = datetime.utcnow()
                if self.scheduler and hasattr(self.scheduler, "_last_news_fetch_time"):
                    last_fetch_time = self.scheduler._last_news_fetch_time
                    if last_fetch_time:
                        # Fetch from last scheduled/command fetch to now
                        fetch_start = last_fetch_time
                        elapsed = (now - fetch_start).total_seconds() / 60
                        logger.info(
                            f"[/news] Fetching from last fetch {elapsed:.1f} min ago"
                        )
                    else:
                        # First /news: fetch from 15 minutes ago
                        fetch_start = now - timedelta(minutes=15)
                        logger.info("[/news] First fetch, getting news from 15 min ago")
                else:
                    # No scheduler: fallback to 15 minutes ago
                    fetch_start = now - timedelta(minutes=15)
                    logger.info("[/news] No scheduler, getting news from 15 min ago")

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
                    platform="telegram",
                    fetch_start_time=fetch_start,
                )

                if not items:
                    await update.message.reply_text("📰 暂无最新新闻")
                    return

                # Format and send
                if any(item.chinese_summary for item in items):
                    message = format_news_digest_with_analysis(items, max_items=10)
                else:
                    message = format_news_digest_simple(items, max_items=10)

                await update.message.reply_text(
                    message,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                )

                total_elapsed = time.time() - start_time
                logger.info(
                    f"[DONE] /news command completed, sent {len(items)} items, took {total_elapsed:.2f}s"
                )
            else:
                # Legacy fallback - use existing logic
                await self._handle_news_legacy(update, context, start_time, chat_id)

        except Exception as e:
            total_elapsed = time.time() - start_time
            logger.error(
                f"[ERROR] /news command failed after {total_elapsed:.2f}s: {e}"
            )
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            await update.message.reply_text(f"❌ 获取失败: {str(e)[:100]}")

    async def _handle_news_legacy(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        start_time: float,
        chat_id: int,
    ) -> None:
        """Legacy /news handler (fallback when NewsProcessor not available)."""
        assert update.message is not None
        # Step 1: Get recent news (last 2 hours)
        logger.info("[Step 1/4] 开始获取新闻...")
        step1_start = time.time()

        news_items = await self.scheduler._get_recent_news(hours=2)

        step1_elapsed = time.time() - step1_start
        logger.info(
            f"[Step 1/4] 新闻获取完成，耗时 {step1_elapsed:.2f}s，共 {len(news_items)} 条"
        )

        if not news_items:
            await update.message.reply_text("📰 暂无最新新闻")
            return

        # Step 2: Aggregate and deduplicate
        logger.info("[Step 2/4] 开始聚合和去重...")
        step2_start = time.time()

        from server.services.news_aggregator import NewsAggregator, NewsAnalyzer

        aggregator = NewsAggregator(similarity_threshold=0.5)
        aggregated = aggregator.aggregate(news_items, time_window_minutes=120)

        step2_elapsed = time.time() - step2_start
        logger.info(
            f"[Step 2/4] 聚合完成，耗时 {step2_elapsed:.2f}s，得到 {len(aggregated)} 条去重新闻"
        )

        if not aggregated:
            await update.message.reply_text("📰 暂无最新新闻")
            return

        # Step 3: Analyze with LLM if available
        if self.report_generator:
            logger.info("[Step 3/4] 开始 LLM 分析...")
            step3_start = time.time()

            try:
                analyzer = NewsAnalyzer(llm=self.report_generator.llm)
                aggregated = await analyzer.analyze_batch(aggregated, max_items=8)
                step3_elapsed = time.time() - step3_start
                logger.info(f"[Step 3/4] LLM 分析完成，耗时 {step3_elapsed:.2f}s")
            except Exception as e:
                step3_elapsed = time.time() - step3_start
                logger.warning(
                    f"[Step 3/4] LLM 分析失败，耗时 {step3_elapsed:.2f}s: {e}"
                )
        else:
            logger.info("[Step 3/4] 跳过 LLM 分析（report_generator 未配置）")

        # Step 4: Format and send
        logger.info("[Step 4/4] 开始格式化消息...")
        step4_start = time.time()

        if any(item.chinese_summary for item in aggregated):
            message = format_news_digest_with_analysis(aggregated, max_items=8)
        else:
            message = format_news_digest_simple(aggregated, max_items=8)

        await update.message.reply_text(
            message, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
        )
        step4_elapsed = time.time() - step4_start
        logger.info(f"[Step 4/4] 消息发送完成，耗时 {step4_elapsed:.2f}s")

        total_elapsed = time.time() - start_time
        logger.info(
            f"[DONE] /news 命令执行完成，总耗时 {total_elapsed:.2f}s，发送到 chat {chat_id}"
        )

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

    async def handle_continue(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /continue command - fetch more news from the same time window."""
        assert update.effective_chat is not None
        assert update.message is not None
        chat_id = update.effective_chat.id
        logger.info(f"/continue command from chat {chat_id}")

        try:
            if not self.scheduler or not self.news_processor:
                await update.message.reply_text("❌ 功能未配置")
                return

            # Get scheduler state
            if not hasattr(self.scheduler, "_last_news_fetch_time"):
                await update.message.reply_text("❌ 未找到上次获取记录，请先使用 /news")
                return

            fetch_start = self.scheduler._last_news_fetch_time
            if not fetch_start:
                await update.message.reply_text("❌ 未找到上次获取记录，请先使用 /news")
                return

            # Increment offset for pagination
            if hasattr(self.scheduler, "_last_news_fetch_offset"):
                self.scheduler._last_news_fetch_offset += 10
                offset = self.scheduler._last_news_fetch_offset
            else:
                offset = 10
                self.scheduler._last_news_fetch_offset = offset

            # Calculate time window end point
            now = datetime.utcnow()
            hours_elapsed = max(0.25, (now - fetch_start).total_seconds() / 3600)

            await update.message.reply_text("⏳ 正在获取更多新闻...")

            # Fetch news with offset
            items = await self.news_processor.get_and_process_news(
                hours=hours_elapsed,
                max_items=10,
                filter_pushed=False,
                push_type="command",
                use_cache=True,
                platform="telegram",
                fetch_start_time=fetch_start,
                offset=offset,
            )

            if not items:
                await update.message.reply_text("📰 没有更多新闻了")
                # Reset offset
                self.scheduler._last_news_fetch_offset = 0
                return

            # Format and send
            if any(item.chinese_summary for item in items):
                message = format_news_digest_with_analysis(items, max_items=10)
            else:
                message = format_news_digest_simple(items, max_items=10)

            # Add pagination hint
            if len(items) >= 10:
                message += (
                    f"\n\n📌 *第 {offset // 10 + 1} 页* — 输入 /continue 继续翻页"
                )

            await update.message.reply_text(
                message,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )

            logger.info(f"[/continue] Fetched {len(items)} items with offset {offset}")

        except Exception as e:
            logger.error(f"/continue command failed: {e}")
            await update.message.reply_text(
                f"❌ 操作失败: {str(e)[:100]}", parse_mode=ParseMode.MARKDOWN
            )


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
    bot.add_command("continue", dispatcher.handle_continue)

    logger.info("Registered 10 bot commands")

    # Chat mode commands (if handlers are available)
    if dispatcher.chat_command_handlers:
        # 创建聊天命令的包装器，将 Telegram Update 转换为通用事件
        chat_handlers = dispatcher.chat_command_handlers

        async def chat_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            event = TelegramMessageAdapter.to_event(update, context)
            response = await chat_handlers.handle_chat(event)
            if response and update.effective_chat:
                await bot.send_markdown(response, str(update.effective_chat.id))

        async def quit_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            event = TelegramMessageAdapter.to_event(update, context)
            response = await chat_handlers.handle_quit(event)
            if response and update.effective_chat:
                await bot.send_markdown(response, str(update.effective_chat.id))

        async def chatstatus_wrapper(
            update: Update, context: ContextTypes.DEFAULT_TYPE
        ):
            event = TelegramMessageAdapter.to_event(update, context)
            response = await chat_handlers.handle_chat_status(event)
            if response and update.effective_chat:
                await bot.send_markdown(response, str(update.effective_chat.id))

        bot.add_command("chat", chat_wrapper)
        bot.add_command("quit", quit_wrapper)
        bot.add_command("chatstatus", chatstatus_wrapper)
        logger.info("Registered 13 bot commands")
    else:
        logger.info("Chat mode commands not registered (no chat_command_handlers)")


def register_chat_commands(
    bot: "TelegramBot | None", dispatcher: CommandDispatcher
) -> None:
    """Register chat mode commands after chat_command_handlers is initialized."""
    if bot is None:
        logger.warning("Cannot register chat commands: bot is None")
        return

    if dispatcher.chat_command_handlers:
        # 创建聊天命令的包装器，将 Telegram Update 转换为通用事件
        chat_handlers = dispatcher.chat_command_handlers

        async def chat_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            event = TelegramMessageAdapter.to_event(update, context)
            response = await chat_handlers.handle_chat(event)
            if response and update.effective_chat:
                await bot.send_markdown(response, str(update.effective_chat.id))

        async def quit_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            event = TelegramMessageAdapter.to_event(update, context)
            response = await chat_handlers.handle_quit(event)
            if response and update.effective_chat:
                await bot.send_markdown(response, str(update.effective_chat.id))

        async def chatstatus_wrapper(
            update: Update, context: ContextTypes.DEFAULT_TYPE
        ):
            event = TelegramMessageAdapter.to_event(update, context)
            response = await chat_handlers.handle_chat_status(event)
            if response and update.effective_chat:
                await bot.send_markdown(response, str(update.effective_chat.id))

        bot.add_command("chat", chat_wrapper)
        bot.add_command("quit", quit_wrapper)
        bot.add_command("chatstatus", chatstatus_wrapper)
        logger.info("Registered 3 chat mode commands")
    else:
        logger.info("Chat mode commands not registered (no chat_command_handlers)")
