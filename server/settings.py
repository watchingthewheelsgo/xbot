from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseModel):
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")


global_settings = Settings()
