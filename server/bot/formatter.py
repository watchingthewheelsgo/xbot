"""Message formatters for Telegram notifications."""

from datetime import datetime
from typing import Optional

from server.analysis.types import CorrelationResults
from server.services.news_aggregator import NewsItem


def escape_md(text: str) -> str:
    """Escape special Markdown characters for safe display."""
    for char in ["_", "*", "`", "[", "]", "(", ")"]:
        text = text.replace(char, "\\" + char)
    return text


def format_source_label(source_type: str, source_name: str = "") -> str:
    """Format news source as a label.

    Examples:
        \[RSS - Bloomberg\]
        \[Finnhub\]
        \[Reddit - r/stocks\]
    """
    if not source_type:
        return ""

    source_type = source_type.lower()

    if source_type == "rss":
        return f"\\[RSS - {source_name}\\]" if source_name else "\\[RSS\\]"
    elif source_type == "finnhub":
        return "\\[Finnhub\\]"
    elif source_type == "reddit":
        return f"\\[Reddit - {source_name}\\]" if source_name else "\\[Reddit\\]"
    else:
        # Generic format for unknown types
        return (
            f"\\[{source_type.upper()}{f' - {source_name}' if source_name else ''}\\]"
        )


def format_change(value: float) -> str:
    """Format a percentage change with sign and emoji."""
    if value > 0:
        return f"+{value:.2f}%"
    elif value < 0:
        return f"{value:.2f}%"
    return "0.00%"


# ============================================================================
# News Push Formats
# ============================================================================


def format_news_digest_with_analysis(
    items: list[NewsItem], timestamp: datetime | None = None, max_items: int = 10
) -> str:
    """Format news digest with LLM analysis and deduplication.

    Example output:
    🔔 新闻速递 — 21:05

    【标题】OpenAI发布GPT-5

    📝 摘要：OpenAI今日发布新一代模型...

    📊 市场影响：
    • 利好：NVDA、MSFT
    • 利空：GOOG
    • 关注：AI芯片板块

    🔗 来源：[TechCrunch](link) | [The Verge](link)
    """
    ts = timestamp or datetime.utcnow()
    time_str = ts.strftime("%H:%M")

    lines = [f"🔔 *新闻速递* — {time_str}", ""]

    if not items:
        lines.append("暂无新消息")
        return "\n".join(lines)

    # Filter by importance (>=2) and sort
    important_items = [i for i in items if i.importance >= 2]
    if important_items:
        items = sorted(important_items, key=lambda x: x.importance, reverse=True)
    items = items[:max_items]

    for i, item in enumerate(items, 1):
        # Title with importance indicator and source label
        importance = ""
        if item.importance >= 4:
            importance = "🔴"
        elif item.importance == 3:
            importance = "🟠"
        elif item.importance == 2:
            importance = "🟡"

        # Get source label
        source_name = item.sources[0].get("name", "") if item.sources else ""
        source_label = format_source_label(item.source_type, source_name)

        # Format title with source (label before title)
        title_text = escape_md(item.title[:80])
        if source_label:
            title_text = f"{source_label} {title_text}"

        lines.append(f"*{i}.* {importance} {title_text}")

        # Chinese summary
        if item.chinese_summary:
            lines.append(f"📝 _{item.chinese_summary}_")

        # Background
        if item.background:
            lines.append(f"📌 {item.background}")

        # Market impact
        if item.market_impact:
            impact_parts = []
            if item.market_impact.get("bullish"):
                impact_parts.append(
                    f"利好 {', '.join(item.market_impact['bullish'][:3])}"
                )
            if item.market_impact.get("bearish"):
                impact_parts.append(
                    f"利空 {', '.join(item.market_impact['bearish'][:3])}"
                )
            if item.market_impact.get("watch"):
                impact_parts.append(
                    f"关注 {', '.join(item.market_impact['watch'][:2])}"
                )

            if impact_parts:
                lines.append(f"📊 {' | '.join(impact_parts)}")

            # Impact reasoning
            if item.market_impact.get("reasoning"):
                lines.append(f"   _{item.market_impact['reasoning']}_")

        # Action suggestion
        if item.action:
            lines.append(f"💡 {item.action}")

        # Sources (show up to 3)
        if item.sources:
            source_links = []
            for s in item.sources[:3]:
                name = s.get("name", "")
                link = s.get("link", "")
                if link:
                    # Escape name
                    safe_name = name.replace("[", "(").replace("]", ")")
                    source_links.append(f"[{safe_name}]({link})")
                elif name:
                    source_links.append(name)

            if len(item.sources) > 3:
                source_links.append(f"+{len(item.sources) - 3} 更多")

            if source_links:
                lines.append(f"🔗 {' | '.join(source_links)}")

        lines.append("")

    return "\n".join(lines)


