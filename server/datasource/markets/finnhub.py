"""
Finnhub API data source for stock indices, sectors, and commodities.

API Documentation: https://finnhub.io/docs/api
Free tier: 60 calls/minute
Get API key at: https://finnhub.io/
"""

from datetime import timedelta
from typing import Any

from loguru import logger
from pydantic import BaseModel

from server.datasource.base import BaseDataSource
from server.services.client import ServiceClient


class MarketItem(BaseModel):
    """Market data item (index, sector, or commodity)."""

    symbol: str
    name: str
    price: float | None = None
    change: float | None = None
    change_percent: float | None = None
    type: str  # 'index' | 'sector' | 'commodity'


class SectorPerformance(BaseModel):
    """Sector ETF performance data."""

    symbol: str
    name: str
    price: float | None = None
    change: float | None = None
    change_percent: float | None = None


# Major indices mapped to ETF proxies (free tier doesn't support direct indices)
INDICES = [
    {"symbol": "^DJI", "etf": "DIA", "name": "Dow Jones"},
    {"symbol": "^GSPC", "etf": "SPY", "name": "S&P 500"},
    {"symbol": "^IXIC", "etf": "QQQ", "name": "NASDAQ"},
    {"symbol": "^RUT", "etf": "IWM", "name": "Russell 2000"},
]

# Sector ETFs
SECTORS = [
    {"symbol": "XLK", "name": "Technology"},
    {"symbol": "XLF", "name": "Financials"},
    {"symbol": "XLV", "name": "Healthcare"},
    {"symbol": "XLE", "name": "Energy"},
    {"symbol": "XLI", "name": "Industrials"},
    {"symbol": "XLY", "name": "Consumer Discretionary"},
    {"symbol": "XLP", "name": "Consumer Staples"},
    {"symbol": "XLU", "name": "Utilities"},
    {"symbol": "XLRE", "name": "Real Estate"},
    {"symbol": "XLB", "name": "Materials"},
    {"symbol": "XLC", "name": "Communication Services"},
]

# Commodities mapped to ETF proxies
COMMODITIES = [
    {"symbol": "GC=F", "etf": "GLD", "name": "Gold"},
    {"symbol": "CL=F", "etf": "USO", "name": "Crude Oil"},
    {"symbol": "NG=F", "etf": "UNG", "name": "Natural Gas"},
    {"symbol": "SI=F", "etf": "SLV", "name": "Silver"},
    {"symbol": "^VIX", "etf": "VIXY", "name": "VIX (Volatility)"},
]


class FinnhubSource(BaseDataSource[MarketItem]):
    """
    Finnhub API data source for market data.

    Fetches stock indices, sector performance, and commodity prices.
    Requires a free API key from https://finnhub.io/
    """

    BASE_URL = "https://finnhub.io/api/v1"
    SERVICE_ID = "finnhub"

    def __init__(
        self,
        api_key: str,
        client: ServiceClient | None = None,
    ):
        super().__init__(client)
        self.api_key = api_key

    @property
    def service_id(self) -> str:
        return self.SERVICE_ID

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def fetch(self) -> list[MarketItem]:
        """Fetch all market data (indices + commodities)."""
        indices = await self.fetch_indices()
        commodities = await self.fetch_commodities()
        return indices + commodities

    async def _fetch_quote(self, symbol: str) -> dict[str, Any] | None:
        """Fetch a single quote from Finnhub."""
        try:
            result = await self.client.request(
                service_id=self.SERVICE_ID,
                url=f"{self.BASE_URL}/quote",
                params={"symbol": symbol, "token": self.api_key},
                cache_ttl=timedelta(minutes=1),
            )

            data = result.data
            # Finnhub returns all zeros when symbol not found
            if data.get("c", 0) == 0 and data.get("pc", 0) == 0:
                return None

            return data

        except Exception as e:
            logger.warning(f"Failed to fetch quote for {symbol}: {e}")
            return None

    def _quote_to_item(
        self,
        symbol: str,
        name: str,
        item_type: str,
        quote: dict[str, Any] | None,
    ) -> MarketItem:
        """Convert Finnhub quote to MarketItem."""
        if not quote:
            return MarketItem(symbol=symbol, name=name, type=item_type)

        return MarketItem(
            symbol=symbol,
            name=name,
            price=quote.get("c"),
            change=quote.get("d"),
            change_percent=quote.get("dp"),
            type=item_type,
        )

    async def fetch_indices(self) -> list[MarketItem]:
        """Fetch major stock indices via ETF proxies."""
        if not self.is_configured():
            logger.warning("Finnhub API key not configured")
            return [
                MarketItem(symbol=i["symbol"], name=i["name"], type="index")
                for i in INDICES
            ]

        results = []
        for index in INDICES:
            quote = await self._fetch_quote(index["etf"])
            results.append(
                self._quote_to_item(index["symbol"], index["name"], "index", quote)
            )

        logger.info(f"Fetched {len(results)} index quotes")
        return results

    async def fetch_sectors(self) -> list[SectorPerformance]:
        """Fetch sector ETF performance."""
        if not self.is_configured():
            return [
                SectorPerformance(symbol=s["symbol"], name=s["name"]) for s in SECTORS
            ]

        results = []
        for sector in SECTORS:
            quote = await self._fetch_quote(sector["symbol"])
            if quote:
                results.append(
                    SectorPerformance(
                        symbol=sector["symbol"],
                        name=sector["name"],
                        price=quote.get("c"),
                        change=quote.get("d"),
                        change_percent=quote.get("dp"),
                    )
                )
            else:
                results.append(
                    SectorPerformance(symbol=sector["symbol"], name=sector["name"])
                )

        logger.info(f"Fetched {len(results)} sector quotes")
        return results

    async def fetch_commodities(self) -> list[MarketItem]:
        """Fetch commodity prices via ETF proxies."""
        if not self.is_configured():
            return [
                MarketItem(symbol=c["symbol"], name=c["name"], type="commodity")
                for c in COMMODITIES
            ]

        results = []
        for commodity in COMMODITIES:
            quote = await self._fetch_quote(commodity["etf"])
            results.append(
                self._quote_to_item(
                    commodity["symbol"], commodity["name"], "commodity", quote
                )
            )

        logger.info(f"Fetched {len(results)} commodity quotes")
        return results

    async def fetch_all(self) -> dict[str, list]:
        """Fetch all market data in parallel."""
        import asyncio

        indices, sectors, commodities = await asyncio.gather(
            self.fetch_indices(),
            self.fetch_sectors(),
            self.fetch_commodities(),
        )

        return {
            "indices": [i.model_dump() for i in indices],
            "sectors": [s.model_dump() for s in sectors],
            "commodities": [c.model_dump() for c in commodities],
        }
