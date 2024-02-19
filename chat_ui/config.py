import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Configuration object for the chat_ui application"""

    # The path to the sqlite database, can include ~/ for the user's home directory
    db_path: str = f"{os.getenv('HOME')}/.cache/chatui.sqlite3"
    backend_url: Optional[str] = None
    backend_api_key: str = "not set"
    backend_system_prompt: str = (
        "You are an intelligent assistant. You always provide well-reasoned answers that are both correct and helpful."
    )
    backend_temperature: float = 0.7

    model_config = SettingsConfigDict(env_prefix="CHATUI_")
