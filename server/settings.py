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


global_settings = Settings()