def format_news_digest_simple(
    items: list[NewsItem], timestamp: datetime | None = None, max_items: int = 10
) -> str:
    """Format news digest without analysis (fallback)."""
    ts = timestamp or datetime.utcnow()
    time_str = ts.strftime("%H:%M")

    lines = [f"📰 *新闻更新* — {time_str}", ""]

    if not items:
        lines.append("暂无新消息")
        return "\n".join(lines)

    for i, item in enumerate(items[:max_items], 1):
        title = item.title[:80]
        safe_title = escape_md(title)

        # Get source label
        source_name = item.sources[0].get("name", "") if item.sources else ""
        source_label = format_source_label(item.source_type, source_name)

        # Format title with source (label before title)
        title_with_source = safe_title
        if source_label:
            title_with_source = f"{source_label} {safe_title}"

        # Sources count
        if item.source_count > 1:
            lines.append(f"*{i}.* {title_with_source} ({item.source_count}个来源)")
        else:
            lines.append(f"*{i}.* {title_with_source}")

        # Add first link
        if item.sources and item.sources[0].get("link"):
            lines.append(f"🔗 {item.sources[0]['link']}")

        lines.append("")

    return "\n".join(lines)


# ============================================================================
# Crypto Push Formats
# ============================================================================


def format_crypto_update(
    crypto_data: list[dict],
    previous_data: list[dict] | None = None,
    timestamp: datetime | None = None,
) -> str:
    """Format cryptocurrency update with comparison.

    Example output:
    💰 Crypto Update — 21:05

    BTC $98,500 (+2.3% 1h | +5.1% 24h) 📈
    ETH $3,850 (+1.8% 1h | +3.2% 24h) 📊
    SOL $145 (+8.5% 1h | +12% 24h) 🔥 异动
    """
    ts = timestamp or datetime.utcnow()
    time_str = ts.strftime("%H:%M")

    lines = [f"💰 *Crypto Update* — {time_str}", ""]

    if not crypto_data:
        lines.append("暂无加密货币数据")
        return "\n".join(lines)

    # Build previous price map
    prev_map = {}
    if previous_data:
        for coin in previous_data:
            if isinstance(coin, dict) and "id" in coin:
                prev_map[coin["id"]] = coin.get("current_price", 0)

    # Symbol mapping
    name_map = {
        "bitcoin": "BTC",
        "ethereum": "ETH",
        "solana": "SOL",
        "binancecoin": "BNB",
        "ripple": "XRP",
        "cardano": "ADA",
        "dogecoin": "DOGE",
        "polkadot": "DOT",
        "avalanche-2": "AVAX",
        "chainlink": "LINK",
    }

    # Sort by 24h change (descending)
    sorted_crypto = sorted(
        crypto_data,
        key=lambda x: x.get("price_change_percentage_24h", 0)
        if isinstance(x, dict)
        else 0,
        reverse=True,
    )

    for coin in sorted_crypto[:8]:
        if not isinstance(coin, dict):
            continue

        coin_id = coin.get("id", "")
        symbol = name_map.get(coin_id, coin_id.upper()[:4])
        price = coin.get("current_price", 0) or 0
        change_24h = coin.get("price_change_percentage_24h", 0) or 0

        # Calculate 1h change if we have previous data
        change_1h = None
        if coin_id in prev_map and prev_map[coin_id] > 0:
            change_1h = ((price - prev_map[coin_id]) / prev_map[coin_id]) * 100

        # Format line
        status_emoji = ""
        if abs(change_24h) >= 5:
            status_emoji = "🔥" if change_24h > 0 else "❄️"
        elif abs(change_24h) >= 2:
            status_emoji = "📈" if change_24h > 0 else "📉"
        else:
            status_emoji = "📊"

        if change_1h is not None:
            line = f"{symbol} ${price:,.2f} ({format_change(change_1h)} 1h | {format_change(change_24h)} 24h) {status_emoji}"
        else:
            line = f"{symbol} ${price:,.2f} ({format_change(change_24h)} 24h) {status_emoji}"

        lines.append(line)

    return "\n".join(lines)


