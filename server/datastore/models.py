"""
数据库模型定义
使用SQLAlchemy 2.0+的声明式映射
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
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
    category: Mapped[str] = mapped_column(String(100), default="", index=True)
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


class MarketNewsDB(Base):
    """市场新闻表 (Finnhub)"""

    __tablename__ = "market_news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    news_id: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(50), default="general", index=True)
    headline: Mapped[str] = mapped_column(String(1000), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(255), default="")
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    related_symbols: Mapped[str] = mapped_column(
        String(500), default=""
    )  # comma-separated
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )

    __table_args__ = (
        Index("idx_market_news_published", "published_at"),
        Index("idx_market_news_category", "category", "published_at"),
    )


class InsiderTransactionDB(Base):
    """内部交易表 (Finnhub)"""

    __tablename__ = "insider_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_id: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # insider name
    share: Mapped[int] = mapped_column(Integer, default=0)
    change: Mapped[int] = mapped_column(Integer, default=0)
    transaction_price: Mapped[float] = mapped_column(Float, default=0)
    transaction_code: Mapped[str] = mapped_column(
        String(10), default=""
    )  # P=Purchase, S=Sale, M=Option
    transaction_date: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, index=True
    )
    filing_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_derivative: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )

    __table_args__ = (Index("idx_insider_symbol_date", "symbol", "transaction_date"),)


class EarningsCalendarDB(Base):
    """财报日历表 (Finnhub)"""

    __tablename__ = "earnings_calendar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    report_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    hour: Mapped[str] = mapped_column(
        String(10), default=""
    )  # bmo=before market open, amc=after market close
    quarter: Mapped[int] = mapped_column(Integer, default=0)
    year: Mapped[int] = mapped_column(Integer, default=0)
    eps_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )

    __table_args__ = (
        Index("idx_earnings_date", "report_date"),
        Index("idx_earnings_symbol_date", "symbol", "report_date"),
    )


class WatchlistDB(Base):
    """用户关注列表（股票/话题/行业/地区）"""

    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), default="")
    watch_type: Mapped[str] = mapped_column(
        String(20), default="stock", nullable=False, index=True
    )  # stock / topic / sector / region
    added_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
