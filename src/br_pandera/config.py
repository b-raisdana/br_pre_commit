from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class BrPanderaConfig(BaseSettings):
    environment: Literal["production", "development"] = "development"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


br_pandera_config = BrPanderaConfig()
