import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Type
from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from pydantic.fields import FieldInfo

CONFIG_FILENAME = "~/.config/chat-ui.json"


class JsonConfigSettingsSource(PydanticBaseSettingsSource):
    """
    A simple settings source class that loads variables from a JSON file
    at the project's root.
    """

    def get_field_value(self, field: FieldInfo, field_name: str) -> Tuple[Any, str, bool]:
        try:
            file_content_json = json.load(Path(CONFIG_FILENAME).expanduser().open(encoding="utf-8"))
            field_value = file_content_json.get(field_name)
            return field_value, field_name, False
        except Exception as error:
            logging.debug("Failed to load config file %s: %s", CONFIG_FILENAME, error)
        return (None, "", False)

    def prepare_field_value(self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool) -> Any:
        return value

    def __call__(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}

        for field_name, field in self.settings_cls.model_fields.items():
            field_value, field_key, value_is_complex = self.get_field_value(field, field_name)
            field_value = self.prepare_field_value(field_name, field, field_value, value_is_complex)
            if field_value is not None:
                d[field_key] = field_value

        return d


class Config(BaseSettings):
    """Configuration object for the chat_ui application"""

    # The path to the sqlite database, can include ~/ for the user's home directory
    db_path: str = f"{os.getenv('HOME')}/.cache/chatui.sqlite3"
    backend_url: Optional[str] = "http://localhost:9196/v1"
    backend_api_key: str = "not set"
    backend_system_prompt: str = (
        "You are an intelligent assistant. You always provide well-reasoned answers that are both correct and helpful."
    )
    backend_temperature: float = 0.7

    model_config = SettingsConfigDict(env_prefix="CHATUI_")

    admin_password: Optional[str] = None

    enable_do_bad_things_mode: str = Field("false", description="Enable bad things mode")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            JsonConfigSettingsSource(settings_cls),
            env_settings,
            file_secret_settings,
        )
