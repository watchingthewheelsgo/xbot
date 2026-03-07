"""
渠道工厂注册表
支持动态发现和管理消息渠道
"""

from typing import Callable, Dict, Optional, Type
from loguru import logger

from .base import Channel


class ChannelRegistry:
    """
    渠道工厂注册表

    使用模式：
    1. 每个渠道模块调用 register_channel(name, factory)
    2. 主程序通过 create_channel(name) 获取渠道实例
    3. 自动发现所有已注册的渠道
    """

    _factories: Dict[str, Callable[..., Channel]] = {}
    _instances: Dict[str, Channel] = {}

    @classmethod
    def register(
        cls,
        name: str,
        factory: Callable[..., Channel],
        channel_class: Optional[Type[Channel]] = None,
    ) -> None:
        """
        注册渠道工厂

        Args:
            name: 渠道名称（如 'telegram'、'feishu'）
            factory: 创建渠道实例的工厂函数
            channel_class: 渠道类（用于类型检查，可选）
        """
        if name in cls._factories:
            logger.warning(f"Channel '{name}' already registered, overwriting")

        cls._factories[name] = factory
        logger.debug(f"Registered channel factory: {name}")

        # 存储类信息用于类型检查
        if channel_class:
            cls._factories[f"{name}_class"] = channel_class

    @classmethod
    def create_channel(cls, name: str, **kwargs) -> Optional[Channel]:
        """
        创建渠道实例

        Args:
            name: 渠道名称
            **kwargs: 传递给工厂函数的参数

        Returns:
            渠道实例，如果渠道未注册则返回 None
        """
        factory = cls._factories.get(name)
        if factory is None:
            logger.error(f"Channel '{name}' not found in registry")
            return None

        try:
            instance = factory(**kwargs)
            cls._instances[name] = instance
            logger.debug(f"Created channel instance: {name}")
            return instance
        except Exception as e:
            logger.error(f"Failed to create channel '{name}': {e}")
            return None

    @classmethod
    def get_channel(cls, name: str) -> Optional[Channel]:
        """
        获取已创建的渠道实例

        Args:
            name: 渠道名称

        Returns:
            渠道实例，如果未创建则返回 None
        """
        return cls._instances.get(name)

    @classmethod
    def get_all_channels(cls) -> Dict[str, Channel]:
        """
        获取所有已创建的渠道实例

        Returns:
            渠道名称到实例的映射
        """
        return cls._instances.copy()

    @classmethod
    def get_registered_names(cls) -> list[str]:
        """
        获取所有已注册的渠道名称

        Returns:
            已注册的渠道名称列表
        """
        return list(cls._factories.keys())

    @classmethod
    def get_channel_class(cls, name: str) -> Optional[Callable[..., Channel]]:
        """
        获取渠道类（用于类型检查）

        Args:
            name: 渠道名称

        Returns:
            渠道类，如果未注册则返回 None
        """
        class_key = f"{name}_class"
        return cls._factories.get(class_key)

    @classmethod
    def clear_instances(cls) -> None:
        """清除所有渠道实例（用于测试或重新初始化）"""
        for instance in cls._instances.values():
            if hasattr(instance, "shutdown"):
                import asyncio

                asyncio.create_task(instance.shutdown())
        cls._instances.clear()
        logger.debug("Cleared all channel instances")


def create_channel_adapter(
    channel_class: Type[Channel],
    name: str,
) -> Callable[..., Channel]:
    """
    将现有的渠道类适配为工厂函数

    Args:
        channel_class: 渠道类
        name: 渠道名称

    Returns:
        工厂函数
    """

    def factory(**kwargs) -> Channel:
        return channel_class(**kwargs)

    return factory
