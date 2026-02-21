"""
Finnhub news and market intelligence data source.

Fetches:
- Market news (general financial news)
- Company news (stock-specific news)
- Insider transactions
- Earnings calendar
- Analyst recommendations
"""

from datetime import datetime, timedelta
from typing import Any

from loguru import logger
from pydantic import BaseModel

from server.services.client import ServiceClient


class MarketNews(BaseModel):
    """Market news item."""

    news_id: str
    category: str
    headline: str
    summary: str
    source: str
    url: str
    image_url: str | None = None
    related_symbols: list[str] = []
    published_at: datetime


class InsiderTransaction(BaseModel):
    """Insider transaction record."""

    transaction_id: str
    symbol: str
    name: str  # insider name
    share: int
    change: int
    transaction_price: float
    transaction_code: str  # P=Purchase, S=Sale, M=Option Exercise
    transaction_date: datetime
    filing_date: datetime
    is_derivative: bool = False


class EarningsEvent(BaseModel):
    """Earnings calendar event."""

    symbol: str
    report_date: datetime
    hour: str  # bmo=before market open, amc=after market close
    quarter: int
    year: int
    eps_estimate: float | None = None
    eps_actual: float | None = None
    revenue_estimate: float | None = None
    revenue_actual: float | None = None


class AnalystRating(BaseModel):
    """Analyst recommendation."""

    symbol: str
    period: str
    strong_buy: int
    buy: int
    hold: int
    sell: int
    strong_sell: int

    @property
    def total(self) -> int:
        return self.strong_buy + self.buy + self.hold + self.sell + self.strong_sell

    @property
    def sentiment(self) -> str:
        """Calculate overall sentiment."""
        if self.total == 0:
            return "neutral"
        bullish = self.strong_buy + self.buy
        bearish = self.sell + self.strong_sell
        ratio = bullish / self.total
        if ratio >= 0.7:
            return "strong_buy"
        elif ratio >= 0.5:
            return "buy"
        elif bearish / self.total >= 0.5:
            return "sell"
        return "hold"


