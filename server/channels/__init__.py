"""
统一消息渠道模块
提供渠道抽象接口和工厂注册系统
"""

from .base import Channel
from .registry import ChannelRegistry

__all__ = ["Channel", "ChannelRegistry"]
