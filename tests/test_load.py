"""Tests for etl/load.py."""

import json

import pytest
from sqlalchemy import inspect, select

from etl.exceptions import LoadError
from etl.load import (
    build_database_url,
    build_engine,
    ensure_table,
    get_secret_value,
    load_chapters,
    resolve_db_settings,
)
from etl.models import ChapterRow, UniversityChapter


class TestBuildDatabaseUrl:
    """Tests for build_database_url."""

    def test_build_database_url_returns_postgres_url(self, settings):
        url = build_database_url(settings)
        assert url == "postgresql+psycopg2://etl:etl@localhost:5432/du_chapters_test"


    def test_build_database_url_uses_secrets_manager_credentials(self, settings, monkeypatch):
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps(
                {
                    "username": "aws_user",
                    "password": "aws_pass",
                    "host": "aws.db.com",
                    "port": "5433",
                    "dbname": "aws_db",
                }
            )
        }
        monkeypatch.setattr(
            "etl.load.boto3.client", lambda service: mock_client
        )

        settings_with_secret = settings.model_copy(update={"db_secret_arn": "arn:aws:secretsmanager:xxx"})
        url = build_database_url(settings_with_secret)
        assert url == "postgresql+psycopg2://aws_user:aws_pass@aws.db.com:5433/aws_db"
        mock_client.get_secret_value.assert_called_once_with(SecretId="arn:aws:secretsmanager:xxx")


class TestGetSecretValue:
    """Tests for get_secret_value."""

    def test_get_secret_value_returns_parsed_secret(self, monkeypatch):
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": '{"username": "aws_user", "password": "aws_pass"}'
        }
        monkeypatch.setattr("etl.load.boto3.client", lambda service: mock_client)

        secret = get_secret_value("arn:aws:secretsmanager:xxx")
        assert secret == {"username": "aws_user", "password": "aws_pass"}

    def test_get_secret_value_raises_load_error_on_client_error(self, monkeypatch):
        from unittest.mock import MagicMock
        from botocore.exceptions import ClientError

        mock_client = MagicMock()
        mock_client.get_secret_value.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "Secret not found"}},
            "GetSecretValue",
        )
        monkeypatch.setattr("etl.load.boto3.client", lambda service: mock_client)

        with pytest.raises(LoadError, match="Failed to retrieve secret"):
            get_secret_value("arn:aws:secretsmanager:xxx")

    def test_resolve_db_settings_falls_back_to_env_vars_for_missing_keys(self, settings, monkeypatch):
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": '{"username": "aws_user"}'  # missing password, host, port, dbname
        }
        monkeypatch.setattr("etl.load.boto3.client", lambda service: mock_client)

        settings_with_secret = settings.model_copy(update={"db_secret_arn": "arn:aws:secretsmanager:xxx"})
        params = resolve_db_settings(settings_with_secret)
        assert params["username"] == "aws_user"
        assert params["password"] == settings.postgres_password
        assert params["host"] == settings.postgres_host
        assert params["port"] == settings.postgres_port
        assert params["dbname"] == settings.postgres_db

    def test_resolve_db_settings_uses_env_vars_when_arn_unset(self, settings):
        params = resolve_db_settings(settings)
        assert params["username"] == settings.postgres_user
        assert params["password"] == settings.postgres_password
        assert params["host"] == settings.postgres_host
        assert params["port"] == settings.postgres_port
        assert params["dbname"] == settings.postgres_db

    def test_resolve_db_settings_overrides_all_connection_params(self, settings, monkeypatch):
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps(
                {
                    "username": "aws_user",
                    "password": "aws_pass",
                    "host": "aws.db.com",
                    "port": "5433",
                    "dbname": "aws_db",
                }
            )
        }
        monkeypatch.setattr("etl.load.boto3.client", lambda service: mock_client)

        settings_with_secret = settings.model_copy(update={"db_secret_arn": "arn:aws:secretsmanager:xxx"})
        params = resolve_db_settings(settings_with_secret)
        assert params["username"] == "aws_user"
        assert params["password"] == "aws_pass"
        assert params["host"] == "aws.db.com"
        assert params["port"] == "5433"
        assert params["dbname"] == "aws_db"


class TestBuildEngine:
    """Tests for build_engine."""

    def test_build_engine_returns_working_engine(self, settings):
        engine = build_engine(settings)
        try:
            with engine.connect() as conn:
                result = conn.exec_driver_sql("SELECT 1")
                assert result.scalar() == 1
        finally:
            engine.dispose()


class TestEnsureTable:
    """Tests for ensure_table."""

    def test_ensure_table_creates_or_verifies_table(self, engine):
        ensure_table(engine)
        inspector = inspect(engine)
        assert "university_chapters" in inspector.get_table_names()

    def test_ensure_table_is_idempotent(self, engine):
        ensure_table(engine)
        ensure_table(engine)
        inspector = inspect(engine)
        assert "university_chapters" in inspector.get_table_names()


