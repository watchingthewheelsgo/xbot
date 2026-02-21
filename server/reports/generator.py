"""
LLM-powered report generator.
"""

from datetime import datetime
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from server.ai.llm import LLM
from server.ai.schema import Message
from server.analysis.types import CorrelationResults
from server.reports.templates import ReportTemplate, ReportType, get_template


class GeneratedReport(BaseModel):
    """Generated report output."""

    report_type: ReportType
    title: str
    content: str
    generated_at: datetime = Field(default_factory=datetime.now)
    token_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReportDataContext(BaseModel):
    """Data context for report generation."""

    news_items: list[dict[str, Any]] = Field(default_factory=list)
    market_data: dict[str, Any] = Field(default_factory=dict)
    economic_data: dict[str, Any] = Field(default_factory=dict)
    correlation_results: CorrelationResults | None = None
    fed_news: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


class ReportGenerator:
    """Generates reports using LLM based on templates and data context."""

    def __init__(self, llm: LLM | None = None):
        self.llm = llm or LLM()

    # ── Data formatters ──────────────────────────────────────────────────────

    def _fmt_news(self, items: list[dict], max_items: int = 20) -> str:
        if not items:
            return "No recent news available."
        lines = [
            f"- [{item.get('source', 'Unknown')}] {item.get('title', '')}"
            for item in items[:max_items]
        ]
        return "\n".join(lines)

    def _fmt_market(self, data: dict) -> str:
        if not data:
            return "Market data unavailable."
        sections: list[str] = []

        if indices := data.get("indices"):
            lines = ["**Indices:**"]
            for idx in indices:
                pct = idx.get("change_percent") or 0
                sign = "+" if pct >= 0 else ""
                price = idx.get("price") or 0
                lines.append(
                    f"- {idx.get('name', idx.get('symbol'))}: {price:,.2f} ({sign}{pct:.2f}%)"
                )
            sections.append("\n".join(lines))

        if sectors := data.get("sectors"):
            lines = ["**Sectors:**"]
            for s in sectors[:6]:
                pct = s.get("change_percent") or 0
                sign = "+" if pct >= 0 else ""
                lines.append(f"- {s.get('name')}: {sign}{pct:.2f}%")
            sections.append("\n".join(lines))

        if crypto := data.get("crypto"):
            lines = ["**Crypto:**"]
            for c in crypto[:5]:
                price = c.get("current_price") or 0
                pct = c.get("price_change_percentage_24h") or 0
                sign = "+" if pct >= 0 else ""
                lines.append(f"- {c.get('symbol')}: ${price:,.2f} ({sign}{pct:.2f}%)")
            sections.append("\n".join(lines))

        if commodities := data.get("commodities"):
            lines = ["**Commodities:**"]
            for c in commodities:
                price = c.get("price") or 0
                pct = c.get("change_percent") or 0
                sign = "+" if pct >= 0 else ""
                lines.append(f"- {c.get('name')}: ${price:,.2f} ({sign}{pct:.2f}%)")
            sections.append("\n".join(lines))

        return "\n\n".join(sections) if sections else "Market data unavailable."

    def _fmt_economic(self, data: dict) -> str:
        if not data:
            return "Economic data unavailable."
        lines: list[str] = []
        labels = {
            "fed_funds_rate": "Fed Funds Rate",
            "cpi": "CPI Inflation",
            "treasury_10y": "10Y Treasury",
            "unemployment": "Unemployment",
        }
        for key, label in labels.items():
            ind = data.get(key)
            if not ind:
                continue
            value = ind.get("value")
            unit = ind.get("unit", "%")
            change = ind.get("change")
            if value is not None:
                line = f"- {label}: {value}{unit}"
                if change is not None:
                    sign = "+" if change >= 0 else ""
                    line += f" ({sign}{change}{unit})"
                lines.append(line)
        return "\n".join(lines) if lines else "Economic data unavailable."

    def _fmt_correlation(self, results: CorrelationResults | None) -> str:
        if not results:
            return "No correlation data available."
        sections: list[str] = []

        if results.emerging_patterns:
            lines = ["**Emerging Patterns:**"]
            for p in results.emerging_patterns[:5]:
                lines.append(
                    f"- {p.name} ({p.category}): {p.count} mentions [{p.level}]"
                )
            sections.append("\n".join(lines))

        if results.momentum_signals:
            lines = ["**Momentum Signals:**"]
            for m in results.momentum_signals[:5]:
                lines.append(f"- {m.name}: {m.momentum} (+{m.delta} in 10 min)")
            sections.append("\n".join(lines))

        if results.predictive_signals:
            lines = ["**Predictive Signals:**"]
            for s in results.predictive_signals[:3]:
                lines.append(
                    f"- {s.name}: {s.prediction} (confidence: {s.confidence}%)"
                )
            sections.append("\n".join(lines))

        return (
            "\n\n".join(sections) if sections else "No significant patterns detected."
        )

    def _fmt_patterns_detail(self, results: CorrelationResults | None) -> str:
        if not results or not results.emerging_patterns:
            return "No emerging patterns detected."
        lines: list[str] = []
        for p in results.emerging_patterns:
            lines.append(
                f"- **{p.name}** ({p.category}): {p.count} mentions, {p.level} level"
            )
            lines.append(f"  Sources: {', '.join(p.sources[:5])}")
        return "\n".join(lines)

    def _fmt_momentum_detail(self, results: CorrelationResults | None) -> str:
        if not results or not results.momentum_signals:
            return "No momentum signals detected."
        return "\n".join(
            f"- **{m.name}**: {m.momentum} (+{m.delta} in 10 min)"
            for m in results.momentum_signals
        )

    def _fmt_cross_source(self, results: CorrelationResults | None) -> str:
        if not results or not results.cross_source_correlations:
            return "No cross-source correlations detected."
        lines: list[str] = []
        for c in results.cross_source_correlations:
            lines.append(f"- **{c.name}**: {c.source_count} sources")
            lines.append(f"  Sources: {', '.join(c.sources)}")
        return "\n".join(lines)

    def _fmt_predictive_detail(self, results: CorrelationResults | None) -> str:
        if not results or not results.predictive_signals:
            return "No predictive signals detected."
        lines: list[str] = []
        for p in results.predictive_signals:
            lines.append(f"- **{p.name}** (confidence: {p.confidence}%)")
            lines.append(f"  Prediction: {p.prediction}")
        return "\n".join(lines)

    def _fmt_headlines(self, results: CorrelationResults | None) -> str:
        if not results:
            return "No headlines available."
        seen: set[str] = set()
        lines: list[str] = []
        for pattern in results.emerging_patterns[:3]:
            for h in pattern.headlines:
                if h.title not in seen:
                    lines.append(f"- [{pattern.name}] {h.title}")
                    seen.add(h.title)
        return "\n".join(lines[:10]) if lines else "No relevant headlines."

    def _fmt_single_indicator(self, ind: dict | None) -> str:
        if not ind:
            return "Data unavailable"
        value = ind.get("value", "N/A")
        unit = ind.get("unit", "")
        change = ind.get("change")
        result = f"{value}{unit}"
        if change is not None:
            sign = "+" if change >= 0 else ""
            result += f" ({sign}{change}{unit})"
        return result

    # ── Prompt builder ───────────────────────────────────────────────────────

    def _build_vars(
        self, report_type: ReportType, ctx: ReportDataContext
    ) -> dict[str, str]:
        base = {
            "news_count": str(len(ctx.news_items)),
            "news_summary": self._fmt_news(ctx.news_items),
            "market_data": self._fmt_market(ctx.market_data),
            "economic_data": self._fmt_economic(ctx.economic_data),
            "correlation_summary": self._fmt_correlation(ctx.correlation_results),
        }

        if report_type == ReportType.MARKET_SUMMARY:
            base.update(
                {
                    "indices_data": self._fmt_market(
                        {"indices": ctx.market_data.get("indices", [])}
                    ),
                    "sectors_data": self._fmt_market(
                        {"sectors": ctx.market_data.get("sectors", [])}
                    ),
                    "crypto_data": self._fmt_market(
                        {"crypto": ctx.market_data.get("crypto", [])}
                    ),
                    "commodities_data": self._fmt_market(
                        {"commodities": ctx.market_data.get("commodities", [])}
                    ),
                }
            )

        elif report_type == ReportType.CORRELATION_ALERT:
            r = ctx.correlation_results
            base.update(
                {
                    "emerging_patterns": self._fmt_patterns_detail(r),
                    "momentum_signals": self._fmt_momentum_detail(r),
                    "cross_source": self._fmt_cross_source(r),
                    "predictive_signals": self._fmt_predictive_detail(r),
                    "headlines": self._fmt_headlines(r),
                }
            )

        elif report_type == ReportType.ECONOMIC_UPDATE:
            econ = ctx.economic_data
            base.update(
                {
                    "fed_funds_rate": self._fmt_single_indicator(
                        econ.get("fed_funds_rate")
                    ),
                    "cpi": self._fmt_single_indicator(econ.get("cpi")),
                    "treasury_10y": self._fmt_single_indicator(
                        econ.get("treasury_10y")
                    ),
                    "unemployment": self._fmt_single_indicator(
                        econ.get("unemployment")
                    ),
                    "fed_news": self._fmt_news(ctx.fed_news, max_items=5),
                    "market_context": self._fmt_market(ctx.market_data),
                }
            )

        return base

    # ── Main generate method ─────────────────────────────────────────────────

    async def generate(
        self,
        report_type: ReportType,
        context: ReportDataContext,
        custom_template: ReportTemplate | None = None,
    ) -> GeneratedReport:
        """Generate a report using LLM."""
        template = custom_template or get_template(report_type)
        vars_ = self._build_vars(report_type, context)

        try:
            user_prompt = template.user_prompt_template.format(**vars_)
        except KeyError as e:
            logger.warning(f"Missing prompt variable {e}, using partial format")
            user_prompt = template.user_prompt_template

        system_msg = Message.system_message(template.system_prompt)
        user_msg = Message.user_message(user_prompt)

        logger.info(f"Generating {report_type.value} report...")

        try:
            content = await self.llm.ask(
                messages=[user_msg],
                system_msgs=[system_msg],
                stream=False,
                temperature=0.3,
            )

            report = GeneratedReport(
                report_type=report_type,
                title=template.title,
                content=content,
                token_count=self.llm.count_tokens(content),
                metadata={
                    "news_count": len(context.news_items),
                    "has_market_data": bool(context.market_data),
                    "has_correlation": context.correlation_results is not None,
                },
            )
            logger.info(f"Report generated: {len(content)} chars")
            return report

        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            return GeneratedReport(
                report_type=report_type,
                title=template.title,
                content=f"Report generation failed: {e}",
                metadata={"error": str(e)},
            )