# ============================================================================
# Briefing Formats
# ============================================================================


def format_morning_briefing(
    highlights: list[NewsItem], market_summary: str = "", date: datetime | None = None
) -> str:
    """Format morning briefing (早间简报).

    Only shows top 3-5 important stories with context.
    """
    ts = date or datetime.utcnow()
    date_str = ts.strftime("%Y-%m-%d")
    time_str = ts.strftime("%H:%M")

    lines = [f"🌅 *早间简报* — {date_str} {time_str}", ""]

    if not highlights:
        lines.append("今日暂无重要动态")
        return "\n".join(lines)

    # Sort by importance
    highlights = sorted(highlights, key=lambda x: x.importance, reverse=True)
    highlights = [h for h in highlights if h.importance >= 3][:5]

    for i, item in enumerate(highlights, 1):
        # Get source label
        source_name = item.sources[0].get("name", "") if item.sources else ""
        source_label = format_source_label(item.source_type, source_name)

        # Format title with source (label before title)
        title_text = escape_md(item.title[:70])
        if source_label:
            title_text = f"{source_label} {title_text}"

        lines.append(f"*{i}.* {title_text}")

        if item.chinese_summary:
            lines.append(f"   _{item.chinese_summary}_")

        # Market impact
        if item.market_impact:
            impacts = []
            if item.market_impact.get("bullish"):
                impacts.append(f"利好: {', '.join(item.market_impact['bullish'][:3])}")
            if item.market_impact.get("bearish"):
                impacts.append(f"利空: {', '.join(item.market_impact['bearish'][:3])}")

            if impacts:
                lines.append(f"   📊 {' | '.join(impacts)}")

        lines.append("")

    # Add market summary
    if market_summary:
        lines.append("---")
        lines.append(f"📈 *隔夜市场*\n{market_summary}")

    return "\n".join(lines)


def format_evening_briefing(
    highlights: list[NewsItem], date: datetime | None = None
) -> str:
    """Format evening briefing (今日回顾)."""
    ts = date or datetime.utcnow()
    date_str = ts.strftime("%Y-%m-%d")

    lines = [f"🌙 *今日回顾* — {date_str}", ""]

    if not highlights:
        lines.append("今日暂无重要动态")
        return "\n".join(lines)

    lines.append("*今日要闻*")

    for i, item in enumerate(highlights[:5], 1):
        # Get source label
        source_name = item.sources[0].get("name", "") if item.sources else ""
        source_label = format_source_label(item.source_type, source_name)

        # Format title with source (label before title)
        title_text = escape_md(item.title[:70])
        if source_label:
            title_text = f"{source_label} {title_text}"

        lines.append(f"{i}. {title_text}")

        if item.chinese_summary:
            lines.append(f"   _{item.chinese_summary}_")

        if item.market_impact and item.market_impact.get("watch"):
            lines.append(f"   关注: {', '.join(item.market_impact['watch'][:2])}")

        lines.append("")

    return "\n".join(lines)


