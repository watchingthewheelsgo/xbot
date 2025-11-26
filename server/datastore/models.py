"""
数据库模型定义
使用SQLAlchemy 2.0+的声明式映射
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(AsyncAttrs, DeclarativeBase):
    """所有模型的基类"""

    pass


class RSSFeedDB(Base):
    """RSS订阅源表"""

    __tablename__ = "rss_feeds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String(500), default="")
    category: Mapped[str] = mapped_column(String(100), default="")
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source: Mapped[str] = mapped_column(String(255), default="")
    last_fetched: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, nullable=False
    )

    def __repr__(self) -> str:
        return f"<RSSFeed(name={self.name}, url={self.url})>"


class RSSArticleDB(Base):
    """RSS文章表"""

    __tablename__ = "rss_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feed_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    guid: Mapped[str] = mapped_column(
        String(500), unique=True, nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    link: Mapped[str] = mapped_column(String(1000), nullable=False)
    published: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )

    # 创建复合索引以优化查询性能
    __table_args__ = (
        Index("idx_feed_published", "feed_name", "published"),
        Index("idx_feed_fetched", "feed_name", "fetched_at"),
    )

    def __repr__(self) -> str:
        return f"<RSSArticle(feed={self.feed_name}, title={self.title[:50]})>"
