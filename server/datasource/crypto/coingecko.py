"""
CoinGecko API data source for cryptocurrency prices.

API Documentation: https://www.coingecko.com/en/api/documentation
Free tier: 10-30 calls/minute (no API key required)
"""

from datetime import timedelta
from typing import Any

from loguru import logger
from pydantic import BaseModel

from server.datasource.base import BaseDataSource
from server.services.client import ServiceClient


class CryptoPrice(BaseModel):
    """Cryptocurrency price data."""

    id: str
    symbol: str
    name: str
    current_price: float
    price_change_24h: float
    price_change_percentage_24h: float
    market_cap: float | None = None
    volume_24h: float | None = None


# Default cryptocurrencies to track
CRYPTO_ASSETS = [
    {"id": "bitcoin", "symbol": "BTC", "name": "Bitcoin"},
    {"id": "ethereum", "symbol": "ETH", "name": "Ethereum"},
    {"id": "solana", "symbol": "SOL", "name": "Solana"},
    {"id": "binancecoin", "symbol": "BNB", "name": "BNB"},
    {"id": "ripple", "symbol": "XRP", "name": "XRP"},
    {"id": "cardano", "symbol": "ADA", "name": "Cardano"},
    {"id": "dogecoin", "symbol": "DOGE", "name": "Dogecoin"},
    {"id": "polkadot", "symbol": "DOT", "name": "Polkadot"},
    {"id": "avalanche-2", "symbol": "AVAX", "name": "Avalanche"},
    {"id": "chainlink", "symbol": "LINK", "name": "Chainlink"},
]


class CoinGeckoSource(BaseDataSource[CryptoPrice]):
    """
    CoinGecko API data source.

    Fetches cryptocurrency prices using the free CoinGecko API.
    No API key required for basic usage.
    """

    BASE_URL = "https://api.coingecko.com/api/v3"
    SERVICE_ID = "coingecko"

    def __init__(
        self,
        client: ServiceClient | None = None,
        assets: list[dict[str, str]] | None = None,
    ):
        super().__init__(client)
        self.assets = assets or CRYPTO_ASSETS

    @property
    def service_id(self) -> str:
        return self.SERVICE_ID

    def is_configured(self) -> bool:
        """CoinGecko free tier doesn't require API key."""
        return True

    async def fetch(self) -> list[CryptoPrice]:
        """
        Fetch cryptocurrency prices from CoinGecko.

        Returns:
            List of CryptoPrice objects
        """
        try:
            ids = ",".join(asset["id"] for asset in self.assets)
            url = f"{self.BASE_URL}/simple/price"

            result = await self.client.request(
                service_id=self.SERVICE_ID,
                url=url,
                params={
                    "ids": ids,
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                    "include_market_cap": "true",
                    "include_24hr_vol": "true",
                },
                cache_ttl=timedelta(minutes=2),
            )

            return self._transform_response(result.data)

        except Exception as e:
            logger.error(f"Failed to fetch crypto prices: {e}")
            return self._get_empty_prices()

    def _transform_response(self, data: dict[str, Any]) -> list[CryptoPrice]:
        """Transform CoinGecko response to CryptoPrice models."""
        prices = []

        for asset in self.assets:
            asset_id = asset["id"]
            if asset_id not in data:
                continue

            price_data = data[asset_id]
            prices.append(
                CryptoPrice(
                    id=asset_id,
                    symbol=asset["symbol"],
                    name=asset["name"],
                    current_price=price_data.get("usd", 0),
                    price_change_24h=price_data.get("usd_24h_change", 0),
                    price_change_percentage_24h=price_data.get("usd_24h_change", 0),
                    market_cap=price_data.get("usd_market_cap"),
                    volume_24h=price_data.get("usd_24h_vol"),
                )
            )

        logger.info(f"Fetched {len(prices)} crypto prices")
        return prices

    def _get_empty_prices(self) -> list[CryptoPrice]:
        """Return empty price objects for all assets."""
        return [
            CryptoPrice(
                id=asset["id"],
                symbol=asset["symbol"],
                name=asset["name"],
                current_price=0,
                price_change_24h=0,
                price_change_percentage_24h=0,
            )
            for asset in self.assets
        ]

    async def fetch_detailed(self, coin_id: str) -> dict[str, Any] | None:
        """
        Fetch detailed information for a specific coin.

        Args:
            coin_id: CoinGecko coin ID (e.g., "bitcoin")

        Returns:
            Detailed coin data or None if failed
        """
        try:
            url = f"{self.BASE_URL}/coins/{coin_id}"

            result = await self.client.request(
                service_id=self.SERVICE_ID,
                url=url,
                params={
                    "localization": "false",
                    "tickers": "false",
                    "community_data": "false",
                    "developer_data": "false",
                },
                cache_ttl=timedelta(minutes=5),
            )

            return result.data

        except Exception as e:
            logger.error(f"Failed to fetch detailed data for {coin_id}: {e}")
            return None

    async def fetch_market_chart(
        self,
        coin_id: str,
        days: int = 7,
    ) -> dict[str, Any] | None:
        """
        Fetch historical market data for a coin.

        Args:
            coin_id: CoinGecko coin ID
            days: Number of days of data (1, 7, 14, 30, 90, 180, 365, max)

        Returns:
            Market chart data or None if failed
        """
        try:
            url = f"{self.BASE_URL}/coins/{coin_id}/market_chart"

            result = await self.client.request(
                service_id=self.SERVICE_ID,
                url=url,
                params={
                    "vs_currency": "usd",
                    "days": str(days),
                },
                cache_ttl=timedelta(minutes=10),
            )

            return result.data

        except Exception as e:
            logger.error(f"Failed to fetch market chart for {coin_id}: {e}")
            return None