# ============================================================================
# Existing Formats (kept for compatibility)
# ============================================================================


def format_daily_briefing(report_content: str, generated_at: datetime) -> str:
    """Format daily briefing report for Telegram."""
    date_str = generated_at.strftime("%Y-%m-%d %H:%M UTC")
    return f"📊 *每日情报简报* — {date_str}\n\n{report_content}"


def format_market_summary(
    indices: dict | list,
    crypto: dict,
    commodities: Optional[dict | list] = None,
    timestamp: Optional[datetime] = None,
) -> str:
    """Format market summary for Telegram."""
    ts = timestamp or datetime.utcnow()
    time_str = ts.strftime("%H:%M UTC")

    lines = [f"📈 *市场摘要* — {time_str}", ""]

    # Indices
    if indices:
        lines.append("*指数*")
        items = indices if isinstance(indices, list) else indices.values()
        for data in items:
            if isinstance(data, dict):
                symbol = data.get("name", data.get("symbol", ""))
                price = data.get("price", data.get("c", 0)) or 0
                change = data.get("change_percent", data.get("dp", 0)) or 0
                lines.append(f"• {symbol}: {price:,.2f} ({format_change(change)})")
        lines.append("")

    # Crypto
    if crypto:
        lines.append("*加密货币*")
        name_map = {
            "bitcoin": "BTC",
            "ethereum": "ETH",
            "solana": "SOL",
            "binancecoin": "BNB",
            "ripple": "XRP",
            "cardano": "ADA",
            "dogecoin": "DOGE",
            "polkadot": "DOT",
            "avalanche-2": "AVAX",
            "chainlink": "LINK",
        }
        for coin_id, data in list(crypto.items())[:5]:
            symbol = name_map.get(coin_id, coin_id.upper()[:4])
            price = data.get("usd", 0) or 0
            change = data.get("usd_24h_change", 0) or 0
            lines.append(f"• {symbol}: ${price:,.2f} ({format_change(change)})")
        lines.append("")

    # Commodities
    if commodities:
        lines.append("*大宗商品*")
        items = commodities if isinstance(commodities, list) else commodities.values()
        for data in items:
            if isinstance(data, dict):
                symbol = data.get("name", data.get("symbol", ""))
                price = data.get("price", data.get("c", 0)) or 0
                change = data.get("change_percent", data.get("dp", 0)) or 0
                lines.append(f"• {symbol}: ${price:,.2f} ({format_change(change)})")

    return "\n".join(lines)


def format_correlation_alert(results: CorrelationResults) -> str:
    """Format correlation analysis results as an alert."""
    total_signals = results.total_signals
    if total_signals == 0:
        return ""

    lines = ["🚨 *关联警报*", "", f"检测到 *{total_signals}* 个信号", ""]

    if results.emerging_patterns:
        lines.append("*新兴模式*")
        for pattern in results.emerging_patterns[:5]:
            level_emoji = {"high": "🔴", "elevated": "🟠", "emerging": "🟡"}.get(
                pattern.level, "⚪"
            )

            sources = ", ".join(pattern.sources[:3])
            lines.append(
                f"{level_emoji} {pattern.name} ({pattern.category}): "
                f"{pattern.count} 次提及 [{pattern.level}]"
            )
            lines.append(f"   来源: {sources}")
        lines.append("")

    if results.momentum_signals:
        lines.append("*趋势信号*")
        for signal in results.momentum_signals[:3]:
            trend_emoji = (
                "📈"
                if signal.momentum == "rising" or signal.momentum == "surging"
                else "➡️"
            )
            lines.append(f"{trend_emoji} {signal.name}: {signal.momentum}")
        lines.append("")

    if results.predictive_signals:
        lines.append("*预测信号*")
        for pred in results.predictive_signals[:3]:
            conf_pct = int(pred.confidence * 100)
            lines.append(f"• {pred.name}: {pred.prediction} (置信度: {conf_pct}%)")
        lines.append("")

    if results.emerging_patterns:
        lines.append("*相关标题*")
        seen_titles = set()
        for pattern in results.emerging_patterns[:3]:
            for headline in pattern.headlines[:2]:
                if headline.title not in seen_titles:
                    display_title = (
                        headline.title[:60] + "..."
                        if len(headline.title) > 60
                        else headline.title
                    )
                    lines.append(f"• {escape_md(display_title)}")
                    seen_titles.add(headline.title)
                if len(seen_titles) >= 5:
                    break
            if len(seen_titles) >= 5:
                break

    return "\n".join(lines)