class TestLoadChapters:
    """Tests for load_chapters SCD2 upserts."""

    def test_load_chapters_inserts_new_rows(self, session, batch_timestamp):
        rows = [
            ChapterRow(
                chapter_id="CA-001",
                chapter_name="Duck State",
                city="Sacramento",
                state="CA",
                coordinates="POINT(-121.4944 38.5816)",
            ),
            ChapterRow(
                chapter_id="CA-002",
                chapter_name="Duck Tech",
                city="Los Angeles",
                state="CA",
                coordinates="POINT(-118.2437 34.0522)",
            ),
        ]
        load_chapters(session, rows, batch_timestamp)

        results = session.execute(
            select(UniversityChapter).order_by(UniversityChapter.chapter_id)
        ).scalars().all()

        assert len(results) == 2
        for row in results:
            assert row.is_current is True
            assert row.valid_to is None

    def test_load_chapters_closes_old_row_on_hash_change(self, session, batch_timestamp):
        original = ChapterRow(
            chapter_id="CA-001",
            chapter_name="Duck State",
            city="Sacramento",
            state="CA",
            coordinates="POINT(-121.4944 38.5816)",
        )
        updated = ChapterRow(
            chapter_id="CA-001",
            chapter_name="Duck State University",
            city="Sacramento",
            state="CA",
            coordinates="POINT(-121.4944 38.5816)",
        )

        load_chapters(session, [original], batch_timestamp)
        load_chapters(session, [updated], batch_timestamp)

        results = session.execute(
            select(UniversityChapter)
            .where(UniversityChapter.chapter_id == "CA-001")
            .order_by(UniversityChapter.valid_from)
        ).scalars().all()

        assert len(results) == 2
        assert results[0].is_current is False
        assert results[0].valid_to is not None
        assert results[0].chapter_name == "Duck State"
        assert results[1].is_current is True
        assert results[1].valid_to is None
        assert results[1].chapter_name == "Duck State University"

    def test_load_chapters_no_op_on_unchanged_data(self, session, batch_timestamp):
        row = ChapterRow(
            chapter_id="CA-001",
            chapter_name="Duck State",
            city="Sacramento",
            state="CA",
            coordinates="POINT(-121.4944 38.5816)",
        )

        load_chapters(session, [row], batch_timestamp)
        load_chapters(session, [row], batch_timestamp)

        results = session.execute(
            select(UniversityChapter).where(UniversityChapter.chapter_id == "CA-001")
        ).scalars().all()

        assert len(results) == 1
        assert results[0].is_current is True

    def test_load_chapters_with_empty_rows(self, session, batch_timestamp):
        load_chapters(session, [], batch_timestamp)
        results = session.execute(select(UniversityChapter)).scalars().all()
        assert len(results) == 0

    def test_load_chapters_with_duplicate_input_rows(self, session, batch_timestamp):
        rows = [
            ChapterRow(
                chapter_id="CA-001",
                chapter_name="Duck State",
                city="Sacramento",
                state="CA",
                coordinates="POINT(-121.4944 38.5816)",
            ),
            ChapterRow(
                chapter_id="CA-001",
                chapter_name="Duck State University",
                city="Sacramento",
                state="CA",
                coordinates="POINT(-121.4944 38.5816)",
            ),
        ]
        load_chapters(session, rows, batch_timestamp)

        results = session.execute(
            select(UniversityChapter).where(UniversityChapter.chapter_id == "CA-001")
        ).scalars().all()

        # Two inserts happen; the second closes the first and becomes current.
        assert len(results) == 2
        current_rows = [r for r in results if r.is_current]
        closed_rows = [r for r in results if not r.is_current]
        assert len(current_rows) == 1
        assert len(closed_rows) == 1
        assert current_rows[0].chapter_name == "Duck State University"
        assert closed_rows[0].chapter_name == "Duck State"

    def test_load_chapters_raises_load_error_on_commit_failure(self, session, monkeypatch, batch_timestamp):
        def fail_commit():
            raise RuntimeError("database error")

        monkeypatch.setattr(session, "commit", fail_commit)

        rows = [
            ChapterRow(
                chapter_id="CA-001",
                chapter_name="Duck State",
                city="Sacramento",
                state="CA",
                coordinates="POINT(-121.4944 38.5816)",
            )
        ]
        with pytest.raises(LoadError, match="Failed to load chapters"):
            load_chapters(session, rows, batch_timestamp)

    def test_load_chapters_rolls_back_on_commit_failure(self, session, monkeypatch, batch_timestamp):
        original_rollback = session.rollback
        rollback_called = {"value": False}

        def fail_commit():
            raise RuntimeError("database error")

        def tracking_rollback():
            rollback_called["value"] = True
            original_rollback()

        monkeypatch.setattr(session, "commit", fail_commit)
        monkeypatch.setattr(session, "rollback", tracking_rollback)

        rows = [
            ChapterRow(
                chapter_id="CA-001",
                chapter_name="Duck State",
                city="Sacramento",
                state="CA",
                coordinates="POINT(-121.4944 38.5816)",
            )
        ]
        with pytest.raises(LoadError):
            load_chapters(session, rows, batch_timestamp)

        assert rollback_called["value"] is True
