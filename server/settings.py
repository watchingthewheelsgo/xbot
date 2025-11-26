from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class Settings(BaseModel):
    # Telegram Bot Configuration
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")

    # RSS Configuration
    rss_config_path: str = Field(
        default="server/datasource/rss/config.json", alias="RSS_CONFIG_PATH"
    )
    rss_update_interval_minutes: int = Field(default=30, alias="RSS_UPDATE_INTERVAL")
    rss_request_timeout: int = Field(default=30, alias="RSS_REQUEST_TIMEOUT")
    rss_max_retries: int = Field(default=3, alias="RSS_MAX_RETRIES")

    # Database Configuration
    database_url: str = Field(
        default="sqlite+aiosqlite:///./xbot.db", alias="DATABASE_URL"
    )
    database_echo: bool = Field(default=False, alias="DATABASE_ECHO")

    # LLM Configuration
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    streaming_model: str = Field(default="gpt-4o-mini", alias="STREAMING_MODEL")
    planning_model: str = Field(default="gpt-4o-mini", alias="PLANNING_MODEL")
    max_tokens: int = Field(default=4096, alias="MAX_TOKENS")
    temperature: float = Field(default=0.7, alias="TEMPERATURE")
    max_input_tokens: int | None = Field(default=None, alias="MAX_INPUT_TOKENS")

    # Azure OpenAI Configuration (optional)
    azure_endpoint: str | None = Field(default=None, alias="AZURE_ENDPOINT")
    azure_api_key: str | None = Field(default=None, alias="AZURE_API_KEY")
    azure_api_version: str = Field(default="2024-02-01", alias="AZURE_API_VERSION")


global_settings = Settings()