def format_news_burst(
    count: int,
    categories: dict[str, int],
    window_minutes: int = 30,
    top_titles: Optional[list[str]] = None,
) -> str:
    """Format news burst notification."""
    lines = [
        "📰 *新闻快报*",
        "",
        f"过去 {window_minutes} 分钟新增 *{count}* 篇文章",
        "",
    ]

    if categories:
        lines.append("*分类统计*")
        sorted_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)
        for cat, cat_count in sorted_cats[:5]:
            lines.append(f"• {cat}: {cat_count} 篇")
        lines.append("")

    if top_titles:
        lines.append("*热门标题*")
        for title in top_titles[:5]:
            display_title = title[:50] + "..." if len(title) > 50 else title
            lines.append(f"• {escape_md(display_title)}")

    return "\n".join(lines)


def format_status(
    scheduler_status: dict, service_status: dict, data_stats: Optional[dict] = None
) -> str:
    """Format system status message."""
    lines = ["🔧 *系统状态*", ""]

    running = scheduler_status.get("running", False)
    status_emoji = "✅" if running else "❌"
    lines.append(f"*调度器*: {status_emoji} {'运行中' if running else '已停止'}")
    lines.append("")

    lines.append("*服务状态*")
    service_names = {
        "rss": "RSS 抓取",
        "coingecko": "CoinGecko",
        "finnhub": "Finnhub",
        "fred": "FRED",
        "cache": "缓存",
        "circuit_breaker": "熔断器",
        "correlation": "关联分析",
        "reports": "报告生成",
    }
    for svc, enabled in service_status.items():
        name = service_names.get(svc, svc)
        emoji = "✅" if enabled else "⚪"
        lines.append(f"• {name}: {emoji}")
    lines.append("")

    if data_stats:
        lines.append("*数据统计*")
        if "articles" in data_stats:
            lines.append(f"• RSS 文章: {data_stats['articles']} 篇")
        if "crypto_prices" in data_stats:
            lines.append(f"• 加密货币: {data_stats['crypto_prices']} 个")
        if "last_fetch" in data_stats:
            lines.append(f"• 最后抓取: {data_stats['last_fetch']}")

    return "\n".join(lines)


def format_help() -> str:
    """Format help message."""
    return """📖 *XBot 命令帮助*

/news — 查看最新新闻（带分析）
/crypto — 查看加密货币动态
/market — 查看市场数据和关注股票
/watch — 管理关注列表
/feed — 管理 RSS 信息源
/status — 查看系统运行状态
/help — 显示此帮助信息

*关注列表管理*
• `/watch` — 查看当前关注
• `/watch add NVDA` — 添加股票
• `/watch add topic:AI监管` — 添加话题
• `/watch add sector:半导体` — 添加行业
• `/watch remove NVDA` — 移除

*RSS 信息源管理*
• `/feed list` — 列出所有 RSS 源
• `/feed add <url> [名称]` — 添加新源（自动验证）
• `/feed remove <名称>` — 删除源

*自动推送*
• 新闻速递: 每 5 分钟（有新消息时）
• Crypto Update: 每 5 分钟
• 市场异动: 每 5 分钟（涨跌超 5%）
• 内部交易: 每 30 分钟（大额买卖）
• 财报预告: 每 6 小时（关注股票）
• 早间简报: 每天 08:00 UTC
• 晚间回顾: 每天 20:00 UTC"""


