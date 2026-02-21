"""
FRED API data source for Federal Reserve economic indicators.

API Documentation: https://fred.stlouisfed.org/docs/api/fred/
Get API key at: https://fred.stlouisfed.org/docs/api/api_key.html
"""

from datetime import date as date_type
from datetime import timedelta
from typing import Any, Optional

from loguru import logger
from pydantic import BaseModel

from server.datasource.base import BaseDataSource
from server.services.client import ServiceClient


class EconomicIndicator(BaseModel):
    """Economic indicator data."""

    series_id: str
    name: str
    value: float | None = None
    previous_value: float | None = None
    change: float | None = None
    unit: str = "%"
    date: Optional[date_type] = None


# Key economic indicators to track
INDICATORS = {
    "FEDFUNDS": {
        "name": "Fed Funds Rate",
        "unit": "%",
        "description": "Federal Funds Effective Rate",
    },
    "CPIAUCSL": {
        "name": "CPI Inflation",
        "unit": "%",
        "description": "Consumer Price Index (YoY)",
        "yoy": True,  # Calculate year-over-year change
    },
    "DGS10": {
        "name": "10Y Treasury",
        "unit": "%",
        "description": "10-Year Treasury Constant Maturity Rate",
    },
    "UNRATE": {
        "name": "Unemployment Rate",
        "unit": "%",
        "description": "Civilian Unemployment Rate",
    },
    "GDP": {
        "name": "GDP Growth",
        "unit": "%",
        "description": "Real Gross Domestic Product",
    },
}


class FREDSource(BaseDataSource[EconomicIndicator]):
    """
    FRED API data source for economic indicators.

    Fetches key economic data from the Federal Reserve Economic Data API.
    Requires a free API key from https://fred.stlouisfed.org/
    """

    BASE_URL = "https://api.stlouisfed.org/fred"
    SERVICE_ID = "fred"

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

    async def fetch(self) -> list[EconomicIndicator]:
        """Fetch all configured economic indicators."""
        indicators = []
        for series_id in INDICATORS:
            indicator = await self._fetch_indicator(series_id)
            if indicator:
                indicators.append(indicator)
        return indicators

    async def _fetch_series(
        self,
        series_id: str,
        limit: int = 2,
    ) -> list[dict[str, Any]]:
        """Fetch observations for a FRED series."""
        try:
            result = await self.client.request(
                service_id=self.SERVICE_ID,
                url=f"{self.BASE_URL}/series/observations",
                params={
                    "series_id": series_id,
                    "api_key": self.api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": str(limit),
                },
                cache_ttl=timedelta(hours=1),
            )

            return result.data.get("observations", [])

        except Exception as e:
            logger.warning(f"Failed to fetch FRED series {series_id}: {e}")
            return []

    def _parse_value(self, obs: dict[str, Any] | None) -> float | None:
        """Parse observation value, handling missing data."""
        if not obs:
            return None
        value = obs.get("value", ".")
        if value == ".":
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    async def _fetch_indicator(self, series_id: str) -> EconomicIndicator | None:
        """Fetch a single economic indicator."""
        if not self.is_configured():
            return self._empty_indicator(series_id)

        config = INDICATORS.get(series_id, {})
        name = config.get("name", series_id)
        unit = config.get("unit", "%")
        is_yoy = config.get("yoy", False)

        if is_yoy:
            return await self._fetch_yoy_indicator(series_id, name, unit)

        observations = await self._fetch_series(series_id, limit=2)
        if not observations:
            return self._empty_indicator(series_id)

        current = self._parse_value(observations[0] if observations else None)
        previous = self._parse_value(observations[1] if len(observations) > 1 else None)

        change = None
        if current is not None and previous is not None:
            change = round(current - previous, 2)

        obs_date = None
        if observations and observations[0].get("date"):
            try:
                obs_date = date_type.fromisoformat(observations[0]["date"])
            except ValueError:
                pass

        return EconomicIndicator(
            series_id=series_id,
            name=name,
            value=current,
            previous_value=previous,
            change=change,
            unit=unit,
            date=obs_date,
        )

    async def _fetch_yoy_indicator(
        self,
        series_id: str,
        name: str,
        unit: str,
    ) -> EconomicIndicator | None:
        """Fetch indicator with year-over-year calculation (e.g., CPI)."""
        # Need 14 observations: current + 12 months ago, plus previous month
        observations = await self._fetch_series(series_id, limit=14)
        if len(observations) < 13:
            return self._empty_indicator(series_id)

        current = self._parse_value(observations[0])
        year_ago = self._parse_value(
            observations[12] if len(observations) > 12 else None
        )
        prev_month = self._parse_value(
            observations[1] if len(observations) > 1 else None
        )
        prev_year_ago = self._parse_value(
            observations[13] if len(observations) > 13 else None
        )

        if current is None or year_ago is None:
            return self._empty_indicator(series_id)

        # Calculate YoY change
        yoy_change = ((current - year_ago) / year_ago) * 100
        yoy_change = round(yoy_change, 2)

        # Calculate previous month's YoY for comparison
        prev_yoy = None
        if prev_month is not None and prev_year_ago is not None:
            prev_yoy = round(((prev_month - prev_year_ago) / prev_year_ago) * 100, 2)

        change = None
        if prev_yoy is not None:
            change = round(yoy_change - prev_yoy, 2)

        obs_date = None
        if observations and observations[0].get("date"):
            try:
                obs_date = date_type.fromisoformat(observations[0]["date"])
            except ValueError:
                pass

        return EconomicIndicator(
            series_id=series_id,
            name=name,
            value=yoy_change,
            previous_value=prev_yoy,
            change=change,
            unit=unit,
            date=obs_date,
        )

    def _empty_indicator(self, series_id: str) -> EconomicIndicator:
        """Return empty indicator for unconfigured or failed fetch."""
        config = INDICATORS.get(series_id, {})
        return EconomicIndicator(
            series_id=series_id,
            name=config.get("name", series_id),
            unit=config.get("unit", "%"),
        )

    async def fetch_fed_funds_rate(self) -> EconomicIndicator | None:
        """Fetch Federal Funds Rate."""
        return await self._fetch_indicator("FEDFUNDS")

    async def fetch_cpi(self) -> EconomicIndicator | None:
        """Fetch CPI Inflation (YoY)."""
        return await self._fetch_indicator("CPIAUCSL")

    async def fetch_treasury_10y(self) -> EconomicIndicator | None:
        """Fetch 10-Year Treasury Yield."""
        return await self._fetch_indicator("DGS10")

    async def fetch_unemployment(self) -> EconomicIndicator | None:
        """Fetch Unemployment Rate."""
        return await self._fetch_indicator("UNRATE")

    async def fetch_all(self) -> dict[str, EconomicIndicator | None]:
        """Fetch all key economic indicators."""
        import asyncio

        results = await asyncio.gather(
            self.fetch_fed_funds_rate(),
            self.fetch_cpi(),
            self.fetch_treasury_10y(),
            self.fetch_unemployment(),
        )

        return {
            "fed_funds_rate": results[0],
            "cpi": results[1],
            "treasury_10y": results[2],
            "unemployment": results[3],
        }
