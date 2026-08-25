"""Pydantic configuration for the ETL pipeline."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and static defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # full url exceeds ruff recommened 88 character limit, so split over two lines
    source_url: str = (
        "https://services2.arcgis.com/5I7u4SJE1vUr79JC/arcgis/rest/services/"
        "UniversityChapters_Public/FeatureServer/0"
    )

    # Kept as a list so additional states such as OR or WA can be added later
    # without changing the application code.
    target_states: list[str] = Field(
        default=["CA"],
        min_length=1,
        description="States to filter from the source API.",
    )

    arcgis_page_size: int = 1000
    request_timeout: int = 30

    postgres_host: str
    postgres_port: int = 5432
    postgres_db: str = "du_chapters"
    postgres_user: str = "etl"
    postgres_password: str = "etl"
    db_secret_arn: str | None = None

    log_level: str = "INFO"
