"""
Analysis result types using Pydantic models.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class HeadlineRef(BaseModel):
    """Reference to a news headline."""

    title: str
    link: str
    source: str


class EmergingPattern(BaseModel):
    """Detected emerging pattern across news items."""

    id: str
    name: str
    category: str
    count: int
    level: Literal["high", "elevated", "emerging"]
    sources: list[str]
    headlines: list[HeadlineRef] = Field(default_factory=list)


class MomentumSignal(BaseModel):
    """Topic momentum signal (rising/falling trends)."""

    id: str
    name: str
    category: str
    current: int
    delta: int
    momentum: Literal["surging", "rising", "stable"]
    headlines: list[HeadlineRef] = Field(default_factory=list)


class CrossSourceCorrelation(BaseModel):
    """Cross-source correlation (same topic across multiple sources)."""

    id: str
    name: str
    category: str
    source_count: int
    sources: list[str]
    level: Literal["high", "elevated", "emerging"]
    headlines: list[HeadlineRef] = Field(default_factory=list)


class PredictiveSignal(BaseModel):
    """Predictive signal based on combined metrics."""

    id: str
    name: str
    category: str
    score: float
    confidence: float
    prediction: str
    level: Literal["high", "medium", "low"]
    headlines: list[HeadlineRef] = Field(default_factory=list)


class CorrelationResults(BaseModel):
    """Complete correlation analysis results."""

    emerging_patterns: list[EmergingPattern] = Field(default_factory=list)
    momentum_signals: list[MomentumSignal] = Field(default_factory=list)
    cross_source_correlations: list[CrossSourceCorrelation] = Field(
        default_factory=list
    )
    predictive_signals: list[PredictiveSignal] = Field(default_factory=list)

    @property
    def total_signals(self) -> int:
        return (
            len(self.emerging_patterns)
            + len(self.momentum_signals)
            + len(self.predictive_signals)
        )

    @property
    def status(self) -> str:
        if self.total_signals == 0:
            return "MONITORING"
        return f"{self.total_signals} SIGNALS"


class CorrelationSummary(BaseModel):
    """Summary of correlation analysis."""

    total_signals: int
    status: str
    top_patterns: list[str] = Field(default_factory=list)
    top_momentum: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_signals": self.total_signals,
            "status": self.status,
            "top_patterns": self.top_patterns,
            "top_momentum": self.top_momentum,
        }
