"""
FRED and Federal Reserve data sources.
"""

from server.datasource.economic.fred import FREDSource, EconomicIndicator
from server.datasource.economic.fed_rss import FedRSSSource, FedNewsItem

__all__ = ["FREDSource", "EconomicIndicator", "FedRSSSource", "FedNewsItem"]