def format_market_with_watchlist(
    indices: list[dict],
    commodities: list[dict],
    watchlist_quotes: list[dict],
    watchlist_news: list[dict] | None = None,
    timestamp: datetime | None = None,
) -> str:
    """Format market summary with watchlist stocks and news.

    Example output:
    📈 市场概览 — 21:05

    *指数*
    • S&P 500: 5,234.50 (+0.85%)
    • NASDAQ: 16,432.10 (+1.20%)

    *关注股票*
    • NVDA: $875.50 (+3.2%) 📈
    • AAPL: $182.30 (-0.5%) 📉

    *相关新闻*
    • [NVDA] Nvidia announces new AI chip...
    """
    ts = timestamp or datetime.utcnow()
    time_str = ts.strftime("%H:%M")

    lines = [f"📈 *市场概览* — {time_str}", ""]

    # Indices
    if indices:
        lines.append("*指数*")
        for data in indices[:4]:
            if isinstance(data, dict):
                name = data.get("name", data.get("symbol", ""))
                price = data.get("price", data.get("c", 0)) or 0
                change = data.get("change_percent", data.get("dp", 0)) or 0
                emoji = "📈" if change > 0 else "📉" if change < 0 else "➡️"
                lines.append(
                    f"• {name}: {price:,.2f} ({format_change(change)}) {emoji}"
                )
        lines.append("")

    # Commodities
    if commodities:
        lines.append("*大宗商品*")
        for data in commodities[:3]:
            if isinstance(data, dict):
                name = data.get("name", data.get("symbol", ""))
                price = data.get("price", data.get("c", 0)) or 0
                change = data.get("change_percent", data.get("dp", 0)) or 0
                lines.append(f"• {name}: ${price:,.2f} ({format_change(change)})")
        lines.append("")

    # Watchlist stocks
    if watchlist_quotes:
        lines.append("*关注股票*")
        for quote in watchlist_quotes:
            symbol = quote.get("symbol", "")
            price = quote.get("price", 0) or 0
            change = quote.get("change_percent", 0) or 0

            emoji = ""
            if abs(change) >= 3:
                emoji = "🔥" if change > 0 else "❄️"
            elif abs(change) >= 1:
                emoji = "📈" if change > 0 else "📉"
            else:
                emoji = "➡️"

            lines.append(f"• {symbol}: ${price:,.2f} ({format_change(change)}) {emoji}")
        lines.append("")

    # Watchlist news
    if watchlist_news:
        lines.append("*相关新闻*")
        for news in watchlist_news[:5]:
            symbol = news.get("symbol", "")
            headline = news.get("headline", "")[:60]
            url = news.get("url", "")

            # Escape headline
            safe_headline = (
                headline.replace("[", "(").replace("]", ")").replace("_", " ")
            )

            if url:
                lines.append(f"• [{symbol}] [{safe_headline}...]({url})")
            else:
                lines.append(f"• [{symbol}] {safe_headline}...")

    if not indices and not commodities and not watchlist_quotes:
        lines.append("暂无市场数据")

    return "\n".join(lines)


# ============================================================================
# Alert Formats
# ============================================================================


