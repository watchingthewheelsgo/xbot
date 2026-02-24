"""
News aggregation service with deduplication and LLM analysis.
"""

import hashlib
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from loguru import logger
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from server.datasource.source_manager import SourceManager


class NewsItem(BaseModel):
    """Aggregated news item with analysis."""

    id: str  # Hash-based unique ID
    title: str
    summary: str = ""
    sources: list[dict] = Field(default_factory=list)  # [{name, link, published}]
    category: str = ""
    published: datetime
    source_type: str = ""  # "rss", "finnhub", "reddit", etc.
    source_priority: int = 50  # Source priority (0-100)

    # LLM-generated analysis
    chinese_summary: str = ""
    background: str = ""  # Why this matters
    market_impact: dict = Field(
        default_factory=dict
    )  # {sectors, bullish, bearish, watch, reasoning}
    action: str = ""  # Suggested action / what to watch
    importance: int = 0  # 1-5 scale

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def source_names(self) -> list[str]:
        return [s.get("name", "") for s in self.sources]


class NewsAggregator:
    """
    Aggregates news from multiple sources with deduplication.
    Groups similar stories and provides unified view.
    """

    # Words to ignore when computing similarity
    STOP_WORDS = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "under",
        "again",
        "further",
        "then",
        "once",
        "and",
        "but",
        "or",
        "nor",
        "so",
        "yet",
        "both",
        "either",
        "neither",
        "not",
        "only",
        "own",
        "same",
        "than",
        "too",
        "very",
        "just",
        "also",
        "now",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "any",
        "only",
        "new",
        "says",
        "said",
        "report",
        "reports",
        "according",
        "news",
        "update",
    }

    def __init__(
        self,
        similarity_threshold: float = 0.5,
        source_manager: "SourceManager | None" = None,
    ):
        self.similarity_threshold = similarity_threshold
        self._seen_hashes: set[str] = set()
        self._source_manager = source_manager

    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison."""
        # Lowercase and remove special chars
        text = text.lower()
        text = re.sub(r"[^\w\s]", " ", text)
        # Remove extra whitespace
        text = " ".join(text.split())
        return text

    def _extract_keywords(self, text: str) -> set[str]:
        """Extract meaningful keywords from text."""
        normalized = self._normalize_text(text)
        words = normalized.split()
        # Filter stop words and short words
        keywords = {w for w in words if w not in self.STOP_WORDS and len(w) > 2}
        return keywords

    def _compute_hash(self, title: str) -> str:
        """Compute hash for deduplication."""
        keywords = self._extract_keywords(title)
        # Sort for consistency
        key_str = " ".join(sorted(keywords))
        return hashlib.md5(key_str.encode()).hexdigest()[:12]

    def _compute_similarity(self, title1: str, title2: str) -> float:
        """Compute Jaccard similarity between two titles."""
        kw1 = self._extract_keywords(title1)
        kw2 = self._extract_keywords(title2)

        if not kw1 or not kw2:
            return 0.0

        intersection = len(kw1 & kw2)
        union = len(kw1 | kw2)

        return intersection / union if union > 0 else 0.0

    def aggregate(
        self,
        articles: list[dict],
        time_window_minutes: int = 60,
        source_manager: "SourceManager | None" = None,
    ) -> list[NewsItem]:
        """
        Aggregate articles, grouping similar stories, and sort by source priority.

        Args:
            articles: List of article dicts with title, link, source, published, summary
            time_window_minutes: Only consider articles within this window
            source_manager: Optional source manager for priority lookup

        Returns:
            List of aggregated NewsItem objects sorted by priority
        """
        if not articles:
            return []

        import time

        start_time = time.time()
        logger.info(
            f"[聚合] 输入 {len(articles)} 条文章，时间窗口 {time_window_minutes} 分钟"
        )

        cutoff = datetime.utcnow() - timedelta(minutes=time_window_minutes)

        # Filter by time and sort by published date
        recent = []
        for a in articles:
            pub = a.get("published")
            if isinstance(pub, datetime) and pub >= cutoff:
                recent.append(a)
            elif isinstance(pub, str):
                try:
                    pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                    if pub_dt.replace(tzinfo=None) >= cutoff:
                        a["published"] = pub_dt.replace(tzinfo=None)
                        recent.append(a)
                except (ValueError, TypeError):
                    pass

        recent.sort(key=lambda x: x.get("published", datetime.min), reverse=True)
        logger.info(f"[聚合] 时间窗口过滤后剩余 {len(recent)} 条文章")

        # Group similar articles
        groups: list[list[dict]] = []
        used: set[int] = set()

        for i, article in enumerate(recent):
            if i in used:
                continue

            group = [article]
            used.add(i)

            # Find similar articles
            for j, other in enumerate(recent):
                if j in used:
                    continue

                sim = self._compute_similarity(
                    article.get("title", ""), other.get("title", "")
                )

                if sim >= self.similarity_threshold:
                    group.append(other)
                    used.add(j)

            groups.append(group)

        logger.info(f"[聚合] 相似度分组后得到 {len(groups)} 个组")

        # Convert groups to NewsItems
        result: list[NewsItem] = []
        skipped_by_hash = 0
        for group in groups:
            # Use first (most recent) article as primary
            primary = group[0]

            # Collect all sources
            sources = []
            seen_links = set()
            for a in group:
                link = a.get("link", "")
                if link and link not in seen_links:
                    sources.append(
                        {
                            "name": a.get("source", a.get("feed_name", "")),
                            "link": link,
                            "published": a.get("published"),
                        }
                    )
                    seen_links.add(link)

            # Create NewsItem
            item_id = self._compute_hash(primary.get("title", ""))

            # Skip if we've seen this hash recently
            if item_id in self._seen_hashes:
                skipped_by_hash += 1
                continue
            self._seen_hashes.add(item_id)

            # Calculate source priority
            source_priority = 50  # Default priority
            source_type = primary.get("source_type", "")
            sm = source_manager or self._source_manager
            if sm:
                if source_type == "finnhub":
                    source_priority = sm.get_finnhub_priority()
                else:
                    # Get highest priority among sources
                    for source_dict in sources:
                        feed_priority = sm.get_feed_priority(
                            source_dict.get("name", "")
                        )
                        if feed_priority > source_priority:
                            source_priority = feed_priority

            item = NewsItem(
                id=item_id,
                title=primary.get("title", ""),
                summary=primary.get("summary", ""),
                sources=sources,
                category=primary.get("category", ""),
                published=primary.get("published", datetime.utcnow()),
                source_type=source_type,
                source_priority=source_priority,
            )

            result.append(item)

        if skipped_by_hash > 0:
            logger.info(
                f"[聚合] 因 seen_hash 跳过了 {skipped_by_hash} 条重复新闻（缓存大小：{len(self._seen_hashes)}）"
            )

        # Limit seen hashes to prevent memory growth
        if len(self._seen_hashes) > 10000:
            self._seen_hashes = set(list(self._seen_hashes)[-5000:])
            logger.info(
                f"[聚合] seen_hash 缓存已清理，当前大小 {len(self._seen_hashes)}"
            )

        # Sort by source priority and published time
        result.sort(key=lambda x: (x.source_priority, x.published), reverse=True)

        elapsed = time.time() - start_time
        logger.info(f"[聚合] 完成得到 {len(result)} 条聚合新闻，耗时 {elapsed:.2f}s")

        return result

    def clear_cache(self):
        """Clear the seen hashes cache."""
        self._seen_hashes.clear()


class NewsAnalyzer:
    """
    Analyzes news items using LLM for market impact and summaries.
    """

    def __init__(self, llm=None, session_factory=None):
        self.llm = llm
        self.session_factory = session_factory

    async def analyze_batch(
        self, items: list[NewsItem], max_items: int = 10
    ) -> list[NewsItem]:
        """
        Analyze a batch of news items with LLM.
        Uses cache if session_factory is configured.

        Returns items with chinese_summary and market_impact filled in.
        """
        import time

        if not self.llm or not items:
            logger.info("[LLM分析] 跳过：LLM未配置或无新闻")
            return items

        items_to_analyze = items[:max_items]
        logger.info(f"[LLM分析] 开始分析 {len(items_to_analyze)} 条新闻")

        # Try to use cache first
        uncached_items = []
        if self.session_factory:
            try:
                from server.datastore.repositories import NewsAnalysisCacheRepository
                from server.datastore.engine import get_session_factory as get_sf

                sf = (
                    self.session_factory if callable(self.session_factory) else get_sf()
                )

                async with sf() as cache_session:  # type: ignore[misc]
                    cache_repo = NewsAnalysisCacheRepository(cache_session)

                    # Check cache for each item
                    cache_hits = 0
                    for item in items_to_analyze:
                        cached = await cache_repo.get(item.id)
                        if cached:
                            # Use cached result
                            item.chinese_summary = cached["chinese_summary"]
                            item.background = cached["background"]
                            item.market_impact = cached["market_impact"]
                            item.action = cached["action"]
                            item.importance = cached["importance"]
                            cache_hits += 1
                            logger.debug(f"[LLM缓存] 命中: {item.title[:30]}...")
                        else:
                            uncached_items.append(item)

                    logger.info(
                        f"[LLM分析] 缓存命中 {cache_hits}/{len(items_to_analyze)}，需分析 {len(uncached_items)} 条"
                    )

                    # If all cached, cleanup expired entries
                    if cache_hits == len(items_to_analyze):
                        deleted = await cache_repo.cleanup_expired()
                        if deleted > 0:
                            logger.info(f"[LLM缓存] 清理过期 {deleted} 条")

            except Exception as e:
                logger.warning(f"[LLM缓存] 缓存操作失败: {e}")
                uncached_items = items_to_analyze
        else:
            uncached_items = items_to_analyze

        # If no items need analysis, return early
        if not uncached_items:
            return items

        # Limit items to analyze to avoid truncation
        # 5 items is safe for most LLMs with 4k-8k context
        if len(uncached_items) > 5:
            logger.info(f"[LLM分析] 减少分析数量避免截断：{len(uncached_items)} -> 5")
            uncached_items = uncached_items[:5]

        # Proceed with LLM analysis for uncached items

        # Build prompt
        prompt_start = time.time()
        articles_text = "\n\n".join(
            [
                f"Article {i + 1}:\nTitle: {item.title}\nSources: {', '.join(item.source_names)}\nSummary: {item.summary[:300] if item.summary else 'N/A'}"
                for i, item in enumerate(items_to_analyze)
            ]
        )

        prompt = f"""分析以下新闻文章，为每篇文章提供：
