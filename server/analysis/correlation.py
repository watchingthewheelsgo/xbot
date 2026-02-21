"""
Correlation engine - analyzes patterns across news items.

Detects:
- Emerging patterns (topics with 3+ mentions)
- Momentum signals (rising topic trends)
- Cross-source correlations (same topic across multiple sources)
- Predictive signals (combined score-based predictions)
"""

from collections import defaultdict
from datetime import datetime
from typing import Any, Literal

from loguru import logger

from server.analysis.config import CORRELATION_TOPICS, CorrelationTopic
from server.analysis.types import (
    CorrelationResults,
    CorrelationSummary,
    CrossSourceCorrelation,
    EmergingPattern,
    HeadlineRef,
    MomentumSignal,
    PredictiveSignal,
)


class CorrelationEngine:
    """
    Analyzes patterns across news items to detect signals and trends.
    """

    HISTORY_RETENTION_MINUTES = 30
    MOMENTUM_WINDOW_MINUTES = 10

    EMERGING_THRESHOLD = 3
    ELEVATED_THRESHOLD = 5
    HIGH_THRESHOLD = 8
    CROSS_SOURCE_THRESHOLD = 3
    PREDICTIVE_SCORE_THRESHOLD = 15

    def __init__(self):
        # {minute_timestamp: {topic_id: count}}
        self._topic_history: dict[int, dict[str, int]] = {}

    @staticmethod
    def _format_topic_name(topic_id: str) -> str:
        return topic_id.replace("-", " ").title()

    def _current_minute(self) -> int:
        return int(datetime.now().timestamp() // 60)

    def _cleanup_history(self, current_minute: int) -> None:
        cutoff = current_minute - self.HISTORY_RETENTION_MINUTES
        for key in [k for k in self._topic_history if k < cutoff]:
            del self._topic_history[key]

    def _get_level(self, count: int) -> Literal["high", "elevated", "emerging"]:
        if count >= self.HIGH_THRESHOLD:
            return "high"
        elif count >= self.ELEVATED_THRESHOLD:
            return "elevated"
        return "emerging"

    def _get_momentum(self, delta: int) -> Literal["surging", "rising", "stable"]:
        if delta >= 4:
            return "surging"
        elif delta >= 2:
            return "rising"
        return "stable"

    def _get_prediction(self, topic: CorrelationTopic, count: int) -> str:
        if topic.id == "tariffs" and count >= 4:
            return "Market volatility likely in next 24-48h"
        if topic.id == "fed-rates":
            return "Expect increased financial sector coverage"
        if "china" in topic.id or "russia" in topic.id:
            return "Geopolitical escalation narrative forming"
        if topic.id == "layoffs":
            return "Employment concerns may dominate news cycle"
        if topic.category == "Conflict":
            return "Breaking developments likely within hours"
        if topic.category == "Finance":
            return "Market reaction expected"
        if topic.category == "Security":
            return "Heightened security posture likely"
        return "Topic gaining mainstream traction"

    def analyze(self, news_items: list[dict[str, Any]]) -> CorrelationResults | None:
        """
        Analyze news items for patterns and signals.

        Args:
            news_items: List of dicts with 'title', 'link', 'source' keys

        Returns:
            CorrelationResults or None if no items
        """
        if not news_items:
            return None

        current_minute = self._current_minute()

        topic_counts: dict[str, int] = defaultdict(int)
        topic_sources: dict[str, set[str]] = defaultdict(set)
        topic_headlines: dict[str, list[HeadlineRef]] = defaultdict(list)

        for item in news_items:
            title = item.get("title", "")
            source = item.get("source", "Unknown")
            link = item.get("link", "")

            for topic in CORRELATION_TOPICS:
                if any(p.search(title) for p in topic.patterns):
                    topic_counts[topic.id] += 1
                    topic_sources[topic.id].add(source)
                    if len(topic_headlines[topic.id]) < 5:
                        topic_headlines[topic.id].append(
                            HeadlineRef(title=title, link=link, source=source)
                        )

        # Update history for momentum tracking
        if current_minute not in self._topic_history:
            self._topic_history[current_minute] = dict(topic_counts)
            self._cleanup_history(current_minute)

        old_counts = self._topic_history.get(
            current_minute - self.MOMENTUM_WINDOW_MINUTES, {}
        )

        results = CorrelationResults()

        for topic in CORRELATION_TOPICS:
            count = topic_counts.get(topic.id, 0)
            sources = list(topic_sources.get(topic.id, set()))
            headlines = topic_headlines.get(topic.id, [])
            delta = count - old_counts.get(topic.id, 0)

            if count >= self.EMERGING_THRESHOLD:
                results.emerging_patterns.append(
                    EmergingPattern(
                        id=topic.id,
                        name=self._format_topic_name(topic.id),
                        category=topic.category,
                        count=count,
                        level=self._get_level(count),
                        sources=sources,
                        headlines=headlines,
                    )
                )

            if delta >= 2 or (count >= 3 and delta >= 1):
                results.momentum_signals.append(
                    MomentumSignal(
                        id=topic.id,
                        name=self._format_topic_name(topic.id),
                        category=topic.category,
                        current=count,
                        delta=delta,
                        momentum=self._get_momentum(delta),
                        headlines=headlines,
                    )
                )

            if len(sources) >= self.CROSS_SOURCE_THRESHOLD:
                results.cross_source_correlations.append(
                    CrossSourceCorrelation(
                        id=topic.id,
                        name=self._format_topic_name(topic.id),
                        category=topic.category,
                        source_count=len(sources),
                        sources=sources,
                        level=self._get_level(len(sources)),
                        headlines=headlines,
                    )
                )

            score = count * 2 + len(sources) * 3 + delta * 5
            if score >= self.PREDICTIVE_SCORE_THRESHOLD:
                confidence = min(95, round(score * 1.5))
                results.predictive_signals.append(
                    PredictiveSignal(
                        id=topic.id,
                        name=self._format_topic_name(topic.id),
                        category=topic.category,
                        score=score,
                        confidence=confidence,
                        prediction=self._get_prediction(topic, count),
                        level="high"
                        if confidence >= 70
                        else "medium"
                        if confidence >= 50
                        else "low",
                        headlines=headlines,
                    )
                )

        results.emerging_patterns.sort(key=lambda x: x.count, reverse=True)
        results.momentum_signals.sort(key=lambda x: x.delta, reverse=True)
        results.cross_source_correlations.sort(
            key=lambda x: x.source_count, reverse=True
        )
        results.predictive_signals.sort(key=lambda x: x.score, reverse=True)

        logger.info(
            f"Correlation: {len(results.emerging_patterns)} patterns, "
            f"{len(results.momentum_signals)} momentum, "
            f"{len(results.predictive_signals)} predictive"
        )
        return results

    def get_summary(self, results: CorrelationResults | None) -> CorrelationSummary:
        if not results:
            return CorrelationSummary(total_signals=0, status="NO DATA")
        return CorrelationSummary(
            total_signals=results.total_signals,
            status=results.status,
            top_patterns=[p.name for p in results.emerging_patterns[:3]],
            top_momentum=[m.name for m in results.momentum_signals[:3]],
        )

    def clear_history(self) -> None:
        self._topic_history.clear()
