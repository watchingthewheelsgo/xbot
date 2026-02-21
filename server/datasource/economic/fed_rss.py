"""
Federal Reserve RSS news source.

Fetches news from Federal Reserve RSS feeds including:
- Press releases
- Speeches
- Testimony
- Board meetings
"""

import hashlib
import re
from datetime import datetime, timedelta

from loguru import logger
from pydantic import BaseModel

from server.services.client import ServiceClient


class FedNewsItem(BaseModel):
    """Federal Reserve news item."""

    id: str
    title: str
    link: str
    description: str
    pub_date: str
    timestamp: int
    news_type: str  # 'monetary' | 'speech' | 'testimony' | 'announcement'
    type_label: str
    is_powell_related: bool = False
    has_video: bool = False


# Fed RSS feeds configuration
FED_BASE_URL = "https://www.federalreserve.gov"

FED_RSS_FEEDS = [
    {
        "url": f"{FED_BASE_URL}/feeds/press_monetary.xml",
        "type": "monetary",
        "label": "Monetary Policy",
    },
    {
        "url": f"{FED_BASE_URL}/feeds/s_t_powell.xml",
        "type": "powell",
        "label": "Chair Powell",
    },
    {
        "url": f"{FED_BASE_URL}/feeds/speeches.xml",
        "type": "speech",
        "label": "Speeches",
    },
    {
        "url": f"{FED_BASE_URL}/feeds/testimony.xml",
        "type": "testimony",
        "label": "Testimony",
    },
    {
        "url": f"{FED_BASE_URL}/feeds/press_other.xml",
        "type": "announcement",
        "label": "Announcements",
    },
]


class FedRSSSource:
    """
    Federal Reserve RSS news source.

    Fetches and parses news from multiple Fed RSS feeds.
    """

    SERVICE_ID = "fed_rss"

    def __init__(self, client: ServiceClient | None = None):
        from server.services.client import get_service_client

        self.client = client or get_service_client()

    @staticmethod
    def _hash_string(s: str) -> str:
        """Generate short hash for ID generation."""
        return hashlib.md5(s.encode()).hexdigest()[:12]

    @staticmethod
    def _parse_rss_xml(xml: str, news_type: str, type_label: str) -> list[FedNewsItem]:
        """Parse RSS XML and extract items."""
        items = []

        # Simple regex-based XML parsing
        item_pattern = re.compile(r"<item>([\s\S]*?)</item>", re.IGNORECASE)
        title_pattern = re.compile(
            r"<title>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</title>", re.IGNORECASE
        )
        link_pattern = re.compile(
            r"<link>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</link>", re.IGNORECASE
        )
        desc_pattern = re.compile(
            r"<description>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</description>",
            re.IGNORECASE,
        )
        pub_date_pattern = re.compile(r"<pubDate>([\s\S]*?)</pubDate>", re.IGNORECASE)

        for match in item_pattern.finditer(xml):
            item_xml = match.group(1)

            title_match = title_pattern.search(item_xml)
            link_match = link_pattern.search(item_xml)
            desc_match = desc_pattern.search(item_xml)
            pub_date_match = pub_date_pattern.search(item_xml)

            title = title_match.group(1).strip() if title_match else ""
            link = link_match.group(1).strip() if link_match else ""
            description = desc_match.group(1).strip() if desc_match else ""
            pub_date = pub_date_match.group(1).strip() if pub_date_match else ""

            if not title or not link:
                continue

            # Clean HTML from description
            description = re.sub(r"<[^>]*>", "", description)

            # Ensure full URL
            if link and not link.startswith("http"):
                link = f"{FED_BASE_URL}{link}"

            # Parse timestamp
            timestamp = int(datetime.now().timestamp() * 1000)
            if pub_date:
                try:
                    dt = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %z")
                    timestamp = int(dt.timestamp() * 1000)
                except ValueError:
                    try:
                        dt = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S GMT")
                        timestamp = int(dt.timestamp() * 1000)
                    except ValueError:
                        pass

            # Check for Powell-related content
            full_text = f"{title} {description}".lower()
            is_powell = news_type == "powell" or bool(
                re.search(r"powell|chair(?:man)?", full_text)
            )
            has_video = bool(
                re.search(r"video|webcast|watch|broadcast|live", full_text)
            )

            items.append(
                FedNewsItem(
                    id=f"fed-{news_type}-{FedRSSSource._hash_string(link)}",
                    title=title,
                    link=link,
                    description=description[:500],  # Truncate long descriptions
                    pub_date=pub_date,
                    timestamp=timestamp,
                    news_type=news_type,
                    type_label=type_label,
                    is_powell_related=is_powell,
                    has_video=has_video,
                )
            )

        return items

    async def _fetch_feed(
        self,
        url: str,
        news_type: str,
        type_label: str,
    ) -> list[FedNewsItem]:
        """Fetch and parse a single RSS feed."""
        try:
            # Use httpx directly for XML content
            import httpx

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                xml = response.text

            return self._parse_rss_xml(xml, news_type, type_label)

        except Exception as e:
            logger.warning(f"Failed to fetch Fed RSS feed {type_label}: {e}")
            return []

    async def fetch(self) -> list[FedNewsItem]:
        """
        Fetch all Fed news from RSS feeds.

        Returns:
            List of FedNewsItem sorted by timestamp (newest first),
            with Powell-related items prioritized.
        """
        import asyncio

        # Fetch all feeds in parallel
        tasks = [
            self._fetch_feed(feed["url"], feed["type"], feed["label"])
            for feed in FED_RSS_FEEDS
        ]

        results = await asyncio.gather(*tasks)

        # Flatten and dedupe by link
        seen_links: set[str] = set()
        all_items: list[FedNewsItem] = []

        for items in results:
            for item in items:
                if item.link not in seen_links:
                    seen_links.add(item.link)
                    all_items.append(item)

        # Sort: Powell items first, then by timestamp
        all_items.sort(key=lambda x: (not x.is_powell_related, -x.timestamp))

        logger.info(f"Fetched {len(all_items)} Fed news items")
        return all_items

    async def fetch_recent(self, hours: int = 24) -> list[FedNewsItem]:
        """Fetch Fed news from the last N hours."""
        all_items = await self.fetch()
        cutoff = int((datetime.now() - timedelta(hours=hours)).timestamp() * 1000)
        return [item for item in all_items if item.timestamp >= cutoff]
