"""
Application settings with support for new data sources and services.
"""

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # Telegram Bot Configuration
    # ═══════════════════════════════════════════════════════════════════════════
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_admin_chat_id: str = Field(default="", alias="TELEGRAM_ADMIN_CHAT_ID")

    # ═══════════════════════════════════════════════════════════════════════════
    # Feishu Bot Configuration
    # ═══════════════════════════════════════════════════════════════════════════
    feishu_app_id: str = Field(default="", alias="FEISHU_APP_ID")
    feishu_app_secret: str = Field(default="", alias="FEISHU_APP_SECRET")
    feishu_verification_token: str = Field(
        default="", alias="FEISHU_VERIFICATION_TOKEN"
    )
    feishu_encrypt_key: str = Field(default="", alias="FEISHU_ENCRYPT_KEY")
    feishu_admin_chat_id: str = Field(default="", alias="FEISHU_ADMIN_CHAT_ID")

    def is_feishu_configured(self) -> bool:
        """Check if Feishu bot is properly configured."""
        return bool(self.feishu_app_id) and bool(self.feishu_app_secret)

    def get_feishu_admin_chat_ids(self) -> list[str]:
        """Get all Feishu admin chat IDs (comma-separated)."""
        if not self.feishu_admin_chat_id:
            return []
        return [
            cid.strip() for cid in self.feishu_admin_chat_id.split(",") if cid.strip()
        ]

    # ═══════════════════════════════════════════════════════════════════════════
    # RSS Configuration
    # ═══════════════════════════════════════════════════════════════════════════
    rss_config_path: str = Field(
        default="server/datasource/rss/config.json", alias="RSS_CONFIG_PATH"
    )
    rss_update_interval_minutes: int = Field(default=15, alias="RSS_UPDATE_INTERVAL")
    rss_request_timeout: int = Field(default=30, alias="RSS_REQUEST_TIMEOUT")
    rss_max_retries: int = Field(default=3, alias="RSS_MAX_RETRIES")
    rss_max_articles_per_feed: int = Field(
        default=50, alias="RSS_MAX_ARTICLES_PER_FEED"
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # Database Configuration
    # ═══════════════════════════════════════════════════════════════════════════
    database_url: str = Field(
        default="sqlite+aiosqlite:///./xbot.db", alias="DATABASE_URL"
    )
    database_echo: bool = Field(default=False, alias="DATABASE_ECHO")

    # ═══════════════════════════════════════════════════════════════════════════
    # LLM Configuration
    # ═══════════════════════════════════════════════════════════════════════════
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    streaming_model: str = Field(default="gpt-4o-mini", alias="STREAMING_MODEL")
    planning_model: str = Field(default="gpt-4o-mini", alias="PLANNING_MODEL")
    max_tokens: int = Field(default=32000, alias="MAX_TOKENS")
    temperature: float = Field(default=0.7, alias="TEMPERATURE")
    max_input_tokens: int | None = Field(default=None, alias="MAX_INPUT_TOKENS")

    # Azure OpenAI Configuration (optional)
    azure_endpoint: str | None = Field(default=None, alias="AZURE_ENDPOINT")
    azure_api_key: str | None = Field(default=None, alias="AZURE_API_KEY")
    azure_api_version: str = Field(default="2024-02-01", alias="AZURE_API_VERSION")

    # ═══════════════════════════════════════════════════════════════════════════
    # Market Data APIs
    # ═══════════════════════════════════════════════════════════════════════════
    # Finnhub API (stocks, indices, commodities)
    finnhub_api_key: str = Field(default="", alias="FINNHUB_API_KEY")
    finnhub_base_url: str = Field(
        default="https://finnhub.io/api/v1", alias="FINNHUB_BASE_URL"
    )
    finnhub_enabled: bool = Field(default=True, alias="FINNHUB_ENABLED")

    # CoinGecko API (cryptocurrency)
    coingecko_api_key: str = Field(default="", alias="COINGECKO_API_KEY")
    coingecko_base_url: str = Field(
        default="https://api.coingecko.com/api/v3", alias="COINGECKO_BASE_URL"
    )
    coingecko_enabled: bool = Field(default=True, alias="COINGECKO_ENABLED")

    # FRED API (Federal Reserve Economic Data)
    fred_api_key: str = Field(default="", alias="FRED_API_KEY")
    fred_base_url: str = Field(
        default="https://api.stlouisfed.org/fred", alias="FRED_BASE_URL"
    )
    fred_enabled: bool = Field(default=True, alias="FRED_ENABLED")

    # ═══════════════════════════════════════════════════════════════════════════
    # Service Layer Configuration
    # ═══════════════════════════════════════════════════════════════════════════
    # Cache settings
    cache_enabled: bool = Field(default=True, alias="CACHE_ENABLED")
    cache_default_ttl_seconds: int = Field(default=300, alias="CACHE_DEFAULT_TTL")
    cache_max_memory_items: int = Field(default=100, alias="CACHE_MAX_MEMORY_ITEMS")

    # Circuit breaker settings
    circuit_breaker_enabled: bool = Field(default=True, alias="CIRCUIT_BREAKER_ENABLED")
    circuit_breaker_failure_threshold: int = Field(
        default=3, alias="CB_FAILURE_THRESHOLD"
    )
    circuit_breaker_reset_timeout_seconds: int = Field(
        default=30, alias="CB_RESET_TIMEOUT"
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # Analysis Configuration
    # ═══════════════════════════════════════════════════════════════════════════
    correlation_enabled: bool = Field(default=True, alias="CORRELATION_ENABLED")
    correlation_history_minutes: int = Field(
        default=30, alias="CORRELATION_HISTORY_MINUTES"
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # Report Generation Configuration
    # ═══════════════════════════════════════════════════════════════════════════
    report_enabled: bool = Field(default=True, alias="REPORT_ENABLED")
    report_default_news_hours: int = Field(default=24, alias="REPORT_NEWS_HOURS")
    report_max_news_items: int = Field(default=100, alias="REPORT_MAX_NEWS_ITEMS")
    report_temperature: float = Field(default=0.3, alias="REPORT_TEMPERATURE")

    # ═══════════════════════════════════════════════════════════════════════════
    # Scheduler Configuration
    # ═══════════════════════════════════════════════════════════════════════════
    scheduler_enabled: bool = Field(default=True, alias="SCHEDULER_ENABLED")
    scheduler_timezone: str = Field(default="UTC", alias="SCHEDULER_TIMEZONE")

    # Data fetch intervals (in minutes)
    fetch_interval_rss: int = Field(default=15, alias="FETCH_INTERVAL_RSS")
    fetch_interval_crypto: int = Field(default=5, alias="FETCH_INTERVAL_CRYPTO")
    fetch_interval_markets: int = Field(default=5, alias="FETCH_INTERVAL_MARKETS")
    fetch_interval_economic: int = Field(default=60, alias="FETCH_INTERVAL_ECONOMIC")

    # ═══════════════════════════════════════════════════════════════════════════
    # Push Notification Configuration
    # ═══════════════════════════════════════════════════════════════════════════
    push_enabled: bool = Field(default=True, alias="PUSH_ENABLED")
    push_daily_briefing_time: str = Field(
        default="08:00", alias="PUSH_DAILY_BRIEFING_TIME"
    )
    push_market_summary_time: str = Field(
        default="16:30", alias="PUSH_MARKET_SUMMARY_TIME"
    )
    push_correlation_min_signals: int = Field(
        default=3, alias="PUSH_CORRELATION_MIN_SIGNALS"
    )
    push_news_burst_threshold: int = Field(
        default=50, alias="PUSH_NEWS_BURST_THRESHOLD"
    )
    push_news_burst_window_minutes: int = Field(
        default=30, alias="PUSH_NEWS_BURST_WINDOW"
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # Watchlist Configuration
    # ═══════════════════════════════════════════════════════════════════════════
    watchlist_symbols: list[str] = Field(
        default=["NVDA", "AAPL", "MSFT", "GOOGL", "TSLA"], alias="WATCHLIST_SYMBOLS"
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # Logging Configuration
    # ═══════════════════════════════════════════════════════════════════════════
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # ═══════════════════════════════════════════════════════════════════════════
    # Helper Methods
    # ═══════════════════════════════════════════════════════════════════════════
    def is_finnhub_configured(self) -> bool:
        """Check if Finnhub API is properly configured."""
        return bool(self.finnhub_api_key) and self.finnhub_enabled

    def is_coingecko_configured(self) -> bool:
        """Check if CoinGecko API is configured (API key optional for free tier)."""
        return self.coingecko_enabled

    def is_fred_configured(self) -> bool:
        """Check if FRED API is properly configured."""
        return bool(self.fred_api_key) and self.fred_enabled

    def get_service_status(self) -> dict[str, bool]:
        """Get status of all configurable services."""
        return {
            "rss": True,
            "finnhub": self.is_finnhub_configured(),
            "coingecko": self.is_coingecko_configured(),
            "fred": self.is_fred_configured(),
            "cache": self.cache_enabled,
            "circuit_breaker": self.circuit_breaker_enabled,
            "correlation": self.correlation_enabled,
            "reports": self.report_enabled,
            "push": self.push_enabled,
        }

    def is_llm_configured(self) -> bool:
        """Check if LLM (OpenAI) is properly configured."""
        return bool(self.openai_api_key)


global_settings = Settings()


def get_settings() -> Settings:
    """Get the global settings instance."""
    return global_settings


def reload_settings() -> Settings:
    """Reload settings from environment."""
    global global_settings
    global_settings = Settings()
    return global_settings
