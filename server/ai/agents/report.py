"""
Report generation agent - orchestrates data collection and report generation.
"""

from datetime import datetime, timedelta
from typing import Any

from loguru import logger
from pydantic import Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from server.ai.agents.base import ToolCallAgent
from server.ai.llm import LLM
from server.ai.schema import AgentState, Memory
from server.analysis.correlation import CorrelationEngine
from server.analysis.types import CorrelationResults
from server.datastore.models import RSSArticleDB
import server.datastore.engine as db_engine
from server.reports.generator import ReportGenerator, ReportDataContext, GeneratedReport
from server.reports.templates import ReportType


class ReportAgent(ToolCallAgent):
    """
    Agent that orchestrates data collection from multiple sources
    and generates comprehensive reports using LLM.
    """

    llm: LLM | None = None
    state: AgentState = AgentState.IDLE
    memory: Memory = Field(default_factory=Memory)

    _report_generator: ReportGenerator | None = None
    _correlation_engine: CorrelationEngine | None = None
    _market_fetcher: Any = None
    _crypto_fetcher: Any = None
    _economic_fetcher: Any = None

    model_config = {"arbitrary_types_allowed": True}

    def __init__(self, llm: LLM | None = None, **kwargs):
        super().__init__(**kwargs)
        self.llm = llm or LLM()
        self.state = AgentState.IDLE
        self.memory = Memory()
        self._report_generator = ReportGenerator(self.llm)
        self._correlation_engine = CorrelationEngine()

    def set_data_sources(
        self,
        market_fetcher: Any = None,
        crypto_fetcher: Any = None,
        economic_fetcher: Any = None,
    ) -> None:
        """Inject data source fetchers."""
        self._market_fetcher = market_fetcher
        self._crypto_fetcher = crypto_fetcher
        self._economic_fetcher = economic_fetcher

    async def _fetch_recent_news(
        self,
        session: AsyncSession,
        hours: int = 24,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch recent news from database."""
        cutoff = datetime.now() - timedelta(hours=hours)

        result = await session.execute(
            select(RSSArticleDB)
            .where(RSSArticleDB.published >= cutoff)
            .order_by(desc(RSSArticleDB.published))
            .limit(limit)
        )

        articles = result.scalars().all()

        return [
            {
                "title": article.title,
                "link": article.link,
                "source": article.feed_name,
                "published": article.published.isoformat()
                if article.published
                else None,
                "summary": article.summary,
            }
            for article in articles
        ]

    async def _fetch_market_data(self) -> dict[str, Any]:
        """Fetch market data from all sources."""
        market_data: dict[str, Any] = {}

        if self._market_fetcher:
            try:
                data = await self._market_fetcher.fetch_all()
                market_data.update(data)
            except Exception as e:
                logger.warning(f"Failed to fetch market data: {e}")

        if self._crypto_fetcher:
            try:
                crypto = await self._crypto_fetcher.fetch()
                market_data["crypto"] = [c.model_dump() for c in crypto]
            except Exception as e:
                logger.warning(f"Failed to fetch crypto data: {e}")

        return market_data

    async def _fetch_economic_data(self) -> dict[str, Any]:
        """Fetch economic indicators from FRED."""
        if not self._economic_fetcher:
            return {}

        try:
            indicators = await self._economic_fetcher.fetch_all()
            return {k: v.model_dump() if v else None for k, v in indicators.items()}
        except Exception as e:
            logger.warning(f"Failed to fetch economic data: {e}")
            return {}

    async def _run_correlation(
        self, news_items: list[dict[str, Any]]
    ) -> CorrelationResults | None:
        """Run correlation analysis on news items."""
        if not self._correlation_engine or not news_items:
            return None

        try:
            return self._correlation_engine.analyze(news_items)
        except Exception as e:
            logger.warning(f"Correlation analysis failed: {e}")
            return None

    async def generate_report(
        self,
        report_type: ReportType = ReportType.DAILY_BRIEFING,
        news_hours: int = 24,
        news_limit: int = 100,
    ) -> GeneratedReport:
        """
        Generate a report.

        Args:
            report_type: Type of report to generate
            news_hours: Hours of news to include
            news_limit: Maximum number of news items

        Returns:
            GeneratedReport with the generated content
        """
        try:
            self.state = AgentState.RUNNING
            logger.info(f"Starting report generation: {report_type.value}")

            if db_engine.AsyncSessionLocal is None:
                raise RuntimeError("Database not initialized")

            async with db_engine.AsyncSessionLocal() as session:
                logger.info("Fetching recent news...")
                news_items = await self._fetch_recent_news(
                    session, hours=news_hours, limit=news_limit
                )
                logger.info(f"Fetched {len(news_items)} news items")

                logger.info("Fetching market and economic data...")
                market_data = await self._fetch_market_data()
                economic_data = await self._fetch_economic_data()

                logger.info("Running correlation analysis...")
                correlation_results = await self._run_correlation(news_items)

                if correlation_results:
                    logger.info(
                        f"Correlation: {correlation_results.total_signals} signals"
                    )

                context = ReportDataContext(
                    news_items=news_items,
                    market_data=market_data,
                    economic_data=economic_data,
                    correlation_results=correlation_results,
                )

                logger.info("Generating report with LLM...")
                assert self._report_generator is not None
                report = await self._report_generator.generate(report_type, context)

                self.state = AgentState.FINISHED
                logger.info(f"Report complete: {len(report.content)} chars")

                return report

        except Exception as e:
            self.state = AgentState.ERROR
            logger.error(f"Report generation failed: {e}")
            return GeneratedReport(
                report_type=report_type,
                title="Error",
                content=f"Report generation failed: {e}",
                metadata={"error": str(e)},
            )

    async def generate_correlation_alert(
        self,
        news_hours: int = 1,
        min_signals: int = 1,
    ) -> GeneratedReport | None:
        """
        Generate a correlation alert if significant patterns are detected.

        Returns:
            GeneratedReport if alert warranted, None otherwise
        """
        try:
            self.state = AgentState.RUNNING

            if db_engine.AsyncSessionLocal is None:
                raise RuntimeError("Database not initialized")

            async with db_engine.AsyncSessionLocal() as session:
                news_items = await self._fetch_recent_news(
                    session, hours=news_hours, limit=200
                )

                correlation_results = await self._run_correlation(news_items)

                if (
                    not correlation_results
                    or correlation_results.total_signals < min_signals
                ):
                    logger.info("No significant patterns, skipping alert")
                    self.state = AgentState.FINISHED
                    return None

                context = ReportDataContext(
                    news_items=news_items,
                    correlation_results=correlation_results,
                )

                assert self._report_generator is not None
                report = await self._report_generator.generate(
                    ReportType.CORRELATION_ALERT, context
                )

                self.state = AgentState.FINISHED
                return report

        except Exception as e:
            self.state = AgentState.ERROR
            logger.error(f"Correlation alert failed: {e}")
            return None

    async def generate_market_summary(self) -> GeneratedReport:
        """Generate a market-focused summary report."""
        return await self.generate_report(
            report_type=ReportType.MARKET_SUMMARY,
            news_hours=4,
            news_limit=50,
        )

    async def generate_economic_update(self) -> GeneratedReport:
        """Generate an economic indicators update."""
        try:
            self.state = AgentState.RUNNING

            economic_data = await self._fetch_economic_data()
            market_data = await self._fetch_market_data()

            fed_news: list[dict] = []
            if db_engine.AsyncSessionLocal:
                async with db_engine.AsyncSessionLocal() as session:
                    all_news = await self._fetch_recent_news(
                        session, hours=48, limit=200
                    )
                    fed_keywords = [
                        "fed",
                        "federal reserve",
                        "powell",
                        "fomc",
                        "interest rate",
                    ]
                    fed_news = [
                        item
                        for item in all_news
                        if any(
                            kw in item.get("title", "").lower() for kw in fed_keywords
                        )
                    ][:10]

            context = ReportDataContext(
                economic_data=economic_data,
                market_data=market_data,
                fed_news=fed_news,
            )

            assert self._report_generator is not None
            report = await self._report_generator.generate(
                ReportType.ECONOMIC_UPDATE, context
            )

            self.state = AgentState.FINISHED
            return report

        except Exception as e:
            self.state = AgentState.ERROR
            logger.error(f"Economic update failed: {e}")
            return GeneratedReport(
                report_type=ReportType.ECONOMIC_UPDATE,
                title="Error",
                content=f"Economic update failed: {e}",
            )
