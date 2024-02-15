from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Configuration object for the chat_ui application"""

    # The path to the sqlite database, can include ~/ for the user's home directory
    db_path: str
    backend_url: Optional[str] = None

    model_config = SettingsConfigDict(env_prefix="CHATUI_")
