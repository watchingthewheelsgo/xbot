"""
Chat Tools - 供对话模式使用的工具定义

这些工具允许 LLM 在对话中访问 XBot 的各种数据源：
- 新闻 (news)
- 加密货币 (crypto)
- 市场数据 (market)
- 关注列表 (watchlist)
- RSS 源 (feed)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger


# ============================================================================
# Tool Result Types
# ============================================================================


@dataclass
class ToolResult:
    """工具执行结果"""

    success: bool
    content: str
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class ToolDefinition:
    """工具定义（OpenAI 函数格式）"""

    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Any  # 工具处理函数


# ============================================================================
# Base Tool Handler
# ============================================================================


class ToolHandler(ABC):
    """工具处理基类"""

    def __init__(self, scheduler=None, news_processor=None):
        self.scheduler = scheduler
        self.news_processor = news_processor

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """执行工具"""
        pass

    @abstractmethod
    def get_definition(self) -> Dict[str, Any]:
        """获取工具定义（OpenAI 格式）"""
        pass


# ============================================================================
# News Tool
# ============================================================================


class GetNewsTool(ToolHandler):
    """获取最新新闻"""

    def get_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "get_news",
                "description": "获取最新新闻，包括标题、摘要、来源和发布时间",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "hours": {
                            "type": "number",
                            "description": "获取多少小时内的新闻，默认 2 小时",
                            "default": 2,
                            "minimum": 0.25,
                            "maximum": 24,
                        },
                        "max_items": {
                            "type": "number",
                            "description": "最多返回多少条新闻，默认 10 条",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 20,
                        },
                        "topic": {
                            "type": "string",
                            "description": "按话题筛选新闻，如 'AI', 'crypto', 'stock' 等",
                        },
                    },
                },
            },
        }

    async def execute(
        self, hours: float = 2, max_items: int = 10, topic: Optional[str] = None
    ) -> ToolResult:
        """执行获取新闻"""
        try:
            if not self.news_processor:
                return ToolResult(success=False, content="新闻处理器未初始化")

            items = await self.news_processor.get_and_process_news(
                hours=hours,
                max_items=max_items,
                filter_pushed=False,
                push_type="command",
                use_cache=True,
                platform="chat",
            )

            if not items:
                return ToolResult(
                    success=True, content=f"最近 {hours} 小时内没有新新闻"
                )

            # 格式化新闻
            lines = [f"📰 *最新新闻* ({hours} 小时内)\n"]
            for i, item in enumerate(items, 1):
                # 重要性标记
                importance = ""
                if item.importance >= 4:
                    importance = "🔴"
                elif item.importance == 3:
                    importance = "🟠"
                elif item.importance == 2:
                    importance = "🟡"

                # 时间
                time_str = (
                    item.published.strftime("%H:%M") if item.published else "未知"
                )

                # 摘要或标题
                summary = item.chinese_summary or item.title or "无标题"
                if len(summary) > 100:
                    summary = summary[:100] + "..."

                lines.append(f"{i}. {importance} {summary}")
                lines.append(f"   🕒 {time_str} | {item.source_type}")

                if item.url:
                    lines.append(f"   🔗 {item.url}")

                # 市场影响分析
                if item.market_impact:
                    impact_lines = []
                    if item.market_impact.beneficiary_stocks:
                        impact_lines.append(
                            f"利好: {', '.join(item.market_impact.beneficiary_stocks)}"
                        )
                    if item.market_impact.affected_stocks:
                        impact_lines.append(
                            f"利空: {', '.join(item.market_impact.affected_stocks)}"
                        )
                    if item.market_impact.related_sectors:
                        impact_lines.append(
                            f"关注: {', '.join(item.market_impact.related_sectors)}"
                        )
                    if impact_lines:
                        lines.append(f"   📊 {' | '.join(impact_lines)}")

                lines.append("")

            return ToolResult(
                success=True,
                content="\n".join(lines),
                metadata={"count": len(items)},
            )

        except Exception as e:
            logger.error(f"GetNewsTool failed: {e}")
            return ToolResult(success=False, content=f"获取新闻失败: {str(e)}")


# ============================================================================
# Crypto Tool
# ============================================================================


class GetCryptoTool(ToolHandler):
    """获取加密货币价格"""

    def get_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "get_crypto",
                "description": "获取加密货币的实时价格和涨跌情况",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symbols": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "加密货币符号列表，如 ['BTC', 'ETH']",
                        },
                    },
                },
            },
        }

    async def execute(self, symbols: Optional[List[str]] = None) -> ToolResult:
        """执行获取加密货币价格"""
        try:
            if not self.scheduler:
                return ToolResult(success=False, content="调度器未初始化")

            crypto_data = self.scheduler.latest_crypto_data
            if not crypto_data:
                return ToolResult(success=False, content="暂无加密货币数据")

            # 获取历史数据用于计算涨跌
            previous_data = self.scheduler._previous_crypto_data or []
            prev_dict = {p.get("symbol"): p for p in previous_data}

            lines = ["💰 *加密货币价格*\n"]

            for crypto in crypto_data:
                symbol = crypto.get("symbol", "")
                price = crypto.get("price_usd", 0)
                change_24h = crypto.get("change_24h_percent", 0)

                # 如果有历史数据，计算实时涨跌
                if symbol in prev_dict:
                    prev_price = prev_dict[symbol].get("price_usd", 0)
                    if prev_price > 0:
                        real_change = ((price - prev_price) / prev_price) * 100
                        change_str = f" ({real_change:+.2f}%)"
                        emoji = (
                            "📈"
                            if real_change > 0
                            else "📉"
                            if real_change < 0
                            else "➡️"
                        )
                    else:
                        change_str = ""
                        emoji = ""
                else:
                    change_str = f" ({change_24h:+.2f}%)"
                    emoji = "📈" if change_24h > 0 else "📉" if change_24h < 0 else "➡️"

                name = crypto.get("name", symbol)
                lines.append(f"{emoji} *{name}* (${symbol})")
                lines.append(f"   💵 ${price:,.2f}{change_str}")
                lines.append("")

            return ToolResult(success=True, content="\n".join(lines))

        except Exception as e:
            logger.error(f"GetCryptoTool failed: {e}")
            return ToolResult(success=False, content=f"获取加密货币价格失败: {str(e)}")


# ============================================================================
# Market Tool
# ============================================================================


class GetMarketTool(ToolHandler):
    """获取市场数据"""

    def get_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "get_market",
                "description": "获取股市指数、大宗商品价格等市场数据",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        }

    async def execute(self) -> ToolResult:
        """执行获取市场数据"""
        try:
            if not self.scheduler:
                return ToolResult(success=False, content="调度器未初始化")

            market_data = self.scheduler.latest_market_data
            indices = market_data.get("indices", [])
            commodities = market_data.get("commodities", [])

            lines = ["📊 *市场数据*\n"]

            if indices:
                lines.append("*股指*")
                for idx in indices:
                    symbol = idx.get("symbol", "")
                    price = idx.get("price", 0)
                    change = idx.get("change_percent", 0)
                    emoji = "📈" if change > 0 else "📉" if change < 0 else "➡️"
                    lines.append(f"  {emoji} {symbol}: {price:.2f} ({change:+.2f}%)")
                lines.append("")

            if commodities:
                lines.append("*大宗商品*")
                for item in commodities:
                    symbol = item.get("symbol", "")
                    price = item.get("price", 0)
                    change = item.get("change_percent", 0)
                    emoji = "📈" if change > 0 else "📉" if change < 0 else "➡️"
                    lines.append(f"  {emoji} {symbol}: {price:.2f} ({change:+.2f}%)")
                lines.append("")

            if not indices and not commodities:
                lines.append("暂无市场数据")

            return ToolResult(success=True, content="\n".join(lines))

        except Exception as e:
            logger.error(f"GetMarketTool failed: {e}")
            return ToolResult(success=False, content=f"获取市场数据失败: {str(e)}")


# ============================================================================
# Watchlist Tools
# ============================================================================


class GetWatchlistTool(ToolHandler):
    """获取关注列表"""

    def get_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "get_watchlist",
                "description": "获取当前的关注列表，包括股票、话题、行业等",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        }

    async def execute(self) -> ToolResult:
        """执行获取关注列表"""
        try:
            from server.datastore.engine import get_session_factory
            from server.services.watchlist import list_watches

            session_factory = get_session_factory()
            items = await list_watches(session_factory)

            if not items:
                return ToolResult(success=True, content="📋 关注列表为空")

            lines = ["📋 *当前关注列表*\n"]
            type_labels = {
                "stock": "📈 股票",
                "topic": "🏷️ 话题",
                "sector": "🏭 行业",
                "region": "🌍 地区",
            }
            grouped: Dict[str, List[str]] = {}
            for item in items:
                grouped.setdefault(item["watch_type"], []).append(item["symbol"])

            for wt, symbols in grouped.items():
                label = type_labels.get(wt, wt)
                lines.append(f"{label}: {', '.join(symbols)}")

            return ToolResult(success=True, content="\n".join(lines))

        except Exception as e:
            logger.error(f"GetWatchlistTool failed: {e}")
            return ToolResult(success=False, content=f"获取关注列表失败: {str(e)}")


class AddWatchTool(ToolHandler):
    """添加关注项"""

    def get_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "add_watch",
                "description": "添加一个项目到关注列表，支持股票、话题、行业、地区",
                "parameters": {
                    "type": "object",
                    "required": ["item"],
                    "properties": {
                        "item": {
                            "type": "string",
                            "description": "要添加的项目，股票代码如 'NVDA'，话题如 'AI监管'",
                        },
                        "watch_type": {
                            "type": "string",
                            "description": "关注类型: stock (股票), topic (话题), sector (行业), region (地区)",
                            "enum": ["stock", "topic", "sector", "region"],
                        },
                    },
                },
            },
        }

    async def execute(self, item: str, watch_type: str = "stock") -> ToolResult:
        """执行添加关注项"""
        try:
            from server.datastore.engine import get_session_factory
            from server.services.watchlist import add_watch

            session_factory = get_session_factory()

            # 自动检测 watch_type
            for prefix in ("topic:", "sector:", "region:"):
                if item.lower().startswith(prefix):
                    watch_type = prefix[:-1]
                    item = item[len(prefix) :]
                    break

            if watch_type == "stock":
                item = item.upper()

            ok = await add_watch(session_factory, item, watch_type=watch_type)

            if ok:
                return ToolResult(
                    success=True, content=f"✅ 已添加 {item} ({watch_type}) 到关注列表"
                )
            else:
                return ToolResult(
                    success=True, content=f"ℹ️ {item} ({watch_type}) 已在关注列表中"
                )

        except Exception as e:
            logger.error(f"AddWatchTool failed: {e}")
            return ToolResult(success=False, content=f"添加关注项失败: {str(e)}")


class RemoveWatchTool(ToolHandler):
    """移除关注项"""

    def get_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "remove_watch",
                "description": "从关注列表中移除一个项目",
                "parameters": {
                    "type": "object",
                    "required": ["item"],
                    "properties": {
                        "item": {
                            "type": "string",
                            "description": "要移除的项目名称",
                        },
                    },
                },
            },
        }

    async def execute(self, item: str) -> ToolResult:
        """执行移除关注项"""
        try:
            from server.datastore.engine import get_session_factory
            from server.services.watchlist import remove_watch

            session_factory = get_session_factory()

            # 统一处理股票代码
            if not any(
                item.lower().startswith(p) for p in ("topic:", "sector:", "region:")
            ):
                item = item.upper()

            ok = await remove_watch(session_factory, item)

            if ok:
                return ToolResult(success=True, content=f"✅ 已从关注列表移除 {item}")
            else:
                return ToolResult(success=True, content=f"ℹ️ {item} 不在关注列表中")

        except Exception as e:
            logger.error(f"RemoveWatchTool failed: {e}")
            return ToolResult(success=False, content=f"移除关注项失败: {str(e)}")


# ============================================================================
# RSS Tools
# ============================================================================


class GetFeedListTool(ToolHandler):
    """获取 RSS 源列表"""

    def get_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "get_feeds",
                "description": "获取当前配置的 RSS 源列表",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        }

    async def execute(self) -> ToolResult:
        """执行获取 RSS 源列表"""
        try:
            if not self.scheduler or not self.scheduler._rss_fetcher:
                return ToolResult(success=False, content="RSS 模块未初始化")

            feeds = self.scheduler._rss_fetcher.feeds
            if not feeds:
                return ToolResult(success=True, content="📡 RSS 源列表为空")

            lines = [f"📡 *RSS 源列表* ({len(feeds)} 个)\n"]
            by_cat: Dict[str, List[str]] = {}
            for f in feeds:
                by_cat.setdefault(f.category or "other", []).append(f.name)

            for cat, names in sorted(by_cat.items()):
                lines.append(f"*{cat}*: {', '.join(names)}")

            return ToolResult(success=True, content="\n".join(lines))

        except Exception as e:
            logger.error(f"GetFeedListTool failed: {e}")
            return ToolResult(success=False, content=f"获取 RSS 源列表失败: {str(e)}")


# ============================================================================
# Tool Registry
# ============================================================================


class ChatToolRegistry:
    """Chat 工具注册表"""

    def __init__(self, scheduler=None, news_processor=None):
        self.scheduler = scheduler
        self.news_processor = news_processor
        self._tools: Dict[str, ToolHandler] = {}
        self._definitions: List[Dict[str, Any]] = []

        self._init_tools()

    def _init_tools(self):
        """初始化所有工具"""
        self.register(GetNewsTool(self.scheduler, self.news_processor))
        self.register(GetCryptoTool(self.scheduler))
        self.register(GetMarketTool(self.scheduler))
        self.register(GetWatchlistTool(self.scheduler))
        self.register(AddWatchTool(self.scheduler))
        self.register(RemoveWatchTool(self.scheduler))
        self.register(GetFeedListTool(self.scheduler))

        logger.info(f"ChatToolRegistry initialized with {len(self._tools)} tools")

    def register(self, tool: ToolHandler):
        """注册工具"""
        definition = tool.get_definition()
        tool_name = definition["function"]["name"]

        self._tools[tool_name] = tool
        self._definitions.append(definition)

        logger.debug(f"Registered tool: {tool_name}")

    async def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> ToolResult:
        """执行工具"""
        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult(success=False, content=f"未知工具: {tool_name}")

        logger.info(f"Executing tool: {tool_name} with arguments: {arguments}")

        try:
            return await tool.execute(**arguments)
        except Exception as e:
            logger.error(f"Tool execution failed for {tool_name}: {e}")
            return ToolResult(success=False, content=f"工具执行失败: {str(e)}")

    @property
    def definitions(self) -> List[Dict[str, Any]]:
        """获取所有工具定义"""
        return self._definitions.copy()

    @property
    def tool_names(self) -> List[str]:
        """获取所有工具名称"""
        return list(self._tools.keys())


# ============================================================================
# System Prompt with Tools
# ============================================================================


def get_system_prompt_with_tools() -> str:
    """获取包含工具说明的系统提示词"""
    return """你是 XBot，一个专业的金融信息聚合和分析助手。

你的特点：
- 专业、准确、乐于助人
- 可以回答金融、市场、经济相关的问题
- 支持多轮对话，会记住上下文
- 对于不确定的信息会诚实说明
- 可以调用工具获取最新数据

可用工具：
- get_news: 获取最新新闻
- get_crypto: 获取加密货币价格
- get_market: 获取市场数据（股指、大宗商品）
- get_watchlist: 查看关注列表
- add_watch: 添加关注项（股票、话题、行业等）
- remove_watch: 移除关注项
- get_feeds: 查看 RSS 源列表

使用建议：
- 当用户询问最新消息时，使用 get_news 工具
- 当用户询问加密货币时，使用 get_crypto 工具
- 当用户询问股市或大宗商品时，使用 get_market 工具
- 当用户想要管理关注列表时，使用 watchlist 相关工具
- 工具参数要准确，不要编造值

回复时请：
- 使用简洁清晰的语言
- 适当使用表情符号增加亲和力
- 对重要信息进行强调
- 工具执行结果要简洁呈现给用户
"""