1. 中文摘要（50-80字，概括事件核心内容）
2. 事件背景（30-50字，为什么这件事重要，有什么前因后果）
3. 市场影响分析（可能影响的板块、利好/利空的股票代码，以及影响逻辑）
4. 行动建议（20-40字，投资者应该关注什么、警惕什么）
5. 重要性评分（1-5，5最重要）

请用以下JSON格式输出，每篇文章一个对象：
[
  {{
    "summary": "50-80字中文摘要",
    "background": "30-50字事件背景",
    "impact": {{
      "sectors": ["科技", "金融"],
      "bullish": ["NVDA", "MSFT"],
      "bearish": ["GOOG"],
      "watch": ["AI芯片板块"],
      "reasoning": "一句话说明影响逻辑"
    }},
    "action": "建议关注XX，警惕XX风险",
    "importance": 4
  }}
]

新闻文章：
{articles_text}

只输出JSON数组，确保格式正确且完整。"""
        prompt_elapsed = time.time() - prompt_start
        logger.info(
            f"[LLM分析] Prompt 构建完成，耗时 {prompt_elapsed:.2f}s，长度约 {len(prompt)} 字符"
        )

        from server.ai.schema import Message

        try:
            llm_start = time.time()
            logger.info("[LLM分析] 开始调用 LLM API...")

            response = await self.llm.ask(
                messages=[Message.user_message(prompt)],
                system_msgs=[
                    Message.system_message(
                        "你是一个金融新闻分析师，擅长分析新闻对市场的影响。"
                        "输出必须是有效的JSON格式。"
                    )
                ],
                stream=False,
                temperature=0.3,
            )

            llm_elapsed = time.time() - llm_start
            logger.info(
                f"[LLM分析] LLM API 调用完成，耗时 {llm_elapsed:.2f}s，响应长度 {len(response)} 字符"
            )

            # Parse JSON response with enhanced error handling
            parse_start = time.time()

            import json

            # Clean response - extract JSON array
            response = response.strip()

            # Handle markdown code blocks
            code_blocks = re.findall(r"```(?:json)?\s*([^`]*?)```", response)
            if code_blocks:
                response = code_blocks[-1]  # Take last code block

            # Find JSON array content
            json_match = re.search(r"\\[\s*\\{", response)
            if json_match:
                response = response[json_match.start() :]

            # Fix common JSON issues
            # 1. Strip trailing commas
            response = re.sub(r",\s*([}\\]])", r"\\1", response)

            # 2. Fix single quotes in property names
            response = re.sub(r"'([^']*)':\s*[\"]", r'"\\1": "', response)
            response = re.sub(r"'([^']*)':\s*{", r'"\\1": {', response)

            # 3. Handle Chinese quotation marks
            response = response.replace('"', '"')
            response = response.replace('"', '"')
            response = response.replace('"', "'")
            response = response.replace('"', "'")

            # 4. Try to parse with increasing tolerance
            analyses = []
            try:
                analyses = json.loads(response)
            except json.JSONDecodeError as parse_err:
                logger.warning(f"JSON parse error, attempting fixes: {parse_err}")

                # Try to fix by finding the last complete object
                # Use a more robust approach: try to close incomplete JSON
                if "Unterminated string" in str(parse_err):
                    # Find last complete closing brace
                    last_complete_idx = -1
                    for i in range(len(response) - 1, 0, -1):
                        if response[i] == "]" and response[i] in "}]":
                            # Check if this creates balanced brackets
                            test_json = response[: i + 1]
                            try:
                                json.loads(test_json)
                                last_complete_idx = i + 1
                                break
                            except Exception:
                                continue

                    if last_complete_idx > 0:
                        response = response[:last_complete_idx]
                        logger.info(f"Truncated response to index {last_complete_idx}")

                # Parse again
                try:
                    analyses = json.loads(response)
                    logger.info("Successfully parsed JSON after fixes")
                except json.JSONDecodeError:
                    logger.error("JSON parsing failed even after fixes")
                    logger.error(f"JSON parsing failed: {parse_err}")
                    # Return empty analyses instead of crashing
                    analyses = []

            parse_elapsed = time.time() - parse_start
            logger.info(
                f"[LLM分析] JSON 解析完成，耗时 {parse_elapsed:.2f}s，得到 {len(analyses)} 条分析"
            )
            # Apply analyses to items
            for i, item in enumerate(uncached_items):
                if i < len(analyses):
                    analysis = analyses[i]
                    item.chinese_summary = analysis.get("summary", "")
                    item.background = analysis.get("background", "")
                    item.market_impact = analysis.get("impact", {})
                    item.action = analysis.get("action", "")
                    item.importance = analysis.get("importance", 0)

            # Save to cache if session_factory available
            if self.session_factory and uncached_items:
                try:
                    from server.datastore.repositories import (
                        NewsAnalysisCacheRepository,
                    )
                    from server.datastore.engine import get_session_factory as get_sf

                    sf = (
                        self.session_factory
                        if callable(self.session_factory)
                        else get_sf()
                    )

                    async with sf() as save_session:  # type: ignore[misc]
                        cache_repo = NewsAnalysisCacheRepository(save_session)

                        for i, item in enumerate(uncached_items):
                            if i < len(analyses):
                                analysis = analyses[i]
                                await cache_repo.set(
                                    news_hash=item.id,
                                    chinese_summary=analysis.get("summary", ""),
                                    background=analysis.get("background", ""),
                                    market_impact=analysis.get("impact", {}),
                                    action=analysis.get("action", ""),
                                    importance=analysis.get("importance", 0),
                                    ttl_hours=24,
                                )

                        await save_session.commit()
                        logger.info(
                            f"[LLM缓存] 保存 {len(uncached_items)} 条分析结果到缓存"
                        )

                except Exception as e:
                    logger.warning(f"[LLM缓存] 保存缓存失败: {e}")

            logger.info(f"[LLM分析] 分析完成，成功更新 {len(uncached_items)} 条新闻")
            return items

        except Exception as e:
            logger.error(f"News analysis failed: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            return items

    async def analyze_single(self, item: NewsItem) -> NewsItem:
        """Analyze a single news item."""
        result = await self.analyze_batch([item], max_items=1)
        return result[0] if result else item
