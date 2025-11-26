"""
RSS数据源获取模块
负责从配置的RSS源获取文章、解析内容并存储到数据库
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import feedparser
import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from loguru import logger
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import server.datastore.engine as db_engine
from server.datastore.models import RSSArticleDB, RSSFeedDB
from server.settings import global_settings
from server.utils import safe_func_wrapper


class RSSFeedConfig(BaseModel):
    """RSS源配置模型"""

    name: str
    description: str = ""
    category: str = ""
    url: HttpUrl
    source: str = ""


class RSSArticle(BaseModel):
    """RSS文章模型"""

    feed_name: str
    title: str
    link: str
    published: datetime
    summary: str = ""
    content: str | None = None
    author: str | None = None
    guid: str


class RSSRepository:
    """RSS数据库操作层"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_feed_by_name(self, name: str) -> RSSFeedDB | None:
        """根据名称获取RSS源"""
        result = await self.session.execute(
            select(RSSFeedDB).where(RSSFeedDB.name == name)
        )
        return result.scalar_one_or_none()

    async def create_or_update_feed(self, feed_config: RSSFeedConfig) -> RSSFeedDB:
        """创建或更新RSS源"""
        feed_db = await self.get_feed_by_name(feed_config.name)

        if feed_db:
            # 更新现有记录
            feed_db.description = feed_config.description
            feed_db.category = feed_config.category
            feed_db.url = str(feed_config.url)
            feed_db.source = feed_config.source
            feed_db.updated_at = datetime.now()
        else:
            # 创建新记录
            feed_db = RSSFeedDB(
                name=feed_config.name,
                description=feed_config.description,
                category=feed_config.category,
                url=str(feed_config.url),
                source=feed_config.source,
            )
            self.session.add(feed_db)

        await self.session.flush()
        return feed_db

    async def update_feed_fetch_time(self, feed_name: str) -> None:
        """更新RSS源的最后抓取时间"""
        feed_db = await self.get_feed_by_name(feed_name)
        if feed_db:
            feed_db.last_fetched = datetime.now()
            feed_db.updated_at = datetime.now()
            await self.session.flush()

    async def get_last_fetch_time(self, feed_name: str) -> datetime | None:
        """获取RSS源的最后抓取时间"""
        feed_db = await self.get_feed_by_name(feed_name)
        return feed_db.last_fetched if feed_db else None

    async def article_exists(self, guid: str) -> bool:
        """检查文章是否已存在（去重）"""
        result = await self.session.execute(
            select(RSSArticleDB).where(RSSArticleDB.guid == guid)
        )
        return result.scalar_one_or_none() is not None

    async def save_articles(self, articles: list[RSSArticle]) -> int:
        """批量保存文章（自动去重）"""
        saved_count = 0

        for article in articles:
            # 检查是否已存在
            if await self.article_exists(article.guid):
                logger.debug(f"Article already exists: {article.title[:50]}")
                continue

            # 创建新文章记录
            article_db = RSSArticleDB(
                feed_name=article.feed_name,
                guid=article.guid,
                title=article.title,
                link=article.link,
                published=article.published,
                summary=article.summary,
                content=article.content,
                author=article.author,
            )
            self.session.add(article_db)
            saved_count += 1

        if saved_count > 0:
            await self.session.flush()

        return saved_count


