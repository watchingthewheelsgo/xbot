"""
Report templates for LLM-powered report generation.
"""

from enum import Enum
from pydantic import BaseModel


class ReportType(str, Enum):
    DAILY_BRIEFING = "daily_briefing"
    MARKET_SUMMARY = "market_summary"
    CORRELATION_ALERT = "correlation_alert"
    ECONOMIC_UPDATE = "economic_update"


class ReportTemplate(BaseModel):
    report_type: ReportType
    title: str
    system_prompt: str
    user_prompt_template: str
    max_tokens: int = 2000


DAILY_BRIEFING_TEMPLATE = ReportTemplate(
    report_type=ReportType.DAILY_BRIEFING,
    title="Daily Intelligence Briefing",
    system_prompt="""You are an intelligence analyst preparing a daily briefing for decision-makers.
Your reports should be concise, actionable, objective, and structured with clear sections.
Write in a professional analytical tone. Avoid speculation unless clearly labeled.""",
    user_prompt_template="""Generate a Daily Intelligence Briefing based on the following data:

## News Headlines ({news_count} items from the last 24h)
{news_summary}

## Market Data
{market_data}

## Correlation Analysis
{correlation_summary}

## Economic Indicators
{economic_data}

Generate a structured briefing with these sections:
1. **Executive Summary** (2-3 sentences on the most important developments)
2. **Key Developments** (bullet points of significant news, grouped by category)
3. **Market Overview** (brief market status and notable movements)
4. **Emerging Patterns** (correlation signals and trends worth watching)
5. **Outlook** (brief forward-looking assessment)

Keep the total length under 800 words. Use markdown formatting.""",
    max_tokens=2000,
)

MARKET_SUMMARY_TEMPLATE = ReportTemplate(
    report_type=ReportType.MARKET_SUMMARY,
    title="Market Summary",
    system_prompt="""You are a financial analyst preparing a market summary.
Be precise with numbers and percentages. Focus on notable movements and cross-market patterns.""",
    user_prompt_template="""Generate a Market Summary based on the following data:

## Stock Indices
{indices_data}

## Sector Performance
{sectors_data}

## Cryptocurrency
{crypto_data}

## Commodities
{commodities_data}

## Economic Indicators
{economic_data}

Generate a concise market summary with:
1. **Market Status** (overall sentiment in 1-2 sentences)
2. **Key Movers** (top gainers/losers across all categories)
3. **Sector Analysis** (brief sector performance overview)
4. **Notable Correlations** (any interesting cross-market patterns)

Keep it under 400 words. Use markdown formatting.""",
    max_tokens=1000,
)

CORRELATION_ALERT_TEMPLATE = ReportTemplate(
    report_type=ReportType.CORRELATION_ALERT,
    title="Correlation Alert",
    system_prompt="""You are an intelligence analyst issuing an alert about detected patterns.
Be direct, provide supporting evidence, assess confidence, and suggest monitoring actions.""",
    user_prompt_template="""Generate a Correlation Alert based on the following detected patterns:

## Emerging Patterns
{emerging_patterns}

## Momentum Signals
{momentum_signals}

## Cross-Source Correlations
{cross_source}

## Predictive Signals
{predictive_signals}

## Supporting Headlines
{headlines}

Generate an alert with:
1. **Alert Summary** (what was detected and why it matters)
2. **Pattern Details** (specific patterns with counts and sources)
3. **Confidence Assessment** (how reliable is this signal)
4. **Recommended Actions** (what to monitor or do next)

Keep it under 300 words. Use markdown formatting.""",
    max_tokens=800,
)

ECONOMIC_UPDATE_TEMPLATE = ReportTemplate(
    report_type=ReportType.ECONOMIC_UPDATE,
    title="Economic Indicators Update",
    system_prompt="""You are an economist preparing an economic indicators update.
Use precise economic terminology. Focus on current values, changes, and policy implications.""",
    user_prompt_template="""Generate an Economic Update based on the following data:

## Federal Reserve Indicators
- Fed Funds Rate: {fed_funds_rate}
- CPI Inflation: {cpi}
- 10Y Treasury: {treasury_10y}
- Unemployment: {unemployment}

## Recent Fed News
{fed_news}

## Related Market Context
{market_context}

Generate an update with:
1. **Summary** (current economic snapshot in 2-3 sentences)
2. **Fed Policy Assessment** (current stance and likely direction)
3. **Inflation & Employment** (trend and implications)
4. **Market Impact** (how markets are responding)

Keep it under 350 words. Use markdown formatting.""",
    max_tokens=900,
)

_TEMPLATES: dict[ReportType, ReportTemplate] = {
    ReportType.DAILY_BRIEFING: DAILY_BRIEFING_TEMPLATE,
    ReportType.MARKET_SUMMARY: MARKET_SUMMARY_TEMPLATE,
    ReportType.CORRELATION_ALERT: CORRELATION_ALERT_TEMPLATE,
    ReportType.ECONOMIC_UPDATE: ECONOMIC_UPDATE_TEMPLATE,
}


def get_template(report_type: ReportType) -> ReportTemplate:
    return _TEMPLATES.get(report_type, DAILY_BRIEFING_TEMPLATE)
