"""Tests for etl/config.py."""

import pytest
from pydantic import ValidationError

from etl.config import Settings

DEFAULT_SOURCE_URL = Settings.model_fields["source_url"].default


@pytest.fixture(autouse=True)
def clear_settings_env(monkeypatch):
    """Clear settings-related env vars so tests control their own inputs."""
    for var in [
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "SOURCE_URL",
        "TARGET_STATES",
        "ARCGIS_PAGE_SIZE",
        "REQUEST_TIMEOUT",
        "LOG_LEVEL",
        "DB_SECRET_ARN",
    ]:
        monkeypatch.delenv(var, raising=False)


class TestSettings:
    """Tests for the Settings configuration class."""

    def test_default_values(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_HOST", "localhost")
        settings = Settings()
        assert settings.source_url == DEFAULT_SOURCE_URL
        assert settings.target_states == ["CA"]
        assert settings.arcgis_page_size == 1000
        assert settings.request_timeout == 30
        assert settings.postgres_port == 5432
        assert settings.postgres_db == "du_chapters"
        assert settings.postgres_user == "etl"
        assert settings.postgres_password == "etl"
        assert settings.log_level == "INFO"
        assert settings.db_secret_arn is None

    def test_env_vars_override_defaults(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_HOST", "aws.db.com")
        monkeypatch.setenv("POSTGRES_PORT", "5433")
        monkeypatch.setenv("POSTGRES_DB", "test_db")
        monkeypatch.setenv("POSTGRES_USER", "test_user")
        monkeypatch.setenv("POSTGRES_PASSWORD", "test_pass")
        monkeypatch.setenv("SOURCE_URL", "http://example.com/arcgis")
        monkeypatch.setenv("TARGET_STATES", '["CA", "OR"]')
        monkeypatch.setenv("ARCGIS_PAGE_SIZE", "500")
        monkeypatch.setenv("REQUEST_TIMEOUT", "60")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("DB_SECRET_ARN", "arn:aws:secretsmanager:xxx")

        settings = Settings()
        assert settings.postgres_host == "aws.db.com"
        assert settings.postgres_port == 5433
        assert settings.postgres_db == "test_db"
        assert settings.postgres_user == "test_user"
        assert settings.postgres_password == "test_pass"
        assert settings.source_url == "http://example.com/arcgis"
        assert settings.target_states == ["CA", "OR"]
        assert settings.arcgis_page_size == 500
        assert settings.request_timeout == 60
        assert settings.log_level == "DEBUG"
        assert settings.db_secret_arn == "arn:aws:secretsmanager:xxx"

    def test_invalid_value_raises_validation_error(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_HOST", "localhost")
        monkeypatch.setenv("POSTGRES_PORT", "not-a-number")
        with pytest.raises(ValidationError):
            Settings()

    def test_target_states_parsed_from_json(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_HOST", "localhost")
        monkeypatch.setenv("TARGET_STATES", '["NY", "NJ"]')
        settings = Settings()
        assert settings.target_states == ["NY", "NJ"]

    def test_empty_target_states_raises_validation_error(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_HOST", "localhost")
        monkeypatch.setenv("TARGET_STATES", "[]")
        with pytest.raises(ValidationError):
            Settings()
