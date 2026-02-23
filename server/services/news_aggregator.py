"""
News aggregation service with deduplication and LLM analysis.
"""

import hashlib
import re
from datetime import datetime, timedelta

from loguru import logger
from pydantic import BaseModel, Field


class NewsItem(BaseModel):
    """Aggregated news item with analysis."""

    id: str  # Hash-based unique ID
    title: str
    summary: str = ""
    sources: list[dict] = Field(default_factory=list)  # [{name, link, published}]
    category: str = ""
    published: datetime
    source_type: str = ""  # "rss", "finnhub", "reddit", etc.

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

    def __init__(self, similarity_threshold: float = 0.5):
        self.similarity_threshold = similarity_threshold
        self._seen_hashes: set[str] = set()

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
        self, articles: list[dict], time_window_minutes: int = 60
    ) -> list[NewsItem]:
        """
        Aggregate articles, grouping similar stories.

        Args:
            articles: List of article dicts with title, link, source, published, summary
            time_window_minutes: Only consider articles within this window

        Returns:
            List of aggregated NewsItem objects
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

            item = NewsItem(
                id=item_id,
                title=primary.get("title", ""),
                summary=primary.get("summary", ""),
                sources=sources,
                category=primary.get("category", ""),
                published=primary.get("published", datetime.utcnow()),
                source_type=primary.get("source_type", ""),
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

    def __init__(self, llm=None):
        self.llm = llm

    async def analyze_batch(
        self, items: list[NewsItem], max_items: int = 10
    ) -> list[NewsItem]:
        """
        Analyze a batch of news items with LLM.

        Returns items with chinese_summary and market_impact filled in.
        """
        import time

        if not self.llm or not items:
            logger.info("[LLM分析] 跳过：LLM未配置或无新闻")
            return items

        items_to_analyze = items[:max_items]
        logger.info(f"[LLM分析] 开始分析 {len(items_to_analyze)} 条新闻")

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

只输出JSON数组，不要其他内容。"""
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
            import re

            # Clean response - extract JSON array
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            # Find JSON array content (handle cases where there's extra text)
            json_match = re.search(r"\[\s*\{", response)
            if json_match:
                response = response[json_match.start() :]

            # Strip trailing commas before } or ] (common LLM mistake)
            response = re.sub(r",\s*([}\]])", r"\1", response)

            # Fix common JSON issues: single quotes instead of double quotes
            # Only replace single quotes that are property names or string values, not in content
            response = re.sub(r"'([^']*)':\s*'", r'"\1": "', response)
            response = re.sub(r"'([^']*)':\s*\{", r'"\1": {', response)

            # Handle unescaped newlines in strings
            response = re.sub(r'\n(?!\s*["{}\[\],])', r"\\n", response)

            try:
                analyses = json.loads(response)
            except json.JSONDecodeError as json_err:
                # Try to fix more issues and retry
                logger.warning(f"JSON parse error, attempting fixes: {json_err}")

                # Remove any text after the closing bracket
                match = re.search(r"\]\s*$", response)
                if match:
                    pass  # already clean at end
                else:
                    # Find where JSON ends
                    bracket_count = 0
                    json_end = -1
                    for i, char in enumerate(response):
                        if char == "[":
                            bracket_count += 1
                        elif char == "]":
                            bracket_count -= 1
                            if bracket_count == 0:
                                json_end = i + 1
                                break
                    if json_end > 0:
                        response = response[:json_end]

                try:
                    analyses = json.loads(response)
                    logger.info("Successfully parsed JSON after fixes")
                except json.JSONDecodeError as e2:
                    logger.error(f"JSON parsing failed even after fixes: {e2}")
                    logger.error(
                        f"Response content (first 500 chars): {response[:500]}"
                    )
                    raise e2

            parse_elapsed = time.time() - parse_start
            logger.info(
                f"[LLM分析] JSON 解析完成，耗时 {parse_elapsed:.2f}s，得到 {len(analyses)} 条分析"
            )

            # Apply analyses to items
            for i, item in enumerate(items_to_analyze):
                if i < len(analyses):
                    analysis = analyses[i]
                    item.chinese_summary = analysis.get("summary", "")
                    item.background = analysis.get("background", "")
                    item.market_impact = analysis.get("impact", {})
                    item.action = analysis.get("action", "")
                    item.importance = analysis.get("importance", 0)

            logger.info(f"[LLM分析] 分析完成，成功更新 {len(items_to_analyze)} 条新闻")
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