def format_insider_alert(transactions: list) -> str:
    """Format insider trading alert.

    Example output:
    🔔 内部交易提醒

    *NVDA* — Jensen Huang (CEO)
    📈 买入 10,000 股 @ $875.50
    💰 交易金额: $8,755,000
    📅 2024-01-15

    *AAPL* — Tim Cook (CEO)
    📉 卖出 50,000 股 @ $182.30
    💰 交易金额: $9,115,000
    """
    lines = ["🔔 *内部交易提醒*", ""]

    if not transactions:
        lines.append("暂无重要内部交易")
        return "\n".join(lines)

    for tx in transactions[:5]:
        symbol = tx.symbol
        name = tx.name[:30] if tx.name else "Unknown"
        shares = abs(tx.change)
        price = tx.transaction_price
        value = shares * price
        is_buy = tx.transaction_code == "P"
        date_str = tx.transaction_date.strftime("%Y-%m-%d")

        action_emoji = "📈" if is_buy else "📉"
        action_text = "买入" if is_buy else "卖出"

        lines.append(f"*{symbol}* — {escape_md(name)}")
        lines.append(f"{action_emoji} {action_text} {shares:,} 股 @ ${price:,.2f}")
        lines.append(f"💰 交易金额: ${value:,.0f}")
        lines.append(f"📅 {date_str}")
        lines.append("")

    # Add insight
    buys = sum(1 for tx in transactions if tx.transaction_code == "P")
    sells = len(transactions) - buys
    if buys > sells:
        lines.append("💡 _内部人士买入信号偏多，可能看好后市_")
    elif sells > buys:
        lines.append("💡 _内部人士卖出较多，注意风险_")

    return "\n".join(lines)


def format_earnings_alert(events: list) -> str:
    """Format earnings calendar alert.

    Example output:
    📊 财报预告

    *NVDA* — 2024-02-21 盘后
    预期 EPS: $4.50 | 预期营收: $20.5B

    *AAPL* — 2024-02-22 盘前
    预期 EPS: $2.10 | 预期营收: $118B
    """
    lines = ["📊 *财报预告*", ""]

    if not events:
        lines.append("近期无关注股票财报")
        return "\n".join(lines)

    for event in events[:5]:
        symbol = event.symbol
        date_str = event.report_date.strftime("%Y-%m-%d")
        hour_map = {"bmo": "盘前", "amc": "盘后", "": ""}
        hour_text = hour_map.get(event.hour, event.hour)

        lines.append(f"*{symbol}* — {date_str} {hour_text}")

        parts = []
        if event.eps_estimate:
            parts.append(f"预期 EPS: ${event.eps_estimate:.2f}")
        if event.revenue_estimate:
            rev_b = event.revenue_estimate / 1e9
            parts.append(f"预期营收: ${rev_b:.1f}B")

        if parts:
            lines.append(f"📈 {' | '.join(parts)}")
        lines.append("")

    lines.append("💡 _财报发布前后波动可能加大，注意风险管理_")

    return "\n".join(lines)


def format_market_anomaly_alert(anomalies: list[dict]) -> str:
    """Format market anomaly alert.

    Example output:
    ⚠️ 市场异动

    🔥 *NVDA* 大涨 +8.5%
    当前价格: $945.00 (前值: $871.00)

    ❄️ *TSLA* 大跌 -6.2%
    当前价格: $175.50 (前值: $187.00)
    """
    lines = ["⚠️ *市场异动*", ""]

    if not anomalies:
        lines.append("暂无异常波动")
        return "\n".join(lines)

    for item in anomalies[:5]:
        symbol = item["symbol"]
        price = item["price"]
        change = item["change_percent"]
        anomaly_type = item["anomaly_type"]
        prev_price = item.get("prev_price")

        # Determine emoji and description
        if "spike" in anomaly_type:
            emoji = "🔥"
            desc = "大涨" if "daily" in anomaly_type else "急涨"
        else:
            emoji = "❄️"
            desc = "大跌" if "daily" in anomaly_type else "急跌"

        lines.append(f"{emoji} *{symbol}* {desc} {format_change(change)}")
        if prev_price:
            lines.append(f"当前: ${price:,.2f} (前值: ${prev_price:,.2f})")
        else:
            lines.append(f"当前: ${price:,.2f}")
        lines.append("")

    # Add context
    spikes = sum(1 for a in anomalies if "spike" in a["anomaly_type"])
    drops = len(anomalies) - spikes
    if spikes > drops:
        lines.append("💡 _多只股票上涨，市场情绪偏乐观_")
    elif drops > spikes:
        lines.append("💡 _多只股票下跌，注意市场风险_")
    else:
        lines.append("💡 _市场分化明显，建议观望_")

    return "\n".join(lines)
