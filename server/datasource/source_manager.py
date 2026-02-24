"""
Source Manager - 统一管理所有消息源及其优先级
"""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, HttpUrl

from loguru import logger


class FeedConfig(BaseModel):
    """单个RSS源配置"""

    name: str
    url: HttpUrl
    priority: int = Field(default=50, ge=0, le=100)
    enabled: bool = True
    description: str = ""


class CategoryConfig(BaseModel):
    """RSS分类配置"""

    name: str
    priority: int = Field(default=50, ge=0, le=100)
    enabled: bool = True
    description: str = ""
    feeds: list[FeedConfig] = Field(default_factory=list)
    min_upvotes: int | None = None  # Reddit特定配置


class SourceConfig(BaseModel):
    """整体源配置"""

    version: str = "1.0"
    sources: dict[str, Any] = Field(default_factory=dict)


class SourceManager:
    """统一的消息源管理器"""

    def __init__(self, config_path: str | None = None):
        if config_path is None:
            config_path = "server/datasource/sources.yaml"
        self.config_path = Path(config_path)
        self.config: SourceConfig = SourceConfig()
        self._load_config()

        # 构建源优先级映射缓存
        self._feed_priority_map: dict[str, int] = {}
        self._build_priority_map()

    def _load_config(self) -> None:
        """加载YAML配置，支持回退到config.json"""
        try:
            import yaml

            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    self.config = SourceConfig(**data)
                logger.info(f"Loaded source config from {self.config_path}")
                return

            # 回退到旧的config.json
            json_path = Path("server/datasource/rss/config.json")
            if json_path.exists():
                logger.info(f"YAML config not found, using legacy {json_path}")
                self._migrate_from_json(json_path)
            else:
                logger.warning(
                    f"Source config not found: {self.config_path}, using defaults"
                )

        except ImportError:
            logger.error("PyYAML not installed, using default config")
        except Exception as e:
            logger.error(f"Failed to load source config: {e}")

    def _migrate_from_json(self, json_path: Path) -> None:
        """从旧的config.json迁移配置"""
        try:
            with open(json_path) as f:
                data = json.load(f)

            rss_list = data.get("rss", [])
            rss_categories = []

            # 按category分组
            by_category: dict[str, list[dict]] = {}
            for rss in rss_list:
                cat = rss.get("category", "other")
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append(
                    {
                        "name": rss["name"],
                        "url": rss["url"],
                        "priority": 50,  # 默认优先级
                        "enabled": True,
                        "description": rss.get("description", ""),
                    }
                )

            # 分类优先级映射
            category_priority = {
                "finance": 85,
                "tech": 65,
                "world": 55,
                "ai": 75,
                "intel": 70,
                "cyber": 72,
                "crypto": 50,
                "reddit": 40,
                "gov": 60,
            }

            for cat, feeds in by_category.items():
                rss_categories.append(
                    {
                        "name": cat,
                        "priority": category_priority.get(cat, 50),
                        "enabled": True,
                        "description": f"{cat.capitalize()} feeds",
                        "feeds": feeds,
                    }
                )

            self.config = SourceConfig(
                version="1.0",
                sources={
                    "finnhub": {
                        "priority": 100,
                        "enabled": True,
                        "description": "Finnhub market news",
                    },
                    "rss_categories": rss_categories,
                },
            )
            logger.info(f"Migrated {len(rss_list)} feeds from JSON config")

        except Exception as e:
            logger.error(f"Failed to migrate from JSON config: {e}")

    def _build_priority_map(self) -> None:
        """构建源优先级映射缓存"""
        self._feed_priority_map.clear()

        rss_categories = self.config.sources.get("rss_categories", [])
        for cat_dict in rss_categories:
            category = CategoryConfig(**cat_dict)
            if not category.enabled:
                continue

            for feed in category.feeds:
                if feed.enabled:
                    # 使用feed的优先级，如果没有则使用分类优先级
                    priority = (
                        feed.priority if feed.priority != 50 else category.priority
                    )
                    self._feed_priority_map[feed.name] = priority

        logger.debug(f"Built priority map with {len(self._feed_priority_map)} feeds")

    def get_feed_priority(self, feed_name: str) -> int:
        """获取指定源的优先级"""
        return self._feed_priority_map.get(feed_name, 50)

    def get_enabled_feeds(self) -> list[FeedConfig]:
        """获取所有启用的RSS源，按优先级排序"""
        all_feeds: list[FeedConfig] = []

        rss_categories = self.config.sources.get("rss_categories", [])
        for cat_dict in rss_categories:
            if not cat_dict.get("enabled", True):
                continue

            category = CategoryConfig(**cat_dict)
            for feed in category.feeds:
                if feed.enabled:
                    # 继承分类的优先级（如果feed使用默认值）
                    feed_with_priority = FeedConfig(**feed.model_dump())
                    if feed_with_priority.priority == 50:
                        feed_with_priority.priority = category.priority
                    all_feeds.append(feed_with_priority)

        # 按优先级降序排序
        all_feeds.sort(key=lambda x: x.priority, reverse=True)
        return all_feeds

    def get_finnhub_priority(self) -> int:
        """获取Finnhub优先级"""
        return self.config.sources.get("finnhub", {}).get("priority", 100)

    def is_finnhub_enabled(self) -> bool:
        """检查Finnhub是否启用"""
        return self.config.sources.get("finnhub", {}).get("enabled", False)

    def get_category_min_upvotes(self, category_name: str) -> int | None:
        """获取Reddit分类的最小点赞数要求"""
        rss_categories = self.config.sources.get("rss_categories", [])
        for cat_dict in rss_categories:
            if cat_dict.get("name") == category_name:
                return cat_dict.get("min_upvotes")
        return None

    def reload(self) -> None:
        """重新加载配置"""
        logger.info("Reloading source configuration...")
        self._load_config()
        self._build_priority_map()
        logger.info("Source configuration reloaded")

    def get_status(self) -> dict[str, Any]:
        """获取源管理器状态"""
        enabled_feeds = self.get_enabled_feeds()
        return {
            "config_path": str(self.config_path),
            "config_version": self.config.version,
            "finnhub_enabled": self.is_finnhub_enabled(),
            "finnhub_priority": self.get_finnhub_priority(),
            "total_feeds": len(self._feed_priority_map),
            "enabled_feeds": len(enabled_feeds),
            "feeds_by_priority": [
                {"name": f.name, "priority": f.priority} for f in enabled_feeds[:10]
            ],
        }
