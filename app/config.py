from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(alias="BOT_TOKEN")
    database_url: str = Field(alias="DATABASE_URL")
    timezone: str = Field(default="Europe/Kyiv", alias="TIMEZONE")

    admin_telegram_ids: list[int] = Field(default_factory=list, alias="ADMIN_TELEGRAM_IDS")
    work_start_hour: int = Field(default=9, alias="WORK_START_HOUR")
    work_end_hour: int = Field(default=18, alias="WORK_END_HOUR")
    slot_step_minutes: int = Field(default=30, alias="SLOT_STEP_MINUTES")
    scheduler_poll_seconds: int = Field(default=300, alias="SCHEDULER_POLL_SECONDS")

    @field_validator("admin_telegram_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: str | list[int] | None) -> list[int]:
        if value in (None, "", []):
            return []
        if isinstance(value, list):
            return [int(item) for item in value]
        return [int(item.strip()) for item in value.split(",") if item.strip()]

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()
