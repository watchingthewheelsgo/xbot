"""
AI工具模块
提供各种工具供AI Agent使用
"""

from server.ai.tools.base import BaseTool
from server.ai.tools.websearch import WebFetcher
from server.ai.tools.chat_tools import (
    ChatToolRegistry,
    GetNewsTool,
    GetCryptoTool,
    GetMarketTool,
    GetWatchlistTool,
    AddWatchTool,
    RemoveWatchTool,
    GetFeedListTool,
    ToolResult,
    ToolDefinition,
    get_system_prompt_with_tools,
)

__all__ = [
    "BaseTool",
    "WebFetcher",
    "ChatToolRegistry",
    "GetNewsTool",
    "GetCryptoTool",
    "GetMarketTool",
    "GetWatchlistTool",
    "AddWatchTool",
    "RemoveWatchTool",
    "GetFeedListTool",
    "ToolResult",
    "ToolDefinition",
    "get_system_prompt_with_tools",
]