class RSSFetcher:
    """RSS获取器"""

    def __init__(self, config_path: str | Path | None = None):
        if config_path is None:
            config_path = global_settings.rss_config_path
        self.config_path = Path(config_path)
        self.feeds: list[RSSFeedConfig] = []
        self._load_config()

    def _load_config(self) -> None:
        """加载RSS配置"""
        try:
            if not self.config_path.exists():
                logger.warning(f"Config file not found: {self.config_path}")
                self.feeds = []
                return

            with open(self.config_path) as f:
                data = json.load(f)
                rss_list = data.get("rss", [])

                # 过滤掉空配置
                valid_rss = [
                    rss for rss in rss_list if rss.get("name") and rss.get("url")
                ]
                self.feeds = [RSSFeedConfig(**feed) for feed in valid_rss]

            logger.info(f"Loaded {len(self.feeds)} RSS feeds from config")
        except Exception as e:
            logger.error(f"Failed to load RSS config: {e}")
            self.feeds = []

    @staticmethod
    def clean_html_content(html: str) -> str:
        """清洗HTML内容，提取纯文本"""
        if not html:
            return ""

        try:
            soup = BeautifulSoup(html, "html.parser")

            # 移除script和style标签
            for script in soup(["script", "style"]):
                script.decompose()

            # 获取纯文本
            text = soup.get_text(separator="\n")

            # 清理多余空白
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = "\n".join(chunk for chunk in chunks if chunk)

            return text
        except Exception as e:
            logger.warning(f"Failed to clean HTML content: {e}")
            return html

    @staticmethod
    def parse_date(date_str: str | None) -> datetime:
        """解析日期字符串，确保返回naive datetime（无时区）"""
        if not date_str:
            return datetime.now()

        try:
            # 使用dateutil进行健壮的日期解析
            dt = date_parser.parse(date_str)
            # 如果有时区信息，转换为UTC并移除时区信息
            if dt.tzinfo is not None:
                dt = dt.astimezone().replace(tzinfo=None)
            return dt
        except Exception:
            # 如果解析失败，使用当前时间
            return datetime.now()

    def _parse_entries(self, entries: list[Any], feed_name: str) -> list[RSSArticle]:
        """解析feed条目为文章模型"""
        articles = []

        for entry in entries:
            try:
                # 提取内容
                content = None
                if hasattr(entry, "content") and entry.content:
                    content = entry.content[0].get("value", "")
                elif hasattr(entry, "description"):
                    content = entry.description

                # 清洗HTML内容
                if content:
                    content = self.clean_html_content(content)

                # 提取摘要
                summary = ""
                if hasattr(entry, "summary"):
                    summary = self.clean_html_content(entry.summary)

                # 解析发布日期
                published_str = getattr(entry, "published", None) or getattr(
                    entry, "updated", None
                )
                published = self.parse_date(published_str)

                # 生成唯一标识符
                guid = getattr(entry, "id", None) or getattr(entry, "link", "")
                if not guid:
                    # 如果没有ID，使用标题+链接的组合
                    guid = f"{entry.get('title', '')}_{entry.get('link', '')}"

                article = RSSArticle(
                    feed_name=feed_name,
                    title=entry.get("title", "Untitled"),
                    link=entry.get("link", ""),
                    published=published,
                    summary=summary[:1000] if summary else "",  # 限制长度
                    content=content,
                    author=entry.get("author", None),
                    guid=guid[:500],  # 限制GUID长度
                )
                articles.append(article)

            except Exception as e:
                logger.warning(f"Failed to parse entry: {e}")
                continue

        return articles

    @safe_func_wrapper
    async def fetch_feed_with_retry(
        self, feed: RSSFeedConfig, session: AsyncSession
    ) -> list[RSSArticle]:
        """带重试机制的RSS获取"""
        max_retries = global_settings.rss_max_retries
        timeout = global_settings.rss_request_timeout

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    logger.info(
                        f"Fetching RSS feed: {feed.name} (attempt {attempt + 1}/{max_retries})"
                    )

                    response = await client.get(str(feed.url))
                    response.raise_for_status()

                    # 解析feed
                    parsed = feedparser.parse(response.content)

                    # 检查是否解析成功
                    if parsed.bozo:
                        logger.warning(
                            f"Feed parsing warning for {feed.name}: {parsed.bozo_exception}"
                        )

                    articles = self._parse_entries(parsed.entries, feed.name)

                    # 过滤新文章（增量更新）
                    articles = await self._filter_new_articles(
                        articles, feed.name, session
                    )

                    logger.info(
                        f"Successfully fetched {len(articles)} new articles from {feed.name}"
                    )
                    return articles

            except httpx.TimeoutException:
                logger.warning(
                    f"Timeout fetching {feed.name} (attempt {attempt + 1}/{max_retries})"
                )
                if attempt < max_retries - 1:
                    # 指数退避
                    await asyncio.sleep(2**attempt)
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"HTTP error fetching {feed.name}: {e.response.status_code}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(2**attempt)
            except Exception as e:
                logger.error(f"Error fetching {feed.name}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2**attempt)

        # 所有重试都失败了
        logger.error(f"Failed to fetch {feed.name} after {max_retries} attempts")
        return []

    async def _filter_new_articles(
        self, articles: list[RSSArticle], feed_name: str, session: AsyncSession
    ) -> list[RSSArticle]:
        """过滤新文章（增量更新）"""
        repo = RSSRepository(session)
        last_fetch = await repo.get_last_fetch_time(feed_name)

        if last_fetch is None:
            # 首次抓取，返回所有文章
            return articles

        # 只返回上次抓取之后发布的文章
        new_articles = [
            article for article in articles if article.published > last_fetch
        ]

        logger.info(
            f"Filtered {len(articles)} articles to {len(new_articles)} new ones for {feed_name}"
        )
        return new_articles

    async def fetch_all_feeds(self) -> dict[str, int]:
        """
        并发获取所有RSS源并保存到数据库
        返回每个源保存的文章数量
        """
        if not self.feeds:
            logger.warning("No RSS feeds configured")
            return {}

        if db_engine.AsyncSessionLocal is None:
            raise RuntimeError("Database not initialized")

        async with db_engine.AsyncSessionLocal() as session:
            repo = RSSRepository(session)

            # 创建或更新所有feed配置
            for feed in self.feeds:
                await repo.create_or_update_feed(feed)
            await session.commit()

            # 并发获取所有RSS源
            tasks = [self.fetch_feed_with_retry(feed, session) for feed in self.feeds]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 处理结果并保存到数据库
            feed_stats = {}
            for feed, result in zip(self.feeds, results):
                if isinstance(result, Exception):
                    logger.error(f"Failed to fetch {feed.name}: {result}")
                    feed_stats[feed.name] = 0
                elif isinstance(result, list):
                    # 保存文章
                    saved_count = await repo.save_articles(result)
                    feed_stats[feed.name] = saved_count

                    # 更新最后抓取时间
                    await repo.update_feed_fetch_time(feed.name)

            await session.commit()

            # 输出统计信息
            total_saved = sum(feed_stats.values())
            logger.info(
                f"RSS fetch completed: {total_saved} new articles from {len(self.feeds)} feeds"
            )

            return feed_stats