class FinnhubNewsSource:
    """
    Finnhub news and market intelligence data source.
    """

    BASE_URL = "https://finnhub.io/api/v1"
    SERVICE_ID = "finnhub_news"

    def __init__(self, api_key: str, client: ServiceClient | None = None):
        self.api_key = api_key
        self.client = client

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def _request(self, endpoint: str, params: dict | None = None) -> Any:
        """Make API request to Finnhub."""
        if not self.client:
            import httpx

            async with httpx.AsyncClient() as client:
                params = params or {}
                params["token"] = self.api_key
                resp = await client.get(f"{self.BASE_URL}/{endpoint}", params=params)
                resp.raise_for_status()
                return resp.json()
        else:
            params = params or {}
            params["token"] = self.api_key
            result = await self.client.request(
                service_id=self.SERVICE_ID,
                url=f"{self.BASE_URL}/{endpoint}",
                params=params,
                cache_ttl=timedelta(minutes=5),
            )
            return result.data

    async def fetch_market_news(self, category: str = "general") -> list[MarketNews]:
        """
        Fetch general market news.

        Categories: general, forex, crypto, merger
        """
        if not self.is_configured():
            return []

        try:
            data = await self._request("news", {"category": category})

            news_items = []
            for item in data[:50]:  # Limit to 50 items
                try:
                    published = datetime.fromtimestamp(item.get("datetime", 0))
                    news_items.append(
                        MarketNews(
                            news_id=str(item.get("id", "")),
                            category=item.get("category", category),
                            headline=item.get("headline", ""),
                            summary=item.get("summary", ""),
                            source=item.get("source", ""),
                            url=item.get("url", ""),
                            image_url=item.get("image"),
                            related_symbols=[
                                s for s in item.get("related", "").split(",") if s
                            ],
                            published_at=published,
                        )
                    )
                except Exception as e:
                    logger.warning(f"Failed to parse news item: {e}")
                    continue

            logger.info(f"Fetched {len(news_items)} market news items")
            return news_items

        except Exception as e:
            logger.error(f"Failed to fetch market news: {e}")
            return []

    async def fetch_company_news(self, symbol: str, days: int = 3) -> list[MarketNews]:
        """Fetch news for a specific company."""
        if not self.is_configured():
            return []

        try:
            to_date = datetime.now().strftime("%Y-%m-%d")
            from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

            data = await self._request(
                "company-news",
                {
                    "symbol": symbol,
                    "from": from_date,
                    "to": to_date,
                },
            )

            news_items = []
            for item in data[:30]:
                try:
                    published = datetime.fromtimestamp(item.get("datetime", 0))
                    news_items.append(
                        MarketNews(
                            news_id=str(item.get("id", "")),
                            category="company",
                            headline=item.get("headline", ""),
                            summary=item.get("summary", ""),
                            source=item.get("source", ""),
                            url=item.get("url", ""),
                            image_url=item.get("image"),
                            related_symbols=[symbol],
                            published_at=published,
                        )
                    )
                except Exception:
                    continue

            logger.info(f"Fetched {len(news_items)} news items for {symbol}")
            return news_items

        except Exception as e:
            logger.error(f"Failed to fetch company news for {symbol}: {e}")
            return []

    async def fetch_insider_transactions(self, symbol: str) -> list[InsiderTransaction]:
        """Fetch insider transactions for a symbol."""
        if not self.is_configured():
            return []

        try:
            data = await self._request("stock/insider-transactions", {"symbol": symbol})

            transactions = []
            for item in data.get("data", [])[:20]:
                try:
                    # Skip derivative transactions for cleaner signal
                    if item.get("isDerivative", False):
                        continue

                    # Only include purchases (P) and sales (S)
                    code = item.get("transactionCode", "")
                    if code not in ["P", "S"]:
                        continue

                    transactions.append(
                        InsiderTransaction(
                            transaction_id=item.get("id", ""),
                            symbol=symbol,
                            name=item.get("name", ""),
                            share=item.get("share", 0),
                            change=item.get("change", 0),
                            transaction_price=item.get("transactionPrice", 0),
                            transaction_code=code,
                            transaction_date=datetime.fromisoformat(
                                item.get("transactionDate", "2000-01-01")
                            ),
                            filing_date=datetime.fromisoformat(
                                item.get("filingDate", "2000-01-01")
                            ),
                            is_derivative=item.get("isDerivative", False),
                        )
                    )
                except Exception:
                    continue

            logger.info(
                f"Fetched {len(transactions)} insider transactions for {symbol}"
            )
            return transactions

        except Exception as e:
            logger.error(f"Failed to fetch insider transactions for {symbol}: {e}")
            return []

    async def fetch_earnings_calendar(self, days: int = 7) -> list[EarningsEvent]:
        """Fetch upcoming earnings reports."""
        if not self.is_configured():
            return []

        try:
            from_date = datetime.now().strftime("%Y-%m-%d")
            to_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")

            data = await self._request(
                "calendar/earnings",
                {
                    "from": from_date,
                    "to": to_date,
                },
            )

            events = []
            for item in data.get("earningsCalendar", []):
                try:
                    events.append(
                        EarningsEvent(
                            symbol=item.get("symbol", ""),
                            report_date=datetime.fromisoformat(
                                item.get("date", "2000-01-01")
                            ),
                            hour=item.get("hour", ""),
                            quarter=item.get("quarter", 0),
                            year=item.get("year", 0),
                            eps_estimate=item.get("epsEstimate"),
                            eps_actual=item.get("epsActual"),
                            revenue_estimate=item.get("revenueEstimate"),
                            revenue_actual=item.get("revenueActual"),
                        )
                    )
                except Exception:
                    continue

            logger.info(f"Fetched {len(events)} earnings events")
            return events

        except Exception as e:
            logger.error(f"Failed to fetch earnings calendar: {e}")
            return []

    async def fetch_analyst_rating(self, symbol: str) -> AnalystRating | None:
        """Fetch analyst recommendations for a symbol."""
        if not self.is_configured():
            return None

        try:
            data = await self._request("stock/recommendation", {"symbol": symbol})

            if not data:
                return None

            # Get most recent rating
            latest = data[0]
            return AnalystRating(
                symbol=symbol,
                period=latest.get("period", ""),
                strong_buy=latest.get("strongBuy", 0),
                buy=latest.get("buy", 0),
                hold=latest.get("hold", 0),
                sell=latest.get("sell", 0),
                strong_sell=latest.get("strongSell", 0),
            )

        except Exception as e:
            logger.error(f"Failed to fetch analyst rating for {symbol}: {e}")
            return None

    async def fetch_quote(self, symbol: str) -> dict | None:
        """Fetch current quote for a symbol."""
        if not self.is_configured():
            return None

        try:
            data = await self._request("quote", {"symbol": symbol})

            if data.get("c", 0) == 0 and data.get("pc", 0) == 0:
                return None

            return {
                "symbol": symbol,
                "price": data.get("c", 0),
                "change": data.get("d", 0),
                "change_percent": data.get("dp", 0),
                "high": data.get("h", 0),
                "low": data.get("l", 0),
                "open": data.get("o", 0),
                "prev_close": data.get("pc", 0),
            }

        except Exception as e:
            logger.error(f"Failed to fetch quote for {symbol}: {e}")
            return None
