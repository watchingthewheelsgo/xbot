"""
Correlation analysis engine for detecting patterns across news items.
"""

from server.analysis.types import (
    CorrelationResults,
    CorrelationSummary,
    EmergingPattern,
    MomentumSignal,
    CrossSourceCorrelation,
    PredictiveSignal,
    HeadlineRef,
)
from server.analysis.correlation import CorrelationEngine
from server.analysis.config import (
    CORRELATION_TOPICS,
    ALERT_KEYWORDS,
    REGION_KEYWORDS,
    TOPIC_KEYWORDS,
)

__all__ = [
    # Types
    "CorrelationResults",
    "CorrelationSummary",
    "EmergingPattern",
    "MomentumSignal",
    "CrossSourceCorrelation",
    "PredictiveSignal",
    "HeadlineRef",
    # Engine
    "CorrelationEngine",
    # Config
    "CORRELATION_TOPICS",
    "ALERT_KEYWORDS",
    "REGION_KEYWORDS",
    "TOPIC_KEYWORDS",
]
